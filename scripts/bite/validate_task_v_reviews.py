#!/usr/bin/env python3
"""Validate completed Task V human adjudications; pending rows are not completion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.adjudication_validation import (
    validate_adjudications,
)
from evaluation_kit.bite_collection.persistence import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04b2b4"))
    args = parser.parse_args()
    cases = [json.loads(line) for line in (args.output / "review_interface/review_cases.jsonl").read_text().splitlines()]
    reviews = []
    for path in sorted((args.output / "human_adjudications/completed").rglob("*.json")):
        reviews.append(json.loads(path.read_text()))
    statistical = json.loads((args.output / "review_sampling/statistical_review_sample.json").read_text())
    result = validate_adjudications(cases, reviews, statistical_case_ids=statistical["case_ids"])
    atomic_json(args.output / "validation/human_adjudication_validation.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
