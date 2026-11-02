#!/usr/bin/env python3
"""Create the endpoint-specific revised Phase 4C-1C readiness decision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.endpoint_readiness import endpoint_readiness
from evaluation_kit.bite_collection.persistence import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1c_revised"))
    args = parser.parse_args()
    load = lambda path: json.loads(Path(path).read_text())
    priors = [load(path) for path in sorted((args.output / "frozen_priors").glob("0_*_*.json"))]
    report = endpoint_readiness(
        protocol=load(args.output / "protocol/task_v_annotation_proxy_protocol_v2.json"),
        human_review=load(args.output / "optional_human_reviews/status.json"),
        frozen_priors=priors,
        provenance=load(args.output / "worker_provenance/sam3_provenance.json"),
        validation_contract=load(args.output / "validation_preflight/preflight_v2.json"),
    )
    atomic_json(args.output / "readiness/readiness.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
