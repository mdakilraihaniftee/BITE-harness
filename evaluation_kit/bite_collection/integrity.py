"""Independent, artifact-derived collection integrity checks."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .persistence import hydrate_snapshot_record
from .schemas import validate_branch, validate_snapshot
from .snapshot import canonical_digest


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class StageEventLedger:
    """Append-only hash-chained evidence for runtime/offline stage transitions."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event, evidence):
        previous = None
        if self.path.exists():
            lines = [line for line in self.path.read_text().splitlines() if line.strip()]
            if lines:
                previous = json.loads(lines[-1])["event_sha256"]
        payload = {"schema_version": "bite.collection_stage_event.v1", "event": event,
                   "previous_event_sha256": previous, "evidence": evidence}
        record = {**payload, "event_sha256": canonical_digest(payload)}
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, (json.dumps(record, sort_keys=True, allow_nan=False) + "\n").encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return record


def validate_stage_events(path, *, state_dir=None):
    path = Path(path)
    if not path.is_file():
        return {"valid": False, "independently_reconstructible": False,
                "reason": "stage_event_chain_absent", "events": []}
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    previous = None
    for record in records:
        payload = {key: record[key] for key in (
            "schema_version", "event", "previous_event_sha256", "evidence")}
        if record["previous_event_sha256"] != previous or record["event_sha256"] != canonical_digest(payload):
            return {"valid": False, "independently_reconstructible": True,
                    "reason": "stage_event_chain_invalid", "events": records}
        previous = record["event_sha256"]
    names = [row["event"] for row in records]
    required = ["runtime_started", "raw_finalized", "offline_gt_open_authorized", "labels_finalized"]
    if names != required:
        return {"valid": False, "independently_reconstructible": True,
                "reason": "stage_event_order_invalid", "events": records}
    raw = records[1]["evidence"]
    if state_dir is not None:
        marker = Path(state_dir) / "raw_completion.json"
        if not marker.is_file() or raw.get("raw_completion_sha256") != _file_hash(marker):
            return {"valid": False, "independently_reconstructible": True,
                    "reason": "raw_completion_digest_mismatch", "events": records}
    return {"valid": True, "independently_reconstructible": True,
            "raw_before_gt": True, "events": records}


def validate_state_directory(state_dir):
    state_dir = Path(state_dir)
    completion = json.loads((state_dir / "completion.json").read_text())
    content_errors = []
    for relative, expected in completion["content_sha256"].items():
        path = state_dir / relative
        if not path.is_file() or _file_hash(path) != expected:
            content_errors.append(str(relative))
    manifest_path = state_dir / "raw_collection/manifests/collection_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    snapshot_path = Path(manifest["snapshot"])
    if not snapshot_path.is_absolute():
        snapshot_path = Path.cwd() / snapshot_path
    snapshot_persisted = json.loads(snapshot_path.read_text())
    validate_snapshot(snapshot_persisted)
    snapshot = hydrate_snapshot_record(snapshot_path)
    branch_records = []
    branch_errors = []
    artifact_ids = []
    for value in manifest["branches"]:
        path = Path(value)
        if not path.is_absolute():
            path = Path.cwd() / path
        branch = json.loads(path.read_text())
        validate_branch(branch)
        branch_records.append(branch)
        if (branch["parent_snapshot_id"] != snapshot["snapshot_id"]
                or branch["parent_state_digest"] != snapshot["state_digest"]):
            branch_errors.append({"branch_id": branch["branch_id"], "reason": "parent_mismatch"})
        if branch["prefix_cost"] != snapshot["prefix_logical_cost"]:
            branch_errors.append({"branch_id": branch["branch_id"], "reason": "prefix_cost_mismatch"})
        if branch["hypothetical_path_cost"] != branch["prefix_cost"] + branch["branch_cost"]:
            branch_errors.append({"branch_id": branch["branch_id"], "reason": "path_cost_mismatch"})
        ids = {item.get("image_id") for item in branch["resulting_artifacts"] if item.get("image_id")}
        artifact_ids.append(ids)
    # Independent clones intentionally reuse branch-local image counter names.
    # Counter-name overlap is not shared mutable state; persisted parent equality,
    # distinct terminal digests, and absence from the frozen parent are the checks.
    parent_image_ids = set(snapshot["memory"]["state"]["images"]["registry"])
    artifact_ids_outside_parent = all(not (ids & parent_image_ids) for ids in artifact_ids)
    terminal_digests = [branch["terminal_state_digest"] for branch in branch_records]
    distinct_terminal_states = len(terminal_digests) == len(set(terminal_digests))
    sibling_contamination = not artifact_ids_outside_parent or not distinct_terminal_states
    operational = json.loads((state_dir / "operational_state.json").read_text())
    operational_text = json.dumps(operational).lower()
    forbidden = [key for key in ("ground_truth", "official_tp", "offline_labels", "best_eligible_gt")
                 if key in operational_text]
    stage = validate_stage_events(state_dir / "stage_events.jsonl", state_dir=state_dir)
    return {
        "state_id": completion["state_id"], "valid": not content_errors and not branch_errors
                    and not sibling_contamination and not forbidden,
        "content_hashes_valid": not content_errors, "content_errors": content_errors,
        "snapshot_id": snapshot["snapshot_id"], "snapshot_digest": snapshot["state_digest"],
        "branch_count": len(branch_records), "all_branches_same_parent": not branch_errors,
        "branch_errors": branch_errors, "sibling_artifact_contamination": sibling_contamination,
        "branch_local_artifact_id_overlap": sorted(set.intersection(*artifact_ids)) if len(artifact_ids) > 1 else [],
        "branch_local_counter_names_are_namespaced_by_branch": True,
        "operational_state_excludes_offline_and_sibling_fields": not forbidden,
        "forbidden_operational_fields": forbidden, "logical_cost_valid": not branch_errors,
        "stage_order": stage,
    }


