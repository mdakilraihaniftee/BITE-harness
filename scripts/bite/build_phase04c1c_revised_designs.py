#!/usr/bin/env python3
"""Persist future-only conditional-evidence and agent-query research designs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_collection.persistence import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1c_revised"))
    args = parser.parse_args()
    conditional = {
        "schema_version": "bite.task_v_conditional_evidence_next_experiment.v1",
        "status": "DESIGN_ONLY_NOT_FITTED",
        "hypothesis": "Zoom-focused evidence improves original-candidate prediction beyond initial state",
        "target": ["H_annotation_0.50", "H_annotation_0.75"],
        "models": [
            "constant_prevalence", "raw_sam3_score", "frozen_score_only_prior",
            "frozen_compact_prior", "restricted_zoom_informed_model",
            "optional_deterministic_evidence_consistency_heuristic",
        ],
        "primary_comparison": {
            "baseline": "frozen_score_only_prior p0=P(H|s0)",
            "candidate": "restricted p1=P(H|s0,O_zoom_focused)",
            "metric": "paired source-group Delta_Brier = Brier(p1)-Brier(p0)",
            "favorable_direction": "negative",
            "does_not_imply_agent_task_improvement": True,
        },
        "development": {
            "allowed_partition": "calibration_fit",
            "joint_initial_and_action_observations_required": True,
            "features_must_be_frozen_before_validation": True,
            "source_group_aware": True,
        },
        "evaluation": {
            "partition": "calibration_validation",
            "validation_outcomes_cannot_select_features": True,
            "paired_source_group_comparisons": True,
            "raw_score_uses_same_cases_labels_and_groups": True,
            "internal_test_locked": True,
        },
        "dependence": {
            "kernel": "K_a(o|H,s0)",
            "same_image_crop_and_backend_dependence_explicit": True,
            "repeated_outputs_multiplied_as_independent": False,
            "exact_repeat_evidence": "73/73 identical; no demonstrated incremental information",
            "focused_median_aligned_iou_approx": 0.97,
        },
        "costs": {"stop": 0, "exact_repeat": 1, "zoom_then_focused_grounding": 2},
        "expected_information_gain_claimed": False,
        "expected_risk_reduction_claimed": False,
        "likelihood_fitted": False,
        "posterior_computed": False,
        "planner_implemented": False,
    }
    agent_selected = {
        "schema_version": "bite.task_v_agent_selected_query_protocol_proposal.v1",
        "status": "FUTURE_ONLY_NOT_EXECUTED",
        "controlled_regime": {
            "queries": ["fish", "jellyfish", "penguin", "puffin", "shark", "starfish", "stingray"],
            "one_representative_image_per_source_group": True,
            "official_coco_endpoint": True,
        },
        "agent_selected_regime": {
            "frozen_vlm_agent": True,
            "query_generated_before_gt_access": True,
            "original_task_context_and_query_persisted": True,
            "query_to_annotation_mapping_prespecified": True,
            "unmappable_or_ambiguous_queries_retained": True,
            "sam3_output_evaluated_under_declared_annotation_policy": True,
        },
        "separate_population": True,
        "same_prevalence_or_calibration_curve_assumed": False,
        "additional_requirements": [
            "freeze agent, prompt, decoding, task population, and query parser",
            "define mapping adjudication without correctness-label access",
            "report unmappable and ambiguous query coverage",
            "use source-group-disjoint development and evaluation",
            "attest VLM and SAM 3 worker identities",
        ],
        "vlm_calls": 0,
        "agent_loop_modified": False,
    }
    destination = args.output / "conditional_evidence_design"
    atomic_json(destination / "conditional_evidence_experiment.json", conditional)
    atomic_json(destination / "agent_selected_query_proposal.json", agent_selected)
    print(json.dumps({"conditional": conditional, "agent_selected": agent_selected}, indent=2))


if __name__ == "__main__":
    main()
