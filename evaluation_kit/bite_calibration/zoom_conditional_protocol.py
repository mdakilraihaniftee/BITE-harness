"""Frozen protocol and integrity checks for the Task V Zoom feasibility study."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

PROTOCOL_VERSION = "bite.task_v_zoom_conditional_feasibility.v1"
RUNTIME_TABLE_VERSION = "bite.task_v_zoom_runtime_modeling_table.v1"
JOINED_TABLE_VERSION = "bite.task_v_zoom_joined_modeling_table.v1"
ALLOWED_ASSOCIATIONS = {
    "target_aligned_supporting_proposal",
    "ambiguous_target_association",
    "no_target_aligned_proposal",
    "execution_failure",
}
GT_MARKERS = {
    "annotation_scope_audit",
    "assigned_gt",
    "best_gt",
    "focused_aligned_labels",
    "ground_truth",
    "h_annotation",
    "label",
    "new_valid_object_localized",
    "official_tp",
    "original_labels",
    "same_assigned_gt",
}
PRIMARY_FEATURES = (
    "initial_score",
    "score_difference",
    "score_change_observed",
    "association_ambiguous",
    "association_no_alignment",
    "association_execution_failure",
)
SECONDARY_GEOMETRY_FEATURE = "root_box_iou"


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _keys_recursive(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).lower()
            yield from _keys_recursive(child)
    elif isinstance(value, list):
        for child in value:
            yield from _keys_recursive(child)


def _finite(value, *, lower=None, upper=None):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return False
    return (lower is None or value >= lower) and (upper is None or value <= upper)


def validate_runtime_row(row):
    """Reject label leakage, silent missingness, or broken branch provenance."""
    if row.get("schema_version") != "bite.focused_evidence_features.v1":
        raise ValueError("Unexpected focused-evidence feature schema")
    leaked = GT_MARKERS & set(_keys_recursive(row))
    if leaked:
        raise ValueError(f"GT-derived field reached runtime table: {sorted(leaked)}")
    required_identity = (
        "state_id", "source_group_id", "query", "original_candidate_id",
        "initial_observation_id", "focused_observation_id", "parent_snapshot_id",
        "root_image_sha256", "crop_image_id", "cohort_id", "query_design_id",
    )
    if any(not isinstance(row.get(key), str) or not row[key] for key in required_identity):
        raise ValueError("Runtime row has incomplete identity or lineage")
    if row.get("association_category") not in ALLOWED_ASSOCIATIONS:
        raise ValueError("Unsupported association category")
    if row.get("incremental_logical_cost") != 2:
        raise ValueError("Zoom-focused branch must cost two logical calls")
    if row.get("coordinate_transform_valid") is not True:
        raise ValueError("Invalid root/crop coordinate transform")
    if row.get("same_backend") is not True:
        raise ValueError("Historical branch does not use the declared same backend")
    if not _finite(row.get("initial_score"), lower=0, upper=1):
        raise ValueError("Missing or invalid initial score")
    category = row["association_category"]
    unique = category == "target_aligned_supporting_proposal"
    if row.get("association_is_unique") is not unique:
        raise ValueError("Unique-association indicator disagrees with category")
    if row.get("association_is_ambiguous") is not (category == "ambiguous_target_association"):
        raise ValueError("Ambiguity indicator disagrees with category")
    if row.get("no_alignment") is not (category == "no_target_aligned_proposal"):
        raise ValueError("No-alignment indicator disagrees with category")
    observed_values = (
        row.get("focused_score"), row.get("score_difference"), row.get("root_box_iou"),
    )
    if unique:
        if not _finite(observed_values[0], lower=0, upper=1):
            raise ValueError("Unique association lacks a valid focused score")
        if not _finite(observed_values[1], lower=-1, upper=1):
            raise ValueError("Unique association lacks a valid score change")
        if not _finite(observed_values[2], lower=0, upper=1):
            raise ValueError("Unique association lacks a valid root-box IoU")
        if row.get("focused_score_available") is not True:
            raise ValueError("Focused-score availability is inconsistent")
    elif any(value is not None for value in observed_values):
        raise ValueError("Non-unique association contains a synthetic aligned observation")
    elif row.get("focused_score_available") is not False:
        raise ValueError("Missing focused score is not explicitly marked unavailable")
    if row.get("mask_geometry_available") is not False or row.get("mask_geometry_iou") is not None:
        raise ValueError("Unverified mask geometry entered the runtime table")
    return row


def freeze_runtime_rows(rows, *, cohort_name, expected_count, expected_groups):
    """Create a label-free, deterministic modeling table from existing runtime vectors."""
    frozen = []
    identities = set()
    for source in rows:
        validate_runtime_row(source)
        identity = (source["state_id"], source["original_candidate_id"])
        if identity in identities:
            raise ValueError("Duplicate state/candidate runtime identity")
        identities.add(identity)
        frozen.append({
            **source,
            "schema_version": RUNTIME_TABLE_VERSION,
            "cohort_name": cohort_name,
            "partition": "calibration_fit",
            "score_change_observed": source["score_difference"] is not None,
            "root_box_iou_observed": source["root_box_iou"] is not None,
            "association_ambiguous": source["association_category"] == "ambiguous_target_association",
            "association_no_alignment": source["association_category"] == "no_target_aligned_proposal",
            "association_execution_failure": source["association_category"] == "execution_failure",
        })
    frozen.sort(key=lambda row: row["state_id"])
    groups = {row["source_group_id"] for row in frozen}
    if len(frozen) != expected_count or len(groups) != expected_groups:
        raise ValueError("Runtime cohort cardinality does not match the frozen protocol")
    return frozen


def _score_predictions(rows):
    selected = [row for row in rows if row.get("model_name") == "score_only_logistic"]
    if not selected:
        raise ValueError("Frozen score-only out-of-fold predictions are missing")
    by_state = {}
    for row in selected:
        if row["state_id"] in by_state:
            raise ValueError("Duplicate frozen M0 state")
        by_state[row["state_id"]] = row
    return by_state


def join_frozen_target(runtime_rows, prediction_rows, *, endpoint):
    """Join immutable labels/folds only after the runtime-only table is finalized."""
    if endpoint not in {"0.5", "0.75"}:
        raise ValueError("Endpoint must be 0.5 or 0.75")
    baseline = _score_predictions(prediction_rows)
    if set(baseline) != {row["state_id"] for row in runtime_rows}:
        raise ValueError("Runtime and frozen M0 candidate sets do not align exactly")
    joined = []
    folds_by_group = defaultdict(set)
    for runtime in runtime_rows:
        prior = baseline[runtime["state_id"]]
        if prior.get("endpoint") != f"H_annotation_{endpoint}":
            raise ValueError("Frozen M0 endpoint mismatch")
        checks = {
            "candidate_id": runtime["original_candidate_id"],
            "source_group_id": runtime["source_group_id"],
            "query": runtime["query"],
            "initial_score": runtime["initial_score"],
        }
        for key, expected in checks.items():
            if prior.get(key) != expected:
                raise ValueError(f"Frozen M0 identity mismatch for {runtime['state_id']}/{key}")
        if not _finite(prior.get("probability"), lower=0, upper=1):
            raise ValueError("Frozen M0 probability is invalid")
        row = {
            **runtime,
            "schema_version": JOINED_TABLE_VERSION,
            "endpoint": endpoint,
            "label": int(prior["label"]),
            "fold_index": int(prior["fold_index"]),
            "m0_probability": float(prior["probability"]),
            "annotation_scope_audit": prior.get("annotation_scope_audit"),
            "target_joined_after_runtime_freeze": True,
        }
        folds_by_group[row["source_group_id"]].add(row["fold_index"])
        joined.append(row)
    crossed = {group: folds for group, folds in folds_by_group.items() if len(folds) != 1}
    if crossed:
        raise ValueError(f"Source groups cross original folds: {crossed}")
    return sorted(joined, key=lambda row: row["state_id"])


def validate_paired_labels(joined_rows, paired_diagnostics, *, endpoint):
    paired = {row["runtime_features"]["state_id"]: row for row in paired_diagnostics}
    if set(paired) != {row["state_id"] for row in joined_rows}:
        raise ValueError("Offline diagnostic and model candidate sets differ")
    for row in joined_rows:
        observed = paired[row["state_id"]]["offline_outcomes"]["H_annotation"][endpoint]
        if row["label"] != int(observed == "positive"):
            raise ValueError("Original frozen correctness label changed")
    return True


def runtime_integrity_report(rows, *, source_path, expected_image_hashes):
    categories = Counter(row["association_category"] for row in rows)
    image_hashes = {row["root_image_sha256"] for row in rows}
    expected = set(expected_image_hashes)
    if image_hashes != expected:
        raise ValueError("Runtime source-image identity differs from the frozen fit cohort")
    return {
        "schema_version": "bite.task_v_zoom_runtime_integrity.v1",
        "status": "PASS",
        "source_path": str(source_path),
        "source_sha256": file_sha256(source_path),
        "candidate_count": len(rows),
        "source_group_count": len({row["source_group_id"] for row in rows}),
        "source_image_count": len(image_hashes),
        "source_image_identities_match_protocol": True,
        "association_categories": dict(sorted(categories.items())),
        "unique_observation_count": categories["target_aligned_supporting_proposal"],
        "ambiguous_observation_count": categories["ambiguous_target_association"],
        "no_alignment_count": categories["no_target_aligned_proposal"],
        "execution_failure_count": categories["execution_failure"],
        "missing_score_change_count": sum(row["score_difference"] is None for row in rows),
        "invented_focused_score_count": 0,
        "invalid_transform_count": sum(not row["coordinate_transform_valid"] for row in rows),
        "cost_histogram": dict(sorted(Counter(row["incremental_logical_cost"] for row in rows).items())),
        "gt_derived_predictor_count": 0,
        "runtime_table_frozen_before_label_join": True,
    }


def build_protocol(*, input_sha256, runtime_integrity, fold_membership):
    return {
        "schema_version": PROTOCOL_VERSION,
        "status": "FROZEN_EXPLORATORY_CALIBRATION_FIT_PROTOCOL",
        "target": {
            "definition": "correctness of the original selected proposal against eligible same-class COCO GT",
            "endpoints": ["H_annotation_0.50", "H_annotation_0.75"],
            "focused_proposal_never_redefines_target": True,
            "no_candidate_is_separate": True,
        },
        "cohorts": {
            "primary": "seven-class expansion; 30 groups; 203 candidate-present states",
            "sensitivity": "two-query pilot; 19 groups; 38 candidate-present states; never pooled",
        },
        "action": {
            "name": "Zoom -> focused SAM 3 grounding",
            "logical_cost": 2,
            "same_backend_dependency_explicit": True,
        },
        "primary_comparison": {
            "m0": "frozen Phase 4C-1A score-only out-of-fold prediction",
            "m1": "L2-regularized initial score + signed score change + explicit association/missingness",
            "primary_metric": "paired Brier difference M1-M0",
            "secondary_metrics": ["log loss", "binary decision error at 0.5"],
            "favorable_direction": "negative",
        },
        "feature_encoding": {
            "schema": "bite.focused_evidence_features.v1",
            "primary_features": list(PRIMARY_FEATURES),
            "score_change": "observed only for unique valid association; train-fold observed mean imputation plus explicit observed indicator",
            "association": "unique reference plus ambiguous/no-alignment/execution-failure indicators",
            "optional_secondary_feature": SECONDARY_GEOMETRY_FEATURE,
            "geometry": "train-fold observed mean imputation; no separate missingness indicator because it shares the prespecified observation indicator",
            "mask_overlap_used": False,
            "identifiers_as_predictors": False,
            "gt_features_as_predictors": False,
        },
        "modeling": {
            "regularization": {"type": "L2", "lambda": 1.0, "intercept_penalized": False},
            "continuous_preprocessing": "training-fold mean/scale only",
            "folds": fold_membership,
            "all_candidate_present_cases_retained": True,
            "aligned_only_primary": False,
        },
        "uncertainty": {
            "method": "paired percentile source-group bootstrap over fixed cross-fitted predictions",
            "replicates": 2000,
            "seed": 461,
            "identical_group_draws_for_all_comparisons": True,
            "refit_inside_bootstrap": False,
        },
        "negative_controls": {
            "exact_repeat": "historical 73/73 deterministic redundancy check",
            "shuffled_zoom": "deterministic within-query cyclic reassignment, declared implementation control",
            "synthetic_signal": "unit-tested pipeline detectability control",
            "used_for_feature_selection": False,
        },
        "input_sha256": input_sha256,
        "runtime_integrity": runtime_integrity,
        "restrictions": {
            "partition": "calibration_fit only",
            "validation_accessed": False,
            "internal_test_accessed": False,
            "human_review_required": False,
            "planner_implemented": False,
            "posterior_computed": False,
            "conditional_kernel_validated": False,
        },
    }
