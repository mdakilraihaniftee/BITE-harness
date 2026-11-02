"""Paired, source-group-aware evaluation of frozen M0 and Zoom-informed M1."""

from __future__ import annotations

import hashlib
import math
import random
import statistics
from collections import Counter, defaultdict

import numpy as np

from .calibration_metrics import (
    calibration_metrics,
    group_balanced_metrics,
    reliability_summary,
)
from .zoom_incremental_model import BASELINE_MODEL, GEOMETRY_MODEL, PRIMARY_MODEL

EVALUATION_VERSION = "bite.task_v_zoom_paired_evaluation.v1"
METRICS = ("brier_score", "log_loss", "decision_error")
MODEL_PAIRS = (
    (PRIMARY_MODEL, BASELINE_MODEL),
    (GEOMETRY_MODEL, BASELINE_MODEL),
    (GEOMETRY_MODEL, PRIMARY_MODEL),
)


def align_predictions(rows):
    by_state = defaultdict(dict)
    for row in rows:
        if row["model_name"] in by_state[row["state_id"]]:
            raise ValueError("Duplicate model prediction for state")
        by_state[row["state_id"]][row["model_name"]] = row
    expected = {BASELINE_MODEL, PRIMARY_MODEL, GEOMETRY_MODEL}
    aligned = []
    identity = ("label", "candidate_id", "source_group_id", "query", "endpoint", "fold_index")
    for state_id, models in sorted(by_state.items()):
        if set(models) != expected:
            raise ValueError("Prediction set is incomplete")
        reference = models[BASELINE_MODEL]
        for row in models.values():
            if any(row[key] != reference[key] for key in identity):
                raise ValueError("Prediction identity mismatch")
        aligned.append({
            **{key: reference[key] for key in identity},
            "state_id": state_id,
            "initial_score": reference["initial_score"],
            "score_difference": reference["score_difference"],
            "root_box_iou": reference["root_box_iou"],
            "association_category": reference["association_category"],
            "score_change_observed": reference["score_change_observed"],
            "annotation_scope_audit": reference["annotation_scope_audit"],
            "probabilities": {name: models[name]["probability"] for name in sorted(models)},
        })
    return aligned


def _loss(label, probability, metric):
    if metric == "brier_score":
        return (probability - label) ** 2
    if metric == "log_loss":
        probability = min(1 - 1e-15, max(1e-15, probability))
        return -(label * math.log(probability) + (1 - label) * math.log(1 - probability))
    if metric == "decision_error":
        return float((probability >= .5) != bool(label))
    raise ValueError(f"Unsupported metric: {metric}")


def paired_difference(rows, model, baseline, metric, *, group_balanced=False):
    if not rows:
        raise ValueError("Paired comparison requires rows")
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["source_group_id"]].append(row)
    if group_balanced:
        return sum(
            sum(
                _loss(row["label"], row["probabilities"][model], metric)
                - _loss(row["label"], row["probabilities"][baseline], metric)
                for row in group_rows
            ) / len(group_rows)
            for group_rows in grouped.values()
        ) / len(grouped)
    return sum(
        _loss(row["label"], row["probabilities"][model], metric)
        - _loss(row["label"], row["probabilities"][baseline], metric)
        for row in rows
    ) / len(rows)


def model_metrics(aligned):
    output = {}
    for model in (BASELINE_MODEL, PRIMARY_MODEL, GEOMETRY_MODEL):
        simple = [{
            "source_group_id": row["source_group_id"],
            "label": row["label"],
            "probability": row["probabilities"][model],
        } for row in aligned]
        output[model] = {
            "case_level": calibration_metrics(
                [row["label"] for row in simple], [row["probability"] for row in simple],
            ),
            "group_balanced": group_balanced_metrics(simple, "probability"),
            "reliability": reliability_summary(
                [row["label"] for row in simple], [row["probability"] for row in simple],
            ),
            "prediction_coverage": 1.0,
            "minimum_probability": min(row["probability"] for row in simple),
            "maximum_probability": max(row["probability"] for row in simple),
        }
    return output


