"""Small prespecified cross-fitted models for incremental Zoom evidence."""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

MODEL_VERSION = "bite.task_v_zoom_incremental_logistic.v1"
PRIMARY_MODEL = "zoom_restricted_m1"
GEOMETRY_MODEL = "zoom_geometry_secondary"
BASELINE_MODEL = "initial_score_only_m0"
MODEL_NAMES = (BASELINE_MODEL, PRIMARY_MODEL, GEOMETRY_MODEL)
L2_PENALTY = 1.0
MAX_ITERATIONS = 100
CONVERGENCE_TOLERANCE = 1e-9


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _continuous_spec(model_name):
    names = ["initial_score", "score_difference"]
    if model_name == GEOMETRY_MODEL:
        names.append("root_box_iou")
    elif model_name != PRIMARY_MODEL:
        raise ValueError(f"Unsupported fitted model: {model_name}")
    return names


def _fit_preprocessing(rows, model_name):
    preprocessing = {}
    for name in _continuous_spec(model_name):
        if name == "initial_score":
            values = [float(row[name]) for row in rows if _finite(row.get(name))]
            if len(values) != len(rows):
                raise ValueError("Initial score must be complete")
        else:
            values = [float(row[name]) for row in rows if _finite(row.get(name))]
            if not values:
                raise ValueError(f"Training fold has no observed {name}")
        mean = float(np.mean(values))
        scale = float(np.std(values))
        if scale < 1e-12:
            scale = 1.0
        preprocessing[name] = {
            "mean": mean,
            "scale": scale,
            "fit_value_count": len(values),
            "missing_value": "training_observed_mean",
        }
    return preprocessing


def _design_row(row, model_name, preprocessing):
    values = []
    for name in _continuous_spec(model_name):
        raw = row.get(name)
        if not _finite(raw):
            if name == "initial_score":
                raise ValueError("Initial score is unavailable")
            raw = preprocessing[name]["mean"]
        values.append((float(raw) - preprocessing[name]["mean"]) / preprocessing[name]["scale"])
    values.extend([
        float(bool(row["score_change_observed"])),
        float(bool(row["association_ambiguous"])),
        float(bool(row["association_no_alignment"])),
        float(bool(row["association_execution_failure"])),
    ])
    return values


def _feature_names(model_name):
    return [f"z_{name}" for name in _continuous_spec(model_name)] + [
        "score_change_observed",
        "association_ambiguous",
        "association_no_alignment",
        "association_execution_failure",
    ]


def fit_zoom_logistic(rows, model_name, *, l2_penalty=L2_PENALTY):
    if not rows or {int(row["label"]) for row in rows} != {0, 1}:
        raise ValueError("Training fold must contain both target classes")
    preprocessing = _fit_preprocessing(rows, model_name)
    raw = np.asarray(
        [_design_row(row, model_name, preprocessing) for row in rows], dtype=np.float64,
    )
    design = np.column_stack([np.ones(len(raw)), raw])
    target = np.asarray([row["label"] for row in rows], dtype=np.float64)
    coefficient = np.zeros(design.shape[1], dtype=np.float64)
    penalty = np.r_[0.0, np.full(design.shape[1] - 1, l2_penalty)]
    converged = False
    for iteration in range(1, MAX_ITERATIONS + 1):
        linear = np.clip(design @ coefficient, -35, 35)
        probability = 1 / (1 + np.exp(-linear))
        gradient = design.T @ (probability - target) + penalty * coefficient
        weight = probability * (1 - probability)
        hessian = design.T @ (design * weight[:, None]) + np.diag(penalty)
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError as error:
            raise ValueError("Zoom logistic Hessian is singular") from error
        coefficient -= step
        if float(np.max(np.abs(step))) < CONVERGENCE_TOLERANCE:
            converged = True
            break
    if not converged:
        raise ValueError("Zoom logistic fit did not converge under frozen settings")
    return {
        "schema_version": MODEL_VERSION,
        "model_name": model_name,
        "feature_names": _feature_names(model_name),
        "preprocessing": preprocessing,
        "regularization": {
            "type": "L2", "lambda": l2_penalty, "intercept_penalized": False,
        },
        "coefficient": coefficient.tolist(),
        "converged": True,
        "iterations": iteration,
        "training_case_count": len(rows),
        "training_positive_count": int(target.sum()),
        "missing_continuous_values_imputed_to_observed_training_mean": True,
        "missingness_indicator_explicit": True,
    }


