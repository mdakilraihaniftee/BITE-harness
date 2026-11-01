"""Pre-registered, unfitted Phase 4C restricted model specification."""

from __future__ import annotations


def phase4c_model_specification():
    return {
        "schema_version": "bite.phase4c_restricted_model_specification.v1",
        "status": "SPECIFICATION_ONLY_NOT_FITTED",
        "estimand": (
            "P(H_visual=1 | supported calibration-fit operational state and action outcome), only after "
            "the prespecified human adjudication endpoint is complete; H_annotation_iou_0_50 is retained "
            "as a distinct proxy/sensitivity endpoint"
        ),
        "label_endpoints": {
            "primary_future": (
                "H_visual=1 iff object_present_in_proposed_region=yes, class_appears_correct=yes, "
                "box_reasonably_localizes_object=yes, and image_evidence_inconclusive=no; H_visual=0 "
                "iff at least one of the first three controls is no and ambiguity/inconclusive controls "
                "are no; all uncertain, class/localization-ambiguous, and insufficient-evidence reviews "
                "remain unknown/abstained"
            ),
            "proxy": "H_annotation at IoU 0.50",
            "unresolved_visual_labels_are_not_coerced": True,
            "official_annotations_overwritten": False,
        },
        "target_distribution": (
            "cohort-stratified Aquarium calibration-fit query designs; not arbitrary VLM-selected queries"
        ),
        "sampling_unit": "source_group_id",
        "prior_candidate_model": {
            "form": "regularized pooled logistic model or monotone low-dimensional alternative",
            "pre_registered_features": [
                "initial_score", "log_original_relative_area", "cohort_query_design_indicator",
                "limited pooled class representation",
            ],
            "forbidden": ["per-class saturated models", "GT IoU", "GT identity", "post-action outcomes"],
        },
        "zoom_observation_model": {
            "action": "Zoom_In_Tool then Visual_Grounding_Tool; logical cost 2",
            "supported_regime": "frozen same-SAM3 controlled collection only",
            "coarse_outcomes": [
                "unique_alignment_high_consistency", "unique_alignment_other_consistency",
                "ambiguous_association", "no_target_alignment", "execution_failure",
            ],
            "candidate_continuous_features": [
                "root_box_iou", "normalized_center_displacement", "score_difference",
                "log_area_ratio", "proposal_count_change",
            ],
            "threshold_policy": (
                "freeze from scientific/engineering tolerances before validation; do not optimize on current labels"
            ),
            "causal_claim": False,
        },
        "bayes_update": {
            "formula": "K_a(o|H=1,s)p(s) / [K_a(o|H=1,s)p(s)+K_a(o|H=0,s)(1-p(s))]",
            "executed_in_phase04b2b4": False,
        },
        "comparators": {
            "A": "constant prevalence within declared cohort/query design",
            "B": "initial retained detector score only",
            "C": "compact initial-state features without new tool evidence",
            "proposed": "same compact initial state plus Zoom-focused evidence",
        },
        "metrics": ["Brier score", "log loss", "reliability diagnostics", "forced binary-decision error"],
        "uncertainty": {
            "resampling_unit": "source_group_id",
            "methods": ["group bootstrap intervals", "cluster-robust sensitivity analysis"],
            "row_iid_intervals_forbidden": True,
        },
        "evaluation_plan": {
            "fit": "existing 50 calibration-fit groups, retaining cohort/design strata",
            "validation": (
                "collect the frozen same branch protocol on calibration-validation groups only after model and "
                "feature choices are frozen; do not use them for feature design"
            ),
            "internal_test": "remain locked until model and evaluation protocol are frozen",
            "group_leakage_forbidden": True,
        },
        "missingness_and_abstention": [
            "unsupported class/context", "no candidate", "unknown fitting label",
            "ambiguous coordinate provenance", "missing action outcome",
            "unsupported backend revision", "insufficient source-group support",
            "severe source-distribution shift",
        ],
        "planning_link": {
            "stop_risk": "min(p,1-p) under equal binary error costs",
            "after_action_risk": "E_o[min(posterior(s,o,a),1-posterior(s,o,a))]",
            "risk_reduction": "stop_risk - after_action_risk",
            "logical_costs": {"repeat_grounding": 1, "zoom_focused_grounding": 2},
            "limitations": (
                "candidate verification is not end-to-end agent loss; dependencies, missed objects, answer "
                "formatting, action feasibility and model misspecification remain outside this proxy"
            ),
            "planner_implemented": False,
            "identifiability_certificate_claimed": False,
        },
    }