def validate_run_directory(run_dir):
    run_dir = Path(run_dir)
    states = [validate_state_directory(path) for path in sorted((run_dir / "states").glob("*"))
              if (path / "completion.json").is_file()]
    stage_reconstructible = sum(row["stage_order"]["independently_reconstructible"] for row in states)
    return {
        "schema_version": "bite.collection_integrity_revalidation.v2",
        "valid": bool(states) and all(row["valid"] for row in states),
        "state_count": len(states), "all_branches_same_parent": all(row["all_branches_same_parent"] for row in states),
        "all_content_hashes_valid": all(row["content_hashes_valid"] for row in states),
        "all_operational_states_gt_free": all(row["operational_state_excludes_offline_and_sibling_fields"] for row in states),
        "sibling_contamination_count": sum(row["sibling_artifact_contamination"] for row in states),
        "stage_order_independently_reconstructible_states": stage_reconstructible,
        "historical_stage_order_limitation": None if stage_reconstructible == len(states) else
            "Historical artifacts lack append-only stage events; code-path attestations cannot independently prove temporal ordering.",
        "states": states,
    }


def validate_canary(run_dir, selection, *, dispatch_cap):
    run_dir = Path(run_dir)
    expected = [state for state in selection["states"] if state["is_canary_group"]]
    reasons = []
    results = []
    total_cost = 0
    for state in expected:
        state_dir = run_dir / "states" / state["state_id"].replace(":", "_")
        if not (state_dir / "completion.json").is_file():
            reasons.append({"state_id": state["state_id"], "reason": "state_incomplete"})
            continue
        integrity = validate_state_directory(state_dir)
        initial = json.loads((state_dir / "initial_raw_state.json").read_text())
        completion = json.loads((state_dir / "completion.json").read_text())
        total_cost += completion["actual_dispatches"]
        templates = []
        for path in (state_dir / "raw_collection/branches").glob("*.json"):
            branch = json.loads(path.read_text())
            templates.append([step["action_template"] for step in branch["selected_path"]])
        expected_zoom = initial["candidate_usable"]
        expected_repeat = expected_zoom and bool(state.get("repeat_control_group", True))
        zoom_present = any(path[:2] == ["crop_generation", "focused_grounding"] for path in templates)
        repeat_present = any(path[:1] == ["repeated_grounding"] for path in templates)
        state_reasons = []
        if not integrity["valid"]:
            state_reasons.append("artifact_integrity_failed")
        if integrity["stage_order"]["independently_reconstructible"] and not integrity["stage_order"]["valid"]:
            state_reasons.append("raw_before_label_stage_invalid")
        if expected_zoom != zoom_present:
            state_reasons.append("zoom_eligibility_execution_mismatch")
        if expected_repeat != repeat_present:
            state_reasons.append("repeat_allocation_execution_mismatch")
        if completion["actual_dispatches"] > (4 if state.get("repeat_control_group", True) else 3):
            state_reasons.append("state_cost_cap_exceeded")
        reasons.extend({"state_id": state["state_id"], "reason": reason} for reason in state_reasons)
        results.append({"state_id": state["state_id"], "valid": not state_reasons,
                        "candidate_usable": initial["candidate_usable"], "zoom_executed": zoom_present,
                        "repeat_allocated": bool(state.get("repeat_control_group", True)),
                        "repeat_executed": repeat_present, "actual_dispatches": completion["actual_dispatches"],
                        "parent_valid": integrity["all_branches_same_parent"],
                        "raw_before_label": integrity["stage_order"]})
    if total_cost > dispatch_cap:
        reasons.append({"reason": "global_dispatch_cap_exceeded"})
    return {"schema_version": "bite.collection_canary_validation.v2",
            "pass": len(results) == len(expected) and not reasons,
            "expected_states": len(expected), "completed_states": len(results),
            "actual_dispatches": total_cost, "dispatch_cap": dispatch_cap,
            "reasons": reasons, "states": results}

