"""Source-group bootstrap intervals over fixed out-of-fold predictions."""

from __future__ import annotations

import random
from collections import defaultdict

import numpy as np

from .calibration_metrics import calibration_metrics

BOOTSTRAP_VERSION = "bite.annotation_proxy_group_bootstrap.v1"


def grouped_bootstrap(predictions, *, replicates=2000, seed=439):
    grouped = defaultdict(list)
    for row in predictions:
        grouped[row["source_group_id"]].append(row)
    groups = sorted(grouped)
    if len(groups) < 2:
        raise ValueError("Grouped bootstrap requires at least two source groups")
    rng = random.Random(seed)
    samples = {name: [] for name in ("brier_score", "log_loss", "decision_error")}
    invalid = 0
    for _ in range(replicates):
        selected = [rng.choice(groups) for _ in groups]
        rows = [row for group in selected for row in grouped[group]]
        labels = [row["label"] for row in rows]
        if set(labels) != {0, 1}:
            invalid += 1
            continue
        metrics = calibration_metrics(labels, [row["probability"] for row in rows])
        for name, values in samples.items():
            values.append(metrics[name])
    valid = replicates - invalid
    intervals = {}
    for name, values in samples.items():
        intervals[name] = {
            "lower_2_5": float(np.quantile(values, .025)) if values else None,
            "upper_97_5": float(np.quantile(values, .975)) if values else None,
            "valid_replicates": len(values),
        }
    positive_groups = len({
        group for group, rows in grouped.items() if any(row["label"] for row in rows)
    })
    return {
        "schema_version": BOOTSTRAP_VERSION,
        "method": "percentile source-group bootstrap over fixed out-of-fold predictions",
        "seed": seed,
        "requested_replicates": replicates,
        "valid_replicates": valid,
        "invalid_single_class_replicates": invalid,
        "unique_group_count": len(groups),
        "positive_bearing_group_count": positive_groups,
        "intervals": intervals,
        "refit_inside_bootstrap": False,
        "interpretation": "evaluation uncertainty conditional on frozen cross-fitted predictions",
    }
