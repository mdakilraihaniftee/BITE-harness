#!/usr/bin/env python3
"""Build the unexecuted fit-only matched-worker bridge protocol."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.matched_worker_bridge import build_bridge_protocol
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=Path("outputs/bite/phase04c1d/matched_worker_bridge/protocol.json"),
    )
    args = parser.parse_args()
    expansion = json.loads((
        ROOT / "outputs/bite/phase04b2b3/protocol/task_v_expansion_protocol.json"
    ).read_text())
    annotation = json.loads((
        ROOT / "outputs/bite/phase04c1c_revised/protocol/task_v_annotation_proxy_protocol_v2.json"
    ).read_text())
    attestation = json.loads((
        ROOT / "outputs/bite/phase04c1d/worker_attestation/preparation.json"
    ).read_text())
    protocol = build_bridge_protocol(expansion, annotation, attestation)
    atomic_json(args.output, protocol)
    print(json.dumps(protocol, indent=2))


if __name__ == "__main__":
    main()
