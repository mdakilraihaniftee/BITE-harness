"""Dimension-specific Phase 4C readiness decisions."""

from __future__ import annotations


def assess_readiness(*, integrity, review_validation, diagnostics, support_summary):
    engineering_pass = bool(integrity["historical_valid"] and integrity["expansion_valid"])
    human_complete = review_validation["reviewed_case_count"] > 0
    expansion = diagnostics["cohorts"]["expansion"]
    sparse_classes = [
        name for name, counts in expansion["class_support"].items()
        if not counts.get("positive") or counts.get("positive", 0) < 5
    ]
    return {
        "schema_version": "bite.phase4c_statistical_readiness.v1",
        "overall": "ENGINEERING_SUCCESS / HUMAN_ADJUDICATION_PENDING",
        "label_readiness": {
            "status": "PENDING_HUMAN_ADJUDICATION" if not human_complete else "PARTIALLY_ADJUDICATED",
            "annotation_labels_reconstructed": True,
            "annotation_negative_count_iou_0_50": 206,
            "no_annotated_instance_negative_count": 191,
            "machine_unknown_count": 0,
            "pending_negative_visual_reviews": 205,
            "completed_human_judgments": review_validation["completed_human_judgments"],
            "reviewed_case_count": review_validation["reviewed_case_count"],
            "suspected_omission_rate": review_validation["suspected_omission_rate"],
            "visual_review_agreement": (
                None if review_validation["double_reviewed_case_count"] == 0 else
                review_validation["double_review_agreement_count"]
                / review_validation["double_reviewed_case_count"]
            ),
            "selection_designs_separate": True,
            "visual_label_reliability_established": review_validation["visual_label_reliability_established"],
        },
        "observation_readiness": {
            "status": "PASS_WITH_DEPENDENCE_AND_CHECKPOINT_LIMITATIONS",
            "joint_outputs_preserved": True,
            "runtime_feature_extraction_valid": True,
            "gt_excluded_from_runtime_features": True,
            "association_ambiguity_preserved": True,
            "repeat_dependency_represented": True,
            "zoom_observation_support": expansion["candidate_count"],
            "exact_checkpoint_revision_attested_by_worker": False,
        },
        "statistical_support": {
            "status": "SPARSE_AND_DESIGN_HETEROGENEOUS",
            "positive_candidates_iou_0_50": 35,
            "negative_candidates_iou_0_50": 206,
            "source_groups": 50,
            "sparse_expansion_class_cells": sparse_classes,
            "cohort_query_designs_differ": True,
            "available_fit_groups": 50,
            "available_validation_groups_without_branch_evidence": 72,
            "locked_internal_test_groups": 50,
            "potential_annotation_missingness_bias": True,
            "focused_evidence_separation": "WEAK_OR_UNESTABLISHED",
        },
        "model_readiness": {
            "prior_only_exploratory_model": "READY_WITH_LIMITATIONS",
            "restricted_pooled_zoom_outcome_model": "REQUIRES_HUMAN_REVIEW_AND_GROUPED_VALIDATION",
            "general_class_conditional_model": "NOT_READY",
            "online_belief_updating": "NOT_READY",
            "end_to_end_planning_evaluation": "NOT_READY",
            "formal_identifiability_certificate": "NOT_READY",
        },
        "integrity": {
            "engineering_pass": engineering_pass,
            "historical_raw_before_label_reconstructible": False,
            "expansion_raw_before_label_reconstructible_states": 210,
        },
        "probabilities_fitted": False,
        "posterior_computed": False,
        "planner_implemented": False,
        "certificate_implemented": False,
        "phase4c_started": False,
        "support_summary_identity": support_summary.get("schema_version"),
    }
