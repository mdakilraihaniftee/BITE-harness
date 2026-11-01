"""Reproducible source-group-aware Task V review sampling."""

from __future__ import annotations

import random
from collections import defaultdict


def statistical_quality_sample(cases, *, seed=420, pilot_groups=10, expansion_groups=15):
    """Sample source groups uniformly within cohort, then retain all their cases."""
    grouped = defaultdict(lambda: defaultdict(list))
    for case in cases:
        grouped[case["cohort_id"]][case["source_group_id"]].append(case)
    allocation = {
        "bite.task_v_pilot.seed417.g20.v1": pilot_groups,
        "bite.task_v_expansion.seed418.g30.v1": expansion_groups,
    }
    selected = []
    probabilities = {}
    selected_groups = {}
    for offset, (cohort, count) in enumerate(allocation.items()):
        frame = sorted(grouped[cohort])
        if count > len(frame):
            raise ValueError(f"Requested {count} groups from {len(frame)} in {cohort}")
        chosen = random.Random(seed + offset).sample(frame, count)
        selected_groups[cohort] = chosen
        probabilities[cohort] = count / len(frame)
        for group in chosen:
            selected.extend(grouped[cohort][group])
    selected.sort(key=lambda row: (row["cohort_id"], row["source_group_id"], row["query"], row["case_id"]))
    return {
        "schema_version": "bite.task_v_statistical_review_sample.v1",
        "seed": seed,
        "sampling_unit": "source_group_id",
        "sampling_frame": "candidate-bearing calibration-fit source groups within each frozen cohort",
        "design": "independent_SRSWOR_within_cohort_all_candidate_cases_in_selected_groups",
        "frame_group_counts": {cohort: len(groups) for cohort, groups in grouped.items()},
        "selected_groups": selected_groups,
        "group_inclusion_probabilities": probabilities,
        "case_inclusion_probability_equals_group_probability": True,
        "case_ids": [row["case_id"] for row in selected],
        "source_group_count": sum(map(len, selected_groups.values())),
        "case_count": len(selected),
        "estimation_scope": "annotation-versus-visual disagreement under each cohort query design",
    }


def targeted_failure_sample(cases):
    """Deterministic diagnostic union; it has no prevalence inclusion probability."""
    reasons = {}
    for case in cases:
        case_reasons = []
        if case["H_annotation"]["0.5"] == "negative" and case["initial_score"] >= 0.90:
            case_reasons.append("high_score_invalid_at_iou_0_50")
        if case["diagnostic_primary"] == "no_annotated_instance":
            case_reasons.append("no_annotated_queried_class_instance")
        if case["diagnostic_primary"] in {
            "insufficient_localization", "wrong_instance_or_class_confusion", "wrong_location",
        }:
            case_reasons.append(case["diagnostic_primary"])
        if case["focused_association_category"] == "ambiguous_target_association":
            case_reasons.append("focused_association_ambiguous")
        if case["candidate_size"] == "small":
            case_reasons.append("small_candidate")
        if case_reasons:
            reasons[case["case_id"]] = sorted(set(case_reasons))
    return {
        "schema_version": "bite.task_v_targeted_review_sample.v1",
        "design": "deterministic_diagnostic_union",
        "case_ids": sorted(reasons),
        "selection_reasons": reasons,
        "case_count": len(reasons),
        "prevalence_estimation_permitted": False,
        "inclusion_probability": None,
    }
