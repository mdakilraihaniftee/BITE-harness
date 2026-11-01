"""Offline paired analysis of original hypotheses and focused observations."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from evaluation_kit.bite_calibration.matching import label_candidates

from .persistence import atomic_json


def analyze_focused_evidence(run_dir, adapter, output_dir):
    run_dir, output_dir = Path(run_dir), Path(output_dir)
    entries = {entry.entry_id: entry for entry in adapter.entries()}
    rows, repeat_exact = [], Counter()
    contingency = {"0.5": defaultdict(Counter), "0.75": defaultdict(Counter)}
    for state_dir in sorted((run_dir / "states").glob("*")):
        initial = json.loads((state_dir / "initial_raw_state.json").read_text())
        candidate = initial.get("selected_candidate")
        if not candidate:
            continue
        entry = entries[initial["source_entry_id"]]
        gt = adapter.load_offline_ground_truth(entry)
        original = json.loads((state_dir / "offline_labels/initial_candidate_labels.json").read_text())["labels"]
        original_by = {str(row["iou_threshold"]): row for row in original}
        focused_observation = None
        focused_candidates = []
        crop = None
        for branch_path in (state_dir / "raw_collection/branches").glob("*.json"):
            branch = json.loads(branch_path.read_text())
            if branch["selected_path"] and branch["selected_path"][0]["action_template"] == "repeated_grounding":
                comparison = branch["observations"][0].get("exact_repeat_comparison") or {}
                repeat_exact["count"] += 1
                repeat_exact["boxes"] += int(comparison.get("boxes_exactly_identical") is True)
                repeat_exact["scores"] += int(comparison.get("scores_exactly_identical") is True)
                repeat_exact["masks"] += int(comparison.get("masks_exactly_identical") is True)
            if any(step["action_template"] == "focused_grounding" for step in branch["selected_path"]):
                crop = branch["observations"][0].get("crop")
                focused_observation = branch["observations"][-1]
                focused_candidates = [item["candidate"] for item in branch["candidate_rows"]
                                      if item["joint_observation_id"] == focused_observation["joint_observation_id"]]
        if focused_observation is None:
            continue
        focused_labels, _ = label_candidates(focused_candidates, gt, (.5, .75),
                                             assignment_scope="per_observation", score_mode="retained")
        target = focused_observation["target_aligned_outcome"]
        aligned_ids = [row["candidate_id"] for row in target.get("association", [])
                       if row.get("status") == "likely_same_object"]
        aligned = (next((row for row in focused_candidates if row["candidate_id"] in aligned_ids), None)
                   if len(aligned_ids) == 1 and target["category"] != "ambiguous_target_association" else None)
        aligned_labels = focused_labels.get(aligned["candidate_id"], []) if aligned else []
        focused_by = {str(row["iou_threshold"]): row for row in aligned_labels}
        record = {
            "schema_version": "bite.task_v_focused_pair.v1", "state_id": initial["state_id"],
            "source_group_id": initial["source_group_id"], "query": initial["query"],
            "original_candidate_id": candidate["candidate_id"], "original_score": (candidate["raw_scores"] or [None])[0],
            "original_bbox_root_xyxy": candidate["bbox_root_xyxy"], "original_labels": original,
            "focused_association_category": target["category"], "focused_observation_id": focused_observation["joint_observation_id"],
            "focused_candidate_count": len(focused_candidates), "focused_aligned_candidate": aligned,
            "focused_aligned_labels": aligned_labels, "zoom_crop": crop, "incremental_logical_cost": 2,
            "root_geometry_changed": aligned is not None and aligned["bbox_root_xyxy"] != candidate["bbox_root_xyxy"],
            "raw_score_changed": aligned is not None and (aligned.get("raw_scores") or [None])[0] != (candidate.get("raw_scores") or [None])[0],
            "same_assigned_gt": {}, "new_valid_object_localized": {},
        }
        for threshold in ("0.5", "0.75"):
            original_label = original_by[threshold]
            focused_label = focused_by.get(threshold)
            original_status = "correct" if original_label.get("validity_label_usable") and original_label.get("geometric_valid") else "incorrect"
            category = ({"target_aligned_supporting_proposal": "focused_target_support",
                         "same_geometry_repeated": "focused_target_support",
                         "localization_disagreement": "localization_disagreement",
                         "ambiguous_target_association": "ambiguous",
                         "no_target_aligned_proposal": "no_alignment",
                         "successful_empty_detection": "no_alignment"}.get(target["category"], target["category"]))
            contingency[threshold][original_status][category] += 1
            same = bool(focused_label and original_label.get("best_eligible_gt_id") is not None
                        and focused_label.get("best_eligible_gt_id") == original_label.get("best_eligible_gt_id")
                        and focused_label.get("geometric_valid"))
            any_valid = any(any(label["iou_threshold"] == float(threshold) and label.get("geometric_valid")
                                for label in labels) for labels in focused_labels.values())
            record["same_assigned_gt"][threshold] = same if aligned else None
            record["new_valid_object_localized"][threshold] = any_valid
        rows.append(record)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "focused_pairs.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows))
    summary = {
        "schema_version": "bite.task_v_focused_analysis.v1", "paired_states": len(rows),
        "contingency": {threshold: {status: dict(counts) for status, counts in table.items()}
                        for threshold, table in contingency.items()},
        "repeat_full_precision": dict(repeat_exact),
        "focused_geometry_changed": sum(row["root_geometry_changed"] for row in rows),
        "focused_score_changed": sum(row["raw_score_changed"] for row in rows),
        "same_assigned_gt_iou_0_50": sum(row["same_assigned_gt"]["0.5"] is True for row in rows),
        "same_assigned_gt_iou_0_75": sum(row["same_assigned_gt"]["0.75"] is True for row in rows),
        "different_or_unresolved_target_iou_0_50": sum(row["same_assigned_gt"]["0.5"] is not True for row in rows),
        "different_or_unresolved_target_iou_0_75": sum(row["same_assigned_gt"]["0.75"] is not True for row in rows),
        "probability_model_fitted": False,
    }
    atomic_json(output_dir / "focused_analysis_summary.json", summary)
    return rows, summary

