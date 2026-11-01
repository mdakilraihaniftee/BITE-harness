#!/usr/bin/env python3
"""Validate blind-review ordering, frozen sample identities and honest human progress."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from PIL import Image

from evaluation_kit.bite_calibration.adjudication_validation import (
    validate_adjudications,
)
from evaluation_kit.bite_calibration.blind_review import (
    load_event_chain,
    progress_summary,
)
from evaluation_kit.bite_calibration.visual_endpoint import VISUAL_ENDPOINT_VERSION
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
PILOT = "bite.task_v_pilot.seed417.g20.v1"
EXPANSION = "bite.task_v_expansion.seed418.g30.v1"


def _jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1a"))
    args = parser.parse_args()
    prior = ROOT / "outputs/bite/phase04b2b4"
    cases = _jsonl(prior / "review_interface/review_cases.jsonl")
    case_map = {row["case_id"]: row for row in cases}
    queue = json.loads((prior / "review_interface/review_queue.json").read_text())["case_ids"]
    statistical = json.loads((prior / "review_sampling/statistical_review_sample.json").read_text())
    completed_dir = prior / "human_adjudications/completed"
    completed = [json.loads(path.read_text()) for path in sorted(completed_dir.glob("*.json"))]
    validation = validate_adjudications(
        cases, completed, statistical_case_ids=statistical["case_ids"],
    )
    frames = defaultdict(set)
    for case in cases:
        frames[case["cohort_id"]].add(case["source_group_id"])
    expected_probabilities = {PILOT: 10 / 19, EXPANSION: 15 / 30}
    for cohort, expected in expected_probabilities.items():
        actual = statistical["group_inclusion_probabilities"][cohort]
        if actual != expected or len(frames[cohort]) != (19 if cohort == PILOT else 30):
            raise RuntimeError("Frozen review sampling probability or frame mismatch")
    source_checks = []
    for case_id in queue:
        case = case_map[case_id]
        source_path = Path(case["source_image_path"])
        actual = hashlib.sha256(source_path.read_bytes()).hexdigest()
        with Image.open(source_path) as image:
            dimensions_valid = image.size == (case["image_width"], case["image_height"])
            image.verify()
        source_checks.append({
            "case_id": case_id, "expected": case["source_image_sha256"],
            "actual": actual, "digest_valid": actual == case["source_image_sha256"],
            "dimensions_valid": dimensions_valid,
            "image_decode_valid": True,
            "valid": actual == case["source_image_sha256"] and dimensions_valid,
        })
    if not all(row["valid"] for row in source_checks):
        raise RuntimeError("A review source image digest mismatch was detected")
    event_root = args.output / "review_validation/events"
    event_root.mkdir(parents=True, exist_ok=True)
    event_chains = []
    for directory in sorted(event_root.glob("*")):
        first_path = directory / "0001_blind_first_pass.json"
        if not first_path.is_file():
            raise RuntimeError(f"Incomplete event directory: {directory}")
        first = json.loads(first_path.read_text())
        case = case_map[first["case_id"]]
        chain = load_event_chain(event_root, case, first["reviewer_id"])
        event_chains.append({
            "case_id": case["case_id"], "reviewer_id": first["reviewer_id"],
            "blind_first_pass": chain["first_pass"] is not None,
            "gt_revealed": chain["reveal"] is not None,
            "post_reveal": chain["post_reveal"] is not None,
        })
    progress = progress_summary(cases, queue, event_root, completed)
    report = {
        **progress,
        "visual_endpoint_schema": VISUAL_ENDPOINT_VERSION,
        "statistical_sample": {
            "case_count": statistical["case_count"],
            "group_count": statistical["source_group_count"],
            "frame_group_counts": statistical["frame_group_counts"],
            "group_inclusion_probabilities": statistical["group_inclusion_probabilities"],
        },
        "targeted_sample_is_not_prevalence_sample": True,
        "source_hashes_checked": len(source_checks),
        "source_hashes_valid": all(row["valid"] for row in source_checks),
        "event_chains": event_chains,
        "authoritative_completion_validation": validation,
        "annotation_omission_prevalence_estimated": validation["suspected_omission_rate"] is not None,
        "reviewer_agreement_reported": validation["double_reviewed_case_count"] > 0,
        "fake_human_reviews_created": False,
    }
    destination = args.output / "review_validation"
    atomic_json(destination / "adjudication_progress.json", report)
    atomic_json(destination / "source_hash_validation.json", {
        "schema_version": "bite.task_v_review_source_validation.v1",
        "checked_case_count": len(source_checks), "all_valid": all(row["valid"] for row in source_checks),
        "checks": source_checks,
    })
    checklist = f"""# Task V human-adjudication completion checklist

Status: **{progress['human_review_status']}**.

- [x] Frozen Set A identity and inclusion probabilities verified.
- [x] All {len(source_checks)} queued source-image hashes verified.
- [x] Server-enforced blind-first event ordering implemented.
- [x] Viewing an image does not mark a case complete.
- [{'x' if progress['completed_case_count'] == progress['queue_case_count'] else ' '}] Complete queued human reviews: {progress['completed_case_count']}/{progress['queue_case_count']}.
- [{'x' if validation['double_reviewed_case_count'] else ' '}] Complete independent second reviews and assess agreement.
- [{'x' if validation['suspected_omission_rate'] is not None else ' '}] Estimate omission prevalence from Set A only.

Run the interface with:

```bash
.venv/bin/python scripts/bite/serve_task_v_blind_review.py
```

Then rerun this validator. Do not use targeted Set B for prevalence estimation.
"""
    (destination / "HUMAN_REVIEW_COMPLETION_CHECKLIST.md").write_text(checklist)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
