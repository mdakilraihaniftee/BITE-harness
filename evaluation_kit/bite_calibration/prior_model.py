"""Small frozen annotation-proxy prior models with no optional ML dependency."""

from __future__ import annotations

import math

import numpy as np

MODEL_VERSION = "bite.annotation_proxy_prior.v1"
MODEL_NAMES = ("constant_prevalence", "score_only_logistic", "compact_initial_logistic")
L2_PENALTY = 1.0
MAX_ITERATIONS = 100
CONVERGENCE_TOLERANCE = 1e-9


def _feature_values(row, model_name):
    score = row.get("initial_score")
    area = row.get("original_relative_area")
    if score is None or not math.isfinite(score) or not 0 <= score <= 1:
        return None, "missing_or_invalid_initial_score"
    if model_name == "score_only_logistic":
        return [float(score)], None
    if model_name == "compact_initial_logistic":
        if area is None or not math.isfinite(area) or area <= 0 or area > 1:
            return None, "missing_or_invalid_relative_area"
        return [float(score), math.log(float(area))], None
    raise ValueError(f"Unknown logistic model: {model_name}")


def fit_constant(labels):
    labels = [int(value) for value in labels]
    if not labels or any(value not in {0, 1} for value in labels):
        raise ValueError("Constant model requires nonempty binary labels")
    positives = sum(labels)
    return {
        "schema_version": MODEL_VERSION,
        "model_name": "constant_prevalence",
        "smoothing": "Beta(1,1)",
        "positive_count": positives,
        "negative_count": len(labels) - positives,
        "probability": (positives + 1) / (len(labels) + 2),
    }


def fit_logistic(rows, labels, model_name, *, l2_penalty=L2_PENALTY):
    if model_name not in MODEL_NAMES[1:]:
        raise ValueError(f"Unsupported logistic model: {model_name}")
    if len(rows) != len(labels) or not rows:
        raise ValueError("Training rows and labels must be nonempty and aligned")
    if set(labels) != {0, 1}:
        raise ValueError("Logistic training fold must contain both target classes")
    values = []
    for row in rows:
        feature, reason = _feature_values(row, model_name)
        if reason:
            raise ValueError(f"Unsupported training row: {reason}")
        values.append(feature)
    raw = np.asarray(values, dtype=np.float64)
    mean = raw.mean(axis=0)
    scale = raw.std(axis=0)
    scale[scale < 1e-12] = 1.0
    standardized = (raw - mean) / scale
    design = np.column_stack([np.ones(len(raw)), standardized])
    target = np.asarray(labels, dtype=np.float64)
    coefficient = np.zeros(design.shape[1], dtype=np.float64)
    converged = False
    iteration = 0
    for iteration in range(1, MAX_ITERATIONS + 1):
        linear = np.clip(design @ coefficient, -35, 35)
        probability = 1 / (1 + np.exp(-linear))
        penalty = np.r_[0.0, np.full(design.shape[1] - 1, l2_penalty)]
        gradient = design.T @ (probability - target) + penalty * coefficient
        weight = probability * (1 - probability)
        hessian = design.T @ (design * weight[:, None]) + np.diag(penalty)
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError as error:
            raise ValueError("Logistic Hessian is singular") from error
        coefficient -= step
        if float(np.max(np.abs(step))) < CONVERGENCE_TOLERANCE:
            converged = True
            break
    if not converged:
        raise ValueError("Logistic fit did not converge under frozen settings")
    return {
        "schema_version": MODEL_VERSION,
        "model_name": model_name,
        "feature_names": (
            ["initial_score"] if model_name == "score_only_logistic"
            else ["initial_score", "log_original_relative_area"]
        ),
        "preprocessing": {
            "fit_on_training_fold_only": True,
            "mean": mean.tolist(),
            "scale": scale.tolist(),
            "score_transform": "identity_on_[0,1]",
            "relative_area_transform": "natural_log" if raw.shape[1] == 2 else None,
        },
        "regularization": {"type": "L2", "lambda": l2_penalty, "intercept_penalized": False},
        "coefficient": coefficient.tolist(),
        "converged": converged,
        "iterations": iteration,
        "training_case_count": len(rows),
        "training_positive_count": int(target.sum()),
    }


def predict(model, rows):
    if model["model_name"] == "constant_prevalence":
        return [{"probability": model["probability"], "supported": True, "reason": None} for _ in rows]
    outputs = []
    mean = np.asarray(model["preprocessing"]["mean"], dtype=np.float64)
    scale = np.asarray(model["preprocessing"]["scale"], dtype=np.float64)
    coefficient = np.asarray(model["coefficient"], dtype=np.float64)
    for row in rows:
        values, reason = _feature_values(row, model["model_name"])
        if reason:
            outputs.append({"probability": None, "supported": False, "reason": reason})
            continue
        standardized = (np.asarray(values, dtype=np.float64) - mean) / scale
        linear = coefficient[0] + standardized @ coefficient[1:]
        probability = 1 / (1 + math.exp(-float(np.clip(linear, -35, 35))))
        outputs.append({"probability": probability, "supported": True, "reason": None})
    return outputs

