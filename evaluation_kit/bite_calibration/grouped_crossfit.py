"""Deterministic source-group-disjoint cross-fitting for prior-only models."""

from __future__ import annotations

import hashlib
from collections import defaultdict

from .calibration_metrics import (
    calibration_metrics,
    group_balanced_metrics,
    reliability_summary,
)
from .prior_model import MODEL_NAMES, fit_constant, fit_logistic, predict

FOLD_VERSION = "bite.annotation_proxy_grouped_crossfit.v1"
FOLD_COUNT = 3
FOLD_SEED = 431


def make_group_folds(records, *, fold_count=FOLD_COUNT, seed=FOLD_SEED):
    grouped = defaultdict(list)
    for row in records:
        grouped[row["source_group_id"]].append(row)
    if len(grouped) < fold_count:
        raise ValueError("Not enough source groups for requested grouped folds")
    summaries = []
    for group, rows in grouped.items():
        summaries.append({
            "group": group,
            "positive": sum(row["label"] for row in rows),
            "count": len(rows),
            "tie": hashlib.sha256(f"{seed}:{group}".encode()).hexdigest(),
        })
    summaries.sort(key=lambda row: (-row["positive"], -row["count"], row["tie"]))
    folds = [{"groups": [], "positive": 0, "count": 0} for _ in range(fold_count)]
    for row in summaries:
        target = min(range(fold_count), key=lambda index: (
            folds[index]["positive"], folds[index]["count"], len(folds[index]["groups"]), index,
        ))
        folds[target]["groups"].append(row["group"])
        folds[target]["positive"] += row["positive"]
        folds[target]["count"] += row["count"]
    return [sorted(fold["groups"]) for fold in folds]


def crossfit(records, *, fold_count=FOLD_COUNT, seed=FOLD_SEED):
    folds = make_group_folds(records, fold_count=fold_count, seed=seed)
    all_groups = {row["source_group_id"] for row in records}
    predictions = []
    fold_reports = []
    fitted_models = []
    for fold_index, evaluation_groups_list in enumerate(folds):
        evaluation_groups = set(evaluation_groups_list)
        training_groups = all_groups - evaluation_groups
        train = [row for row in records if row["source_group_id"] in training_groups]
        evaluation = [row for row in records if row["source_group_id"] in evaluation_groups]
        if {row["source_group_id"] for row in train} & {row["source_group_id"] for row in evaluation}:
            raise AssertionError("Source group crossed a cross-fitting boundary")
        if {row["label"] for row in train} != {0, 1}:
            raise ValueError(f"Fold {fold_index} training split lacks both classes")
        models = {"constant_prevalence": fit_constant([row["label"] for row in train])}
        for name in MODEL_NAMES[1:]:
            models[name] = fit_logistic(train, [row["label"] for row in train], name)
        for name, model in models.items():
            outputs = predict(model, evaluation)
            if any(not output["supported"] for output in outputs):
                raise ValueError(f"Fold {fold_index} contains unsupported evaluation features for {name}")
            for row, output in zip(evaluation, outputs, strict=True):
                predictions.append({
                    **row,
                    "fold_index": fold_index,
                    "model_name": name,
                    "probability": output["probability"],
                })
            fitted_models.append({
                "fold_index": fold_index,
                "model_name": name,
                "training_groups": sorted(training_groups),
                "evaluation_groups": sorted(evaluation_groups),
                "model": model,
            })
        fold_reports.append({
            "fold_index": fold_index,
            "training_group_count": len(training_groups),
            "evaluation_group_count": len(evaluation_groups),
            "training_case_count": len(train),
            "evaluation_case_count": len(evaluation),
            "training_positive_count": sum(row["label"] for row in train),
            "evaluation_positive_count": sum(row["label"] for row in evaluation),
            "training_positive_group_count": len({
                row["source_group_id"] for row in train if row["label"]
            }),
            "evaluation_positive_group_count": len({
                row["source_group_id"] for row in evaluation if row["label"]
            }),
            "training_groups": sorted(training_groups),
            "evaluation_groups": sorted(evaluation_groups),
        })
    if len(predictions) != len(records) * len(MODEL_NAMES):
        raise AssertionError("Cross-fitting did not produce one prediction per case and model")
    metrics = {}
    for name in MODEL_NAMES:
        rows = [row for row in predictions if row["model_name"] == name]
        metrics[name] = {
            "case_level": calibration_metrics(
                [row["label"] for row in rows], [row["probability"] for row in rows],
            ),
            "group_balanced": group_balanced_metrics(rows, "probability"),
            "reliability": reliability_summary(
                [row["label"] for row in rows], [row["probability"] for row in rows],
            ),
        }
    return {
        "schema_version": FOLD_VERSION,
        "fold_count": fold_count,
        "seed": seed,
        "folds": fold_reports,
        "metrics": metrics,
        "predictions": predictions,
        "fitted_models": fitted_models,
    }

