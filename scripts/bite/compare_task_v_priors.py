#!/usr/bin/env python3
"""Reproduce frozen prior metrics and run paired source-group comparisons."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from evaluation_kit.bite_calibration.paired_model_comparison import (
    load_frozen_predictions,
    paired_group_bootstrap,
    reproduce_metrics,
)
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1b"))
    args = parser.parse_args()
    source = ROOT / "outputs/bite/phase04c1a"
    previous = json.loads((source / "implementation_manifest.json").read_text())
    frozen = json.loads((source / "proxy_models/prior_experiment_summary.json").read_text())
    integrity = []
    intentionally_versioned = {
        "evaluation_kit/bite_calibration/blind_review.py",
        "evaluation_kit/bite_calibration/visual_endpoint.py",
        "scripts/bite/serve_task_v_blind_review.py",
    }
    for section in ("source_sha256", "script_sha256", "test_sha256", "documentation_sha256", "artifact_sha256"):
        for name, expected in previous[section].items():
            path = ROOT / name
            actual = sha(path) if path.is_file() else None
            integrity.append({
                "path": name, "expected": expected, "actual": actual,
                "valid": actual == expected,
                "classification": (
                    "expected_versioned_phase04c1b_source_change"
                    if name in intentionally_versioned else "must_remain_unchanged"
                ),
            })
    immutable = [row for row in integrity if row["classification"] == "must_remain_unchanged"]
    versioned = [row for row in integrity if row["classification"] != "must_remain_unchanged"]
    if not all(row["valid"] for row in immutable):
        raise RuntimeError("Phase 4C-1A integrity verification failed")
    atomic_json(args.output / "integrity/phase04c1a_verification.json", {
        "schema_version": "bite.phase04c1a_integrity_verification.v1",
        "reference_count": len(integrity),
        "immutable_reference_count": len(immutable),
        "immutable_references_all_valid": True,
        "versioned_source_change_count": len(versioned),
        "versioned_source_changes": versioned,
        "historical_artifacts_rewritten": False,
        "checks": integrity,
    })
    for index, (experiment, summary) in enumerate(frozen["experiments"].items()):
        path = source / "crossfit" / f"{experiment}_predictions.jsonl"
        _, aligned = load_frozen_predictions(path)
        reproduction = reproduce_metrics(aligned, summary)
        reproduction.update({
            "schema_version": "bite.phase04c1a_metric_reproduction.v1",
            "experiment": experiment,
            "prediction_artifact": str(path.relative_to(ROOT)),
            "prediction_sha256": sha(path),
            "models_refit": False,
        })
        atomic_json(args.output / "integrity" / f"{experiment}_metric_reproduction.json", reproduction)
        paired = paired_group_bootstrap(aligned, replicates=2000, seed=451 + index)
        paired.update({
            "experiment": experiment, "cohort": summary["cohort"],
            "endpoint": summary["endpoint"], "prediction_sha256": sha(path),
            "development_model_selection_optimism": True,
        })
        atomic_json(args.output / "paired_comparisons" / f"{experiment}.json", paired)
    print(json.dumps({"status": "PAIRED_COMPARISON_COMPLETE", "experiments": 4,
                      "phase04c1a_immutable_references_verified": len(immutable)}, indent=2))


if __name__ == "__main__":
    main()
