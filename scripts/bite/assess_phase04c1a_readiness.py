#!/usr/bin/env python3
"""Write dimension-specific readiness after the exploratory proxy-prior experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_collection.persistence import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1a"))
    args = parser.parse_args()
    prior = json.loads((args.output / "proxy_models/prior_experiment_summary.json").read_text())
    review = json.loads((args.output / "review_validation/adjudication_progress.json").read_text())
    validation = json.loads((
        args.output / "validation_protocol/task_v_validation_collection_v1.json"
    ).read_text())
    expansion50 = prior["experiments"]["expansion_iou_0_5"]
    score = expansion50["crossfit_metrics"]["score_only_logistic"]["case_level"]
    compact = expansion50["crossfit_metrics"]["compact_initial_logistic"]["case_level"]
    readiness = {
        "schema_version": "bite.phase04c1a_readiness.v1",
        "overall": "ENGINEERING_SUCCESS / PROXY_PRIOR_EXPLORATORY / HUMAN_REVIEW_PENDING",
        "human_adjudication": {
            "status": review["human_review_status"],
            "completed_human_judgments": review["completed_human_judgment_count"],
            "visual_endpoint_reliability_established": False,
            "annotation_omission_prevalence_estimated": False,
            "blind_first_pass_server_enforced": True,
        },
        "proxy_prior": {
            "status": "EXPLORATORY_CROSSFIT_COMPLETE",
            "label": "H_annotation at IoU 0.50 and 0.75; explicitly imperfect proxy",
            "primary_cohort": "seven-class expansion",
            "pilot_role": "separate sparse sensitivity cohort",
            "source_group_disjoint_folds": 3,
            "score_only_improves_over_constant_on_primary_brier": True,
            "compact_relative_area_consistently_improves_over_score_only": False,
            "primary_iou_0_50_score_only_brier": score["brier_score"],
            "primary_iou_0_50_compact_brier": compact["brier_score"],
            "deployment_authorized": False,
        },
        "validation_collection": {
            "status": validation["status"],
            "group_count": validation["selection"]["group_count"],
            "maximum_query_states": validation["query_design"]["maximum_query_states"],
            "maximum_logical_dispatches": validation["action_policy"]["maximum_logical_dispatches"],
            "executed": False,
            "internal_test_locked": True,
        },
        "next_models": {
            "visually_grounded_prior": "BLOCKED_ON_HUMAN_ADJUDICATION",
            "conditional_zoom_likelihood": "BLOCKED_ON_LABEL_RELIABILITY_AND_GROUPED_VALIDATION",
            "zoom_informed_posterior": "NOT_AUTHORIZED",
            "online_belief_updating": "NOT_READY",
            "planner": "NOT_READY",
            "identifiability_certificate": "NOT_READY",
        },
        "restrictions": {
            "zoom_likelihood_fitted": False,
            "posterior_computed": False,
            "validation_inference_run": False,
            "internal_test_accessed": False,
            "main_agent_modified": False,
            "official_evaluator_modified": False,
            "phase04c1b_started": False,
        },
    }
    atomic_json(args.output / "readiness/phase04c1a_readiness.json", readiness)
    print(json.dumps(readiness, indent=2))


if __name__ == "__main__":
    main()
