#!/usr/bin/env python3
"""Freeze the metadata-only future validation collection protocol; do not execute it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.validation_protocol import (
    build_validation_protocol,
    validate_validation_protocol,
)
from evaluation_kit.bite_collection.persistence import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--partition-manifest", type=Path,
        default=Path("outputs/bite/phase04b2b1a/manifests/calibration_partition_manifest.json"),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("outputs/bite/phase04c1a/validation_protocol/task_v_validation_collection_v1.json"),
    )
    args = parser.parse_args()
    protocol = validate_validation_protocol(build_validation_protocol(args.partition_manifest))
    atomic_json(args.output, protocol)
    print(json.dumps({
        "status": protocol["status"],
        "groups": protocol["selection"]["group_count"],
        "maximum_query_states": protocol["query_design"]["maximum_query_states"],
        "maximum_logical_dispatches": protocol["action_policy"]["maximum_logical_dispatches"],
        "executed": protocol["execution"]["authorized_in_phase04c1a"],
    }, indent=2))


if __name__ == "__main__":
    main()
