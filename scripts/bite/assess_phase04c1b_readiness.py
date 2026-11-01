#!/usr/bin/env python3
"""Assemble the Phase 4C-1B machine-readable readiness decision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_collection.persistence import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1b"))
    args = parser.parse_args()
    pair50 = json.loads((args.output / "paired_comparisons/expansion_iou_0_5.json").read_text())
    pair75 = json.loads((args.output / "paired_comparisons/expansion_iou_0_75.json").read_text())
    sensitivity = json.loads((args.output / "label_sensitivity/summary.json").read_text())
    progress = json.loads((args.output / "review_progress/progress.json").read_text())
    preflight = json.loads((args.output / "validation_preflight/preflight.json").read_text())
    key = "score_only_logistic_minus_constant_prevalence"
    report = {
        "schema_version": "bite.phase04c1b_readiness.v1",
        "overall": "ENGINEERING_SUCCESS / PAIRED_COMPARISON_COMPLETE / LABEL_REVIEW_PENDING",
        "prior_reproduction": "PASS",
        "paired_comparison": {
            "status": "DEVELOPMENT_PAIRED_ANALYSIS_COMPLETE",
            "expansion_iou_0_50_brier": pair50["comparisons"][key]["case_level"]["brier_score"],
            "expansion_iou_0_75_brier": pair75["comparisons"][key]["case_level"]["brier_score"],
            "selection_optimism_removed": False,
        },
        "label_sensitivity": {
            "status": sensitivity["status"],
            "predictions_refit": False,
            "empirical_omission_rate_estimated": False,
            "primary_suspected_missing_reversal_flips": {"0.50": 28, "0.75": 18},
            "primary_suspected_missing_reversal_groups": {"0.50": 6, "0.75": 4},
        },
        "human_review": {
            "status": "PENDING",
            "genuine_completed": progress["genuine_completed_review_count"],
            "set_a": progress["set_a"], "set_b": progress["set_b"],
            "visual_label_reliability": progress["visual_label_reliability"],
            "fake_reviews_created": False,
        },
        "validation": {
            "status": preflight["status"],
            "engineering_compatible": preflight["authorization"]["engineering_compatible"],
            "new_inference_authorized": False,
            "maximum_logical_dispatches": preflight["protocol"]["maximum_logical_dispatches"],
            "checkpoint_gate": preflight["checkpoint_provenance"]["gate"],
            "internal_test_accessed": False,
        },
        "next": {
            "priority": "COMPLETE_SET_A_HUMAN_ADJUDICATION_AND_CHECKPOINT_ATTESTATION",
            "conditional_zoom_likelihood": "NOT_AUTHORIZED",
            "posterior": "NOT_IMPLEMENTED",
            "planner": "NOT_IMPLEMENTED",
            "certificate": "NOT_CLAIMED",
            "phase04c1c_started": False,
        },
        "restrictions": {
            "gpu_inference_calls": 0, "vlm_calls": 0, "downloads": 0,
            "zoom_likelihood_fitted": False, "validation_collection_executed": False,
            "main_agent_modified_by_phase04c1b": False,
            "official_evaluator_modified_by_phase04c1b": False,
            "historical_outputs_rewritten": False, "git_commit_created": False,
        },
    }
    atomic_json(args.output / "readiness/phase04c1b_readiness.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
