#!/usr/bin/env python3
"""Run the calibration-fit-only Task V Zoom incremental feasibility experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.paired_zoom_evaluation import (
    align_predictions,
    evaluate_predictions,
    model_metrics,
)
from evaluation_kit.bite_calibration.zoom_action_cost_analysis import analyze_cost_risk
from evaluation_kit.bite_calibration.zoom_conditional_protocol import (
    build_protocol,
    file_sha256,
    freeze_runtime_rows,
    join_frozen_target,
    read_jsonl,
    runtime_integrity_report,
    validate_paired_labels,
)
from evaluation_kit.bite_calibration.zoom_incremental_model import (
    crossfit_zoom,
    deterministic_shuffled_rows,
)
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")


def _relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def _fold_membership(prediction_rows):
    output = {}
    for endpoint, rows in prediction_rows.items():
        groups = {}
        for row in rows:
            if row["model_name"] != "score_only_logistic":
                continue
            groups.setdefault(str(row["fold_index"]), set()).add(row["source_group_id"])
        output[endpoint] = {fold: sorted(values) for fold, values in sorted(groups.items())}
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1d"))
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    args = parser.parse_args()
    output = args.output
    for name in (
        "integrity", "protocol", "runtime_features", "crossfit_predictions", "models",
        "paired_metrics", "grouped_uncertainty", "evidence_dependence", "cost_analysis",
    ):
        (output / name).mkdir(parents=True, exist_ok=True)

    annotation_protocol_path = ROOT / "outputs/bite/phase04c1c_revised/protocol/task_v_annotation_proxy_protocol_v2.json"
    annotation_protocol = json.loads(annotation_protocol_path.read_text())
    definitions = {
        "expansion": {
            "runtime": ROOT / "outputs/bite/phase04b2b4/conditional_features/expansion_runtime_features.jsonl",
            "paired": ROOT / "outputs/bite/phase04b2b4/diagnostics/expansion_paired_diagnostics.jsonl",
            "count": 203,
            "groups": 30,
        },
        "pilot_sensitivity": {
            "runtime": ROOT / "outputs/bite/phase04b2b4/conditional_features/pilot_runtime_features.jsonl",
            "paired": ROOT / "outputs/bite/phase04b2b4/diagnostics/pilot_paired_diagnostics.jsonl",
            "count": 38,
            "groups": 19,
        },
    }
    prediction_paths = {
        cohort: {
            endpoint: ROOT / f"outputs/bite/phase04c1a/crossfit/{prefix}_iou_{endpoint.replace('.', '_')}_predictions.jsonl"
            for endpoint in ("0.5", "0.75")
        } for cohort, prefix in (
            ("expansion", "expansion"),
            ("pilot_sensitivity", "pilot_sensitivity"),
        )
    }
    frozen_predictions = {
        cohort: {endpoint: read_jsonl(path) for endpoint, path in paths.items()}
        for cohort, paths in prediction_paths.items()
    }
    input_paths = [annotation_protocol_path]
    for definition in definitions.values():
        input_paths.extend([definition["runtime"], definition["paired"]])
    for paths in prediction_paths.values():
        input_paths.extend(paths.values())
    input_identity = {
        "schema_version": "bite.phase04c1d_input_identity.v1",
        "status": "VERIFIED_BEFORE_FITTING",
        "files": {_relative(path): file_sha256(path) for path in input_paths},
        "validation_partition_accessed": False,
        "internal_test_accessed": False,
    }
    atomic_json(output / "integrity/input_identity.json", input_identity)

    frozen_runtime = {}
    runtime_reports = {}
    for cohort, definition in definitions.items():
        rows = freeze_runtime_rows(
            read_jsonl(definition["runtime"]), cohort_name=cohort,
            expected_count=definition["count"], expected_groups=definition["groups"],
        )
        frozen_runtime[cohort] = rows
        expected_hashes = (
            annotation_protocol["identity"]["fit_source_image_sha256"]
            if cohort == "expansion" else sorted({row["root_image_sha256"] for row in rows})
        )
        report = runtime_integrity_report(
            rows, source_path=definition["runtime"], expected_image_hashes=expected_hashes,
        )
        report["independent_source_identity_contract"] = cohort == "expansion"
        runtime_reports[cohort] = report
        _write_jsonl(output / f"runtime_features/{cohort}_runtime_features_v1.jsonl", rows)
    atomic_json(output / "integrity/runtime_feature_integrity.json", runtime_reports)

    protocol = build_protocol(
        input_sha256=input_identity["files"],
        runtime_integrity=runtime_reports,
        fold_membership=_fold_membership(frozen_predictions["expansion"]),
    )
    atomic_json(output / "protocol/zoom_conditional_feasibility_v1.json", protocol)

    all_results = {}
    all_costs = {}
    all_evidence = {}
    shuffled_controls = {}
    for cohort, runtime_rows in frozen_runtime.items():
        all_results[cohort] = {}
        all_costs[cohort] = {}
        all_evidence[cohort] = {}
        shuffled_controls[cohort] = {}
        paired = read_jsonl(definitions[cohort]["paired"])
        for endpoint in ("0.5", "0.75"):
            joined = join_frozen_target(
                runtime_rows, frozen_predictions[cohort][endpoint], endpoint=endpoint,
            )
            validate_paired_labels(joined, paired, endpoint=endpoint)
            crossfit = crossfit_zoom(joined)
            evaluation = evaluate_predictions(
                crossfit["predictions"],
                bootstrap_replicates=args.bootstrap_replicates,
                bootstrap_seed=461,
            )
            aligned = align_predictions(crossfit["predictions"])
            cost = analyze_cost_risk(aligned)
            key = f"iou_{endpoint.replace('.', '_')}"
            _write_jsonl(output / f"crossfit_predictions/{cohort}_{key}.jsonl", crossfit["predictions"])
            atomic_json(output / f"models/{cohort}_{key}_fold_models.json", crossfit["fitted_models"])
            atomic_json(output / f"grouped_uncertainty/{cohort}_{key}.json", evaluation["paired_uncertainty"])
            all_results[cohort][endpoint] = {
                key: value for key, value in evaluation.items() if key not in {"paired_uncertainty", "evidence_diagnostics"}
            }
            all_costs[cohort][endpoint] = cost
            all_evidence[cohort][endpoint] = evaluation["evidence_diagnostics"]

            shuffled = deterministic_shuffled_rows(joined)
            shuffled_crossfit = crossfit_zoom(shuffled)
            shuffled_aligned = align_predictions(shuffled_crossfit["predictions"])
            shuffled_controls[cohort][endpoint] = {
                "schema_version": "bite.task_v_zoom_shuffled_control.v1",
                "status": "IMPLEMENTATION_CONTROL_NOT_MODEL_SELECTION",
                "pairing": "deterministic within-query one-position cyclic reassignment",
                "real_pairing_broken": True,
                "label_or_fold_shuffled": False,
                "metrics": model_metrics(shuffled_aligned),
            }

    support_path = ROOT / "outputs/bite/phase04b2b3/analysis/task_v_support_summary.json"
    support = json.loads(support_path.read_text())
    exact_repeat = {
        "schema_version": "bite.task_v_exact_repeat_negative_control.v1",
        "source_path": _relative(support_path),
        "source_sha256": file_sha256(support_path),
        "pilot": support["cohorts"]["original_pilot"]["conditional_outcomes"]["exact_repeat"],
        "expansion": support["cohorts"]["expansion"]["conditional_outcomes"]["exact_repeat"],
        "total_repeat_observations": support["pooled_descriptive"]["repeat_observations"],
        "all_recorded_boxes_scores_masks_exact": True,
        "incremental_independent_evidence_claimed": False,
    }
    atomic_json(output / "paired_metrics/results.json", all_results)
    atomic_json(output / "cost_analysis/stop_vs_always_zoom.json", all_costs)
    atomic_json(output / "evidence_dependence/diagnostics.json", all_evidence)
    atomic_json(output / "evidence_dependence/shuffled_zoom_control.json", shuffled_controls)
    atomic_json(output / "evidence_dependence/exact_repeat_control.json", exact_repeat)
    summary = {
        "schema_version": "bite.phase04c1d_zoom_experiment_results.v1",
        "status": "EXPLORATORY_CALIBRATION_FIT_ONLY",
        "primary_cohort": "expansion",
        "sensitivity_cohort": "pilot_sensitivity",
        "results": all_results,
        "runtime_integrity": runtime_reports,
        "restrictions": {
            "validation_accessed": False,
            "internal_test_accessed": False,
            "new_model_inference": False,
            "underlying_model_retrained": False,
            "posterior_computed": False,
            "planner_implemented": False,
        },
    }
    atomic_json(output / "paired_metrics/summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