def paired_group_bootstrap(aligned, *, replicates=2000, seed=461):
    grouped = defaultdict(list)
    for row in aligned:
        grouped[row["source_group_id"]].append(row)
    groups = sorted(grouped)
    if len(groups) < 2:
        raise ValueError("Paired group bootstrap requires at least two groups")
    rng = random.Random(seed)
    samples = {
        f"{model}_minus_{baseline}": {
            scope: {metric: [] for metric in METRICS}
            for scope in ("case_level", "group_balanced")
        } for model, baseline in MODEL_PAIRS
    }
    draw_hashes = []
    for replicate in range(replicates):
        selected = [rng.choice(groups) for _ in groups]
        if replicate < 10:
            draw_hashes.append(hashlib.sha256("\n".join(selected).encode()).hexdigest())
        drawn = []
        for index, group in enumerate(selected):
            drawn.extend({**row, "source_group_id": f"{index}:{group}"} for row in grouped[group])
        for model, baseline in MODEL_PAIRS:
            name = f"{model}_minus_{baseline}"
            for metric in METRICS:
                samples[name]["case_level"][metric].append(
                    paired_difference(drawn, model, baseline, metric),
                )
                samples[name]["group_balanced"][metric].append(
                    paired_difference(drawn, model, baseline, metric, group_balanced=True),
                )
    comparisons = {}
    for model, baseline in MODEL_PAIRS:
        name = f"{model}_minus_{baseline}"
        comparisons[name] = {"model": model, "baseline": baseline}
        for scope in ("case_level", "group_balanced"):
            comparisons[name][scope] = {}
            for metric in METRICS:
                values = samples[name][scope][metric]
                comparisons[name][scope][metric] = {
                    "observed_difference": paired_difference(
                        aligned, model, baseline, metric, group_balanced=scope == "group_balanced",
                    ),
                    "lower_2_5": float(np.quantile(values, .025)),
                    "upper_97_5": float(np.quantile(values, .975)),
                    "valid_replicates": len(values),
                }
    return {
        "schema_version": "bite.task_v_zoom_paired_group_bootstrap.v1",
        "method": "paired percentile source-group bootstrap over fixed out-of-fold predictions",
        "seed": seed,
        "requested_replicates": replicates,
        "valid_replicates": replicates,
        "source_group_count": len(groups),
        "candidate_rows_resampled_iid": False,
        "same_group_draw_used_for_all_comparisons": True,
        "refit_inside_bootstrap": False,
        "first_ten_draw_sha256": draw_hashes,
        "sign_convention": "model loss minus baseline loss; negative favors model",
        "comparisons": comparisons,
    }


def _numeric_summary(values):
    values = [float(value) for value in values if value is not None and math.isfinite(value)]
    if not values:
        return {"count": 0, "mean": None, "median": None, "minimum": None, "maximum": None}
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
    }


