"""Build GT-free focused features, then descriptive offline diagnostics."""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from .conditional_features import (
    extract_runtime_features,
    join_offline_labels,
    runtime_projection,
)


def _jsonl(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _state_dir(run_root, state_id):
    return Path(run_root) / "states" / state_id.replace(":", "_", 1)


def _runtime_context(run_root, pair, cohort_id, query_design_id):
    directory = _state_dir(run_root, pair["state_id"])
    initial = json.loads((directory / "initial_raw_state.json").read_text())
    observation = initial["prefix_observation"]
    focused_branch = None
    for path in (directory / "raw_collection/branches").glob("*.json"):
        branch = json.loads(path.read_text())
        if any(step["action_template"] == "focused_grounding" for step in branch["selected_path"]):
            focused_branch = branch
            break
    if focused_branch is None:
        raise ValueError(f"Missing focused branch for {pair['state_id']}")
    rank_by_id = {}
    focused_observation_id = pair["focused_observation_id"]
    rows = [
        row for row in focused_branch["candidate_rows"]
        if row["candidate"]["source_observation_id"] == focused_observation_id
    ]
    for rank, row in enumerate(rows):
        rank_by_id[row["candidate"]["candidate_id"]] = rank
    transform = observation["source_frame"]["child_to_root_transform"]
    return {
        "cohort_id": cohort_id, "query_design_id": query_design_id,
        "initial_observation_id": observation["joint_observation_id"],
        "parent_snapshot_id": initial["parent_snapshot_id"],
        "source_image_sha256": initial["source_image_sha256"],
        "initial_backend": observation["backend"],
        "root_width": observation["root_image"]["width"],
        "root_height": observation["root_image"]["height"],
        "initial_candidate_count": initial["candidate_count"],
        "initial_detector_rank": initial.get("selected_detector_rank"),
        "coordinate_transform_valid": transform == [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "focused_candidate_ranks": rank_by_id,
    }


def build_feature_records(*, pair_path, run_root, cohort_id, query_design_id):
    records = []
    for pair in _jsonl(pair_path):
        context = _runtime_context(run_root, pair, cohort_id, query_design_id)
        features = extract_runtime_features(runtime_projection(pair), context)
        records.append(join_offline_labels(features, pair))
    return records


def _quantiles(values):
    values = sorted(value for value in values if value is not None and math.isfinite(value))
    if not values:
        return {"count": 0, "median": None, "q1": None, "q3": None, "min": None, "max": None}
    quantiles = statistics.quantiles(values, n=4, method="inclusive") if len(values) > 1 else [values[0]] * 3
    return {
        "count": len(values), "median": statistics.median(values), "q1": quantiles[0],
        "q3": quantiles[2], "min": values[0], "max": values[-1],
    }


def _cohort_summary(records):
    numeric = (
        "root_box_iou", "normalized_center_displacement", "log_area_ratio",
        "score_difference", "proposal_count_change",
    )
    by_label = {}
    for label in ("positive", "negative"):
        rows = [row for row in records if row["offline_outcomes"]["H_annotation"]["0.5"] == label]
        aligned = [row for row in rows if row["runtime_features"]["association_is_unique"]]
        by_label[label] = {
            "case_count": len(rows),
            "source_group_count": len({row["runtime_features"]["source_group_id"] for row in rows}),
            "association_categories": dict(sorted(Counter(
                row["runtime_features"]["association_category"] for row in rows).items())),
            "all_cases_explicit_categories": {name: _quantiles(
                [row["runtime_features"][name] for row in rows]) for name in numeric},
            "aligned_only_sensitivity": {name: _quantiles(
                [row["runtime_features"][name] for row in aligned]) for name in numeric},
            "focused_correctness": dict(sorted(Counter(
                row["offline_outcomes"]["focused_proposal_correctness"]["0.5"] for row in rows
            ).items(), key=lambda item: str(item[0]))),
            "same_target_count": sum(
                row["offline_outcomes"]["same_target_preservation"]["0.5"] is True
                for row in rows),
            "focused_iou_improved_count": sum(
                (row["offline_outcomes"]["localization_change_iou"]["0.5"] or 0) > 0 for row in rows),
        }
    classes = defaultdict(lambda: Counter())
    for row in records:
        features = row["runtime_features"]
        label = row["offline_outcomes"]["H_annotation"]["0.5"]
        classes[features["query"]][label] += 1
    return {
        "candidate_count": len(records),
        "source_group_count": len({row["runtime_features"]["source_group_id"] for row in records}),
        "by_annotation_label_iou_0_50": by_label,
        "class_support": {key: dict(value) for key, value in sorted(classes.items())},
        "ambiguous_cases_retained": sum(row["runtime_features"]["association_is_ambiguous"] for row in records),
        "no_alignment_cases_retained": sum(row["runtime_features"]["no_alignment"] for row in records),
        "execution_failure_cases_retained": sum(
            row["runtime_features"]["association_category"] == "execution_failure" for row in records),
        "mask_geometry_available_count": sum(row["runtime_features"]["mask_geometry_available"] for row in records),
    }


def build_diagnostics(cohorts):
    summaries = {name: _cohort_summary(records) for name, records in cohorts.items()}
    return {
        "schema_version": "bite.task_v_conditional_evidence_diagnostics.v1",
        "status": "DESCRIPTIVE_ONLY_NO_MODEL_FITTED",
        "cohorts": summaries,
        "separability_assessment": {
            "focused_evidence_clearly_separates_correctness": False,
            "reason": (
                "Unique alignment dominates both annotation classes; feature distributions overlap and "
                "positive source-group support remains sparse. Exploratory summaries are not a held-out test."
            ),
            "ambiguous_and_no_alignment_preserved": True,
            "gt_used_in_runtime_features": False,
            "threshold_optimized_on_labels": False,
            "statistical_significance_claimed": False,
            "information_gain_claimed": False,
        },
        "dependence": {
            "clustering_unit": "source_group_id",
            "same_image_queries_are_dependent": True,
            "zoom_uses_derived_pixels_and_same_backend": True,
            "repeat_outputs_are_not_independent_evidence": True,
        },
    }
