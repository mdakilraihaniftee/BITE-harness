"""Paired comparisons of frozen out-of-fold annotation-proxy predictions."""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from pathlib import Path

import numpy as np

from .calibration_metrics import calibration_metrics, group_balanced_metrics

PAIRED_COMPARISON_VERSION = "bite.annotation_proxy_paired_group_comparison.v1"
MODEL_PAIRS = (
    ("score_only_logistic", "constant_prevalence"),
    ("compact_initial_logistic", "constant_prevalence"),
    ("compact_initial_logistic", "score_only_logistic"),
)
METRICS = ("brier_score", "log_loss", "decision_error")


def load_frozen_predictions(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if not rows:
        raise ValueError("Frozen prediction artifact is empty")
    aligned = align_predictions(rows)
    return rows, aligned


def align_predictions(rows):
    """Return one aligned record per case and reject any correspondence defect."""
    by_case = defaultdict(dict)
    for row in rows:
        key = row.get("state_id")
        model = row.get("model_name")
        if not key or not model or model in by_case[key]:
            raise ValueError("Predictions require unique state/model identities")
        probability = row.get("probability")
        if not isinstance(probability, (int, float)) or not math.isfinite(probability):
            raise ValueError("Prediction probability is missing or invalid")
        if not 0 <= probability <= 1:
            raise ValueError("Prediction probability is outside [0, 1]")
        by_case[key][model] = row
    expected_models = {"constant_prevalence", "score_only_logistic", "compact_initial_logistic"}
    aligned = []
    identity_fields = (
        "label", "source_group_id", "fold_index", "candidate_id", "cohort_name", "endpoint",
        "query_design_id", "annotation_scope_audit",
    )
    for state_id, models in sorted(by_case.items()):
        if set(models) != expected_models:
            raise ValueError(f"Case {state_id} does not contain all frozen model predictions")
        reference = models["constant_prevalence"]
        for model, row in models.items():
            if any(row.get(field) != reference.get(field) for field in identity_fields):
                raise ValueError(f"Case metadata mismatch for {state_id}/{model}")
        aligned.append({
            **{field: reference.get(field) for field in identity_fields},
            "state_id": state_id,
            "initial_score": reference.get("initial_score"),
            "original_relative_area": reference.get("original_relative_area"),
            "probabilities": {name: models[name]["probability"] for name in sorted(models)},
        })
    folds_by_group = defaultdict(set)
    for row in aligned:
        folds_by_group[row["source_group_id"]].add(row["fold_index"])
    crossed = {group: sorted(folds) for group, folds in folds_by_group.items() if len(folds) != 1}
    if crossed:
        raise ValueError(f"Source groups cross folds: {crossed}")
    return aligned


def _loss(label, probability, metric, *, threshold=0.5):
    if metric == "brier_score":
        return (probability - label) ** 2
    if metric == "log_loss":
        p = min(1 - 1e-15, max(1e-15, probability))
        return -(label * math.log(p) + (1 - label) * math.log(1 - p))
    if metric == "decision_error":
        return float((probability >= threshold) != bool(label))
    raise ValueError(f"Unsupported loss: {metric}")


def paired_difference(rows, model, baseline, metric, *, group_balanced=False):
    if not rows:
        raise ValueError("Paired comparison requires rows")
    if not group_balanced:
        return sum(
            _loss(row["label"], row["probabilities"][model], metric)
            - _loss(row["label"], row["probabilities"][baseline], metric)
            for row in rows
        ) / len(rows)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["source_group_id"]].append(row)
    return sum(
        sum(
            _loss(row["label"], row["probabilities"][model], metric)
            - _loss(row["label"], row["probabilities"][baseline], metric)
            for row in group_rows
        ) / len(group_rows)
        for group_rows in grouped.values()
    ) / len(grouped)


