"""Orchestrate the restricted calibration-fit annotation-proxy experiment."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from .calibration_metrics import calibration_metrics
from .grouped_crossfit import crossfit
from .grouped_uncertainty import grouped_bootstrap
from .prior_model import MODEL_NAMES

EXPERIMENT_VERSION = "bite.annotation_proxy_prior_experiment.v1"
ALLOWED_PREDICTIVE_FEATURES = {"initial_score", "original_relative_area"}
FORBIDDEN_INPUT_MARKERS = {
    "official_tp", "h_annotation", "root_box_iou", "focused_score", "score_difference",
    "source_group_id_as_category", "root_image_sha256", "annotation_presence",
}


def _jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_proxy_records(paired_path, review_cases_path, *, endpoint, cohort_name):
    if endpoint not in {"0.5", "0.75"}:
        raise ValueError("Endpoint must be 0.5 or 0.75")
    cases = {row["state_id"]: row for row in _jsonl(review_cases_path)}
    records = []
    for paired in _jsonl(paired_path):
        features = paired["runtime_features"]
        case = cases[features["state_id"]]
        record = {
            "schema_version": "bite.annotation_proxy_initial_state.v1",
            "partition": "calibration_fit",
            "cohort_name": cohort_name,
            "cohort_id": features["cohort_id"],
            "query_design_id": features["query_design_id"],
            "state_id": features["state_id"],
            "candidate_id": features["original_candidate_id"],
            "source_group_id": features["source_group_id"],
            "query": features["query"],
            "candidate_size": features["candidate_size"],
            "initial_score": features["initial_score"],
            "original_relative_area": features["original_relative_area"],
            "label": int(paired["offline_outcomes"]["H_annotation"][endpoint] == "positive"),
            "endpoint": f"H_annotation_{endpoint}",
            "annotation_scope_audit": (
                "no_annotated_queried_class_instance"
                if case["diagnostic_primary"] == "no_annotated_instance"
                else "annotated_or_other_diagnostic"
            ),
            "predictive_feature_names": sorted(ALLOWED_PREDICTIVE_FEATURES),
        }
        if record["initial_score"] is None or record["original_relative_area"] is None:
            raise ValueError("Initial-state proxy experiment requires complete prespecified features")
        records.append(record)
    if not records or any(row["partition"] != "calibration_fit" for row in records):
        raise ValueError("Proxy experiment is calibration_fit only")
    return records


def _descriptive_audit(records, predictions):
    support_by_class = defaultdict(Counter)
    support_by_size = defaultdict(Counter)
    for row in records:
        support_by_class[row["query"]]["positive" if row["label"] else "negative"] += 1
        support_by_size[row["candidate_size"]]["positive" if row["label"] else "negative"] += 1
    high_score_negatives = [row for row in records if not row["label"] and row["initial_score"] >= .9]
    model_high = {}
    for model_name in MODEL_NAMES:
        selected = [
            row for row in predictions
            if row["model_name"] == model_name and not row["label"] and row["initial_score"] >= .9
        ]
        values = [row["probability"] for row in selected]
        model_high[model_name] = {
            "count": len(values),
            "mean_probability": sum(values) / len(values) if values else None,
            "minimum_probability": min(values) if values else None,
            "maximum_probability": max(values) if values else None,
        }
    def stratified(key):
        output = {}
        for value in sorted({row[key] for row in records}):
            output[value] = {}
            for model_name in MODEL_NAMES:
                rows = [
                    row for row in predictions
                    if row["model_name"] == model_name and row[key] == value
                ]
                labels = [row["label"] for row in rows]
                supported = len(rows) >= 5 and set(labels) == {0, 1}
                output[value][model_name] = {
                    "case_count": len(rows), "positive_count": sum(labels),
                    "source_group_count": len({row["source_group_id"] for row in rows}),
                    "metrics_supported": supported,
                    "metrics": (
                        calibration_metrics(labels, [row["probability"] for row in rows])
                        if supported else None
                    ),
                }
        return output
    saturation = {}
    for band, predicate in (
        ("score_below_0_9", lambda row: row["initial_score"] < .9),
        ("score_at_or_above_0_9", lambda row: row["initial_score"] >= .9),
    ):
        saturation[band] = {}
        for model_name in MODEL_NAMES:
            rows = [row for row in predictions if row["model_name"] == model_name and predicate(row)]
            saturation[band][model_name] = {
                "case_count": len(rows), "annotation_positive_count": sum(row["label"] for row in rows),
                "mean_probability": (
                    sum(row["probability"] for row in rows) / len(rows) if rows else None
                ),
            }
    return {
        "source_group_count": len({row["source_group_id"] for row in records}),
        "positive_bearing_group_count": len({
            row["source_group_id"] for row in records if row["label"]
        }),
        "candidate_count": len(records),
        "positive_count": sum(row["label"] for row in records),
        "negative_count": sum(not row["label"] for row in records),
        "missing_score_count": sum(row["initial_score"] is None for row in records),
        "score_at_or_above_0_9_count": sum(row["initial_score"] >= .9 for row in records),
        "high_score_annotation_negative_count": len(high_score_negatives),
        "high_score_annotation_negative_model_probabilities": model_high,
        "class_support": {name: dict(counts) for name, counts in sorted(support_by_class.items())},
        "candidate_size_support": {name: dict(counts) for name, counts in sorted(support_by_size.items())},
        "annotation_scope": dict(Counter(row["annotation_scope_audit"] for row in records)),
        "annotation_scope_is_not_a_predictive_feature": True,
        "class_specific_descriptive_metrics": stratified("query"),
        "candidate_size_descriptive_metrics": stratified("candidate_size"),
        "annotation_scope_descriptive_metrics": stratified("annotation_scope_audit"),
        "score_saturation_descriptive_audit": saturation,
        "stratified_metrics_are_exploratory_not_model_selection": True,
    }


def _model_cards(crossfit_result, *, cohort_name, endpoint, source_hash):
    cards = []
    for model_name in MODEL_NAMES:
        fits = [row for row in crossfit_result["fitted_models"] if row["model_name"] == model_name]
        cards.append({
            "schema_version": "bite.annotation_proxy_model_card.v1",
            "status": "ANNOTATION_PROXY_EXPLORATORY_NONDEPLOYMENT",
            "model_name": model_name,
            "cohort": cohort_name,
            "target_population": (
                "candidate-present Aquarium calibration-fit states under the declared cohort query design"
            ),
            "training_partition": "calibration_fit",
            "label_definition": f"H_annotation at IoU {endpoint}",
            "visual_truth_claimed": False,
            "feature_schema": (
                [] if model_name == "constant_prevalence"
                else ["initial_score"] if model_name == "score_only_logistic"
                else ["initial_score", "log_original_relative_area"]
            ),
            "regularization": (
                "Beta(1,1) smoothing" if model_name == "constant_prevalence"
                else "L2 lambda=1.0; intercept unpenalized"
            ),
            "fold_design": "three deterministic source-group-disjoint folds; preprocessing fit in train fold",
            "folds": [{
                "fold_index": row["fold_index"],
                "training_groups": row["training_groups"],
                "evaluation_groups": row["evaluation_groups"],
                "fit": row["model"],
            } for row in fits],
            "metrics": crossfit_result["metrics"][model_name],
            "known_annotation_uncertainty": (
                "COCO negatives can include omitted visible objects; no human review was completed at fit time"
            ),
            "limitations": [
                "one Aquarium source domain", "sparse annotation-positive support",
                "query schedule is not a natural VLM-query distribution",
                "not a visual-truth or deployment model", "no conditional tool likelihood",
            ],
            "source_record_sha256": source_hash,
            "intended_use": "offline development comparison only",
        })
    return cards


def run_experiment(records, *, cohort_name, endpoint, source_hash, bootstrap_replicates=2000):
    result = crossfit(records)
    uncertainty = {}
    for offset, model_name in enumerate(MODEL_NAMES):
        predictions = [row for row in result["predictions"] if row["model_name"] == model_name]
        uncertainty[model_name] = grouped_bootstrap(
            predictions, replicates=bootstrap_replicates, seed=439 + offset,
        )
    paired_deltas = {}
    proposed = {
        row["state_id"]: row["probability"]
        for row in result["predictions"] if row["model_name"] == "compact_initial_logistic"
    }
    for baseline in ("constant_prevalence", "score_only_logistic"):
        base = [row for row in result["predictions"] if row["model_name"] == baseline]
        proposed_rows = [{**row, "probability": proposed[row["state_id"]]} for row in base]
        base_metrics = calibration_metrics(
            [row["label"] for row in base], [row["probability"] for row in base],
        )
        proposed_metrics = calibration_metrics(
            [row["label"] for row in proposed_rows], [row["probability"] for row in proposed_rows],
        )
        paired_deltas[baseline] = {
            name: proposed_metrics[name] - base_metrics[name]
            for name in ("brier_score", "log_loss", "decision_error")
        }
    return {
        "schema_version": EXPERIMENT_VERSION,
        "status": "ANNOTATION_PROXY_EXPLORATORY",
        "cohort": cohort_name,
        "endpoint": f"H_annotation_{endpoint}",
        "target_distribution": (
            "candidate-present states under this cohort's frozen query design; calibration_fit only"
        ),
        "source_record_sha256": source_hash,
        "allowed_predictive_features": sorted(ALLOWED_PREDICTIVE_FEATURES),
        "forbidden_input_markers": sorted(FORBIDDEN_INPUT_MARKERS),
        "crossfit": {key: value for key, value in result.items() if key not in {"predictions", "fitted_models"}},
        "predictions": result["predictions"],
        "fitted_models": result["fitted_models"],
        "uncertainty": uncertainty,
        "paired_compact_minus_baseline_metrics": paired_deltas,
        "support_audit": _descriptive_audit(records, result["predictions"]),
        "model_cards": _model_cards(
            result, cohort_name=cohort_name, endpoint=endpoint, source_hash=source_hash,
        ),
        "zoom_likelihood_fitted": False,
        "posterior_update_executed": False,
        "deployment_authorized": False,
    }


def validate_prediction_artifacts(experiment):
    for row in experiment["predictions"]:
        if not math.isfinite(row["probability"]) or not 0 <= row["probability"] <= 1:
            raise ValueError("Invalid cross-fitted probability")
        if row["partition"] != "calibration_fit":
            raise ValueError("Non-fit partition reached proxy predictions")
    for fold in experiment["crossfit"]["folds"]:
        if set(fold["training_groups"]) & set(fold["evaluation_groups"]):
            raise ValueError("Cross-fitting group leakage")
    return True
