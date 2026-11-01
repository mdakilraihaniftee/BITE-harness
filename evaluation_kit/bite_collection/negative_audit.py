"""Offline reconstruction and diagnosis of original Task V candidates."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

from evaluation_kit.bite_calibration.matching import label_candidates

from .persistence import atomic_json


def reference_iou_xyxy(left, right):
    if not all(isinstance(box, list) and len(box) == 4 for box in (left, right)):
        return None
    lx1, ly1, lx2, ly2 = left
    rx1, ry1, rx2, ry2 = right
    if not all(isinstance(value, (int, float)) and math.isfinite(value)
               for value in (*left, *right)):
        return None
    intersection = max(0.0, min(lx2, rx2) - max(lx1, rx1)) * max(0.0, min(ly2, ry2) - max(ly1, ry1))
    left_area = max(0.0, lx2 - lx1) * max(0.0, ly2 - ly1)
    right_area = max(0.0, rx2 - rx1) * max(0.0, ry2 - ry1)
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def _diagnosis(candidate, gt, label, threshold=.5):
    query = candidate["class_name"].strip().casefold()
    category = gt.class_map.get(query)
    compatible = [row for row in gt.annotations if row["category_id"] == category
                  and not row.get("ignore") and not row.get("iscrowd")]
    other = [row for row in gt.annotations if row["category_id"] != category
             and not row.get("ignore") and not row.get("iscrowd")]
    box = label["bbox_for_matching_xyxy"]
    same = sorted(((reference_iou_xyxy(box, row["bbox_xyxy"]), row["id"]) for row in compatible), reverse=True)
    different = sorted(((reference_iou_xyxy(box, row["bbox_xyxy"]), row["id"], row["category_id"])
                        for row in other), reverse=True)
    facts = {
        "eligible_same_class_instances": len(compatible),
        "best_same_class_iou_reference": same[0][0] if same else 0.0,
        "best_same_class_gt_id_reference": same[0][1] if same else None,
        "best_other_class_iou_reference": different[0][0] if different else 0.0,
        "best_other_class_gt_id_reference": different[0][1] if different else None,
        "best_other_class_category_id_reference": different[0][2] if different else None,
    }
    categories = []
    if not compatible:
        categories.append("no_annotated_instance")
    if compatible and facts["best_same_class_iou_reference"] < threshold:
        categories.append("insufficient_localization" if facts["best_same_class_iou_reference"] >= .1 else "wrong_location")
    if facts["best_other_class_iou_reference"] >= max(.3, facts["best_same_class_iou_reference"]):
        categories.append("wrong_instance_or_class_confusion")
    if not categories:
        categories.append("matching_or_geometry_defect")
    primary = ("no_annotated_instance" if "no_annotated_instance" in categories else
               "wrong_instance_or_class_confusion" if "wrong_instance_or_class_confusion" in categories else
               "insufficient_localization" if "insufficient_localization" in categories else categories[0])
    review = (primary in {"no_annotated_instance", "wrong_instance_or_class_confusion"}
              or (candidate.get("raw_scores") or [0])[0] >= .8)
    return primary, categories, facts, "pending_visual_review" if review else "not_required_by_rule"


def _overlay(path, candidate, gt, label, destination, query, diagnosis):
    with Image.open(path) as raw:
        image = raw.convert("RGB")
    draw = ImageDraw.Draw(image)
    box = candidate["bbox_root_xyxy"]
    draw.rectangle(box, outline=(255, 30, 30), width=4)
    category = gt.class_map.get(query.casefold())
    for annotation in gt.annotations:
        color = (30, 220, 30) if annotation["category_id"] == category else (255, 170, 20)
        draw.rectangle(annotation["bbox_xyxy"], outline=color, width=2)
    score = (candidate.get("raw_scores") or [None])[0]
    text = f"query={query} score={score} IoU={label.get('max_eligible_iou')} {diagnosis}"
    draw.rectangle((0, 0, min(image.width, max(500, len(text) * 7)), 22), fill=(0, 0, 0))
    draw.text((4, 4), text, fill=(255, 255, 255))
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)


def audit_original_candidates(run_dir, adapter, output_dir):
    run_dir, output_dir = Path(run_dir), Path(output_dir)
    rows, defects, review = [], [], []
    entry_by_id = {entry.entry_id: entry for entry in adapter.entries()}
    for state_dir in sorted((run_dir / "states").glob("*")):
        initial = json.loads((state_dir / "initial_raw_state.json").read_text())
        candidate = initial.get("selected_candidate")
        if not candidate:
            continue
        entry = entry_by_id[initial["source_entry_id"]]
        gt = adapter.load_offline_ground_truth(entry)
        reconstructed, summary = label_candidates([candidate], gt, (.5, .75),
                                                   assignment_scope="per_observation", score_mode="retained")
        persisted = json.loads((state_dir / "offline_labels/initial_candidate_labels.json").read_text())
        labels = reconstructed[candidate["candidate_id"]]
        persisted_labels = persisted["labels"]
        exact = labels == persisted_labels
        label50 = next(row for row in labels if row["iou_threshold"] == .5)
        label75 = next(row for row in labels if row["iou_threshold"] == .75)
        width, height = gt.image["width"], gt.image["height"]
        box = candidate["bbox_root_xyxy"]
        normalized_reference = [round(max(0, min(1000, box[0] / width * 1000))),
                                round(max(0, min(1000, box[1] / height * 1000))),
                                round(max(0, min(1000, box[2] / width * 1000))),
                                round(max(0, min(1000, box[3] / height * 1000)))]
        canonical = initial["prefix_observation"]["canonical_result"]
        rank = initial["selected_detector_rank"]
        normalized_persisted = (canonical.get("boxes_normalized") or [None] * (rank + 1))[rank]
        geometry_checks = {
            "root_matches_local": candidate["bbox_root_xyxy"] == candidate["bbox_local_xyxy"],
            "root_image_hash_matches_gt": candidate["source_image_sha256"] == gt.provenance["source_image_sha256"],
            "image_dimensions_match": [width, height] == [entry.width, entry.height],
            "annotation_image_id_matches": gt.image["id"] == entry.annotation_image_id,
            "normalized_reference": normalized_reference,
            "normalized_persisted": normalized_persisted,
            "normalized_matches": normalized_persisted == normalized_reference,
            "class_mapping_id": gt.class_map.get(candidate["class_name"].strip().casefold()),
            "out_of_bounds_raw": any(value < 0 for value in box[::2]) or box[2] > width or box[3] > height,
        }
        reference_best = max((reference_iou_xyxy(label50["bbox_for_matching_xyxy"], row["bbox_xyxy"])
                              for row in gt.annotations
                              if row["category_id"] == geometry_checks["class_mapping_id"]
                              and not row.get("ignore") and not row.get("iscrowd")), default=0.0)
        geometry_checks["reference_iou_matches"] = abs(reference_best - label50["max_eligible_iou"]) <= 1e-12
        defect = not exact or not all(value for key, value in geometry_checks.items()
                                      if key in {"root_matches_local", "root_image_hash_matches_gt", "image_dimensions_match",
                                                 "annotation_image_id_matches", "normalized_matches", "reference_iou_matches"})
        if defect:
            defects.append(initial["state_id"])
        valid50 = bool(label50["validity_label_usable"] and label50["geometric_valid"])
        if valid50:
            primary, categories, facts, review_status = "positive", [], {}, "not_required"
        else:
            primary, categories, facts, review_status = _diagnosis(candidate, gt, label50)
        overlay = output_dir / "overlays" / f"{initial['state_id'].split(':')[-1]}.png"
        _overlay(entry.image_path, candidate, gt, label50, overlay, initial["query"], primary)
        row = {
            "schema_version": "bite.task_v_negative_diagnostic.v1", "state_id": initial["state_id"],
            "source_entry_id": entry.entry_id, "source_group_id": entry.source_group_id,
            "source_image_sha256": entry.image_sha256, "query": initial["query"],
            "image_width": width, "image_height": height,
            "initial_observation_id": initial["prefix_observation"]["joint_observation_id"],
            "candidate_id": candidate["candidate_id"], "bbox_root_xyxy": box,
            "bbox_normalized_reference": normalized_reference, "raw_score": (candidate["raw_scores"] or [None])[0],
            "detector_rank": rank, "source_frame": initial["prefix_observation"]["source_frame"],
            "label_iou_0_50": label50, "label_iou_0_75": label75,
            "matching_summary": summary, "labels_reconstructed_exactly": exact,
            "independent_geometry": geometry_checks, "suspected_implementation_defect": defect,
            "primary_diagnosis_iou_0_50": primary, "diagnostic_categories_iou_0_50": categories,
            "diagnostic_facts": facts, "manual_review_status": review_status,
            "overlay_path_internal": str(overlay.resolve()),
        }
        rows.append(row)
        if review_status == "pending_visual_review":
            review.append({"state_id": initial["state_id"], "query": initial["query"],
                           "reason": primary, "overlay_path_internal": str(overlay.resolve())})
    output_dir.mkdir(parents=True, exist_ok=True)
    table = output_dir / "negative_diagnostics.jsonl"
    table.write_text("".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows))
    counts = Counter(row["primary_diagnosis_iou_0_50"] for row in rows if row["primary_diagnosis_iou_0_50"] != "positive")
    report = {
        "schema_version": "bite.task_v_negative_audit.v1", "candidate_states": len(rows),
        "positive_iou_0_50": sum(row["primary_diagnosis_iou_0_50"] == "positive" for row in rows),
        "negative_iou_0_50": sum(row["primary_diagnosis_iou_0_50"] != "positive" for row in rows),
        "negative_primary_diagnoses": dict(counts), "reconstructed_exactly": all(row["labels_reconstructed_exactly"] for row in rows),
        "independent_geometry_all_passed": not defects, "suspected_defect_state_ids": defects,
        "manual_review_queue_count": len(review), "systematic_defect_found": bool(defects),
        "expansion_allowed": not defects,
    }
    atomic_json(output_dir / "negative_audit_summary.json", report)
    atomic_json(output_dir / "manual_review_queue.json", {"schema_version": "bite.manual_review_queue.v1", "entries": review})
    return rows, report

