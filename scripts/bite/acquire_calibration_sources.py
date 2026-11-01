#!/usr/bin/env python3
"""Dry-run or explicitly approved acquisition of allowlisted ODinW sources."""

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.source_acquisition import acquire_source, acquisition_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path("docs/bite/dataset_source_registry_v1.json"))
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--destination", type=Path, default=Path("data/calibration_sources/odinw13"))
    parser.add_argument("--approval-record", type=Path)
    parser.add_argument("--execute", action="store_true", help="Perform network transfer; requires an exact researcher approval record")
    parser.add_argument("--existing", choices=["error", "reuse_verified"], default="error")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text())
    approval = json.loads(args.approval_record.read_text()) if args.approval_record else None
    if args.execute:
        if approval is None:
            raise SystemExit("--execute requires --approval-record; assistant recommendations are not approval")
        result = acquire_source(registry, args.source_id, args.destination, approval, existing=args.existing)
    else:
        result = acquisition_plan(registry, args.source_id, args.destination, approval)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