def evidence_diagnostics(aligned):
    m0 = [row["probabilities"][BASELINE_MODEL] for row in aligned]
    m1 = [row["probabilities"][PRIMARY_MODEL] for row in aligned]
    m0_range = (min(m0), max(m0))
    group_delta = defaultdict(list)
    class_delta = defaultdict(list)
    for row in aligned:
        delta = (
            _loss(row["label"], row["probabilities"][PRIMARY_MODEL], "brier_score")
            - _loss(row["label"], row["probabilities"][BASELINE_MODEL], "brier_score")
        )
        group_delta[row["source_group_id"]].append(delta)
        class_delta[row["query"]].append(delta)
    group_means = {key: statistics.fmean(values) for key, values in group_delta.items()}
    class_means = {key: statistics.fmean(values) for key, values in class_delta.items()}
    association = {}
    for category in sorted({row["association_category"] for row in aligned}):
        rows = [row for row in aligned if row["association_category"] == category]
        association[category] = {
            "case_count": len(rows),
            "positive_count": sum(row["label"] for row in rows),
            "mean_m0_probability": statistics.fmean(
                row["probabilities"][BASELINE_MODEL] for row in rows
            ),
            "mean_m1_probability": statistics.fmean(
                row["probabilities"][PRIMARY_MODEL] for row in rows
            ),
            "score_change": _numeric_summary(row["score_difference"] for row in rows),
        }
    by_label = {}
    for label in (0, 1):
        rows = [row for row in aligned if row["label"] == label]
        by_label[str(label)] = {
            "case_count": len(rows),
            "association_categories": dict(sorted(Counter(
                row["association_category"] for row in rows
            ).items())),
            "score_change": _numeric_summary(row["score_difference"] for row in rows),
            "root_box_iou": _numeric_summary(row["root_box_iou"] for row in rows),
        }
    high_negative = [row for row in aligned if not row["label"] and row["initial_score"] >= .9]
    absent = [
        row for row in aligned
        if row["annotation_scope_audit"] == "no_annotated_queried_class_instance"
    ]
    aligned_only = [row for row in aligned if row["score_change_observed"]]
    primary = paired_difference(aligned, PRIMARY_MODEL, BASELINE_MODEL, "brier_score")
    improvements = sorted(group_means.items(), key=lambda item: item[1])
    return {
        "schema_version": "bite.task_v_zoom_evidence_diagnostics.v1",
        "candidate_count": len(aligned),
        "association": association,
        "by_annotation_label": by_label,
        "m1_outside_m0_probability_support_count": sum(
            probability < m0_range[0] or probability > m0_range[1] for probability in m1
        ),
        "m0_probability_support": {"minimum": m0_range[0], "maximum": m0_range[1]},
        "m1_nearly_deterministic_count": sum(p < .01 or p > .99 for p in m1),
        "source_group_brier_differences": dict(sorted(group_means.items())),
        "most_favorable_groups": [{"source_group_id": key, "difference": value} for key, value in improvements[:5]],
        "most_unfavorable_groups": [{"source_group_id": key, "difference": value} for key, value in improvements[-5:]],
        "class_brier_differences": dict(sorted(class_means.items())),
        "improvement_concentrated_in_one_class": (
            min(class_means.values()) < 0 and sum(value < 0 for value in class_means.values()) == 1
        ),
        "high_score_annotation_negative": {
            "count": len(high_negative),
            "paired_brier_difference": (
                paired_difference(high_negative, PRIMARY_MODEL, BASELINE_MODEL, "brier_score")
                if high_negative else None
            ),
        },
        "class_absence_dominated_offline_diagnostic": {
            "count": len(absent),
            "paired_brier_difference": (
                paired_difference(absent, PRIMARY_MODEL, BASELINE_MODEL, "brier_score")
                if absent else None
            ),
            "used_as_predictor": False,
        },
        "aligned_only_selection_biased_sensitivity": {
            "case_count": len(aligned_only),
            "paired_brier_difference": paired_difference(
                aligned_only, PRIMARY_MODEL, BASELINE_MODEL, "brier_score",
            ),
            "primary_analysis": False,
        },
        "all_case_primary_brier_difference": primary,
        "same_backend_dependency": True,
        "successful_association_is_independent_verification": False,
        "geometry_change_is_information_gain_claim": False,
    }


def evaluate_predictions(prediction_rows, *, bootstrap_replicates=2000, bootstrap_seed=461):
    aligned = align_predictions(prediction_rows)
    metrics = model_metrics(aligned)
    uncertainty = paired_group_bootstrap(
        aligned, replicates=bootstrap_replicates, seed=bootstrap_seed,
    )
    return {
        "schema_version": EVALUATION_VERSION,
        "status": "EXPLORATORY_CALIBRATION_FIT_ONLY",
        "endpoint": aligned[0]["endpoint"],
        "candidate_count": len(aligned),
        "positive_count": sum(row["label"] for row in aligned),
        "negative_count": sum(not row["label"] for row in aligned),
        "source_group_count": len({row["source_group_id"] for row in aligned}),
        "valid_zoom_observation_count": sum(row["score_change_observed"] for row in aligned),
        "missing_or_ambiguous_observation_count": sum(not row["score_change_observed"] for row in aligned),
        "models": metrics,
        "paired_uncertainty": uncertainty,
        "evidence_diagnostics": evidence_diagnostics(aligned),
        "validation_result": False,
        "ideal_information_gain_claimed": False,
    }
