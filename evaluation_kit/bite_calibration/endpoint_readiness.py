"""Endpoint-specific readiness decisions for revised Phase 4C-1C."""

from __future__ import annotations

READINESS_VERSION = "bite.phase04c1c_revised_readiness.v1"


def endpoint_readiness(*, protocol, human_review, frozen_priors, provenance, validation_contract):
    if not frozen_priors or not all(
        row["training"]["partition"] == "calibration_fit" for row in frozen_priors
    ):
        raise ValueError("Annotation-proxy readiness requires frozen fit-only models")
    checkpoint_unverified = provenance["status"] != "LOADED_MODEL_ATTESTED"
    return {
        "schema_version": READINESS_VERSION,
        "overall": (
            "ENGINEERING_SUCCESS / ANNOTATION_PROXY_READY / VALIDATION_EXECUTION_PENDING / "
            "CHECKPOINT_COMPARABILITY_UNVERIFIED"
            if checkpoint_unverified else
            "ENGINEERING_SUCCESS / ANNOTATION_PROXY_READY / VALIDATION_EXECUTION_PENDING"
        ),
        "annotation_proxy_prior": {
            "status": "READY_FOR_INDEPENDENT_VALIDATION_AFTER_EXECUTION_GATES",
            "primary_endpoint": protocol["primary_endpoint"],
            "companion_endpoint": protocol["companion_endpoint"],
            "primary_model": "score_only_logistic",
            "models_frozen": True,
            "source_partitions_disjoint": True,
            "human_review_required": False,
            "execution_authorized": False,
        },
        "visual_truth_prior": {
            "status": "NOT_VERIFIED",
            "human_review_required": True,
            "completed_supplemental_reviews": human_review["validated_finalized_review_count"],
            "probability_sample_complete": human_review["probability_sample_complete"],
        },
        "restricted_zoom_observation_model": {
            "status": "EXPLORATORY_FIT_POTENTIALLY_ELIGIBLE / NOT_STARTED",
            "coco_labels_permitted": True,
            "incremental_benefit_established": False,
            "held_out_grouped_validation_required": True,
            "fit_executed": False,
        },
        "budgeted_planning": {
            "status": "NOT_READY",
            "reason": "no validated conditional observation model or action-value estimate",
        },
        "identifiability_theory": {
            "status": "NOT_READY",
            "reason": "a calibrated prior alone does not identify an operational observation model",
        },
        "end_to_end_evaluation": {
            "status": "NOT_READY",
            "controller_integrated": False,
            "original_agent_modified": False,
            "original_evaluator_modified": False,
        },
        "human_review_policy": {
            "ANNOTATION_PROXY_CALIBRATION_ALLOWED_WITHOUT_HUMAN_REVIEW": True,
            "VISUAL_TRUTH_CLAIMS_REQUIRE_SEPARATE_VALIDATION": True,
        },
        "validation": {
            "metadata_preflight": validation_contract["status"],
            "go_no_go": validation_contract["authorization"]["go_no_go"],
            "checkpoint_comparability": (
                "UNVERIFIED" if checkpoint_unverified else "VERIFIED"
            ),
            "human_review_blocks_annotation_proxy": False,
        },
        "next": {
            "recommended_action": "CHECKPOINT_REMEDIATION_OR_EXPLICIT_COMPARABILITY_APPROVAL",
            "then": "SEPARATELY_AUTHORIZED_CONTROLLED_HELD_OUT_VALIDATION",
            "phase_after_04c1c_started": False,
        },
        "restrictions": {
            "validation_inference_executed": False,
            "conditional_zoom_likelihood_fitted": False,
            "posterior_computed": False,
            "planner_implemented": False,
            "bellman_optimization_implemented": False,
            "certificate_claimed": False,
        },
    }
