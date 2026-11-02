#!/usr/bin/env python3
"""Build revised endpoint-aware metadata-only validation execution contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.validation_model_contract import (
    build_validation_contract,
    validate_contract,
)
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1c_revised"))
    args = parser.parse_args()
    frozen = sorted((args.output / "frozen_priors").glob("0_*_*.json"))
    contract = build_validation_contract(
        validation_protocol_path=ROOT / "outputs/bite/phase04c1a/validation_protocol/task_v_validation_collection_v1.json",
        prior_preflight_path=ROOT / "outputs/bite/phase04c1b/validation_preflight/preflight.json",
        annotation_protocol_path=args.output / "protocol/task_v_annotation_proxy_protocol_v2.json",
        frozen_prior_paths=frozen,
        provenance_path=args.output / "worker_provenance/sam3_provenance.json",
        partition_manifest_path=ROOT / "outputs/bite/phase04b2b1a/manifests/calibration_partition_manifest.json",
    )
    validate_contract(contract)
    atomic_json(args.output / "validation_preflight/preflight_v2.json", contract)
    print(json.dumps(contract, indent=2))


if __name__ == "__main__":
    main()
