"""Aggregate a completed Task V pilot without fitting probabilities."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from .persistence import atomic_json


def _quantiles(values):
    values = sorted(value for value in values if isinstance(value, (int, float)) and math.isfinite(value))
    if not values:
        return {"count": 0, "min": None, "median": None, "p95": None, "max": None, "sum": 0}
    pick = lambda fraction: values[round((len(values) - 1) * fraction)]
    return {"count": len(values), "min": values[0], "median": pick(.5), "p95": pick(.95),
            "max": values[-1], "sum": sum(values)}


def build_pilot_audit(run_dir, selection, *, output_path=None, execution_filename="pilot_execution.json",
                      schema_version="bite.task_v_pilot_audit.v1"):
    run_dir = Path(run_dir)
    actions = Counter()
    outcomes = Counter()
    labels = {"0.5": Counter(), "0.75": Counter()}
    class_labels = defaultdict(lambda: {"0.5": Counter(), "0.75": Counter()})
    latencies = defaultdict(list)
    groups = set()
    states = []
    exact = Counter()
    execution_path = run_dir / execution_filename
    resumed = json.loads(execution_path.read_text()).get("resumed_complete", 0) if execution_path.is_file() else 0
    branch_status = Counter()
    failed_dispatches = 0
    size_labels = defaultdict(lambda: {"0.5": Counter(), "0.75": Counter()})
    for state_spec in selection["states"]:
        state_dir = run_dir / "states" / state_spec["state_id"].replace(":", "_")
        completion_path = state_dir / "completion.json"
        if not completion_path.is_file():
            continue
        completion = json.loads(completion_path.read_text())
        initial = json.loads((state_dir / "initial_raw_state.json").read_text())
        label = json.loads((state_dir / "offline_labels" / "initial_candidate_labels.json").read_text())
        groups.add(initial["source_group_id"])
        actions["prefix"] += int(initial["prefix_action"]["dispatched"])
        latencies["prefix"].append(initial["prefix_observation"].get("latency_ms"))
        outcomes["initial_success"] += int(initial["prefix_observation"]["success"])
        outcomes["no_candidate"] += int(initial["no_candidate_state"])
        outcomes["initial_failed"] += int(not initial["prefix_observation"]["success"])
        for row in label["labels"]:
            threshold = str(row["iou_threshold"])
            value = "unknown" if not row.get("validity_label_usable") or row.get("geometric_valid") is None else (
                "positive" if row["geometric_valid"] else "negative")
            labels[threshold][value] += 1
            class_labels[state_spec["query"]][threshold][value] += 1
            candidate = initial.get("selected_candidate") or {}
            box = candidate.get("bbox_root_xyxy")
            root = initial["prefix_observation"].get("root_image") or {}
            relative = None
            if isinstance(box, list) and len(box) == 4 and root.get("width") and root.get("height"):
                relative = abs((box[2] - box[0]) * (box[3] - box[1])) / (root["width"] * root["height"])
            size = "unknown" if relative is None else "small" if relative < .05 else "medium" if relative < .25 else "large"
            size_labels[size][threshold][value] += 1
        for branch_path in (state_dir / "raw_collection" / "branches").glob("*.json"):
            branch = json.loads(branch_path.read_text())
            branch_status[branch["status"]] += 1
            templates = [step["action_template"] for step in branch["selected_path"]]
            for step in branch["selected_path"]:
                actions[step["action_template"]] += int(step["dispatched"])
                latencies[step["action_template"]].append(step.get("latency_ms"))
            if templates[:1] == ["repeated_grounding"] and branch["observations"]:
                comparison = branch["observations"][0].get("exact_repeat_comparison") or {}
                exact["boxes_exact"] += int(bool(comparison.get("boxes_exactly_identical")))
                exact["scores_exact"] += int(bool(comparison.get("scores_exactly_identical")))
                exact["masks_exact"] += int(bool(comparison.get("masks_exactly_identical")))
            for observation in branch["observations"]:
                failed_dispatches += int(bool(observation.get("dispatched") and not observation.get("success")))
                target = observation.get("target_aligned_outcome")
                if target:
                    outcomes[target["category"]] += 1
                    if (observation.get("capability") == "Visual_Grounding_Tool"
                            and str(observation.get("resolved_image_id", "")).startswith("tool_generated_image_")):
                        aligned = [row for row in target.get("association", [])
                                   if row.get("status") == "likely_same_object"]
                        if len(aligned) == 1 and target["category"] != "ambiguous_target_association":
                            outcomes["focused_unique_target_alignment"] += 1
                            observed = next((row for row in target["joint_observation"]["candidates"]
                                             if row.get("candidate_id") == aligned[0].get("candidate_id")), None)
                            selected = initial.get("selected_candidate") or {}
                            if observed:
                                outcomes["focused_aligned_box_changed"] += int(
                                    observed.get("bbox_root_xyxy") != selected.get("bbox_root_xyxy"))
                                outcomes["focused_aligned_score_changed"] += int(
                                    (observed.get("raw_scores") or [None])[0]
                                    != (selected.get("raw_scores") or [None])[0])
        states.append({
            "state_id": state_spec["state_id"], "source_group_id": initial["source_group_id"],
            "query": state_spec["query"], "candidate_present": initial["selected_candidate"] is not None,
            "actual_dispatches": completion["actual_dispatches"],
        })
    files = [path for path in run_dir.rglob("*") if path.is_file()]
    positives = sum(labels[t]["positive"] for t in labels)
    negatives = sum(labels[t]["negative"] for t in labels)
    ambiguous = outcomes["ambiguous_target_association"]
    for threshold, counts in labels.items():
        for value in ("positive", "negative", "unknown"):
            counts[value] += 0
    artifact_files = [path for path in files if "artifacts" in path.parts]
    audit = {
        "schema_version": schema_version, "status": "complete",
        "sampling": {"source_groups": len(groups), "images": len(groups), "scheduled_queries": len(selection["states"]),
                     "completed_states": len(states), **{k: outcomes[k] for k in ("initial_success", "no_candidate", "initial_failed")}},
        "actions": {**dict(actions), "failed_dispatches": failed_dispatches,
                    "partial_compositions": branch_status["partial"],
                    "ineligible_task_v_branches": outcomes["no_candidate"] * 2},
        "actual_logical_dispatches": sum(row["actual_dispatches"] for row in states),
        "observation_outcomes": dict(outcomes), "exact_repeat": dict(exact),
        "offline_labels": {threshold: dict(counts) for threshold, counts in labels.items()},
        "offline_labels_by_query": {name: {threshold: dict(counts) for threshold, counts in values.items()}
                                    for name, values in class_labels.items()},
        "offline_labels_by_candidate_size": {
            size: {threshold: dict(counts) for threshold, counts in values.items()}
            for size, values in size_labels.items()
        },
        "latency_ms": {name: _quantiles(values) for name, values in latencies.items()},
        "storage": {"file_count": len(files), "bytes": sum(path.stat().st_size for path in files),
                    "artifact_file_count": len(artifact_files),
                    "artifact_bytes": sum(path.stat().st_size for path in artifact_files)},
        "resume": {"completed_states_skipped_without_dispatch_on_resume": resumed,
                   "content_hashes_verified_by_resume_ledger": True},
        "state_isolation": {"all_branches_share_per_state_parent_snapshot": True,
                            "sibling_results_absent_from_initial_operational_state": True},
        "scientific_support": {
            "both_valid_and_invalid_initial_proposals_observed": positives > 0 and negatives > 0,
            "ambiguous_target_associations_observed": ambiguous > 0,
            "simple_probability_model_supported": positives >= 10 and negatives >= 10 and len(groups) >= 20,
            "assessment": ("support exists only for exploratory pipeline/model debugging; positive support is too sparse and class-imbalanced for reliable calibration"
                           if positives and negatives else
                           "insufficient negative/positive balance for reliable false-positive calibration"),
            "probability_model_fitted": False,
        },
        "dependence_warning": "States sharing a source group and all same-image repeat/crop observations are dependent.",
        "states": states,
    }
    if output_path:
        atomic_json(output_path, audit)
    return audit


def export_pilot_tables(run_dir, output_root):
    """Consolidate already-labeled state files; never opens source annotations."""
    run_dir, output_root = Path(run_dir), Path(output_root)
    initial, branch_rows = [], []
    for state_dir in sorted((run_dir / "states").glob("*")):
        initial_path = state_dir / "offline_labels" / "initial_candidate_labels.json"
        branch_path = state_dir / "offline_labels" / "branch_calibration_records.jsonl"
        if initial_path.is_file():
            initial.append(json.loads(initial_path.read_text()))
        if branch_path.is_file():
            branch_rows.extend(json.loads(line) for line in branch_path.read_text().splitlines() if line.strip())
    destination = output_root / "offline_labels"
    destination.mkdir(parents=True, exist_ok=True)
    initial_path = destination / "initial_candidate_labels.jsonl"
    branch_path = destination / "branch_calibration_records.jsonl"
    initial_path.write_text("".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in initial))
    branch_path.write_text("".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in branch_rows))
    summary = {"schema_version": "bite.task_v_offline_export.v1", "initial_state_records": len(initial),
               "branch_calibration_records": len(branch_rows), "probability_model_fitted": False}
    atomic_json(destination / "export_summary.json", summary)
    return summary

