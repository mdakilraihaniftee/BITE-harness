#!/usr/bin/env python3
"""Run a read-only SAM 3 provenance audit without importing or loading the model."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from evaluation_kit.bite_calibration.sam3_provenance import (
    audit_sam3_provenance,
    validate_provenance,
)
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1c_revised"))
    args = parser.parse_args()
    process = subprocess.run(
        ["ps", "-eo", "pid,lstart,cmd"], capture_output=True, text=True, check=True,
    )
    lines = [
        line for line in process.stdout.splitlines()
        if "sam3" in line.lower() and "audit_sam3_provenance.py" not in line
    ]
    report = audit_sam3_provenance(
        cache_root=ROOT / ".cache/huggingface/hub/models--facebook--sam3",
        site_packages=ROOT / ".venvs/sam3/lib/python3.11/site-packages",
        worker_source=ROOT / "openvlharness/services/tools/sam3_segment/server.py",
        worker_config=ROOT / "configs/agent/qwen3_8b_paper.yaml",
        worker_log_paths=[ROOT / "outputs/services/sam3.log", ROOT / "outputs/services/sam3-current.log"],
        active_process_lines=lines,
    )
    validate_provenance(report)
    atomic_json(args.output / "worker_provenance/sam3_provenance.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
