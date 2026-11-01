#!/usr/bin/env python3
"""Validate one persisted collection manifest and all referenced branches."""

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_collection.persistence import hydrate_snapshot_record
from evaluation_kit.bite_collection.validation import validate_collection


def main():
    parser = argparse.ArgumentParser(description="Validate BITE collection_state.v1 and collection.v1 files")
    parser.add_argument("manifest")
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text())
    def resolve(value):
        path = Path(value)
        return path if path.is_absolute() or path.exists() else manifest_path.parent / path
    snapshot_path = resolve(manifest["snapshot"])
    snapshot = hydrate_snapshot_record(snapshot_path)
    branches = [json.loads(resolve(path).read_text()) for path in manifest["branches"]]
    print(json.dumps(validate_collection(snapshot, branches), indent=2))


if __name__ == "__main__":
    main()
