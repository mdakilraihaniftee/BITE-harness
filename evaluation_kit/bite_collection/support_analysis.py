"""Descriptive, design-aware support summary for Task V collection cohorts."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .persistence import atomic_json


def _read_json(path):
    return json.loads(Path(path).read_text())


def _read_jsonl(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _cell_support(audit, dimension, threshold="0.5"):
    result = {}
    for name, counts_by_threshold in audit[dimension].items():
        counts = counts_by_threshold[threshold]
        positive = counts.get("positive", 0)
        negative = counts.get("negative", 0)
        result[name] = {
            "positive": positive,
            "negative": negative,
            "support": "both" if positive and negative else "positive_only" if positive else "negative_only",
        }
    return result


def _cohort_summary(name, design, audit, diagnostics, focused):
    negatives = [row for row in diagnostics if not row["label_iou_0_50"]["official_tp"]]
    diagnoses = Counter(row["primary_diagnosis_iou_0_50"] for row in negatives)
    return {
        "cohort_id": name,
        "selection_design": design,
        "sampling": audit["sampling"],
        "candidate_present_states": len(diagnostics),
        "offline_labels": audit["offline_labels"],
        "offline_labels_by_query": audit["offline_labels_by_query"],
        "offline_labels_by_candidate_size": audit["offline_labels_by_candidate_size"],
        "high_score_invalid_definition": "raw retained SAM3 score >= 0.90 and H_V negative at IoU 0.50",
        "high_score_invalid_count": sum(row["raw_score"] >= 0.90 for row in negatives),
        "negative_primary_diagnoses": dict(sorted(diagnoses.items())),
        "manual_review_pending": sum(row["manual_review_status"] == "pending_visual_review" for row in diagnostics),
        "conditional_outcomes": {
            "actions": audit["actions"],
            "observation_outcomes": audit["observation_outcomes"],
            "exact_repeat": audit["exact_repeat"],
            "focused": focused,
        },
        "cost_and_resources": {
            "actual_logical_dispatches": audit["actual_logical_dispatches"],
            "latency_ms": audit["latency_ms"],
            "storage": audit["storage"],
            "resume": audit["resume"],
        },
        "support_cells_iou_0_50": {
            "query": _cell_support(audit, "offline_labels_by_query"),
            "candidate_size": _cell_support(audit, "offline_labels_by_candidate_size"),
        },
    }


def build_support_summary(
    *, pilot_audit_path, expansion_audit_path, pilot_diagnostics_path,
    expansion_diagnostics_path, pilot_focused_path, expansion_focused_path,
    output_path=None,
):
    pilot_audit = _read_json(pilot_audit_path)
    expansion_audit = _read_json(expansion_audit_path)
    pilot_diagnostics = _read_jsonl(pilot_diagnostics_path)
    expansion_diagnostics = _read_jsonl(expansion_diagnostics_path)
    pilot_focused = _read_json(pilot_focused_path)
    expansion_focused = _read_json(expansion_focused_path)
    pilot = _cohort_summary(
        "bite.task_v_pilot.seed417.g20.v1", "two_source_classes_per_group.v1",
        pilot_audit, pilot_diagnostics, pilot_focused,
    )
    expansion = _cohort_summary(
        "bite.task_v_expansion.seed418.g30.v1", "all_seven_source_classes_per_group.v1",
        expansion_audit, expansion_diagnostics, expansion_focused,
    )
    pooled_labels = {}
    for threshold in ("0.5", "0.75"):
        pooled_labels[threshold] = {
            label: pilot_audit["offline_labels"][threshold].get(label, 0)
            + expansion_audit["offline_labels"][threshold].get(label, 0)
            for label in ("positive", "negative", "unknown")
        }
    summary = {
        "schema_version": "bite.task_v_support_summary.v1",
        "status": "DESCRIPTIVE_ONLY_NO_PROBABILITIES_FITTED",
        "cohorts": {"original_pilot": pilot, "expansion": expansion},
        "pooled_descriptive": {
            "scope": "raw count aggregation only; retain cohort/design strata for any estimand",
            "source_groups": pilot_audit["sampling"]["source_groups"]
            + expansion_audit["sampling"]["source_groups"],
            "query_states": pilot_audit["sampling"]["scheduled_queries"]
            + expansion_audit["sampling"]["scheduled_queries"],
            "candidate_present_states": len(pilot_diagnostics) + len(expansion_diagnostics),
            "no_candidate_states": pilot_audit["sampling"]["no_candidate"]
            + expansion_audit["sampling"]["no_candidate"],
            "offline_labels": pooled_labels,
            "actual_logical_dispatches": pilot_audit["actual_logical_dispatches"]
            + expansion_audit["actual_logical_dispatches"],
            "repeat_observations": pilot_audit["actions"]["repeated_grounding"]
            + expansion_audit["actions"]["repeated_grounding"],
            "focused_pairs": pilot_focused["paired_states"] + expansion_focused["paired_states"],
            "warning": (
                "The pilot used two scheduled classes per group; the expansion used all seven. "
                "Counts are not an unweighted population estimate and are not VLM-query calibration."
            ),
        },
        "support_assessment": {
            "both_hypothesis_classes_observed": True,
            "expansion_positive_groups_are_sparse": True,
            "negative_only_expansion_query_cells_iou_0_50": [
                key for key, value in expansion["support_cells_iou_0_50"]["query"].items()
                if value["support"] == "negative_only"
            ],
            "negative_only_expansion_size_cells_iou_0_50": [
                key for key, value in expansion["support_cells_iou_0_50"]["candidate_size"].items()
                if value["support"] == "negative_only"
            ],
            "focused_outcomes_show_descriptive_separation": False,
            "focused_outcomes_reason": (
                "Target-support is common for both correct and incorrect initial hypotheses; ambiguity and "
                "same-target labels do not provide a well-supported class-conditional kernel."
            ),
            "repeat_full_precision_deterministic_in_observed_deployment": True,
            "class_conditional_kernels_ready": False,
            "recommended_model_complexity": (
                "Do not fit a general conditional model yet. If exploratory fitting is authorized later, "
                "use a restricted pooled model with group-aware validation and conservative abstention."
            ),
            "probability_model_fitted": False,
        },
        "dependence": {
            "source_group_is_sampling_unit": True,
            "same_image_class_queries_dependent": True,
            "repeat_and_crop_observations_share_pixels_and_backend": True,
            "row_independence_assumption_permitted": False,
        },
    }
    if output_path is not None:
        atomic_json(output_path, summary)
    return summary