def reproduce_metrics(aligned, frozen_summary, *, tolerance=1e-12):
    """Recompute every headline metric without refitting and compare to Phase 4C-1A."""
    report = {}
    for model in sorted(aligned[0]["probabilities"]):
        simple = [
            {"source_group_id": row["source_group_id"], "label": row["label"],
             "probability": row["probabilities"][model]}
            for row in aligned
        ]
        observed = {
            "case_level": calibration_metrics(
                [row["label"] for row in simple], [row["probability"] for row in simple],
            ),
            "group_balanced": group_balanced_metrics(simple, "probability"),
        }
        expected = frozen_summary["crossfit_metrics"][model]
        differences = {}
        for scope in ("case_level", "group_balanced"):
            differences[scope] = {}
            for metric in METRICS:
                delta = observed[scope][metric] - expected[scope][metric]
                differences[scope][metric] = delta
                if abs(delta) > tolerance:
                    raise ValueError(
                        f"Frozen {model}/{scope}/{metric} failed reproduction: {delta}",
                    )
        report[model] = {"recomputed": observed, "difference_from_frozen": differences}
    return {
        "tolerance": tolerance,
        "all_metrics_match": True,
        "case_count": len(aligned),
        "positive_count": sum(row["label"] for row in aligned),
        "negative_count": sum(not row["label"] for row in aligned),
        "source_group_count": len({row["source_group_id"] for row in aligned}),
        "fold_membership": {
            str(fold): sorted({row["source_group_id"] for row in aligned if row["fold_index"] == fold})
            for fold in sorted({row["fold_index"] for row in aligned})
        },
        "missing_or_invalid_prediction_count": 0,
        "models": report,
    }


def paired_group_bootstrap(aligned, *, replicates=2000, seed=451):
    """Use identical source-group draws for every model pair and metric."""
    grouped = defaultdict(list)
    for row in aligned:
        grouped[row["source_group_id"]].append(row)
    groups = sorted(grouped)
    if len(groups) < 2:
        raise ValueError("Paired group bootstrap requires at least two source groups")
    comparisons = {
        f"{model}_minus_{baseline}": {
            "model": model,
            "baseline": baseline,
            "case_level": {metric: [] for metric in METRICS},
            "group_balanced": {metric: [] for metric in METRICS},
        }
        for model, baseline in MODEL_PAIRS
    }
    rng = random.Random(seed)
    invalid_reasons = defaultdict(int)
    draw_hashes = []
    for replicate in range(replicates):
        selected = [rng.choice(groups) for _ in groups]
        if replicate < 10:
            draw_hashes.append(__import__("hashlib").sha256("\n".join(selected).encode()).hexdigest())
        rows = []
        # Keep duplicate group draws as independent bootstrap multiplicities.
        for draw_index, group in enumerate(selected):
            rows.extend({**row, "source_group_id": f"{draw_index}:{group}"} for row in grouped[group])
        try:
            for value in comparisons.values():
                for metric in METRICS:
                    value["case_level"][metric].append(
                        paired_difference(rows, value["model"], value["baseline"], metric),
                    )
                    value["group_balanced"][metric].append(
                        paired_difference(
                            rows, value["model"], value["baseline"], metric, group_balanced=True,
                        ),
                    )
        except (KeyError, TypeError, ValueError) as error:
            invalid_reasons[type(error).__name__] += 1
    output = {}
    for name, value in comparisons.items():
        result = {"model": value["model"], "baseline": value["baseline"]}
        for scope in ("case_level", "group_balanced"):
            result[scope] = {}
            for metric, samples in value[scope].items():
                result[scope][metric] = {
                    "observed_difference": paired_difference(
                        aligned, value["model"], value["baseline"], metric,
                        group_balanced=scope == "group_balanced",
                    ),
                    "lower_2_5": float(np.quantile(samples, .025)) if samples else None,
                    "upper_97_5": float(np.quantile(samples, .975)) if samples else None,
                    "valid_replicates": len(samples),
                }
        output[name] = result
    invalid = sum(invalid_reasons.values())
    return {
        "schema_version": PAIRED_COMPARISON_VERSION,
        "method": "paired percentile source-group bootstrap over frozen out-of-fold predictions",
        "seed": seed,
        "requested_replicates": replicates,
        "valid_replicates": replicates - invalid,
        "invalid_replicates": invalid,
        "invalid_reasons": dict(sorted(invalid_reasons.items())),
        "source_group_count": len(groups),
        "same_group_draw_used_for_every_model_pair": True,
        "candidate_rows_resampled_iid": False,
        "refit_inside_bootstrap": False,
        "first_ten_draw_sha256": draw_hashes,
        "sign_convention": "model loss minus baseline loss; negative favors model",
        "comparisons": output,
        "selection_optimism_removed": False,
    }
