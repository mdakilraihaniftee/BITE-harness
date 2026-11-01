"""GT-free focused-evidence feature extraction and explicit offline joins."""

from __future__ import annotations

import math

FEATURE_VERSION = "bite.focused_evidence_features.v1"
OFFLINE_PAIR_FIELDS = {"focused_aligned_labels", "original_labels", "same_assigned_gt", "new_valid_object_localized"}


def runtime_projection(pair):
    """Remove all offline matching outcomes before feature construction."""
    return {key: value for key, value in pair.items() if key not in OFFLINE_PAIR_FIELDS}


def _geometry(box):
    x1, y1, x2, y2 = map(float, box)
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    return width, height, width * height, ((x1 + x2) / 2, (y1 + y2) / 2)


def box_iou(a, b):
    _, _, aa, _ = _geometry(a)
    _, _, ba, _ = _geometry(b)
    intersection = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = aa + ba - intersection
    return intersection / union if union > 0 else None


def extract_runtime_features(pair, runtime_context):
    """Construct features without accepting or reading any ground-truth object."""
    forbidden = {"H_annotation", "ground_truth", "official_tp"} | OFFLINE_PAIR_FIELDS
    if forbidden & (set(runtime_context) | set(pair)):
        raise ValueError("Runtime feature input contains offline-only labels")
    original = pair["original_bbox_root_xyxy"]
    focused = pair.get("focused_aligned_candidate")
    crop = pair["zoom_crop"]
    root_width = runtime_context["root_width"]
    root_height = runtime_context["root_height"]
    ow, oh, oa, oc = _geometry(original)
    initial_score = pair.get("original_score")
    relative_area = oa / (root_width * root_height)
    row = {
        "schema_version": FEATURE_VERSION,
        "state_id": pair["state_id"],
        "cohort_id": runtime_context["cohort_id"],
        "query_design_id": runtime_context["query_design_id"],
        "source_group_id": pair["source_group_id"],
        "query": pair["query"],
        "original_candidate_id": pair["original_candidate_id"],
        "initial_observation_id": runtime_context["initial_observation_id"],
        "focused_observation_id": pair["focused_observation_id"],
        "parent_snapshot_id": runtime_context["parent_snapshot_id"],
        "root_image_sha256": runtime_context["source_image_sha256"],
        "crop_image_id": crop["child_image_id"],
        "same_backend": focused is None or focused.get("source_backend") == runtime_context["initial_backend"],
        "backend": runtime_context["initial_backend"],
        "coordinate_transform_valid": runtime_context["coordinate_transform_valid"],
        "association_category": pair["focused_association_category"],
        "association_is_unique": pair["focused_association_category"] == "target_aligned_supporting_proposal",
        "association_is_ambiguous": pair["focused_association_category"] == "ambiguous_target_association",
        "no_alignment": pair["focused_association_category"] == "no_target_aligned_proposal",
        "initial_score": float(initial_score) if initial_score is not None else None,
        "initial_score_available": initial_score is not None,
        "initial_candidate_count": runtime_context["initial_candidate_count"],
        "focused_candidate_count": pair["focused_candidate_count"],
        "proposal_count_change": pair["focused_candidate_count"] - runtime_context["initial_candidate_count"],
        "class_compatible_focused_count": pair["focused_candidate_count"],
        "original_relative_area": relative_area,
        "candidate_size": "small" if relative_area < .05 else "medium" if relative_area < .25 else "large",
        "crop_width": crop["child_width"],
        "crop_height": crop["child_height"],
        "incremental_logical_cost": pair["incremental_logical_cost"],
        "mask_geometry_iou": None,
        "mask_geometry_available": False,
        "mask_unavailable_reason": "root_frame_mask_transform_not_implemented_and_not_unambiguous",
        "joint_observation_reference": pair["focused_observation_id"],
    }
    if focused is None:
        row.update({
            "focused_score": None, "focused_score_available": False, "score_difference": None,
            "absolute_score_difference": None, "root_box_iou": None,
            "normalized_center_displacement": None, "log_area_ratio": None,
            "relative_width_change": None, "relative_height_change": None,
            "focused_crosses_crop_boundary": None, "focused_near_crop_boundary": None,
            "focused_detector_rank": None,
            "detector_rank_change": None,
        })
        return row
    focused_box = focused["bbox_root_xyxy"]
    fw, fh, fa, fc = _geometry(focused_box)
    local = focused["bbox_local_xyxy"]
    margin_x = crop["child_width"] * 0.05
    margin_y = crop["child_height"] * 0.05
    score = focused.get("raw_scores", [None])[0]
    rank = runtime_context.get("focused_candidate_ranks", {}).get(focused["candidate_id"])
    row.update({
        "focused_score": float(score) if score is not None else None,
        "focused_score_available": score is not None,
        "score_difference": (
            float(score) - float(initial_score) if score is not None and initial_score is not None else None
        ),
        "absolute_score_difference": (
            abs(float(score) - float(initial_score)) if score is not None and initial_score is not None else None
        ),
        "root_box_iou": box_iou(original, focused_box),
        "normalized_center_displacement": math.dist(oc, fc) / math.hypot(root_width, root_height),
        "log_area_ratio": math.log(fa / oa) if fa > 0 and oa > 0 else None,
        "relative_width_change": (fw - ow) / ow if ow > 0 else None,
        "relative_height_change": (fh - oh) / oh if oh > 0 else None,
        "focused_crosses_crop_boundary": (
            local[0] < 0 or local[1] < 0 or local[2] > crop["child_width"] or local[3] > crop["child_height"]
        ),
        "focused_near_crop_boundary": (
            local[0] <= margin_x or local[1] <= margin_y
            or local[2] >= crop["child_width"] - margin_x
            or local[3] >= crop["child_height"] - margin_y
        ),
        "focused_detector_rank": rank,
        "detector_rank_change": (
            rank - runtime_context["initial_detector_rank"]
            if rank is not None and runtime_context.get("initial_detector_rank") is not None else None
        ),
    })
    return row


def join_offline_labels(features, pair):
    """Add offline outcomes after the immutable runtime vector has been built."""
    labels = {str(row["iou_threshold"]): row for row in pair["original_labels"]}
    focused = {str(row["iou_threshold"]): row for row in pair.get("focused_aligned_labels", [])}
    changes = {
        threshold: (
            None if threshold not in focused
            else focused[threshold]["max_eligible_iou"] - labels[threshold]["max_eligible_iou"]
        ) for threshold in ("0.5", "0.75")
    }
    return {
        "schema_version": "bite.focused_evidence_diagnostic.v1",
        "runtime_features": features,
        "offline_outcomes": {
            "H_annotation": {
                threshold: "positive" if labels[threshold]["official_tp"] else "negative"
                for threshold in ("0.5", "0.75")
            },
            "focused_proposal_correctness": {
                threshold: (
                    None if threshold not in focused
                    else "positive" if focused[threshold]["official_tp"] else "negative"
                ) for threshold in ("0.5", "0.75")
            },
            "same_target_preservation": pair["same_assigned_gt"],
            "new_valid_object_localized": pair["new_valid_object_localized"],
            "localization_change_iou": changes,
            "localization_change_direction": {
                threshold: (
                    None if value is None else "improved" if value > 0 else "worsened" if value < 0 else "unchanged"
                ) for threshold, value in changes.items()
            },
        },
    }
