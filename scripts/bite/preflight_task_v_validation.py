#!/usr/bin/env python3
"""Run metadata-only preflight of the frozen Task V validation protocol."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.validation_readiness import preflight_validation
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1b"))
    args = parser.parse_args()
    report = preflight_validation(
        ROOT / "outputs/bite/phase04c1a/validation_protocol/task_v_validation_collection_v1.json",
        ROOT / "outputs/bite/phase04b2b1a/manifests/calibration_partition_manifest.json",
        ROOT / "outputs/bite/phase04b2b1a/manifests/development_debug_exclusions.json",
        ROOT / "outputs/bite/phase04c1a/implementation_manifest.json",
        ROOT / "outputs/bite/reference_baseline/attempt_20261029T210515Z/checkpoint_refs.json",
        ROOT / "outputs/bite/phase04b2b3/preflight/preflight_report.json",
    )
    atomic_json(args.output / "validation_preflight/preflight.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
