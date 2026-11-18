"""Validated multimodal case manifests and stable cross-run replay ordering."""

from __future__ import annotations

import heapq
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ALLOWED_MODALITIES = frozenset({"image", "video", "audio", "audiovisual"})


@dataclass(frozen=True)
class CaseBranch:
    name: str
    modality: str
    run_id: str
    trace_path: Path
    result_path: Path | None
    evidence_root: Path | None
    memory_root: Path | None
    trace_started_after: float = 0.0


@dataclass(frozen=True)
class CaseManifest:
    path: Path
    case_id: str
    source_media_id: str
    source_media_path: Path | None
    modalities: tuple[str, ...]
    audio_offset_seconds: float | None
    branches: tuple[CaseBranch, ...]
    simulation_fixture: bool = False
    time_mapping_path: Path | None = None
    crossmodal_board_path: Path | None = None


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_owned(base: Path, value: Any, *, required: bool) -> Path | None:
    if value in {None, ""}:
        if required:
            raise ValueError("A required case-manifest path is missing")
        return None
    candidate = Path(str(value)).expanduser()
    candidate = (base / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    # Trace/result/evidence paths are run-owned dashboard inputs. Keeping them
    # below the manifest directory prevents a browser-selected manifest from
    # becoming a general local-file resolver.
    if not _inside(candidate, base):
        raise ValueError(f"Case path escapes its manifest directory: {value}")
    if required and not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def load_case_manifest(path: Path) -> CaseManifest:
    manifest_path = Path(path).expanduser().resolve(strict=True)
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Case manifest must be a JSON object")
    case_id = str(value.get("case_id", "")).strip()
    if not case_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in case_id):
        raise ValueError("case_id must contain only letters, digits, '_' or '-'")
    base = manifest_path.parent.resolve()
    declared = tuple(str(item).lower() for item in value.get("modalities", ()))
    if not declared or any(item not in ALLOWED_MODALITIES for item in declared):
        raise ValueError("modalities must contain image, video, audio, or audiovisual")
    runs = value.get("runs")
    if not isinstance(runs, dict) or not runs:
        raise ValueError("Case manifest must contain at least one run")
    branches: list[CaseBranch] = []
    for name, raw in runs.items():
        if not isinstance(raw, dict):
            raise ValueError(f"Run {name!r} must be an object")
        modality = str(raw.get("modality") or name).lower()
        if modality not in ALLOWED_MODALITIES:
            raise ValueError(f"Unsupported modality for run {name!r}: {modality}")
        watch_directory = raw.get("watch_directory") is True
        trace = _resolve_owned(base, raw.get("trace_path"), required=not watch_directory)
        if watch_directory and (trace is None or not trace.is_dir()):
            raise ValueError(f"Run {name!r} must name an existing trace directory")
        assert trace is not None
        result = _resolve_owned(base, raw.get("result_path"), required=False)
        evidence = _resolve_owned(base, raw.get("evidence_root"), required=False)
        memory = _resolve_owned(base, raw.get("memory_root"), required=False)
        branches.append(CaseBranch(
            name=str(name), modality=modality, run_id=str(raw.get("run_id", "")),
            trace_path=trace, result_path=result, evidence_root=evidence,
            memory_root=memory,
            trace_started_after=float(raw.get("trace_started_after", 0.0)),
        ))
    source_value = value.get("source_media_path")
    source = Path(str(source_value)).expanduser().resolve() if source_value else None
    offset = value.get("audio_offset_seconds")
    return CaseManifest(
        path=manifest_path, case_id=case_id,
        source_media_id=str(value.get("source_media_id", "")),
        source_media_path=source, modalities=declared,
        audio_offset_seconds=float(offset) if offset is not None else None,
        branches=tuple(branches),
        simulation_fixture=bool(value.get("simulation_fixture", False)),
        time_mapping_path=_resolve_owned(base, value.get("time_mapping_path"), required=False),
        crossmodal_board_path=_resolve_owned(base, value.get("crossmodal_board_path"), required=False),
    )


def _timestamp_key(value: Any) -> tuple[int, str]:
    text = str(value or "")
    try:
        return (0, datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat())
    except ValueError:
        return (1, text)


def merge_case_rows(
    branch_rows: Iterable[tuple[CaseBranch, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """Merge branches without replacing their original run/event/sequence IDs.

    Concurrent branches interleave by timestamp, but a k-way merge never
    reorders events *within* a branch, so a tool result can never be placed
    before its own call even when a branch clock is not monotonic.
    """
    streams: list[list[tuple[tuple[Any, ...], dict[str, Any]]]] = []
    for branch_index, (branch, rows) in enumerate(branch_rows):
        decorated: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        for row_index, source in enumerate(rows):
            row = dict(source)
            metadata = dict(row.get("metadata") or {})
            metadata.setdefault("modality", branch.modality)
            metadata["case_branch"] = branch.name
            row["metadata"] = metadata
            row["global_event_id"] = f"{row.get('run_id', branch.run_id)}:{row.get('event_id', row_index)}"
            decorated.append(((
                _timestamp_key(row.get("timestamp")), branch_index,
                int(row.get("sequence_num", 0) or 0), row_index,
            ), row))
        streams.append(decorated)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, row in heapq.merge(*streams, key=lambda item: item[0]):
        if row["global_event_id"] in seen:
            continue
        seen.add(row["global_event_id"])
        row["dashboard_sequence_num"] = len(merged) + 1
        merged.append(row)
    return merged
