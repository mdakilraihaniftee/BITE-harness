#!/usr/bin/env python3
"""Create the versioned Task V annotation-proxy protocol amendment artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.annotation_proxy_protocol import (
    build_protocol,
    validate_protocol,
)
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1c_revised"))
    args = parser.parse_args()
    protocol = build_protocol(
        partition_manifest_path=ROOT / "outputs/bite/phase04b2b1a/manifests/calibration_partition_manifest.json",
        expansion_records_path=ROOT / "outputs/bite/phase04b2b4/diagnostics/expansion_paired_diagnostics.jsonl",
        review_cases_path=ROOT / "outputs/bite/phase04b2b4/review_interface/review_cases.jsonl",
    )
    validate_protocol(protocol)
    destination = args.output / "protocol/task_v_annotation_proxy_protocol_v2.json"
    atomic_json(destination, protocol)
    print(json.dumps(protocol, indent=2))


if __name__ == "__main__":
    main()
