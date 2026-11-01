#!/usr/bin/env python3
"""Print an exact acquisition plan; intentionally performs no download."""

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.source_preparation import acquisition_plan
from evaluation_kit.bite_calibration.source_registry import default_registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true", default=True, help="Required safety mode; downloads are not implemented")
    args = parser.parse_args()
    source = next((item for item in default_registry()["sources"] if item["source_id"] == args.source_id), None)
    if source is None:
        raise SystemExit(f"Unknown source: {args.source_id}")
    plan = acquisition_plan(source, args.destination)
    rendered = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
