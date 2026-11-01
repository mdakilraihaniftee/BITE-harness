#!/usr/bin/env python3
"""Extract GT-free focused evidence and produce separate offline diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.evidence_diagnostics import (
    build_diagnostics,
    build_feature_records,
)
from evaluation_kit.bite_collection.persistence import atomic_json


def _write_jsonl(path, rows, projection=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(projection(row) if projection else row, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04b2b4"))
    args = parser.parse_args()
    definitions = {
        "pilot": {
            "pair_path": "outputs/bite/phase04b2b3/analysis/focused_pairs.jsonl",
            "run_root": "outputs/bite/phase04b2b2/observations/aquarium_task_v_seed417_g20",
            "cohort_id": "bite.task_v_pilot.seed417.g20.v1",
            "query_design_id": "two_source_classes_per_group.v1",
        },
        "expansion": {
            "pair_path": "outputs/bite/phase04b2b3/analysis/expansion_focused/focused_pairs.jsonl",
            "run_root": "outputs/bite/phase04b2b3/expansion/aquarium_task_v_expansion_seed418_g30",
            "cohort_id": "bite.task_v_expansion.seed418.g30.v1",
            "query_design_id": "all_seven_source_classes_per_group.v1",
        },
    }
    cohorts = {}
    for name, kwargs in definitions.items():
        records = build_feature_records(**kwargs)
        cohorts[name] = records
        _write_jsonl(args.output / f"conditional_features/{name}_runtime_features.jsonl", records,
                     lambda row: row["runtime_features"])
        _write_jsonl(args.output / f"diagnostics/{name}_paired_diagnostics.jsonl", records)
    diagnostics = build_diagnostics(cohorts)
    atomic_json(args.output / "diagnostics/conditional_evidence_summary.json", diagnostics)
    print(json.dumps(diagnostics, indent=2))


if __name__ == "__main__":
    main()
