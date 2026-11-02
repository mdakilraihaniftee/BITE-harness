"""Freeze final fit-only annotation-proxy priors without touching held-out data."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

import numpy as np

from .prior_model import L2_PENALTY, MODEL_NAMES, fit_constant, fit_logistic, predict
from .proxy_calibration import ALLOWED_PREDICTIVE_FEATURES, load_proxy_records

EXPORT_VERSION = "bite.task_v_frozen_annotation_proxy_prior.v1"
FEATURE_SCHEMA_VERSION = "bite.annotation_proxy_initial_state.v1"
PRIMARY_MODEL = "score_only_logistic"


def canonical_sha(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _fit(records, model_name):
    labels = [row["label"] for row in records]
    if model_name == "constant_prevalence":
        return fit_constant(labels)
    return fit_logistic(records, labels, model_name, l2_penalty=L2_PENALTY)


def _prediction_contract(model, records):
    synthetic = [
        {"initial_score": 0.1, "original_relative_area": 0.01},
        {"initial_score": 0.5, "original_relative_area": 0.05},
        {"initial_score": 0.9, "original_relative_area": 0.20},
    ]
    fit_outputs = predict(model, records)
    synthetic_outputs = predict(model, synthetic)
    return {
        "fit_prediction_count": len(fit_outputs),
        "fit_predictions_sha256": canonical_sha(fit_outputs),
        "synthetic_inputs": synthetic,
        "synthetic_outputs": synthetic_outputs,
        "synthetic_predictions_sha256": canonical_sha(synthetic_outputs),
        "all_fit_predictions_supported": all(row["supported"] for row in fit_outputs),
    }


def build_frozen_priors(*, paired_path, review_cases_path, prior_model_path):
    cases = [
        json.loads(line) for line in Path(review_cases_path).read_text().splitlines()
        if line.strip()
    ]
    case_by_state = {row["state_id"]: row for row in cases}
    paired = [
        json.loads(line) for line in Path(paired_path).read_text().splitlines() if line.strip()
    ]
    selected_cases = [case_by_state[row["runtime_features"]["state_id"]] for row in paired]
    annotation_hashes = {row["annotation_sha256"] for row in selected_cases}
    if len(annotation_hashes) != 1:
        raise ValueError("Frozen fit must have exactly one annotation identity")
    implementation_sha = file_sha(prior_model_path)
    artifacts = []
    for endpoint in ("0.5", "0.75"):
        records = load_proxy_records(
            paired_path, review_cases_path, endpoint=endpoint, cohort_name="expansion",
        )
        groups = {row["source_group_id"] for row in records}
        labels = [row["label"] for row in records]
        expected = (31, 172) if endpoint == "0.5" else (23, 180)
        if len(records) != 203 or len(groups) != 30:
            raise ValueError("Final prior fit must use exactly 203 rows from 30 source groups")
        if (sum(labels), len(labels) - sum(labels)) != expected:
            raise ValueError("Final prior label counts changed")
        if {row["partition"] for row in records} != {"calibration_fit"}:
            raise ValueError("Final prior fit reached a held-out partition")
        if any(set(row["predictive_feature_names"]) != ALLOWED_PREDICTIVE_FEATURES for row in records):
            raise ValueError("Predictive feature contract changed")
        record_identity = [{
            "state_id": row["state_id"],
            "candidate_id": row["candidate_id"],
            "source_group_id": row["source_group_id"],
            "label": row["label"],
            "initial_score": row["initial_score"],
            "original_relative_area": row["original_relative_area"],
        } for row in records]
        for model_name in MODEL_NAMES:
            model = _fit(records, model_name)
            role = "primary" if model_name == PRIMARY_MODEL else "comparator"
            artifact = {
                "schema_version": EXPORT_VERSION,
                "status": "FROZEN_RESEARCH_ARTIFACT_NOT_FOR_DEPLOYMENT",
                "model_role": role,
                "model_name": model_name,
                "endpoint": f"H_annotation_{endpoint}",
                "label_interpretation": "official COCO annotation proxy; not exhaustive visual truth",
                "training": {
                    "partition": "calibration_fit",
                    "cohort_id": "bite.task_v_expansion.seed418.g30.v1",
                    "query_design_id": "all_seven_source_classes_per_group.v1",
                    "pilot_included": False,
                    "calibration_validation_accessed": False,
                    "internal_test_accessed": False,
                    "source_group_count": len(groups),
                    "candidate_count": len(records),
                    "positive_count": sum(labels),
                    "negative_count": len(labels) - sum(labels),
                    "record_identity_sha256": canonical_sha(record_identity),
                },
                "feature_contract": {
                    "schema_version": FEATURE_SCHEMA_VERSION,
                    "features": (
                        [] if model_name == "constant_prevalence"
                        else ["initial_score"] if model_name == "score_only_logistic"
                        else ["initial_score", "log_original_relative_area"]
                    ),
                    "score": "original retained SAM 3 score, identity transform on finite [0,1]",
                    "relative_area": "candidate root-frame area divided by image area; natural log",
                    "missing_features": "unsupported prediction; no imputation",
                    "gt_derived_predictors": False,
                    "zoom_or_focused_predictors": False,
                    "post_action_predictors": False,
                },
                "fit": model,
                "regularization": (
                    {"type": "Beta", "alpha": 1, "beta": 1}
                    if model_name == "constant_prevalence"
                    else {"type": "L2", "lambda": L2_PENALTY, "intercept_penalized": False}
                ),
                "source_identity": {
                    "paired_records_sha256": file_sha(paired_path),
                    "review_cases_sha256": file_sha(review_cases_path),
                    "annotation_sha256": next(iter(annotation_hashes)),
                    "source_image_sha256_count": len({row["source_image_sha256"] for row in selected_cases}),
                },
                "implementation": {
                    "prior_model_sha256": implementation_sha,
                    "python": platform.python_version(),
                    "numpy": np.__version__,
                    "package_versions": {
                        "numpy": importlib.metadata.version("numpy"),
                    },
                },
                "prediction_reproducibility": _prediction_contract(model, records),
                "limitations": [
                    "single Aquarium source domain",
                    "fixed seven-class query schedule rather than natural VLM-selected queries",
                    "official COCO labels can omit visually present objects",
                    "development model selection can be optimistic",
                    "no conditional Zoom likelihood, posterior, planner, or deployment authority",
                ],
            }
            artifact["serialized_model_payload_sha256"] = canonical_sha(artifact["fit"])
            artifacts.append(artifact)
    return artifacts


def validate_frozen_artifact(artifact):
    if artifact.get("schema_version") != EXPORT_VERSION:
        raise ValueError("Unexpected frozen-prior schema")
    if artifact["training"]["partition"] != "calibration_fit":
        raise ValueError("Frozen prior is not fit-only")
    if artifact["training"]["calibration_validation_accessed"]:
        raise ValueError("Validation data reached a frozen prior")
    if artifact["training"]["internal_test_accessed"]:
        raise ValueError("Internal-test data reached a frozen prior")
    if artifact["serialized_model_payload_sha256"] != canonical_sha(artifact["fit"]):
        raise ValueError("Frozen model payload digest mismatch")
    if artifact["feature_contract"]["gt_derived_predictors"]:
        raise ValueError("GT leakage in predictor contract")
    if artifact["feature_contract"]["zoom_or_focused_predictors"]:
        raise ValueError("Future-action leakage in prior")
    return artifact


def verify_serialized_predictions(artifact, rows):
    validate_frozen_artifact(artifact)
    outputs = predict(artifact["fit"], rows)
    return canonical_sha(outputs)
