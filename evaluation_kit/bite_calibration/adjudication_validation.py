"""Validate pending and completed visual-adjudication records."""

from __future__ import annotations

from collections import Counter

from .adjudication_schema import validate_case, validate_review


def validate_adjudications(cases, reviews, *, statistical_case_ids=None):
    case_map = {case["case_id"]: validate_case(case) for case in cases}
    if len(case_map) != len(cases):
        raise ValueError("Duplicate review case IDs")
    by_case = {}
    reviewer_pairs = set()
    for review in reviews:
        case_id = review.get("case_id")
        if case_id not in case_map:
            raise ValueError(f"Unknown review case: {case_id}")
        validate_review(review, expected_case=case_map[case_id])
        pair = (case_id, review["reviewer_id"])
        if pair in reviewer_pairs:
            raise ValueError("A reviewer may submit at most one judgment per case")
        reviewer_pairs.add(pair)
        by_case.setdefault(case_id, []).append(review)
    agreements = disagreements = 0
    for rows in by_case.values():
        if len(rows) >= 2:
            if len({row["H_visual_review"] for row in rows}) == 1:
                agreements += 1
            else:
                disagreements += 1
    labels = Counter(row["H_visual_review"] for rows in by_case.values() for row in rows)
    statistical_ids = set(statistical_case_ids or ())
    statistical_reviews = [
        row for case_id, rows in by_case.items() if case_id in statistical_ids for row in rows
    ]
    statistical_labels = Counter(row["H_visual_review"] for row in statistical_reviews)
    statistical_reviewed_cases = len(statistical_ids & set(by_case))
    return {
        "schema_version": "bite.task_v_adjudication_validation.v1",
        "case_count": len(cases),
        "completed_human_judgments": len(reviews),
        "reviewed_case_count": len(by_case),
        "pending_case_count": len(cases) - len(by_case),
        "double_reviewed_case_count": agreements + disagreements,
        "double_review_agreement_count": agreements,
        "double_review_disagreement_count": disagreements,
        "visual_label_counts": dict(sorted(labels.items())),
        "statistical_sample_case_count": len(statistical_ids),
        "statistical_sample_reviewed_case_count": statistical_reviewed_cases,
        "suspected_omission_rate": (
            statistical_labels.get("possible_annotation_omission", 0) / len(statistical_reviews)
            if statistical_reviews else None
        ),
        "omission_rate_scope": "statistical_quality_sample_only",
        "targeted_queue_excluded_from_prevalence_estimate": True,
        "visual_label_reliability_established": (
            bool(statistical_ids) and statistical_reviewed_cases == len(statistical_ids)
            and agreements > 0 and disagreements == 0
        ),
    }
