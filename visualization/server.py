"""Dependency-free local server for live ARGUS trajectory visualization."""

from __future__ import annotations

import argparse
import io
import json
import math
import mimetypes
import re
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qs, urlparse

from PIL import Image

from .agents import annotate_moments, assemble_agent_model, global_event_id
from .case import CaseBranch, CaseManifest, load_case_manifest, merge_case_rows
from .story import (
    assemble_story, assemble_tool_observability, event_sequence,
    tool_catalog,
)


STATIC_ROOT = Path(__file__).with_name("static")
EVIDENCE_ID = re.compile(r"^(?:ev_[0-9]+|audio_ev_[0-9]+)$")
REUSABLE_ARTIFACT_ID = re.compile(r"^artifact_[0-9]+$")
BYTE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def infer_evidence_root(trace_path: Path) -> Path | None:
    for parent in trace_path.parents:
        if parent.name == "traces":
            candidate = parent.parent / "evidence"
            if candidate.is_dir():
                return candidate
    return None


def infer_memory_root(trace_path: Path) -> Path | None:
    for parent in trace_path.parents:
        if parent.name == "traces":
            candidate = parent.parent / "memory"
            if candidate.is_dir():
                return candidate
    return None


def resolve_active_trace(source: Path, *, started_after: float = 0.0) -> Path | None:
    if source.is_file():
        return source if source.stat().st_mtime >= started_after else None
    # Native Codex/Claude session logs can be newer than the normalized trace,
    # but they do not implement the dashboard schema.  Only follow top-level
    # normalized trajectories when watching a directory.
    candidates = [
        path
        for path in source.rglob("*.jsonl")
        if path.is_file() and path.stat().st_mtime >= started_after
        and not any(parent.name.endswith(".native") for parent in path.parents)
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime_ns) if candidates else None


def infer_output_root(trace_path: Path) -> Path | None:
    """Return the experiment directory containing ``traces`` and result files."""
    for parent in trace_path.parents:
        if parent.name == "traces":
            return parent.parent
    return None