def predict_zoom(model, rows):
    coefficient = np.asarray(model["coefficient"], dtype=np.float64)
    outputs = []
    for row in rows:
        features = np.asarray(
            _design_row(row, model["model_name"], model["preprocessing"]), dtype=np.float64,
        )
        linear = coefficient[0] + features @ coefficient[1:]
        probability = 1 / (1 + math.exp(-float(np.clip(linear, -35, 35))))
        outputs.append(float(probability))
    return outputs


def crossfit_zoom(joined_rows):
    """Fit M1 with the exact original evaluation folds and retain frozen M0."""
    if not joined_rows:
        raise ValueError("Zoom cross-fitting requires records")
    folds_by_group = defaultdict(set)
    for row in joined_rows:
        folds_by_group[row["source_group_id"]].add(row["fold_index"])
    if any(len(folds) != 1 for folds in folds_by_group.values()):
        raise ValueError("A source group crosses original folds")
    folds = sorted({row["fold_index"] for row in joined_rows})
    predictions = []
    fits = []
    for fold in folds:
        train = [row for row in joined_rows if row["fold_index"] != fold]
        evaluation = [row for row in joined_rows if row["fold_index"] == fold]
        train_groups = {row["source_group_id"] for row in train}
        evaluation_groups = {row["source_group_id"] for row in evaluation}
        if train_groups & evaluation_groups:
            raise ValueError("Source-group leakage in Zoom cross-fitting")
        for model_name in (PRIMARY_MODEL, GEOMETRY_MODEL):
            model = fit_zoom_logistic(train, model_name)
            probabilities = predict_zoom(model, evaluation)
            fits.append({
                "fold_index": fold,
                "model_name": model_name,
                "training_groups": sorted(train_groups),
                "evaluation_groups": sorted(evaluation_groups),
                "model": model,
            })
            for row, probability in zip(evaluation, probabilities, strict=True):
                predictions.append(_prediction_record(row, model_name, probability))
        for row in evaluation:
            predictions.append(_prediction_record(row, BASELINE_MODEL, row["m0_probability"]))
    expected = len(joined_rows) * len(MODEL_NAMES)
    if len(predictions) != expected:
        raise AssertionError("Cross-fitting did not emit every model/case pair")
    predictions.sort(key=lambda row: (row["state_id"], row["model_name"]))
    return {
        "schema_version": "bite.task_v_zoom_crossfit.v1",
        "models": list(MODEL_NAMES),
        "fold_count": len(folds),
        "candidate_count": len(joined_rows),
        "source_group_count": len(folds_by_group),
        "predictions": predictions,
        "fitted_models": fits,
        "m0_is_original_out_of_fold_prediction": True,
        "full_fit_prior_used_as_baseline": False,
        "preprocessing_fit_within_training_fold": True,
    }


def _prediction_record(row, model_name, probability):
    if not 0 <= probability <= 1 or not math.isfinite(probability):
        raise ValueError("Invalid model probability")
    return {
        "schema_version": "bite.task_v_zoom_oof_prediction.v1",
        "state_id": row["state_id"],
        "candidate_id": row["original_candidate_id"],
        "source_group_id": row["source_group_id"],
        "root_image_sha256": row["root_image_sha256"],
        "query": row["query"],
        "endpoint": row["endpoint"],
        "fold_index": row["fold_index"],
        "label": row["label"],
        "model_name": model_name,
        "probability": probability,
        "association_category": row["association_category"],
        "score_change_observed": row["score_change_observed"],
        "initial_score": row["initial_score"],
        "score_difference": row["score_difference"],
        "root_box_iou": row["root_box_iou"],
        "annotation_scope_audit": row["annotation_scope_audit"],
        "partition": "calibration_fit",
    }


def deterministic_shuffled_rows(joined_rows):
    """Break real Zoom pairing within query for a declared implementation control."""
    by_query = defaultdict(list)
    for row in joined_rows:
        by_query[row["query"]].append(row)
    result = []
    zoom_fields = (
        "score_difference", "score_change_observed", "root_box_iou", "root_box_iou_observed",
        "association_ambiguous", "association_no_alignment", "association_execution_failure",
        "association_category",
    )
    for query, rows in sorted(by_query.items()):
        ordered = sorted(rows, key=lambda row: row["state_id"])
        donors = ordered[1:] + ordered[:1]
        for row, donor in zip(ordered, donors, strict=True):
            copied = dict(row)
            for field in zoom_fields:
                copied[field] = donor[field]
            copied["shuffled_zoom_donor_state_id"] = donor["state_id"]
            copied["shuffled_zoom_pairing"] = True
            result.append(copied)
    return sorted(result, key=lambda row: row["state_id"])
