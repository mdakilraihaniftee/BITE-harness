"""Safe persisted-run loading and public replay reconstruction."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .topology import ActivityMapper, build_topology, sanitize

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def safe_run_dir(root: Path, run_id: str) -> Path:
    if not _RUN_ID.fullmatch(run_id):
        raise KeyError(run_id)
    root = root.resolve()
    path = (root / run_id).resolve()
    if path.parent != root or not path.is_dir() or path.is_symlink():
        raise KeyError(run_id)
    return path


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    values = []
    for line in lines:
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                values.append(value)
        except json.JSONDecodeError:
            # The final line may be in flight. It becomes visible on the next poll.
            continue
    return values


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    """Upgrade pre-Studio orchestration records without inventing new evidence."""
    if event.get("schema_version") == "studio.event.v1":
        return event
    event_type = str(event.get("event_type", "UNKNOWN"))
    return {
        "schema_version": "studio.event.v1",
        "run_id": str(event.get("run_id", "unknown")),
        "task_id": str(event.get("task_id", "unknown")),
        "agent_id": str(event.get("agent_id", "unknown")),
        "event_id": str(event.get("event_id", f"legacy_{event.get('sequence', 0)}")),
        "sequence": int(event.get("sequence", 0)),
        "timestamp": str(event.get("timestamp", "")),
        "event_type": event_type,
        "parent_event_id": None,
        "causal_refs": [],
        "tool_name": None,
        "status": "completed",
        "summary": event_type.replace("_", " ").capitalize(),
        "artifact_refs": [],
        "payload": event.get("payload")
        if isinstance(event.get("payload"), dict)
        else {},
    }


def list_runs(root: Path) -> list[dict[str, Any]]:
    root.mkdir(parents=True, exist_ok=True)
    result = []
    for path in root.iterdir():
        if not path.is_dir() or path.is_symlink() or not _RUN_ID.fullmatch(path.name):
            continue
        manifest = read_json(path / "run_manifest.json", {}) or {}
        state = read_json(path / "run_state.json", {}) or {}
        final = read_json(path / "final_result.json", {}) or {}
        events = read_jsonl(path / "events.jsonl")
        result.append(
            {
                "run_id": path.name,
                "task": manifest.get("original_task"),
                "status": state.get("status") or final.get("run_status") or "RUNNING",
                "worker_count": manifest.get("worker_count"),
                "effective_config": manifest.get("effective_config"),
                "created_at": manifest.get("created_at")
                or (events[0].get("timestamp") if events else None),
                "event_count": len(events),
            }
        )
    return sorted(result, key=lambda item: item.get("created_at") or "", reverse=True)


class RunEventCache:
    """Incrementally read a run's append-only event log and annotate activity.

    Each poll reads only bytes appended since the previous poll. A trailing
    partial line stays unread until it is complete. The topology (and so the
    activity mapper) is rebuilt only when the manifest changes or a new
    observed component appears; otherwise annotations are computed once per
    event, in sequence order, from the event prefix alone.
    """

    def __init__(self, run: Path) -> None:
        self.run = run
        self.path = run / "events.jsonl"
        self.offset = 0
        self.events: list[dict[str, Any]] = []
        self.ids: set[str] = set()
        self.manifest_stamp: tuple[float, int] | None = None
        self.manifest: dict[str, Any] = {}
        self.topology: dict[str, Any] = {}
        self.mapper = ActivityMapper()
        self.annotated: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def _manifest_stamp(self) -> tuple[float, int] | None:
        try:
            stat = (self.run / "run_manifest.json").stat()
            return (stat.st_mtime, stat.st_size)
        except OSError:
            return None

    def _reset(self) -> None:
        self.offset = 0
        self.events = []
        self.ids = set()
        self.annotated = []

    def _read_new(self) -> bool:
        try:
            size = self.path.stat().st_size
        except OSError:
            if self.events:
                self._reset()
                return True
            return False
        if size < self.offset:
            self._reset()
        if size == self.offset:
            return False
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            chunk = stream.read(size - self.offset)
        end = chunk.rfind(b"\n")
        if end < 0:
            return False
        self.offset += end + 1
        changed = False
        for line in chunk[: end + 1].splitlines():
            try:
                value = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            event = normalize_event(value)
            if event["event_id"] in self.ids:
                continue
            self.ids.add(event["event_id"])
            self.events.append(event)
            changed = True
        return changed

    def _rebuild(self) -> None:
        self.events.sort(key=lambda item: (item["sequence"], item["event_id"]))
        self.topology = build_topology(self.manifest, self.events, run_id=self.run.name)
        self.mapper = ActivityMapper(self.topology)
        self.annotated = []
        for event in self.events:
            self.annotated.append({**event, "activity": self.mapper.annotate(event)})

    def refresh(self) -> None:
        with self.lock:
            stamp = self._manifest_stamp()
            manifest_changed = stamp != self.manifest_stamp
            if manifest_changed:
                self.manifest_stamp = stamp
                self.manifest = read_json(self.run / "run_manifest.json", {}) or {}
            previous = len(self.annotated)
            changed = self._read_new()
            if not changed and not manifest_changed:
                return
            new = self.events[previous:]
            ordered = all(
                (a["sequence"], a["event_id"]) < (b["sequence"], b["event_id"])
                for a, b in zip(self.events[max(0, previous - 1) :], new)
            )
            fingerprint = self.topology.get("fingerprint")
            candidate = build_topology(self.manifest, self.events, run_id=self.run.name)
            if (
                manifest_changed
                or not ordered
                or candidate["fingerprint"] != fingerprint
            ):
                self._rebuild()
                return
            for event in new:
                self.annotated.append(
                    {**event, "activity": self.mapper.annotate(event)}
                )

    def snapshot(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self.refresh()
        with self.lock:
            return list(self.annotated), self.topology


_CACHES: dict[Path, RunEventCache] = {}
_CACHES_LOCK = threading.Lock()


def run_cache(root: Path, run_id: str) -> RunEventCache:
    run = safe_run_dir(root, run_id)
    with _CACHES_LOCK:
        cache = _CACHES.get(run)
        if cache is None:
            if len(_CACHES) > 64:
                _CACHES.clear()
            cache = _CACHES[run] = RunEventCache(run)
    return cache


def annotated_events(
    root: Path, run_id: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return run_cache(root, run_id).snapshot()


def public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Manifest view safe for display: credentials and process identifiers removed."""
    clean = sanitize(manifest)
    for actor in (clean.get("actors") or {}).values():
        if isinstance(actor, dict):
            actor.pop("agent_object_id", None)
            actor.pop("adapter_object_id", None)
    clean.pop("pid", None)
    return clean


