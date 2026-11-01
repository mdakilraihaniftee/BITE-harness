"""Honest Task V review progress and deterministic independent-review planning."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

SECOND_REVIEW_VERSION = "bite.task_v_second_review_sample.v1"
PROGRESS_VERSION = "bite.task_v_review_progress.v2"


def _json(path):
    return json.loads(Path(path).read_text())


def _jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def build_second_review_sample(cases, statistical_sample, *, seed=457,
                               pilot_group_count=2, expansion_group_count=3):
    case_map = {row["case_id"]: row for row in cases}
    selected = {}
    counts = {
        "bite.task_v_pilot.seed417.g20.v1": pilot_group_count,
        "bite.task_v_expansion.seed418.g30.v1": expansion_group_count,
    }
    for cohort, groups in statistical_sample["selected_groups"].items():
        ordered = sorted(
            groups,
            key=lambda group: hashlib.sha256(f"{seed}:{cohort}:{group}".encode()).hexdigest(),
        )
        selected[cohort] = ordered[:counts[cohort]]
    selected_pairs = {(cohort, group) for cohort, groups in selected.items() for group in groups}
    case_ids = [
        case_id for case_id in statistical_sample["case_ids"]
        if (case_map[case_id]["cohort_id"], case_map[case_id]["source_group_id"]) in selected_pairs
    ]
    return {
        "schema_version": SECOND_REVIEW_VERSION,
        "seed": seed,
        "sampling_unit": "source_group_id",
        "sampling_frame": "frozen Set A groups only",
        "selection_rule": "lowest sha256(seed:cohort:source_group_id) within cohort",
        "selected_groups": selected,
        "source_group_count": sum(map(len, selected.values())),
        "case_ids": case_ids,
        "case_count": len(case_ids),
        "preserves_original_set_a": True,
        "second_reviewer_blinded_to_first_reviewer": True,
        "agreement_claimed": False,
    }


def review_progress(cases, statistical_sample, targeted_sample, completed_reviews,
                    event_roots=(), *, second_review_sample=None):
    case_ids = {row["case_id"] for row in cases}
    set_a = set(statistical_sample["case_ids"])
    set_b = set(targeted_sample["case_ids"])
    completed = [row for row in completed_reviews if row.get("case_id") in case_ids]
    completed_pairs = {(row["case_id"], row["reviewer_id"]) for row in completed}
    completed_cases = {row["case_id"] for row in completed}
    chains = defaultdict(list)
    first_count = reveal_count = post_count = changed_count = 0
    omission_investigation = set()
    for root in map(Path, event_roots):
        if not root.is_dir():
            continue
        for directory in sorted(root.iterdir()):
            first_path = directory / "0001_blind_first_pass.json"
            if not first_path.is_file():
                continue
            first = json.loads(first_path.read_text())
            case_id = first.get("case_id")
            reviewer_id = first.get("reviewer_id")
            if case_id not in case_ids:
                continue
            first_count += 1
            reveal_path = directory / "0002_gt_revealed.json"
            post_path = directory / "0003_post_reveal.json"
            reveal_count += int(reveal_path.is_file())
            post = json.loads(post_path.read_text()) if post_path.is_file() else None
            post_count += int(post is not None)
            changed_count += int(bool(post and post.get("changed_from_blind")))
            selected = post or first
            controls = selected.get("legacy_evidence_controls", {})
            if controls.get("relevant_annotation_appears_missing") == "yes":
                omission_investigation.add(case_id)
            chains[case_id].append({
                "reviewer_id": reviewer_id,
                "first_endpoint": first.get("derived_visual_endpoint", {}).get("binary_visual_endpoint"),
                "post_endpoint": post.get("derived_visual_endpoint", {}).get("binary_visual_endpoint") if post else None,
            })
    double_reviewed = {case_id: rows for case_id, rows in chains.items() if len(rows) >= 2}
    disagreements = 0
    comparable_double_reviews = 0
    for rows in double_reviewed.values():
        endpoints = [row["post_endpoint"] if row["post_endpoint"] is not None else row["first_endpoint"] for row in rows]
        decisive = [value for value in endpoints if value in {0, 1}]
        if len(decisive) >= 2:
            comparable_double_reviews += 1
            disagreements += int(len(set(decisive)) > 1)
    second_ids = set(second_review_sample["case_ids"]) if second_review_sample else set()
    return {
        "schema_version": PROGRESS_VERSION,
        "queue_union_case_count": len(set_a | set_b),
        "genuine_completed_review_count": len(completed_pairs),
        "completed_case_count": len(completed_cases),
        "set_a": {
            "total": len(set_a), "completed": len(set_a & completed_cases),
            "remaining": len(set_a - completed_cases),
        },
        "set_b": {
            "total": len(set_b), "completed": len(set_b & completed_cases),
            "remaining": len(set_b - completed_cases),
            "prevalence_estimation_permitted": False,
        },
        "event_progress": {
            "blind_first_pass_count": first_count,
            "gt_reveal_count": reveal_count,
            "post_reveal_count": post_count,
            "first_to_post_change_count": changed_count,
        },
        "double_review": {
            "prespecified_case_count": len(second_ids),
            "prespecified_completed_case_count": len(second_ids & completed_cases),
            "cases_with_two_event_chains": len(double_reviewed),
            "comparable_decisive_case_count": comparable_double_reviews,
            "reviewer_disagreement_count": disagreements,
            "agreement_statistic": None if comparable_double_reviews == 0 else 1 - disagreements / comparable_double_reviews,
        },
        "annotation_omission_investigation_case_count": len(omission_investigation),
        "visual_label_reliability": "UNKNOWN" if not completed_pairs else "REQUIRES_ANALYSIS",
        "annotation_omission_prevalence": None,
        "fake_human_reviews_created": False,
    }


def load_review_inputs(root):
    root = Path(root)
    prior = root / "outputs/bite/phase04b2b4"
    cases = _jsonl(prior / "review_interface/review_cases.jsonl")
    statistical = _json(prior / "review_sampling/statistical_review_sample.json")
    targeted = _json(prior / "review_sampling/targeted_review_sample.json")
    completed_dir = prior / "human_adjudications/completed"
    completed = [_json(path) for path in sorted(completed_dir.glob("*.json"))]
    return cases, statistical, targeted, completed
