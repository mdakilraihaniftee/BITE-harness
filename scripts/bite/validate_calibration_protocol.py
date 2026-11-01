#!/usr/bin/env python3
"""Validate a frozen bite.calibration_protocol.v1 document."""

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.protocol_validation import validate_protocol


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text())
    validate_protocol(protocol)
    print(json.dumps({"valid": True, "schema_version": protocol["schema_version"], "status": protocol["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