def _result_records(path: Path) -> list[dict[str, Any]]:
    try:
        if path.suffix == ".jsonl":
            return [
                value for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and isinstance((value := json.loads(line)), dict)
            ]
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(value, dict):
        return [value]
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def find_run_result(trace_path: Path, run_id: str) -> dict[str, Any]:
    root = infer_output_root(trace_path)
    if root is None or not root.is_dir():
        return {}
    candidates = [*root.glob("*.json"), *root.glob("*.jsonl")]
    # Evaluation runs keep the normalized trace/evidence/memory in
    # ``<execution>/case_store`` and the full model record in the sibling
    # ``runs/<sample>/attempt-*`` directory.  Include those records so replay
    # retains the source video, final verdict, hypotheses, and explanations.
    if root.name == "case_store":
        candidates.extend((root.parent / "runs").glob("*/attempt-*/record.json"))
    candidates = sorted(
        candidates,
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for candidate in candidates:
        for record in _result_records(candidate):
            if str(record.get("run_id", "")) == run_id:
                return record
    return {}


def _read_json_files(directory: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    if not directory.is_dir():
        return values
    for path in sorted(directory.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            values.append(value)
    return values


def build_run_context(
    trace_path: Path | None,
    rows: list[dict[str, Any]],
    evidence_root: Path | None,
    memory_root: Path | None = None,
    result_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    first = rows[0] if rows else {}
    run_id = str(first.get("run_id", ""))
    result = result_override or (find_run_result(trace_path, run_id) if trace_path and run_id else {})
    evidence = list(result.get("additional_evidence") or result.get("evidence") or [])
    claims = list(result.get("evidence_claims") or [])
    hypotheses = list(result.get("hypotheses") or [])
    questions = list(result.get("investigation_questions") or [])
    peer_reviews = list(result.get("peer_reviews") or [])
    if evidence_root and run_id:
        run_root = evidence_root / run_id
        stored_evidence = _read_json_files(run_root / "records")
        if stored_evidence:
            merged_evidence = {str(item.get("evidence_id")): item for item in evidence if item.get("evidence_id")}
            merged_evidence.update({str(item.get("evidence_id")): item for item in stored_evidence if item.get("evidence_id")})
            evidence = list(merged_evidence.values())
        claims = _read_json_files(run_root / "claims") or claims
        board = _read_json_files(run_root / "hypotheses")
        hypotheses = [item for item in board if item.get("hypothesis_id")] or hypotheses
        questions = [item for item in board if item.get("question_id")] or questions
        peer_reviews = [item for item in board if item.get("review_id")] or peer_reviews
        artifacts = _read_json_files(run_root / "artifact_records")
    else:
        artifacts = list(result.get("reusable_artifacts") or [])
    memories = list(result.get("investigation_memory") or [])
    if memory_root and run_id:
        memories = _read_json_files(memory_root / run_id / "entries") or memories
    observations = result.get("observations") or result.get("original_observations") or {}
    video_path = str(result.get("video_path", ""))
    audio_metadata = result.get("audio_metadata") or {}
    if not isinstance(audio_metadata, dict):
        audio_metadata = {}
    if not audio_metadata:
        audio_metadata = next(
            (
                dict(row.get("result") or {})
                for row in reversed(rows)
                if row.get("surface") in {"audio_prepared", "audio_track_extracted"}
                and isinstance(row.get("result"), dict)
            ),
            {},
        )
    audio_verdict = next(
        (
            row.get("result") or {}
            for row in reversed(rows)
            if row.get("surface") == "audio_verdict_generated"
            and isinstance(row.get("result"), dict)
        ),
        {},
    )
    verification_summary = result.get("verification_summary") or {}
    audio_references = list(verification_summary.get("references") or []) if isinstance(verification_summary, dict) else []
    if not audio_references:
        by_id: dict[str, dict[str, Any]] = {}
        for item in evidence:
            parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
            for reference in parameters.get("reference_records", []):
                if isinstance(reference, dict) and reference.get("reference_id"):
                    by_id[str(reference["reference_id"])] = reference
        audio_references = list(by_id.values())
    if not video_path and audio_metadata.get("source_kind") == "video":
        video_path = str(audio_metadata.get("original_media_ref", ""))
    if not video_path:
        for row in rows:
            sampling = (row.get("result") or {}).get("sampling") if isinstance(row.get("result"), dict) else None
            if isinstance(sampling, dict) and sampling.get("source"):
                video_path = str(sampling["source"])
                break
    context = {
        "run_id": run_id,
        "video_path": video_path,
        "video_available": bool(video_path and Path(video_path).is_file()),
        "audio_enabled": bool(audio_metadata),
        "audio_metadata": audio_metadata,
        "audio_path": str(audio_metadata.get("normalized_audio_ref", "")),
        "audio_available": bool(
            audio_metadata.get("normalized_audio_ref")
            and Path(str(audio_metadata.get("normalized_audio_ref"))).is_file()
        ),
        "audio_evidence": [
            item for item in evidence
            if str(item.get("evidence_id", "")).startswith("audio_ev_")
        ],
        "tooldf_original_prediction": result.get("tooldf_original_prediction") or audio_verdict.get("tooldf_original_prediction"),
        "audio_investigation_assessment": result.get("audio_investigation_assessment") or audio_verdict.get("audio_investigation_assessment"),
        "audio_mode": result.get("audio_mode") or ("forensic" if any(
            bool((row.get("metadata") or {}).get("outer_controller")) for row in rows
        ) else "baseline"),
        "forensic_verification_assessment": result.get("forensic_verification_assessment") or "not_run",
        "verification_summary": verification_summary,
        "audio_references": audio_references,
        "audio_topology": (
            "clawteam"
            if any(
                str(row.get("harness", "")).lower() == "clawteam"
                or row.get("agent_role") in {"audio_case_coordinator", "clawteam_coordinator"}
                for row in rows
            )
            else "direct"
        ) if audio_metadata else "unavailable",
        "simulation_fixture": bool(result.get("simulation_fixture")) or any(
            str(row.get("harness", "")).lower() in {"fixture", "simulation"}
            or bool((row.get("metadata") or {}).get("simulation_fixture"))
            for row in rows
        ),
        "observations": observations if isinstance(observations, dict) else {},
        "original_explanation": result.get("original_explanation") or result.get("explanation") or "",
        "augmented_explanation": result.get("augmented_explanation") or "",
        "original_prediction": result.get("original_prediction") or result.get("answer"),
        "augmented_prediction": result.get("augmented_prediction"),
        "evidence": evidence,
        "artifacts": artifacts,
        "claims": claims,
        "reinspection_requests": result.get("reinspection_requests") or [],
        "memories": memories,
        "memory_policy": result.get("memory_policy") or {},
        "tool_catalog": tool_catalog(),
        "hypotheses": hypotheses,
        "questions": questions,
        "peer_reviews": peer_reviews,
        "investigator_mode": result.get("investigator_mode") or (
            "direct_demo" if any(str(row.get("agent_role", "")) == "direct_demo" for row in rows)
            else "generic" if any(str(row.get("agent_role", "")).startswith("investigator_") for row in rows)
            else "specialized"
        ),
        "generic_investigator_reports": result.get("generic_investigator_reports") or {},
        "visual_investigation_assessment": result.get("visual_investigation_assessment") or "inconclusive",
        "source_footage_status": result.get("source_footage_status") or "not_requested",
    }
    # Launch metadata identifies a real investigator run even while model
    # weights are loading and no domain event has been emitted yet.
    if evidence_root is not None:
        execution_path = evidence_root.parent / "execution.json"
        try:
            execution = json.loads(execution_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            execution = {}
        if isinstance(execution, dict) and execution.get("execution_mode") == "live_inference":
            context["execution"] = {key: execution.get(key) for key in (
                "execution_mode", "mode", "backend", "framework", "media", "started_at", "status",
            )}
            context["execution"]["completed"] = any(row.get("surface") == "run_completed" for row in rows)
    context["story"] = assemble_story(rows, context)
    context["observability"] = assemble_tool_observability(rows, context)
    _attach_agent_model(context, rows)
    return context


def _attach_agent_model(context: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    agent_model = assemble_agent_model(rows, context)
    annotate_moments(context["story"], agent_model)
    # Per-event annotations now live on the moments; raw rows resolve through role_map.
    agent_model.pop("annotations", None)
    context["agent_model"] = agent_model


def build_trace_preview(rows: Any) -> dict[str, Any]:
    """Normalize browser-imported events using the live/replay presentation path.

    A JSONL upload contains events, not the evidence directory belonging to the
    server's active run. Never attach that run's media or artifacts to it.
    """
    if not isinstance(rows, list) or not rows:
        raise ValueError("Trace must contain at least one event object")
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("surface"), str):
            raise ValueError("Every event must be an object with a surface")
        if not isinstance(row.get("sequence_num"), int) or row["sequence_num"] < 1:
            raise ValueError("Every event must have a positive integer sequence_num")
        if "dashboard_sequence_num" in row and (
            not isinstance(row["dashboard_sequence_num"], int) or row["dashboard_sequence_num"] < 1
        ):
            raise ValueError("dashboard_sequence_num must be a positive integer")
        for field in ("result", "metadata", "tool_args"):
            if row.get(field) is not None and not isinstance(row[field], dict):
                raise ValueError(f"{field} must be an object")
        for field in ("evidence_ids", "frame_indices"):
            if row.get(field) is not None and not isinstance(row[field], list):
                raise ValueError(f"{field} must be an array")
        unique.setdefault(global_event_id(row), dict(row))
    events = sorted(unique.values(), key=event_sequence)
    context = build_run_context(None, events, None)
    context.update(video_available=False, audio_available=False, imported_trace=True)
    context["media_notice"] = "Imported events only. Replay the trace with its evidence directory to view source media and artifacts."
    return {"events": events, "context": context, "summary": summarize(events, Path("Imported browser trace"))}


def _branch_result(branch: CaseBranch, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if branch.result_path is None or not rows:
        return {}
    records = _result_records(branch.result_path)
    run_id = branch.run_id or str(rows[0].get("run_id", ""))
    if run_id:
        return next(
            (item for item in records if str(item.get("run_id", "")) == run_id),
            {},
        )
    return records[-1] if records else {}


def build_case_context(
    manifest: CaseManifest,
    branch_rows: dict[str, list[dict[str, Any]]],
    merged_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compose independent branch contexts without inventing a fused verdict."""
    contexts: dict[str, dict[str, Any]] = {}
    for branch in manifest.branches:
        contexts[branch.name] = build_run_context(
            resolve_active_trace(branch.trace_path, started_after=branch.trace_started_after), branch_rows.get(branch.name, []),
            branch.evidence_root or infer_evidence_root(branch.trace_path),
            branch.memory_root or infer_memory_root(branch.trace_path),
            result_override=_branch_result(branch, branch_rows.get(branch.name, [])),
        )
    visual = next(
        (contexts[item.name] for item in manifest.branches if item.modality in {"image", "video"}),
        {},
    )
    audio = next(
        (contexts[item.name] for item in manifest.branches if item.modality == "audio"),
        {},
    )
    evidence: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    for branch in manifest.branches:
        if branch.modality == "audiovisual":
            continue
        for record in contexts[branch.name].get("evidence", []):
            item = dict(record)
            item.setdefault("run_id", contexts[branch.name].get("run_id", branch.run_id))
            item["case_branch"] = branch.name
            evidence.append(item)
        for record in contexts[branch.name].get("artifacts", []):
            item = dict(record)
            item["case_branch"] = branch.name
            artifacts.append(item)
    context = dict(visual or audio)
    context.update({
        "run_id": manifest.case_id,
        "case_id": manifest.case_id,
        "source_media_id": manifest.source_media_id,
        "modalities": list(manifest.modalities),
        "dashboard_mode": "combined" if visual and audio else "audio" if audio else "visual",
        "simulation_fixture": manifest.simulation_fixture or any(
            bool(item.get("simulation_fixture")) for item in contexts.values()
        ),
        "branch_contexts": contexts,
        "evidence": evidence,
        "artifacts": artifacts,
        "audio_evidence": [item for item in evidence if str(item.get("evidence_id", "")).startswith("audio_ev_")],
        "audio_enabled": bool(audio),
        "audio_metadata": dict(audio.get("audio_metadata") or {}),
        "audio_path": audio.get("audio_path", ""),
        "audio_available": bool(audio.get("audio_available")),
        "tooldf_original_prediction": audio.get("tooldf_original_prediction"),
        "audio_investigation_assessment": audio.get("audio_investigation_assessment"),
        "audio_mode": audio.get("audio_mode", "baseline"),
        "forensic_verification_assessment": audio.get("forensic_verification_assessment", "not_run"),
        "verification_summary": audio.get("verification_summary", {}),
        "audio_references": audio.get("audio_references", []),
        "audio_topology": audio.get("audio_topology", "direct"),
        "visual_prediction": visual.get("original_prediction"),
        "visual_investigation_assessment": visual.get("visual_investigation_assessment", "unavailable"),
        "case_assessment": next(
            (
                (row.get("result") or {}).get("case_assessment")
                for row in merged_rows
                if row.get("surface") == "audiovisual_case_review"
                and isinstance(row.get("result"), dict)
            ),
            "unavailable",
        ),
        "verdicts_independent": True,
    })
    if manifest.source_media_path and manifest.source_media_path.is_file():
        context["video_path"] = str(manifest.source_media_path)
        context["video_available"] = manifest.source_media_path.suffix.lower() not in {
            ".wav", ".flac", ".mp3", ".ogg", ".m4a",
        }
    if manifest.audio_offset_seconds is not None:
        context["audio_metadata"]["audio_offset_seconds"] = manifest.audio_offset_seconds
        context["alignment_available"] = True
    else:
        context["alignment_available"] = False
    context["story"] = assemble_story(merged_rows, context)
    context["observability"] = assemble_tool_observability(merged_rows, context)
    _attach_agent_model(context, merged_rows)
    if manifest.time_mapping_path and manifest.time_mapping_path.is_file():
        timing = json.loads(manifest.time_mapping_path.read_text())
        # Full source PTS are timeline metadata, not investigator conclusions.
        context["av_timing"] = timing
        context["alignment_available"] = timing.get("quality") in {"verified", "estimated"}
    if manifest.crossmodal_board_path and manifest.crossmodal_board_path.is_file():
        context["crossmodal_board"] = json.loads(manifest.crossmodal_board_path.read_text())
    context["crossmodal_events"] = [r for r in merged_rows if str(r.get("surface", "")).startswith(("crossmodal_", "av_")) or r.get("surface") == "case_review_completed"]
    return context


@lru_cache(maxsize=256)
def extract_video_frame(
    video_path: Path, timestamp: float = 0.0, source_frame_index: int | None = None
) -> bytes:
    """Decode one source-video frame as JPEG for codec-independent browser display."""
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - project runtime installs OpenCV
        raise RuntimeError("OpenCV is required to render source frames") from exc
    capture = cv2.VideoCapture(str(video_path))
    try:
        if not capture.isOpened():
            raise RuntimeError(f"Could not open video: {video_path}")
        if source_frame_index is not None:
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(source_frame_index))
        else:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
        ok, frame = capture.read()
        if not ok or frame is None:
            raise RuntimeError(f"Could not decode video at {timestamp:.3f}s")
        encoded, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not encoded:
            raise RuntimeError("Could not encode source frame")
        return buffer.tobytes()
    finally:
        capture.release()


def map_processed_roi_to_source(
    roi: Sequence[int | float], transform: dict[str, Any]
) -> tuple[int, int, int, int]:
    """Map an exact processed-frame ROI through recorded resize/padding geometry."""
    if len(roi) != 4:
        raise ValueError("ROI must contain four coordinates")
    scale_x = float(transform.get("scale_x", 0))
    scale_y = float(transform.get("scale_y", 0))
    if not math.isfinite(scale_x) or not math.isfinite(scale_y) or scale_x <= 0 or scale_y <= 0:
        raise ValueError("Recorded ROI transform has invalid scale")
    offset_x = float(transform.get("offset_x", 0))
    offset_y = float(transform.get("offset_y", 0))
    if not math.isfinite(offset_x) or not math.isfinite(offset_y):
        raise ValueError("Recorded ROI transform has invalid padding offset")
    mapped = (
        int(round((float(roi[0]) - offset_x) / scale_x)),
        int(round((float(roi[1]) - offset_y) / scale_y)),
        int(round((float(roi[2]) - offset_x) / scale_x)),
        int(round((float(roi[3]) - offset_y) / scale_y)),
    )
    if mapped[0] >= mapped[2] or mapped[1] >= mapped[3]:
        raise ValueError("Mapped ROI is empty")
    return mapped


@dataclass(frozen=True)
class DashboardConfig:
    trace_path: Path
    host: str = "127.0.0.1"
    port: int = 8765
    evidence_root: Path | None = None
    memory_root: Path | None = None
    poll_interval: float = 0.35
    case_path: Path | None = None

    def normalized(self) -> "DashboardConfig":
        trace = self.trace_path.expanduser().resolve()
        if not trace.exists():
            raise FileNotFoundError(trace)
        if trace.is_file() and trace.suffix != ".jsonl":
            raise ValueError("ARGUS dashboard expects a normalized .jsonl trace or directory")
        if not trace.is_file() and not trace.is_dir():
            raise ValueError("trace source must be a file or directory")
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be in [0, 65535]")
        if self.poll_interval <= 0:
            raise ValueError("poll interval must be positive")
        case = self.case_path.expanduser().resolve(strict=True) if self.case_path else None
        if case is not None:
            load_case_manifest(case)
        evidence = (
            self.evidence_root.expanduser().resolve()
            if self.evidence_root
            else infer_evidence_root(trace)
        )
        memory = (
            self.memory_root.expanduser().resolve()
            if self.memory_root
            else infer_memory_root(trace)
        )
        return DashboardConfig(
            trace, self.host, self.port, evidence, memory, self.poll_interval, case
        )


def read_trace(path: Path) -> list[dict[str, Any]]:
    """Read complete JSONL rows and tolerate one in-flight partial final line."""
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        lines = handle.readlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                break
            raise
        if isinstance(value, dict):
            rows.append(value)
    return rows


class IncrementalTraceReader:
    """Tail one JSONL trace without reparsing its completed prefix."""

    def __init__(self) -> None:
        self._path: Path | None = None
        self._inode: int | None = None
        self._offset = 0
        self._tail = b""
        self._rows: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def read(self, path: Path | None) -> list[dict[str, Any]]:
        if path is None:
            return []
        resolved = path.resolve()
        with self._lock:
            stat = resolved.stat()
            if (
                resolved != self._path
                or stat.st_ino != self._inode
                or stat.st_size < self._offset
            ):
                self._path = resolved
                self._inode = stat.st_ino
                self._offset = 0
                self._tail = b""
                self._rows = []
            if stat.st_size == self._offset:
                return list(self._rows)
            with resolved.open("rb") as handle:
                handle.seek(self._offset)
                chunk = handle.read()
                self._offset = handle.tell()
            data = self._tail + chunk
            lines = data.split(b"\n")
            self._tail = lines.pop() if lines else data
            for line in lines:
                if not line.strip():
                    continue
                value = json.loads(line.decode("utf-8"))
                if isinstance(value, dict):
                    self._rows.append(value)
            return list(self._rows)


def stream_sequence(row: dict[str, Any]) -> int:
    """Monotonic SSE cursor: arrival order in a case, trace order otherwise."""
    return int(row.get("stream_sequence_num") or event_sequence(row))


def summarize(rows: list[dict[str, Any]], trace_path: Path) -> dict[str, Any]:
    surfaces: dict[str, int] = {}
    agents: dict[str, dict[str, Any]] = {}
    for row in rows:
        surface = str(row.get("surface", "unknown"))
        surfaces[surface] = surfaces.get(surface, 0) + 1
        role = str(row.get("agent_role", "unknown"))
        item = agents.setdefault(
            role,
            {"events": 0, "tool_calls": 0, "evidence": 0, "errors": 0, "last_surface": ""},
        )
        item["events"] += 1
        item["tool_calls"] += int(surface == "tool_call")
        item["evidence"] += int(surface in {"evidence_created", "audio_evidence_created"})
        item["errors"] += int(row.get("status") == "error")
        item["last_surface"] = surface
    first = rows[0] if rows else {}
    last = rows[-1] if rows else {}
    return {
        "trace_path": str(trace_path),
        "run_id": first.get("run_id"),
        "video_id": first.get("video_id"),
        "harness": first.get("harness"),
        "event_count": len(rows),
        "meaningful_event_count": sum(row.get("surface") != "native_event" for row in rows),
        "surfaces": surfaces,
        "agents": agents,
        # Native CLI events may be merged after the domain run-completed event.
        "complete": any(row.get("surface") == "run_completed" for row in rows),
        "last_sequence": event_sequence(last),
        "last_stream_sequence": max((stream_sequence(row) for row in rows), default=0),
        "error_count": sum(row.get("status") == "error" for row in rows),
    }


class TraceDashboardServer:
    def __init__(self, config: DashboardConfig) -> None:
        self.config = config.normalized()
        self.httpd: ThreadingHTTPServer | None = None
        self._trace_reader = IncrementalTraceReader()
        self.case_manifest = (
            load_case_manifest(self.config.case_path) if self.config.case_path else None
        )
        self._case_readers = {
            branch.name: IncrementalTraceReader()
            for branch in (self.case_manifest.branches if self.case_manifest else ())
        }
        # Display order in a case may shift when a late branch event arrives;
        # the SSE cursor therefore uses a stable first-seen arrival index.
        self._stream_ids: dict[str, int] = {}
        self._stream_lock = threading.Lock()

    def _case_rows(self) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        if self.case_manifest is None:
            return {}, []
        branches = {
            branch.name: self._case_readers[branch.name].read(
                resolve_active_trace(branch.trace_path, started_after=branch.trace_started_after)
            )
            for branch in self.case_manifest.branches
        }
        merged = merge_case_rows(
            (branch, branches[branch.name]) for branch in self.case_manifest.branches
        )
        with self._stream_lock:
            for row in merged:
                row["stream_sequence_num"] = self._stream_ids.setdefault(
                    str(row["global_event_id"]), len(self._stream_ids) + 1
                )
        return branches, merged

    def bind(self) -> ThreadingHTTPServer:
        """Bind synchronously so launchers can report port conflicts cleanly."""
        if self.httpd is not None:
            return self.httpd
        try:
            self.httpd = ThreadingHTTPServer(
                (self.config.host, self.config.port), self._handler()
            )
        except OSError as exc:
            if exc.errno in {48, 98, 10048}:
                raise OSError(
                    exc.errno,
                    f"Dashboard address {self.config.host}:{self.config.port} is already in use; "
                    "stop the existing dashboard or choose another --port",
                ) from exc
            raise
        return self.httpd

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        config = self.config
        trace_reader = self._trace_reader
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ARGUSTraceDashboard/1.0"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _headers(self, content_type: str, length: int | None = None) -> None:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                if length is not None:
                    self.send_header("Content-Length", str(length))
                self.end_headers()

            def _json(self, value: Any) -> None:
                data = json.dumps(value, ensure_ascii=False).encode("utf-8")
                self._headers("application/json; charset=utf-8", len(data))
                self.wfile.write(data)

            def _not_found(self) -> None:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")

            def _active_path(self) -> Path | None:
                if dashboard.case_manifest is not None:
                    return None  # Branch discovery must not reset the case's SSE cursor.
                return resolve_active_trace(config.trace_path)

            def _all_rows(self, path: Path | None = None) -> list[dict[str, Any]]:
                if dashboard.case_manifest is not None:
                    return dashboard._case_rows()[1]
                active = path or self._active_path()
                return trace_reader.read(active)

            def _context(self) -> dict[str, Any]:
                if dashboard.case_manifest is not None:
                    branches, merged = dashboard._case_rows()
                    return build_case_context(dashboard.case_manifest, branches, merged)
                active = self._active_path()
                return build_run_context(
                    active, trace_reader.read(active), config.evidence_root, config.memory_root
                )

            def _evidence_roots(self, record: dict[str, Any] | None = None) -> list[Path]:
                if dashboard.case_manifest is None:
                    return [config.evidence_root] if config.evidence_root else []
                branch_name = str((record or {}).get("case_branch", ""))
                roots: list[Path] = []
                for branch in dashboard.case_manifest.branches:
                    if branch_name and branch.name != branch_name:
                        continue
                    root = branch.evidence_root or infer_evidence_root(branch.trace_path)
                    if root is not None:
                        roots.append(root)
                return roots

            def _events(self, after: int = 0, path: Path | None = None) -> list[dict[str, Any]]:
                active = path or self._active_path()
                if active is None and dashboard.case_manifest is None:
                    return []
                rows = [row for row in self._all_rows(active) if stream_sequence(row) > after]
                return sorted(rows, key=stream_sequence)

            def _summary(self, path: Path | None = None) -> dict[str, Any]:
                active = path or self._active_path()
                if active is None and dashboard.case_manifest is None:
                    value = summarize([], config.trace_path)
                    value["waiting_for_trace"] = True
                    return value
                rows = self._all_rows(active)
                value = summarize(rows, dashboard.case_manifest.path if dashboard.case_manifest else active)
                if dashboard.case_manifest is not None:
                    value.update({
                        "run_id": dashboard.case_manifest.case_id,
                        "video_id": dashboard.case_manifest.source_media_id,
                        "harness": "multimodal-case",
                        "modalities": list(dashboard.case_manifest.modalities),
                        "complete": all(
                            any(row.get("surface") == "run_completed" for row in branch_rows)
                            for branch_rows in dashboard._case_rows()[0].values()
                        ),
                    })
                return value

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                if urlparse(self.path).path != "/api/trace-preview":
                    self._not_found()
                    return
                if self.headers.get_content_type() != "application/json":
                    self.send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Expected application/json")
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 16 * 1024 * 1024:
                        self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Trace preview accepts up to 16 MiB")
                        return
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError("Expected an object containing events")
                    preview = build_trace_preview(payload.get("events"))
                except (ValueError, TypeError, OverflowError) as exc:
                    self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                    return
                self._json(preview)

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                parsed = urlparse(self.path)
                if parsed.path == "/api/events":
                    try:
                        after = max(0, int(parse_qs(parsed.query).get("after", ["0"])[0]))
                    except ValueError:
                        self.send_error(HTTPStatus.BAD_REQUEST, "after must be an integer")
                        return
                    active = self._active_path()
                    rows = self._events(after, active)
                    self._json({"events": rows, "summary": self._summary(active)})
                    return
                if parsed.path == "/api/meta":
                    self._json(self._summary())
                    return
                if parsed.path == "/api/context":
                    self._json(self._context())
                    return
                if parsed.path == "/api/av-artifact":
                    self._av_artifact(parsed.query)
                    return
                if parsed.path == "/api/stream":
                    self._stream(parsed.query)
                    return
                if parsed.path == "/api/artifact":
                    self._artifact(parsed.query)
                    return
                if parsed.path == "/api/reusable-artifact":
                    self._reusable_artifact(parsed.query)
                    return
                if parsed.path == "/api/video":
                    self._video()
                    return
                if parsed.path == "/api/audio":
                    self._audio()
                    return
                if parsed.path == "/api/audio-waveform":
                    self._audio_metadata_artifact("waveform_ref", "application/json; charset=utf-8")
                    return
                if parsed.path == "/api/audio-spectrogram":
                    self._audio_metadata_artifact("spectrogram_ref", "image/png")
                    return
                if parsed.path == "/api/audio-stem":
                    self._audio_stem(parsed.query)
                    return
                if parsed.path == "/api/reference-audio":
                    self._reference_audio(parsed.query)
                    return
                if parsed.path == "/api/frame":
                    self._frame(parsed.query)
                    return
                if parsed.path == "/api/crop":
                    self._crop(parsed.query)
                    return
                if parsed.path == "/api/input-crop":
                    self._input_crop(parsed.query)
                    return
                if parsed.path == "/api/reference-frame":
                    self._reference_frame(parsed.query)
                    return
                if parsed.path == "/api/raw":
                    active = self._active_path()
                    if active is None and dashboard.case_manifest is None:
                        self._not_found()
                        return
                    if dashboard.case_manifest is not None:
                        data = "".join(
                            json.dumps(row, ensure_ascii=False) + "\n"
                            for row in self._all_rows()
                        ).encode("utf-8")
                        self._headers("application/x-ndjson; charset=utf-8", len(data))
                        self.wfile.write(data)
                    else:
                        self._serve_file(active, "application/x-ndjson; charset=utf-8")
                    return
                asset = "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
                candidate = (STATIC_ROOT / asset).resolve()
                if STATIC_ROOT.resolve() not in candidate.parents or not candidate.is_file():
                    self._not_found()
                    return
                self._serve_file(candidate)

            def _stream(self, query: str) -> None:
                try:
                    after = max(0, int(parse_qs(query).get("after", ["0"])[0]))
                except ValueError:
                    self.send_error(HTTPStatus.BAD_REQUEST, "after must be an integer")
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                idle = 0
                active = self._active_path()
                try:
                    while True:
                        latest = self._active_path()
                        if latest != active:
                            active = latest
                            after = 0
                            payload = json.dumps(self._summary(active), ensure_ascii=False)
                            self.wfile.write(f"event: reset\ndata: {payload}\n\n".encode("utf-8"))
                        rows = self._events(after, active)
                        for row in rows:
                            after = stream_sequence(row)
                            payload = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                            self.wfile.write(f"id: {after}\nevent: trace\ndata: {payload}\n\n".encode("utf-8"))
                            idle = 0
                        if not rows:
                            idle += 1
                            if idle % max(1, int(10 / config.poll_interval)) == 0:
                                self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        time.sleep(config.poll_interval)
                except (BrokenPipeError, ConnectionResetError):
                    return

            def _artifact(self, query: str) -> None:
                evidence_id = parse_qs(query).get("id", [""])[0]
                if not EVIDENCE_ID.fullmatch(evidence_id):
                    self._not_found()
                    return
                context = self._context()
                record = next((item for item in context.get("evidence", []) if item.get("evidence_id") == evidence_id), None)
                run_id = str((record or {}).get("run_id", context.get("run_id", "")))
                candidates = tuple(
                    candidate
                    for root in self._evidence_roots(record)
                    for candidate in (
                        root / run_id / "artifacts" / f"{evidence_id}.png",
                        root / "artifacts" / f"{evidence_id}.png",
                    )
                )
                artifact = next((path for path in candidates if path.is_file()), None)
                if artifact is None:
                    self._not_found()
                    return
                self._serve_file(artifact, "image/png")

            def _reusable_artifact(self, query: str) -> None:
                artifact_id = parse_qs(query).get("id", [""])[0]
                if not REUSABLE_ARTIFACT_ID.fullmatch(artifact_id):
                    self.send_error(HTTPStatus.BAD_REQUEST, "invalid artifact id")
                    return
                context = self._context()
                record = next(
                    (item for item in context.get("artifacts", [])
                     if item.get("artifact_id") == artifact_id), None
                )
                if record is None:
                    self.send_error(HTTPStatus.NOT_FOUND, "artifact not found")
                    return
                run_id = str(record.get("run_id", ""))
                candidates: list[Path] = []
                for root in self._evidence_roots():
                    directory = root / run_id / "reusable_artifacts"
                    candidates.extend(directory.glob(f"{artifact_id}.*"))
                payload = next((path for path in candidates if path.is_file()), None)
                if payload is None:
                    self.send_error(HTTPStatus.NOT_FOUND, "artifact payload not found")
                    return
                mime = str(record.get("mime_type") or mimetypes.guess_type(payload.name)[0]
                           or "application/octet-stream")
                self._serve_file(payload, mime)

            def _video(self) -> None:
                context = self._context()
                source = Path(str(context.get("video_path", "")))
                if not source.is_file():
                    self._not_found()
                    return
                size = source.stat().st_size
                start, end = 0, max(0, size - 1)
                status = HTTPStatus.OK
                requested = self.headers.get("Range", "")
                match = BYTE_RANGE.fullmatch(requested)
                if requested and not match:
                    self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    return
                if match:
                    if match.group(1):
                        start = int(match.group(1))
                    if match.group(2):
                        end = min(end, int(match.group(2)))
                    if not match.group(1) and match.group(2):
                        start = max(0, size - int(match.group(2)))
                    if start > end or start >= size:
                        self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                        return
                    status = HTTPStatus.PARTIAL_CONTENT
                length = end - start + 1
                self.send_response(status)
                self.send_header("Content-Type", mimetypes.guess_type(source.name)[0] or "video/mp4")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                if status == HTTPStatus.PARTIAL_CONTENT:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Cache-Control", "private, max-age=60")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                with source.open("rb") as handle:
                    handle.seek(start)
                    remaining = length
                    while remaining:
                        chunk = handle.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)

            def _audio(self) -> None:
                context = self._context()
                source = Path(str(context.get("audio_path", "")))
                if not source.is_file():
                    self._not_found()
                    return
                self._serve_range(source, "audio/wav")

            def _audio_metadata_artifact(self, field: str, content_type: str) -> None:
                context = self._context()
                source = Path(str((context.get("audio_metadata") or {}).get(field, "")))
                audio_path = Path(str(context.get("audio_path", "")))
                if not source.is_file() or not audio_path.is_file() or audio_path.parent.resolve() not in source.resolve().parents:
                    self._not_found()
                    return
                self._serve_file(source, content_type)

            def _audio_stem(self, query: str) -> None:
                evidence_id = parse_qs(query).get("id", [""])[0]
                stem = parse_qs(query).get("stem", [""])[0]
                if not EVIDENCE_ID.fullmatch(evidence_id) or stem not in {"vocals", "background"}:
                    self._not_found()
                    return
                context = self._context()
                record = next((item for item in context.get("audio_evidence", []) if item.get("evidence_id") == evidence_id), None)
                if not record:
                    self._not_found()
                    return
                refs = [Path(str(value)).resolve() for value in record.get("artifact_refs", [])]
                source = next((path for path in refs if path.name == f"{stem}.wav" and path.is_file()), None)
                audio_path = Path(str(context.get("audio_path", "")))
                if source is None or not audio_path.is_file() or audio_path.parent.resolve() not in source.parents:
                    self._not_found()
                    return
                self._serve_range(source, "audio/wav")

            def _reference_audio(self, query: str) -> None:
                reference_id = parse_qs(query).get("id", [""])[0]
                if not re.fullmatch(r"ref_[a-f0-9]{12}", reference_id):
                    self._not_found()
                    return
                context = self._context()
                record = next(
                    (item for item in context.get("audio_references", [])
                     if item.get("reference_id") == reference_id), None,
                )
                if not record:
                    self._not_found()
                    return
                source = Path(str(record.get("local_audio_ref", ""))).expanduser().resolve()
                if not source.is_file() or source.name.startswith("."):
                    self._not_found()
                    return
                self._serve_range(source, mimetypes.guess_type(source.name)[0] or "audio/wav")

            def _serve_range(self, source: Path, content_type: str) -> None:
                size = source.stat().st_size
                start, end = 0, max(0, size - 1)
                status = HTTPStatus.OK
                requested = self.headers.get("Range", "")
                match = BYTE_RANGE.fullmatch(requested)
                if requested and not match:
                    self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    return
                if match:
                    if match.group(1):
                        start = int(match.group(1))
                    if match.group(2):
                        end = min(end, int(match.group(2)))
                    if not match.group(1) and match.group(2):
                        start = max(0, size - int(match.group(2)))
                    if start > end or start >= size:
                        self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                        return
                    status = HTTPStatus.PARTIAL_CONTENT
                length = end - start + 1
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                if status == HTTPStatus.PARTIAL_CONTENT:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Cache-Control", "private, max-age=60")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                with source.open("rb") as handle:
                    handle.seek(start)
                    remaining = length
                    while remaining:
                        chunk = handle.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)

            def _reference_frame(self, query: str) -> None:
                values = parse_qs(query)
                evidence_id = values.get("id", [""])[0]
                if not EVIDENCE_ID.fullmatch(evidence_id):
                    self._not_found()
                    return
                context = self._context()
                record = next((item for item in context.get("evidence", [])
                               if item.get("evidence_id") == evidence_id), None)
                if not record or not record.get("reference_source"):
                    self._not_found()
                    return
                source = Path(str(record["reference_source"])).expanduser().resolve()
                if not source.is_file():
                    self._not_found()
                    return
                try:
                    sample = int(values.get("sample", [str((record.get("reference_frame_indices") or [0])[0])])[0])
                    if source.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                        from PIL import Image
                        import io
                        with Image.open(source) as image:
                            buffer = io.BytesIO()
                            image.convert("RGB").save(buffer, format="JPEG", quality=90)
                            data = buffer.getvalue()
                    else:
                        import cv2
                        capture = cv2.VideoCapture(str(source))
                        count = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
                        candidates = min(32, count)
                        source_index = int(round(sample * max(0, count - 1) / max(1, candidates - 1)))
                        capture.set(cv2.CAP_PROP_POS_FRAMES, source_index)
                        ok, frame = capture.read()
                        capture.release()
                        if not ok:
                            raise RuntimeError("Could not decode reference frame")
                        encoded, payload = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                        if not encoded:
                            raise RuntimeError("Could not encode reference frame")
                        data = payload.tobytes()
                except (ValueError, RuntimeError, OSError) as exc:
                    self.send_error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc))
                    return
                self._headers("image/jpeg", len(data))
                self.wfile.write(data)

            def _evidence_selection(
                self, query: str
            ) -> tuple[dict[str, Any], dict[str, Any], int] | None:
                values = parse_qs(query)
                evidence_id = values.get("id", [""])[0]
                if not EVIDENCE_ID.fullmatch(evidence_id):
                    return None
                context = self._context()
                record = next(
                    (
                        item for item in context.get("evidence", [])
                        if item.get("evidence_id") == evidence_id
                    ),
                    None,
                )
                if record is None:
                    return None
                try:
                    sampled_index = int(
                        values.get("sample", [str((record.get("frame_indices") or [0])[0])])[0]
                    )
                except ValueError:
                    return None
                return context, record, sampled_index

            @staticmethod
            def _reference(
                record: dict[str, Any], sampled_index: int
            ) -> tuple[dict[str, Any], int]:
                indices = [int(item) for item in record.get("frame_indices", [])]
                position = indices.index(sampled_index) if sampled_index in indices else 0
                references = record.get("frame_references") or []
                if position < len(references) and isinstance(references[position], dict):
                    return dict(references[position]), position
                timestamps = record.get("frame_timestamps") or []
                return {
                    "sampled_frame_index": indices[position] if indices else sampled_index,
                    "timestamp": timestamps[position] if position < len(timestamps) else None,
                    "timestamp_exact": False,
                    "timestamp_basis": "legacy_trace_without_source_mapping",
                }, position

            def _frame(self, query: str) -> None:
                selection = self._evidence_selection(query)
                context: dict[str, Any]
                reference: dict[str, Any]
                if selection:
                    context, record, sampled_index = selection
                    reference, _ = self._reference(record, sampled_index)
                    raw_timestamp = str(reference.get("timestamp", ""))
                    source_index = reference.get("source_frame_index")
                else:
                    values = parse_qs(query)
                    raw_timestamp = values.get("t", ["0"])[0]
                    source_index = None
                    context = self._context()
                try:
                    timestamp = float(raw_timestamp)
                except (TypeError, ValueError):
                    self.send_error(HTTPStatus.BAD_REQUEST, "t must be a number of seconds")
                    return
                if not math.isfinite(timestamp) or not 0 <= timestamp <= 86_400:
                    self.send_error(HTTPStatus.BAD_REQUEST, "t is outside the supported range")
                    return
                source = Path(str(context.get("video_path", "")))
                if not source.is_file():
                    self._not_found()
                    return
                try:
                    data = extract_video_frame(
                        source,
                        timestamp,
                        int(source_index) if source_index is not None else None,
                    )
                except RuntimeError as exc:
                    self.send_error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc))
                    return
                self._headers("image/jpeg", len(data))
                self.wfile.write(data)

            def _crop(self, query: str) -> None:
                selection = self._evidence_selection(query)
                if selection is None:
                    self._not_found()
                    return
                context, record, sampled_index = selection
                reference, position = self._reference(record, sampled_index)
                transform = reference.get("transform") or record.get("crop_transform") or {}
                if record.get("coordinate_space") != "processed_frame" or not transform:
                    self.send_error(
                        HTTPStatus.UNPROCESSABLE_ENTITY,
                        "Exact crop transform is unavailable for this evidence record",
                    )
                    return
                tracked = (record.get("summary_statistics") or {}).get("tracked_boxes") or []
                roi = tracked[position] if position < len(tracked) else record.get("roi")
                if not roi or len(roi) != 4:
                    self.send_error(HTTPStatus.UNPROCESSABLE_ENTITY, "Evidence has no ROI")
                    return
                try:
                    source_roi = map_processed_roi_to_source(roi, transform)
                except ValueError as exc:
                    self.send_error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc))
                    return
                source = Path(str(context.get("video_path", "")))
                if not source.is_file():
                    self._not_found()
                    return
                timestamp = float(reference.get("timestamp", 0) or 0)
                source_index = reference.get("source_frame_index")
                try:
                    frame = extract_video_frame(
                        source,
                        timestamp,
                        int(source_index) if source_index is not None else None,
                    )
                    with Image.open(io.BytesIO(frame)) as image:
                        x1, y1, x2, y2 = source_roi
                        x1, y1 = max(0, x1), max(0, y1)
                        x2, y2 = min(image.width, x2), min(image.height, y2)
                        if x1 >= x2 or y1 >= y2:
                            raise RuntimeError("Mapped ROI is outside the source frame")
                        crop = image.crop((x1, y1, x2, y2))
                        buffer = io.BytesIO()
                        crop.save(buffer, format="JPEG", quality=92)
                        data = buffer.getvalue()
                except (OSError, RuntimeError) as exc:
                    self.send_error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc))
                    return
                self._headers("image/jpeg", len(data))
                self.wfile.write(data)

            def _input_crop(self, query: str) -> None:
                """Serve the lossless processed pixels persisted at tool execution time."""
                selection = self._evidence_selection(query)
                if selection is None:
                    self._not_found()
                    return
                _, record, sampled_index = selection
                _, position = self._reference(record, sampled_index)
                refs = record.get("input_crop_refs") or []
                if position >= len(refs):
                    self._not_found()
                    return
                evidence_id = str(record.get("evidence_id", ""))
                run_id = str(record.get("run_id", ""))
                if not EVIDENCE_ID.fullmatch(evidence_id):
                    self._not_found()
                    return
                candidates = tuple(
                    candidate
                    for root in self._evidence_roots(record)
                    for candidate in (
                        root / run_id / "inputs" / f"{evidence_id}_{position:03d}.png",
                        root / "inputs" / f"{evidence_id}_{position:03d}.png",
                    )
                )
                crop = next((path for path in candidates if path.is_file()), None)
                if crop is None:
                    self._not_found()
                    return
                self._serve_file(crop, "image/png")

            def _av_artifact(self, query: str) -> None:
                manifest = dashboard.case_manifest
                if not manifest or not manifest.crossmodal_board_path:
                    self._not_found(); return
                values = parse_qs(query)
                board = self._context().get("crossmodal_board") or {}
                request = next((r for r in board.get("requests", []) if r["request_id"] == values.get("request", [""])[0]), None)
                if not request or not request.get("window"):
                    self._not_found(); return
                window = request["window"]
                kind = values.get("kind", [""])[0]
                try:
                    index = int(values.get("index", ["0"])[0])
                    if index < 0: raise ValueError("negative index")
                    if kind in {"audio", "waveform", "spectrogram"}:
                        candidate = window[kind + "_path"]
                    elif kind == "frame":
                        candidate = window["frames"][index]["path"]
                    elif kind == "sync-crop":
                        measured = next(e["measurements"] for e in board["evidence"]
                                        if e.get("request_id") == request["request_id"] and e.get("tool_name") == "estimate_lip_speech_synchrony")
                        track = next(t for t in measured["track_measurements"] if t["face_track_id"] == values.get("track", [""])[0])
                        candidate = track["crop_artifact"]
                    elif kind in {"face", "mouth"}:
                        tracks = next(e["measurements"]["candidate_face_tracks"] for e in board["evidence"]
                                      if e.get("request_id") == request["request_id"] and e.get("tool_name") == "locate_visible_speakers")
                        track = next(t for t in tracks if t["track_id"] == values.get("track", [""])[0])
                        candidate = track["frames"][index]["crop_path" if kind == "face" else "mouth_region_path"]
                    else:
                        self._not_found(); return
                    path = Path(candidate).resolve()
                    path.relative_to(manifest.crossmodal_board_path.parent.resolve())
                    if not path.is_file(): raise ValueError("Missing registered artifact")
                except (KeyError, IndexError, ValueError, StopIteration):
                    self._not_found(); return
                self._serve_file(path)

            def _serve_file(self, path: Path, content_type: str | None = None) -> None:
                data = path.read_bytes()
                mime = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self._headers(mime, len(data))
                self.wfile.write(data)

        return Handler

    def serve_forever(self) -> None:
        httpd = self.bind()
        host, port = httpd.server_address[:2]
        print(f"ARGUS trajectory dashboard: http://{host}:{port}", flush=True)
        mode = "directory" if self.config.trace_path.is_dir() else "trace"
        print(f"Watching {mode}: {self.config.trace_path}", flush=True)
        try:
            httpd.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay or live-tail an ARGUS normalized trajectory in a local dashboard."
    )
    parser.add_argument(
        "trace",
        type=Path,
        nargs="?",
        help="Normalized ARGUS JSONL trace, or a directory whose newest trace should be followed.",
    )
    parser.add_argument(
        "--case", dest="case_path", type=Path, default=None,
        help="Validated multimodal case manifest. Branch identities remain unchanged.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=None,
        help="Root containing <run_id>/artifacts/*.png, enabling evidence previews.",
    )
    parser.add_argument(
        "--memory-root",
        type=Path,
        default=None,
        help="Root containing <run_id>/entries/*.json investigation notebooks.",
    )
    parser.add_argument("--poll-interval", type=float, default=0.35)
    args = parser.parse_args(argv)
    if args.trace is None and args.case_path is None:
        parser.error("provide a trace/directory or --case manifest.json")
    return args


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    case = load_case_manifest(args.case_path) if args.case_path else None
    trace = args.trace or (case.branches[0].trace_path if case else None)
    assert trace is not None
    TraceDashboardServer(
        DashboardConfig(
            trace_path=trace,
            host=args.host,
            port=args.port,
            evidence_root=args.evidence_root,
            memory_root=args.memory_root,
            poll_interval=args.poll_interval,
            case_path=args.case_path,
        )
    ).serve_forever()


if __name__ == "__main__":
    main()
