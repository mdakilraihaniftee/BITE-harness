#!/usr/bin/env python3
"""Create SOURCE_PENDING or freeze an explicitly approved verified source."""

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.manifest_freeze import freeze_manifest, provisional_manifest, validate_frozen_manifest
from evaluation_kit.bite_calibration.source_registry import default_registry, validate_registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--source-id")
    parser.add_argument("--verified-entries", type=Path)
    parser.add_argument("--validate-existing", type=Path, help="Validate an existing frozen manifest and its checksum")
    parser.add_argument("--exclusions", type=Path)
    parser.add_argument("--salt", default="bite-calibration-v1")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text()) if args.registry else default_registry()
    validate_registry(registry)
    exclusions = json.loads(args.exclusions.read_text()) if args.exclusions else []
    if isinstance(exclusions, dict):
        exclusions = exclusions.get("entries", [])
    if args.validate_existing:
        if not args.source_id:
            raise SystemExit("--source-id is required with --validate-existing")
        source = next((item for item in registry["sources"] if item["source_id"] == args.source_id), None)
        if source is None:
            raise SystemExit(f"Unknown source: {args.source_id}")
        validate_frozen_manifest(json.loads(args.validate_existing.read_text()), source)
        print(json.dumps({"valid": True, "manifest": str(args.validate_existing), "source_id": args.source_id}, sort_keys=True))
        return
    if not args.output:
        raise SystemExit("--output is required unless --validate-existing is used")
    if not args.source_id:
        manifest = provisional_manifest(registry, exclusions=exclusions)
    else:
        if not args.verified_entries:
            raise SystemExit("--verified-entries is required when --source-id is supplied")
        source = next((item for item in registry["sources"] if item["source_id"] == args.source_id), None)
        if source is None:
            raise SystemExit(f"Unknown source: {args.source_id}")
        document = json.loads(args.verified_entries.read_text())
        entries = document.get("entries", document) if isinstance(document, dict) else document
        manifest = freeze_manifest(source, entries, salt=args.salt, exclusions=exclusions)
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if not args.dry_run:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
