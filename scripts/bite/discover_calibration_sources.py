#!/usr/bin/env python3
"""Emit the reviewed source registry; never downloads data."""

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.source_registry import default_registry, validate_registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional registry JSON path")
    parser.add_argument("--dry-run", action="store_true", help="Print only; do not write")
    args = parser.parse_args()
    registry = default_registry()
    validate_registry(registry)
    rendered = json.dumps(registry, indent=2, sort_keys=True) + "\n"
    if args.output and not args.dry_run:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
