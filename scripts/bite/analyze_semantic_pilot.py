#!/usr/bin/env python3
"""Phase 4C-1F analysis of a completed, authorized live semantic pilot run.

Refuses to run on a missing, incomplete, mock or mismatched run. Writes the
GT-free feature table and its digest before any label file is opened, and records
that order in a hash-chained stage-event ledger.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from evaluation_kit.bite_calibration.semantic_feature_extractor import (
    finalize_feature_table,
)
from evaluation_kit.bite_calibration.semantic_pilot_analysis import (
    ENDPOINTS,
    LOGICAL_COST,
    canonical_targets,
    evaluate_endpoint,
    failure_analysis,
    join_rows,
    research_decision,
    validate_observations,
)
from evaluation_kit.bite_calibration.semantic_pilot_protocol import (
    collect_observations,
    verify_manifest,
)
from evaluation_kit.bite_calibration.zoom_conditional_protocol import (
    file_sha256,
    read_jsonl,
)
from evaluation_kit.bite_collection.integrity import StageEventLedger
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
PHASE04C1D = ROOT / "outputs/bite/phase04c1d"


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")


def _verified(relative, inventory):
    path = ROOT / relative
    if inventory.get(relative) != file_sha256(path):
        raise ValueError(f"Phase 4C-1D input digest mismatch: {relative}")
    return read_jsonl(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=ROOT / "outputs/bite/phase04c1f/raw_observations/semantic_pilot_run")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/bite/phase04c1f")
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    args = parser.parse_args()
    if not (args.run / "run_configuration.json").is_file():
        raise SystemExit(f"No semantic pilot run at {args.run}; nothing to analyze")
    manifest = verify_manifest(json.loads(
        (ROOT / "outputs/bite/phase04c1e/semantic_pilot_manifest/manifest.json").read_text()))
    observations = collect_observations(args.run)
    validation = validate_observations(observations, manifest)
    if not validation["complete"]:
        raise SystemExit(f"Run is incomplete ({len(validation['missing_case_ids'])} cases missing); "
                         "the primary analysis requires every frozen case")
    output = args.output
    events = StageEventLedger(output / "finalized_evidence/stage_events.jsonl")
    table = finalize_feature_table(observations)
    _write_jsonl(output / "runtime_features/semantic_runtime_features.jsonl", table["rows"])
    descriptive = {
        "schema_version": "bite.semantic_observation_descriptive.v1",
        "status": "GT_FREE",
        "compatibility": dict(Counter(row["semantic_compatibility"] for row in table["rows"])),
        "response_status": validation["response_status_counts"],
        "fields": {field: dict(Counter(str(row[field]) for row in table["rows"])) for field in (
            "semantic_object_visible", "semantic_region_localization", "semantic_multiple_objects",
            "semantic_evidence_status")},
    }
    evidence = {
        "schema_version": "bite.semantic_finalized_evidence.v1",
        "rows_sha256": table["rows_sha256"],
        "observation_file_sha256": {
            str(path.relative_to(ROOT)): file_sha256(path)
            for path in sorted(args.run.glob("states/*/semantic_observation.json"))},
        "validation": validation,
        "offline_labels_joined": False,
    }
    atomic_json(output / "finalized_evidence/evidence.json", evidence)
    atomic_json(output / "failure_analysis/gt_free_descriptive.json", descriptive)
    events.append("raw_finalized", {"rows_sha256": table["rows_sha256"],
                                    "evidence_sha256": file_sha256(output / "finalized_evidence/evidence.json")})

    inventory = json.loads((PHASE04C1D / "manifest_checksums.json").read_text())["artifact_sha256"]
    events.append("offline_gt_open_authorized", {"label_source": "phase04c1d OOF M0 rows"})
    zoom_rows = _verified("outputs/bite/phase04c1d/runtime_features/expansion_runtime_features_v1.jsonl", inventory)
    results = {}
    for endpoint in ENDPOINTS:
        key = f"iou_{endpoint.replace('.', '_')}"
        targets = canonical_targets(_verified(f"outputs/bite/phase04c1d/crossfit_predictions/expansion_{key}.jsonl",
                                              inventory))
        rows = join_rows(table, table["rows_sha256"], targets, zoom_rows)
        _write_jsonl(output / f"offline_labels/joined_rows_{key}.jsonl", rows)
        result = evaluate_endpoint(rows, replicates=args.bootstrap_replicates)
        results[endpoint] = result
        if result["status"] == "ESTIMATED":
            _write_jsonl(output / f"crossfit_predictions/{key}.jsonl", result["predictions"])
            atomic_json(output / f"paired_metrics/{key}.json", {
                "support": result["support"], "model_metrics": result["model_metrics"],
                "frozen_design_comparisons": result["frozen_design_comparisons"]})
            atomic_json(output / f"grouped_uncertainty/{key}.json", result["paired_uncertainty"])
            atomic_json(output / f"costs/decision_screens_{key}.json", result["decision_screens"])
        else:
            atomic_json(output / f"paired_metrics/{key}.json", result)
        atomic_json(output / f"failure_analysis/{key}.json", failure_analysis(rows))
    events.append("labels_finalized", {"endpoints": list(ENDPOINTS)})
    atomic_json(output / "costs/action_costs.json", {
        "schema_version": "bite.action_cost_comparison.v1",
        "logical_dispatches_per_candidate": LOGICAL_COST,
        "semantic_measured": {"token_usage_total": validation["token_usage_total"],
                              "latency_ms": validation["latency_ms"],
                              "requests": validation["attempted"]},
        "zoom_tokens": "not applicable (SAM 3)",
        "gpu_time_measured": False,
        "monetary_cost_known": False,
        "sam3_and_vlm_dispatch_treated_as_equal_cost": False,
    })
    decision = research_decision(validation["valid_rate"], results)
    atomic_json(output / "research_decision/decision.json", decision)
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()
