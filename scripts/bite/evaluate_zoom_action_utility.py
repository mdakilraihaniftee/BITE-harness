#!/usr/bin/env python3
"""Phase 4C-1E Stage A: net-utility screen of Zoom over frozen Phase 4C-1D predictions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.action_utility_screen import (
    classify_zoom_collection,
    screen_action,
    squared_loss_identity_diagnostic,
)
from evaluation_kit.bite_calibration.paired_zoom_evaluation import align_predictions
from evaluation_kit.bite_calibration.zoom_action_cost_analysis import (
    LOGICAL_ACTION_COST,
)
from evaluation_kit.bite_calibration.zoom_conditional_protocol import (
    file_sha256,
    read_jsonl,
)
from evaluation_kit.bite_calibration.zoom_incremental_model import (
    BASELINE_MODEL,
    PRIMARY_MODEL,
)
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
PHASE04C1D = ROOT / "outputs/bite/phase04c1d"
EXPANSION_SELECTION = ROOT / (
    "outputs/bite/phase04b2b3/expansion/aquarium_task_v_expansion_seed418_g30/sample_selection_manifest.json"
)


def _relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/bite/phase04c1e")
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    args = parser.parse_args()
    checksums = json.loads((PHASE04C1D / "manifest_checksums.json").read_text())["artifact_sha256"]
    selection = json.loads(EXPANSION_SELECTION.read_text())
    unused_fit_groups = selection["eligible_source_group_count"] - selection["source_group_count"]
    inputs = {}
    screens = {}
    identity = {}
    for cohort in ("expansion", "pilot_sensitivity"):
        screens[cohort] = {}
        identity[cohort] = {}
        for endpoint in ("0.5", "0.75"):
            path = PHASE04C1D / f"crossfit_predictions/{cohort}_iou_{endpoint.replace('.', '_')}.jsonl"
            digest = file_sha256(path)
            if checksums.get(_relative(path)) != digest:
                raise ValueError(f"Frozen Phase 4C-1D prediction digest mismatch: {path}")
            inputs[_relative(path)] = digest
            aligned = align_predictions(read_jsonl(path))
            screens[cohort][endpoint] = screen_action(
                aligned, baseline=BASELINE_MODEL, treatment=PRIMARY_MODEL,
                action_cost=LOGICAL_ACTION_COST, endpoint=endpoint,
                replicates=args.bootstrap_replicates, seed=463,
                unused_fit_groups=unused_fit_groups,
            )
            identity[cohort][endpoint] = squared_loss_identity_diagnostic(
                aligned, baseline=BASELINE_MODEL, treatment=PRIMARY_MODEL)
    atomic_json(args.output / "theory/zoom_squared_loss_identity_diagnostic.json", {
        "schema_version": "bite.squared_loss_identity_diagnostic.v1",
        "status": "DESCRIPTIVE_DEVELOPMENT_DIAGNOSTIC",
        "baseline": BASELINE_MODEL,
        "treatment": PRIMARY_MODEL,
        "results": identity,
    })
    inputs[_relative(EXPANSION_SELECTION)] = file_sha256(EXPANSION_SELECTION)
    decision = classify_zoom_collection(screens["expansion"])
    output = args.output / "utility_screening"
    atomic_json(args.output / "integrity/stage_a_input_identity.json", {
        "schema_version": "bite.phase04c1e_stage_a_inputs.v1",
        "status": "VERIFIED_AGAINST_PHASE04C1D_CHECKSUM_INVENTORY",
        "files": inputs,
        "models_refit": False,
        "validation_partition_accessed": False,
        "internal_test_accessed": False,
    })
    for cohort, by_endpoint in screens.items():
        for endpoint, screen in by_endpoint.items():
            atomic_json(output / f"{cohort}_iou_{endpoint.replace('.', '_')}.json", screen)
    summary = {
        "schema_version": "bite.phase04c1e_zoom_utility_summary.v1",
        "status": "EXPLORATORY_DEVELOPMENT_SCREEN_NOT_A_POLICY_OR_GUARANTEE",
        "primary_cohort": "expansion",
        "sensitivity_cohort": "pilot_sensitivity",
        "unused_calibration_fit_groups": unused_fit_groups,
        "endpoints": {
            cohort: {endpoint: {
                "additional_logical_calls": screen["additional_logical_calls"],
                "errors_avoided": screen["errors_avoided"],
                "errors_introduced": screen["errors_introduced"],
                "gross_error_utility": screen["error_loss"]["gross_utility"]["case_level"],
                "gross_brier_utility": screen["brier_loss"]["gross_utility"]["case_level"],
                "break_even_lambda_error": screen["error_loss"]["break_even_lambda_per_logical_call"],
                "break_even_lambda_brier": screen["brier_loss"]["break_even_lambda_brier_per_logical_call"],
                "futility_projection": screen["futility_projection"],
                "leave_one_group_out": screen["influence_sensitivity"]["leave_one_group_out"],
            } for endpoint, screen in by_endpoint.items()}
            for cohort, by_endpoint in screens.items()
        },
        "zoom_collection_decision": decision,
    }
    atomic_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
