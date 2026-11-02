#!/usr/bin/env python3
"""Prepare, but do not launch, an immutable-revision SAM 3 attestation plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.sam3_attested_worker import prepare_attested_worker
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=Path("outputs/bite/phase04c1d/worker_attestation/preparation.json"),
    )
    args = parser.parse_args()
    historical = json.loads((
        ROOT / "outputs/bite/phase04c1c_revised/worker_provenance/sam3_provenance.json"
    ).read_text())
    cached = historical["cached_checkpoint"]
    files = cached["files"]
    preparation = prepare_attested_worker(
        model_id=historical["configured_checkpoint"]["model_id"],
        revision=cached["expected_revision"],
        cache_root=cached["cache_root"],
        expected_weight_sha256=files["sam3.pt"]["sha256"],
        expected_config_sha256=files["config.json"]["sha256"],
        expected_processor_sha256=files["processor_config.json"]["sha256"],
        worker_source=ROOT / "openvlharness/services/tools/sam3_segment/server.py",
        worker_config=ROOT / "openvlharness/services/tools/sam3_segment/run_sam3_server.sh",
        environment=historical["environment"],
    )
    preparation["historical_provenance_input"] = {
        "path": "outputs/bite/phase04c1c_revised/worker_provenance/sam3_provenance.json",
        "status": historical["status"],
    }
    atomic_json(args.output, preparation)
    print(json.dumps(preparation, indent=2))


if __name__ == "__main__":
    main()
