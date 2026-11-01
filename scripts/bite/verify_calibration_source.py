#!/usr/bin/env python3
"""Verify one already-local source; no network or dataset construction."""

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.source_registry import default_registry, registry_with_local_paths
from evaluation_kit.bite_calibration.source_verification import verify_detection_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--image-root", required=True, type=Path)
    parser.add_argument("--annotation", required=True, type=Path)
    parser.add_argument("--heldout-entries", type=Path, help="Optional JSON array from the Phase 4A inventory")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Resolve inputs and report checks without writing")
    args = parser.parse_args()
    registry = registry_with_local_paths(default_registry(), args.source_id, image_root=args.image_root, annotation_path=args.annotation)
    source = next(item for item in registry["sources"] if item["source_id"] == args.source_id)
    heldout = json.loads(args.heldout_entries.read_text()) if args.heldout_entries else []
    if isinstance(heldout, dict):
        heldout = heldout.get("image_entries", heldout.get("entries", []))
    report = verify_detection_source(source, heldout)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output and not args.dry_run:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
