"""GT-free target-aligned outcome summaries layered over full joint outputs."""

from __future__ import annotations

import copy

from .candidate_association import compare


TARGET_VERSION = "bite.target_aligned_outcome.v1"
DISCOVERY_VERSION = "bite.discovery_outcome.v1"


def _failure(observation, version):
    if not observation or not observation.get("dispatched"):
        return {"schema_version": version, "category": "invalid_or_missing_result",
                "reason": "missing_or_undispatched_observation"}
    if not observation.get("success"):
        return {"schema_version": version, "category": "backend_failure",
                "reason": (observation.get("error") or {}).get("code")}
    return None


def _exact_geometry(left, right, tolerance=1e-6):
    if not isinstance(left, list) or not isinstance(right, list) or len(left) != 4 or len(right) != 4:
        return False
    return all(abs(a - b) <= tolerance for a, b in zip(left, right))


def summarize_target_aligned(initial_candidate, observed_candidates, observation):
    """Summarize evidence about one runtime candidate without asserting GT identity."""
    failure = _failure(observation, TARGET_VERSION)
    joint = {
        "joint_observation_id": (observation or {}).get("joint_observation_id"),
        "candidate_count": len(observed_candidates),
        "candidates": copy.deepcopy(list(observed_candidates)),
        "canonical_result": copy.deepcopy((observation or {}).get("canonical_result")),
    }
    lineage = {
        "initial_candidate_id": initial_candidate.get("candidate_id"),
        "initial_observation_id": initial_candidate.get("source_observation_id"),
        "current_observation_id": (observation or {}).get("joint_observation_id"),
        "repeat_metadata": copy.deepcopy((observation or {}).get("repeat_metadata")),
        "source_frame": copy.deepcopy((observation or {}).get("source_frame")),
        "same_original_evidence_lineage": initial_candidate.get("source_image_sha256") ==
                                          (observation or {}).get("root_image", {}).get("sha256"),
    }
    if failure:
        return {**failure, "target_candidate_id": initial_candidate.get("candidate_id"),
                "association": [], "joint_observation": joint, "dependency_lineage": lineage,
                "score_is_candidate_belief": False}
    canonical = observation.get("canonical_result")
    if not isinstance(canonical, dict) or not isinstance(canonical.get("boxes"), list):
        category, reason, comparisons = "invalid_or_missing_result", "canonical_boxes_unavailable", []
    elif not observed_candidates and not canonical["boxes"]:
        category, reason, comparisons = "successful_empty_detection", None, []
    else:
        comparisons = [{"candidate_id": candidate.get("candidate_id"),
                        **compare(initial_candidate, candidate)} for candidate in observed_candidates]
        aligned = [item for item in comparisons if item["status"] == "likely_same_object"]
        ambiguous = [item for item in comparisons if item["status"] in {
            "ambiguous_overlap", "unavailable_frame", "unavailable_class"
        }]
        same_class = [item for item in comparisons if item["status"] not in {"incompatible_class", "distinct_source"}]
        if len(aligned) > 1 or ambiguous:
            category, reason = "ambiguous_target_association", "multiple_or_ambiguous_runtime_associations"
        elif len(aligned) == 1:
            observed = next(item for item in observed_candidates if item.get("candidate_id") == aligned[0]["candidate_id"])
            if _exact_geometry(initial_candidate.get("bbox_root_xyxy"), observed.get("bbox_root_xyxy")):
                category, reason = "same_geometry_repeated", None
            else:
                category, reason = "target_aligned_supporting_proposal", None
        elif len(same_class) == 1 and 0.1 < (same_class[0].get("iou") or 0) < 0.8:
            category, reason = "localization_disagreement", "single_same_class_proposal_disagrees_in_root_geometry"
        else:
            category, reason = "no_target_aligned_proposal", None
    return {
        "schema_version": TARGET_VERSION, "category": category, "reason": reason,
        "target_candidate_id": initial_candidate.get("candidate_id"),
        "association": comparisons, "joint_observation": joint,
        "dependency_lineage": lineage, "score_is_candidate_belief": False,
        "gt_identity_used": False,
    }


def summarize_discovery(prior_candidates, observed_candidates, observation):
    """Runtime proposal-set novelty summary; it is not the offline H_D label."""
    failure = _failure(observation, DISCOVERY_VERSION)
    joint = {"joint_observation_id": (observation or {}).get("joint_observation_id"),
             "candidates": copy.deepcopy(list(observed_candidates)),
             "canonical_result": copy.deepcopy((observation or {}).get("canonical_result"))}
    if failure:
        return {**failure, "joint_observation": joint, "gt_identity_used": False}
    canonical = observation.get("canonical_result")
    if not isinstance(canonical, dict) or not isinstance(canonical.get("boxes"), list):
        category, comparisons = "invalid_or_missing_result", []
    elif not observed_candidates and not canonical["boxes"]:
        category, comparisons = "successful_empty_detection", []
    else:
        comparisons = []
        statuses = []
        for candidate in observed_candidates:
            candidate_comparisons = [compare(candidate, prior) for prior in prior_candidates]
            comparisons.append({"candidate_id": candidate.get("candidate_id"), "prior": candidate_comparisons})
            statuses.extend(item["status"] for item in candidate_comparisons)
        if any(status in {"ambiguous_overlap", "unavailable_frame", "unavailable_class"} for status in statuses):
            category = "ambiguous_runtime_discovery"
        elif observed_candidates and all(any(item["status"] == "likely_same_object" for item in row["prior"])
                                         for row in comparisons):
            category = "redundant_proposal_set"
        else:
            category = "new_runtime_proposal"
    return {
        "schema_version": DISCOVERY_VERSION, "category": category,
        "joint_observation": joint, "association": comparisons,
        "offline_discovery_label_required": True, "gt_identity_used": False,
    }
