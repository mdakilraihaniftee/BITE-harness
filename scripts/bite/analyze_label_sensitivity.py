#!/usr/bin/env python3
"""Run exact candidate- and group-budget endpoint-label sensitivity analyses."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.grouped_label_sensitivity import analyze_grouped
from evaluation_kit.bite_calibration.label_sensitivity import (
    analyze_scenarios,
    brute_force_bounds,
    exact_cardinality_bounds,
    flip_effect,
    scenario_predicates,
    with_group_balanced_weights,
)
from evaluation_kit.bite_calibration.paired_model_comparison import (
    load_frozen_predictions,
)
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1b"))
    args = parser.parse_args()
    source = ROOT / "outputs/bite/phase04c1a/crossfit"
    summary = {}
    for path in sorted(source.glob("*_predictions.jsonl")):
        experiment = path.name.removesuffix("_predictions.jsonl")
        _, aligned = load_frozen_predictions(path)
        sensitivity = analyze_scenarios(aligned)
        sensitivity["group_balanced_scenarios"] = analyze_scenarios(
            with_group_balanced_weights(aligned),
        )["scenarios"]
        sensitivity.update({"experiment": experiment, "endpoint": aligned[0]["endpoint"],
                            "cohort": aligned[0]["cohort_name"]})
        atomic_json(args.output / "label_sensitivity" / f"{experiment}.json", sensitivity)
        grouped = {
            "schema_version": "bite.fixed_prediction_grouped_sensitivity_bundle.v1",
            "experiment": experiment,
            "endpoint": aligned[0]["endpoint"],
            "cohort": aligned[0]["cohort_name"],
            "scenarios": {},
        }
        for name, predicate in scenario_predicates().items():
            grouped["scenarios"][name] = analyze_grouped(
                aligned, "score_only_logistic", "constant_prevalence", eligible=predicate,
            )
        atomic_json(args.output / "grouped_sensitivity" / f"{experiment}.json", grouped)
        summary[experiment] = {
            name: {
                "eligible_count": data["eligible_count"],
                "minimum_ranking_reversal": data["minimum_ranking_reversal"],
                "budget_bounds": [
                    {key: row[key] for key in (
                        "effective_budget", "eligible_percentage", "minimum_difference",
                        "maximum_difference", "includes_zero",
                    )} for row in data["budgets"]
                ],
            } for name, data in sensitivity["scenarios"].items()
        }
    synthetic = [
        {"state_id": "a", "candidate_id": "a", "source_group_id": "g1", "label": 0,
         "probabilities": {"score_only_logistic": .8, "constant_prevalence": .2}},
        {"state_id": "b", "candidate_id": "b", "source_group_id": "g2", "label": 1,
         "probabilities": {"score_only_logistic": .7, "constant_prevalence": .4}},
        {"state_id": "c", "candidate_id": "c", "source_group_id": "g2", "label": 0,
         "probabilities": {"score_only_logistic": .1, "constant_prevalence": .3}},
    ]
    checks = []
    for budget in range(4):
        exact = exact_cardinality_bounds(
            synthetic, "score_only_logistic", "constant_prevalence", budget=budget,
        )
        brute = brute_force_bounds(
            synthetic, "score_only_logistic", "constant_prevalence", budget=budget,
        )
        checks.append({
            "budget": budget, "exact": [exact["minimum_difference"], exact["maximum_difference"]],
            "brute_force": list(brute), "match": all(abs(x - y) < 1e-15 for x, y in zip(
                (exact["minimum_difference"], exact["maximum_difference"]), brute, strict=True,
            )),
        })
    identity = flip_effect(0, .8, .2)
    atomic_json(args.output / "theory_checks/exact_optimization_checks.json", {
        "schema_version": "bite.label_sensitivity_theory_checks.v1",
        "flip_identity_example": identity,
        "brute_force_checks": checks,
        "all_checks_pass": all(row["match"] for row in checks),
    })
    atomic_json(args.output / "label_sensitivity/summary.json", {
        "schema_version": "bite.phase04c1b_label_sensitivity_summary.v1",
        "status": "HYPOTHETICAL_FIXED_PREDICTION_SENSITIVITY",
        "experiments": summary,
        "predictions_refit": False,
        "empirical_omission_rate_estimated": False,
    })
    print(json.dumps({"status": "LABEL_SENSITIVITY_COMPLETE", "experiments": 4,
                      "exact_checks_pass": all(row["match"] for row in checks)}, indent=2))


if __name__ == "__main__":
    main()
