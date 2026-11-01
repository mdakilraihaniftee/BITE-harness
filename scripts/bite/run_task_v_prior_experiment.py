#!/usr/bin/env python3
"""Run the authorized calibration-fit-only annotation-proxy prior experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.proxy_calibration import (
    file_sha256,
    load_proxy_records,
    run_experiment,
    validate_prediction_artifacts,
)
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")


def _card_markdown(card):
    metrics = card["metrics"]
    return f"""# {card['model_name']} — {card['cohort']} — {card['label_definition']}

Status: **{card['status']}**. Intended use: {card['intended_use']}.

- Target: {card['target_population']}
- Partition: `{card['training_partition']}`
- Features: `{', '.join(card['feature_schema']) or 'constant only'}`
- Regularization: {card['regularization']}
- Fold design: {card['fold_design']}
- Brier score: {metrics['case_level']['brier_score']:.6f}
- Log loss: {metrics['case_level']['log_loss']:.6f}
- Decision error: {metrics['case_level']['decision_error']:.6f}

This model estimates an annotation proxy, not visually verified truth. COCO negatives can
contain omitted visible objects. It is an offline, nondeployment research artifact. It has
no Zoom likelihood, online posterior update, planning authority, or certificate.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1a"))
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    args = parser.parse_args()
    output = args.output
    for name in ("proxy_models", "crossfit", "model_cards", "uncertainty"):
        (output / name).mkdir(parents=True, exist_ok=True)
    cases_path = ROOT / "outputs/bite/phase04b2b4/review_interface/review_cases.jsonl"
    definitions = {
        "expansion": ROOT / "outputs/bite/phase04b2b4/diagnostics/expansion_paired_diagnostics.jsonl",
        "pilot_sensitivity": ROOT / "outputs/bite/phase04b2b4/diagnostics/pilot_paired_diagnostics.jsonl",
    }
    summary = {
        "schema_version": "bite.phase04c1a_prior_results.v1",
        "status": "ANNOTATION_PROXY_EXPLORATORY",
        "primary_cohort": "expansion",
        "sensitivity_cohort": "pilot_sensitivity",
        "calibration_validation_accessed": False,
        "internal_test_accessed": False,
        "human_reviews_used": 0,
        "experiments": {},
        "input_sha256": {str(cases_path.relative_to(ROOT)): file_sha256(cases_path)},
    }
    for cohort_name, paired_path in definitions.items():
        source_hash = file_sha256(paired_path)
        summary["input_sha256"][str(paired_path.relative_to(ROOT))] = source_hash
        for endpoint in ("0.5", "0.75"):
            key = f"{cohort_name}_iou_{endpoint.replace('.', '_')}"
            records = load_proxy_records(
                paired_path, cases_path, endpoint=endpoint, cohort_name=cohort_name,
            )
            experiment = run_experiment(
                records, cohort_name=cohort_name, endpoint=endpoint, source_hash=source_hash,
                bootstrap_replicates=args.bootstrap_replicates,
            )
            validate_prediction_artifacts(experiment)
            _write_jsonl(output / f"crossfit/{key}_predictions.jsonl", experiment.pop("predictions"))
            atomic_json(output / f"proxy_models/{key}_fold_models.json", experiment.pop("fitted_models"))
            cards = experiment.pop("model_cards")
            atomic_json(output / f"uncertainty/{key}_group_bootstrap.json", experiment["uncertainty"])
            atomic_json(output / f"crossfit/{key}_summary.json", experiment)
            for card in cards:
                stem = f"{key}_{card['model_name']}"
                atomic_json(output / f"model_cards/{stem}.json", card)
                (output / f"model_cards/{stem}.md").write_text(_card_markdown(card))
            summary["experiments"][key] = {
                "cohort": cohort_name,
                "endpoint": experiment["endpoint"],
                "crossfit_metrics": experiment["crossfit"]["metrics"],
                "paired_compact_minus_baseline_metrics": experiment[
                    "paired_compact_minus_baseline_metrics"
                ],
                "support_audit": experiment["support_audit"],
                "uncertainty": experiment["uncertainty"],
            }
    summary["restrictions"] = {
        "fit_partition": "calibration_fit only",
        "zoom_likelihood_fitted": False,
        "zoom_posterior_computed": False,
        "visual_endpoint_fitted": False,
        "planner_implemented": False,
        "deployment_authorized": False,
    }
    atomic_json(output / "proxy_models/prior_experiment_summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

