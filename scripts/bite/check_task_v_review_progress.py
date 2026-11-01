#!/usr/bin/env python3
"""Validate Task V human-review readiness and report genuine progress only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

from evaluation_kit.bite_calibration.review_progress import (
    build_second_review_sample,
    load_review_inputs,
    review_progress,
)
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1b"))
    args = parser.parse_args()
    cases, statistical, targeted, completed = load_review_inputs(ROOT)
    second = build_second_review_sample(cases, statistical)
    atomic_json(args.output / "review_progress/second_review_sample.json", second)
    progress = review_progress(
        cases, statistical, targeted, completed,
        event_roots=(
            ROOT / "outputs/bite/phase04c1a/review_validation/events",
            args.output / "review_progress/events",
        ),
        second_review_sample=second,
    )
    checks = []
    queue = set(statistical["case_ids"]) | set(targeted["case_ids"])
    case_map = {row["case_id"]: row for row in cases}
    for case_id in sorted(queue):
        case = case_map[case_id]
        path = Path(case["source_image_path"])
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        with Image.open(path) as image:
            dimensions = list(image.size)
            image.verify()
        checks.append({
            "case_id": case_id, "digest_valid": actual == case["source_image_sha256"],
            "dimensions_valid": dimensions == [case["image_width"], case["image_height"]],
        })
    if not all(row["digest_valid"] and row["dimensions_valid"] for row in checks):
        raise RuntimeError("Human-review source identity check failed")
    progress.update({
        "source_case_count_checked": len(checks), "all_source_identities_valid": True,
        "blind_protocol_for_new_reviews": "bite.task_v_blind_adjudication_protocol.v3",
        "visual_endpoint_for_new_reviews": "bite.visual_verification.v2",
    })
    atomic_json(args.output / "review_progress/progress.json", progress)
    atomic_json(args.output / "review_progress/source_identity_checks.json", {
        "schema_version": "bite.task_v_review_source_validation.v2",
        "checked": len(checks), "all_valid": True, "checks": checks,
    })
    print(json.dumps(progress, indent=2))


if __name__ == "__main__":
    main()
