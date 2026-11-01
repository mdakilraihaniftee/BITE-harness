"""Metrics for annotation-proxy calibration with explicit finite support."""

from __future__ import annotations

import math
from collections import defaultdict
from itertools import pairwise


def _validated(labels, probabilities):
    if len(labels) != len(probabilities) or not labels:
        raise ValueError("Labels and probabilities must be nonempty and aligned")
    y = [int(value) for value in labels]
    p = [float(value) for value in probabilities]
    if any(value not in {0, 1} for value in y):
        raise ValueError("Calibration labels must be binary")
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in p):
        raise ValueError("Probabilities must be finite and in [0, 1]")
    return y, p


def calibration_metrics(labels, probabilities, *, threshold=0.5):
    y, p = _validated(labels, probabilities)
    epsilon = 1e-15
    clipped = [min(1 - epsilon, max(epsilon, value)) for value in p]
    return {
        "case_count": len(y),
        "positive_count": sum(y),
        "negative_count": len(y) - sum(y),
        "brier_score": sum((prob - label) ** 2 for label, prob in zip(y, p, strict=True)) / len(y),
        "log_loss": -sum(
            label * math.log(prob) + (1 - label) * math.log(1 - prob)
            for label, prob in zip(y, clipped, strict=True)
        ) / len(y),
        "decision_error": sum((prob >= threshold) != bool(label) for label, prob in zip(y, p, strict=True))
        / len(y),
        "decision_threshold": threshold,
    }


def reliability_summary(labels, probabilities, *, edges=(0, .2, .4, .6, .8, 1.0)):
    y, p = _validated(labels, probabilities)
    bins = []
    for index, (lower, upper) in enumerate(pairwise(edges)):
        positions = [
            position for position, value in enumerate(p)
            if (
                lower <= value <= upper
                if index == len(edges) - 2
                else lower <= value < upper
            )
        ]
        bins.append({
            "lower": lower,
            "upper": upper,
            "right_inclusive": index == len(edges) - 2,
            "count": len(positions),
            "mean_probability": (
                sum(p[position] for position in positions) / len(positions) if positions else None
            ),
            "observed_fraction": (
                sum(y[position] for position in positions) / len(positions) if positions else None
            ),
        })
    return bins


def group_balanced_metrics(records, probability_key):
    grouped = defaultdict(list)
    for row in records:
        grouped[row["source_group_id"]].append(row)
    per_group = []
    for group, rows in sorted(grouped.items()):
        metrics = calibration_metrics(
            [row["label"] for row in rows], [row[probability_key] for row in rows],
        )
        per_group.append({"source_group_id": group, **metrics})
    return {
        "group_count": len(per_group),
        "brier_score": sum(row["brier_score"] for row in per_group) / len(per_group),
        "log_loss": sum(row["log_loss"] for row in per_group) / len(per_group),
        "decision_error": sum(row["decision_error"] for row in per_group) / len(per_group),
    }

