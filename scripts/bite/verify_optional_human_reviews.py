#!/usr/bin/env python3
"""Validate genuine Task V human records and write a non-mutating optional summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.optional_human_review import (
    summarize_optional_reviews,
    validate_optional_review_summary,
)
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1c_revised"))
    args = parser.parse_args()
    prior = ROOT / "outputs/bite/phase04b2b4"
    summary = summarize_optional_reviews(
        review_cases_path=prior / "review_interface/review_cases.jsonl",
        statistical_sample_path=prior / "review_sampling/statistical_review_sample.json",
        targeted_sample_path=prior / "review_sampling/targeted_review_sample.json",
        completed_dir=prior / "human_adjudications/completed",
        event_root=ROOT / "outputs/bite/phase04c1b/review_validation/events",
        second_review_sample_path=ROOT / "outputs/bite/phase04c1b/review_progress/second_review_sample.json",
    )
    validate_optional_review_summary(summary)
    atomic_json(args.output / "optional_human_reviews/status.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
