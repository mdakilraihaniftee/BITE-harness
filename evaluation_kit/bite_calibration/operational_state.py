"""Frozen runtime-visible feature map for future conditional calibration."""

from __future__ import annotations

import json
import math
import re

from .candidate_association import compare
from .common import identity, valid_box


STATE_VERSION = "bite.operational_state.v1"
_GT = re.compile(r"(^gt($|_)|ground_truth|annotation|official_tp|geometric_valid|novel_gt|best_eligible)", re.I)


def _ensure_gt_free(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if _GT.search(str(key)):
                raise ValueError(f"Offline label field is forbidden in operational state: {key}")
            _ensure_gt_free(child)
    elif isinstance(value, list):
        for child in value:
            _ensure_gt_free(child)


def _relative_area(candidate, root_dimensions):
    if not candidate or not valid_box(candidate.get("bbox_root_xyxy")):
        return None
    width, height = root_dimensions
    if not width or not height:
        return None
    x1, y1, x2, y2 = candidate["bbox_root_xyxy"]
    return abs((x2 - x1) * (y2 - y1)) / (width * height)


def build_operational_state(*, task, candidate, prior_candidates=(), previous_observation=None,
                            current_action=None, root_dimensions=(None, None), remaining_budget=None,
                            source_group_id, source_image_sha256):
    _ensure_gt_free({"task": task, "candidate": candidate, "prior_candidates": list(prior_candidates),
                     "previous_observation": previous_observation, "current_action": current_action})
    comparisons = [compare(candidate, prior) for prior in prior_candidates] if candidate else []
    scores = candidate.get("raw_scores", []) if candidate else []
    score = scores[0] if scores and isinstance(scores[0], (int, float)) and math.isfinite(scores[0]) else None
    action = current_action or {}
    previous = previous_observation or {}
    source_frame = previous.get("source_frame", {})
    action_backend = action.get("backend")
    previous_backend = previous.get("backend")
    predictive = {
        "hypothesis_task": task.get("hypothesis_task", "candidate_verification"),
        "candidate_class": candidate.get("class_name") if candidate else task.get("query"),
        "source_domain": task.get("source_domain"),
        "relative_candidate_size": _relative_area(candidate, root_dimensions),
        "raw_detector_score": score, "raw_score_available": score is not None,
        "overlapping_prior_candidates": sum((item.get("iou") or 0) > 0 for item in comparisons),
        "same_class_likely_repeats": sum(item.get("status") == "likely_same_object" for item in comparisons),
        "uncomparable_prior_candidates": sum(item.get("iou") is None for item in comparisons),
        "image_frame": "crop" if (candidate or {}).get("resolved_image_id", "").startswith("tool_generated_image_") else
                       "root" if candidate and candidate.get("root_image_id") == candidate.get("resolved_image_id") else "unknown",
        "previous_observation_category": (previous.get("outcome") or {}).get("category"),
        "shared_backend": bool(action_backend and previous_backend and action_backend == previous_backend),
        "repeated_query": action.get("action_template") == "repeated_grounding",
        "derived_artifact_dependency": bool(source_frame.get("child_to_root_transform") or
                                             str(action.get("arguments", {}).get("image_id", "")).startswith("tool_generated_image_")),
        "known_localization_ambiguity": (candidate or {}).get("association_status") in {
            "ambiguous_association", "unavailable_frame", "unavailable_class"
        },
        "coordinate_provenance_valid": bool(candidate and valid_box(candidate.get("bbox_root_xyxy")) and
                                            not candidate.get("frame_reason")),
        "remaining_logical_budget": remaining_budget,
    }
    if source_image_sha256 and len(source_image_sha256) != 64:
        raise ValueError("Source image SHA-256 is required for audit clustering")
    state = {
        "schema_version": STATE_VERSION,
        "state_id": identity(predictive, "operational_state"),
        "predictive_features": predictive,
        "audit_cluster": {"source_group_id": source_group_id, "source_image_sha256": source_image_sha256},
        "feature_policy": {
            "runtime_visible_only": True,
            "exact_identifiers_excluded_from_predictive_features": True,
            "representation": "restricted operational projection phi(H_t), not complete hidden world state",
        },
    }
    json.dumps(state, allow_nan=False)
    return state
