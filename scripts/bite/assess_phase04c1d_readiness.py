#!/usr/bin/env python3
"""Classify Phase 4C-1D from the frozen paired Zoom comparisons."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.zoom_evidence_readiness import (
    assess_zoom_readiness,
)
from evaluation_kit.bite_collection.persistence import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path("outputs/bite/phase04c1d"),
    )
    args = parser.parse_args()
    root = args.root
    results = json.loads((root / "paired_metrics/results.json").read_text())["expansion"]
    for endpoint in ("0.5", "0.75"):
        key = f"iou_{endpoint.replace('.', '_')}"
        uncertainty = json.loads((root / f"grouped_uncertainty/expansion_{key}.json").read_text())
        results[endpoint]["paired_uncertainty"] = uncertainty
    preparation = json.loads((root / "worker_attestation/preparation.json").read_text())
    readiness = assess_zoom_readiness(
        results, checkpoint_status=preparation["historical_comparability_status"],
    )
    readiness["matched_worker_bridge"] = json.loads((
        root / "matched_worker_bridge/protocol.json"
    ).read_text())["status"]
    atomic_json(root / "readiness/readiness.json", readiness)
    print(json.dumps(readiness, indent=2))


if __name__ == "__main__":
    main()
