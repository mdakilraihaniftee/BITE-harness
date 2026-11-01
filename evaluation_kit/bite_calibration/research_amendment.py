"""Versioned machine-readable Phase 4B-2B-1 research amendment."""

from __future__ import annotations

import copy

from jsonschema import validate


AMENDMENT_VERSION = "bite.calibration_research_amendment.v1"
AMENDMENT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "additionalProperties": False,
    "required": ["schema_version", "candidate_belief", "conditional_observation_kernel", "operational_state",
                 "decision_risk", "target_outcomes", "dependency_classes", "query_schedule_amendment", "boundaries"],
    "properties": {
        "schema_version": {"const": AMENDMENT_VERSION}, "candidate_belief": {"type": "object"},
        "conditional_observation_kernel": {"type": "object"}, "operational_state": {"type": "object"},
        "decision_risk": {"type": "object"}, "target_outcomes": {"type": "object"},
        "dependency_classes": {"type": "array", "minItems": 4}, "query_schedule_amendment": {"type": "object"},
        "boundaries": {"type": "object"},
    },
}


def default_amendment():
    return {
        "schema_version": AMENDMENT_VERSION,
        "candidate_belief": {
            "variable": "H_V in {0,1} separately at IoU 0.50 and 0.75",
            "runtime_belief": "p_t=P(H_V=1|s_t)",
            "raw_detector_score_is_probability": False,
        },
        "conditional_observation_kernel": {
            "estimand": "K_a(o|H_V,s_t)=P(O_a=o|H_V,s_t,do(a))",
            "generalization_unit": "source images clustered by source_group_id",
            "causal_claim": "restricted operational intervention estimate, not automatically a fully identified physical-world kernel",
            "fitted_in_this_phase": False,
        },
        "operational_state": {
            "feature_map": "s_t=phi(H_t)", "schema_version": "bite.operational_state.v1",
            "runtime_visible_only": True, "complete_hidden_world": False,
            "exact_image_hash_predictive_feature": False, "identities_for_clustering_and_audit_only": True,
        },
        "decision_risk": {
            "calibration_losses": ["Brier score", "negative log likelihood"],
            "task_v_forced_decision_loss": "1[hat(H_V) != H_V]",
            "official_detection_evaluation": "unchanged original evaluator/AP plus prespecified per-image localization/recall diagnostics",
            "brier_is_official_odinw_ap": False,
        },
        "target_outcomes": {
            "verification_schema": "bite.target_aligned_outcome.v1",
            "discovery_schema": "bite.discovery_outcome.v1", "full_joint_output_retained": True,
            "gt_used_online": False, "strongest_crop_detection_assumed_target": False,
        },
        "dependency_classes": [
            {"kind": "identical_image_backend_query", "independent": False},
            {"kind": "modified_query_same_backend", "independent": False},
            {"kind": "derived_crop_same_backend", "independent": False, "new_raw_image_information": False},
            {"kind": "different_verified_backend", "available": False},
        ],
        "query_schedule_amendment": {
            "schema_version": "bite.query_schedule.v2", "requested_classes_per_group": 2,
            "scheduled_count": "min(requested_classes_per_group, available_verified_classes)",
            "seed": 417, "gt_presence_used": False,
        },
        "boundaries": {
            "posterior_computation": False, "probability_fitting": False, "planner": False,
            "identifiability_certificate": False,
            "certificate_note": "Requires later validated outcome models, uncertainty treatment, solver bounds and mathematical assumptions.",
        },
    }


def validate_amendment(amendment):
    validate(amendment, AMENDMENT_SCHEMA)
    if amendment["candidate_belief"].get("raw_detector_score_is_probability") is not False:
        raise ValueError("Raw detector score cannot be declared a calibrated candidate belief")
    if amendment["conditional_observation_kernel"].get("fitted_in_this_phase") is not False:
        raise ValueError("This phase cannot fit an observation kernel")
    if any(amendment["boundaries"].get(key) for key in ("posterior_computation", "probability_fitting", "planner", "identifiability_certificate")):
        raise ValueError("Research amendment crosses the Phase 4B-2B-1 boundary")
    return True


def amendment_schema():
    return copy.deepcopy(AMENDMENT_SCHEMA)