def public_snapshot(root: Path, run_id: str) -> dict[str, Any]:
    run = safe_run_dir(root, run_id)
    events, topology = annotated_events(root, run_id)
    artifact_payload = read_json(run / "artifacts.json", {}) or {}
    manifest = public_manifest(read_json(run / "run_manifest.json", {}) or {})
    workers = []
    worker_root = run / "workers"
    if worker_root.is_dir():
        for path in sorted(worker_root.iterdir()):
            result = read_json(path / "result.json", {}) or {}
            workers.append(
                {
                    "agent_id": path.name,
                    "status": result.get("status", "RUNNING"),
                    "objective": result.get("assigned_scope"),
                    "candidate_answer": result.get("candidate_answer"),
                    "tool_calls": result.get("tool_calls", 0),
                    "messages_sent": result.get("messages_sent", 0),
                    "messages_received": result.get("messages_received", 0),
                }
            )
    return {
        "schema_version": "studio.snapshot.v2",
        "run_id": run_id,
        "manifest": manifest,
        # Canonical settings the run executed with; None for legacy runs.
        "effective_config": manifest.get("effective_config"),
        "topology": topology,
        "state": read_json(run / "run_state.json", {}) or {},
        "final": read_json(run / "final_result.json", {}) or {},
        "budgets": read_json(run / "budgets.json", {}) or {},
        "events": events,
        "messages": read_jsonl(run / "messages.jsonl"),
        "artifacts": artifact_payload.get("artifacts", {}),
        "artifact_aliases": artifact_payload.get("aliases", {}),
        "workers": workers,
    }


def memory_policy(root: Path, run_id: str, agent_id: str) -> dict[str, Any]:
    """What memory the agent had, from the recorded configuration only."""
    run = safe_run_dir(root, run_id)
    manifest = read_json(run / "run_manifest.json", {}) or {}
    effective = manifest.get("effective_config")
    if agent_id == "coordinator":
        return {
            "optional_memory": "not_applicable",
            "description": "Coordinator run record: plan, reassessments, and synthesis inputs.",
        }
    if not isinstance(effective, dict):
        return {
            "optional_memory": "unknown",
            "description": "This run predates recorded memory policy; its optional-memory setting is unknown.",
        }
    enabled = bool(effective.get("optional_worker_memory_enabled"))
    return {
        "optional_memory": "on" if enabled else "off",
        "description": (
            "Optional private notebook ON: the worker wrote its findings after each phase and "
            "retrieved them at the start of later phases."
            if enabled
            else "Optional private notebook OFF: no notebook records were written or retrieved. "
            "The worker still used its per-question working context (conversation and image "
            "registry), which tool use requires; execution logging continued."
        ),
    }


def authorized_memory(root: Path, run_id: str, agent_id: str) -> list[dict[str, Any]]:
    run = safe_run_dir(root, run_id)
    if agent_id == "coordinator":
        values = read_json(run / "coordinator" / "memory.json", []) or []
        return values if isinstance(values, list) else []
    if not re.fullmatch(r"worker_[0-9]{2,}", agent_id):
        raise KeyError(agent_id)
    values = read_json(run / "workers" / agent_id / "private_memory.json", []) or []
    cards = []
    for value in values if isinstance(values, list) else []:
        source = value.get("peer_review", value) if isinstance(value, dict) else {}
        if not isinstance(source, dict):
            continue
        cards.append(
            {
                key: source.get(key)
                for key in (
                    "phase",
                    "agent_id",
                    "assigned_scope",
                    "status",
                    "candidate_answer",
                    "evidence_references",
                    "uncertainty_or_limitations",
                    "failure_reason",
                    "tool_observations",
                )
                if key in source
            }
        )
    return cards


def artifact_file(root: Path, run_id: str, artifact_id: str):
    run = safe_run_dir(root, run_id)
    return ArtifactStore.load(run).resolve(artifact_id)
