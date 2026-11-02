"""Offline stop-only versus always-Zoom decision and cost diagnostics."""

from __future__ import annotations

from .calibration_metrics import calibration_metrics
from .zoom_incremental_model import BASELINE_MODEL, PRIMARY_MODEL

COST_VERSION = "bite.task_v_zoom_offline_cost_risk.v1"
LOGICAL_ACTION_COST = 2
LAMBDA_GRID = (0.0, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1)


def _decision_counts(rows, model):
    predictions = [row["probabilities"][model] >= .5 for row in rows]
    labels = [bool(row["label"]) for row in rows]
    return {
        "false_positive": sum(prediction and not label for prediction, label in zip(predictions, labels, strict=True)),
        "false_negative": sum(not prediction and label for prediction, label in zip(predictions, labels, strict=True)),
        "correct": sum(prediction == label for prediction, label in zip(predictions, labels, strict=True)),
        "error": sum(prediction != label for prediction, label in zip(predictions, labels, strict=True)),
    }


def analyze_cost_risk(aligned_rows):
    if not aligned_rows:
        raise ValueError("Cost analysis requires paired predictions")
    stop = _decision_counts(aligned_rows, BASELINE_MODEL)
    zoom = _decision_counts(aligned_rows, PRIMARY_MODEL)
    avoided = 0
    introduced = 0
    for row in aligned_rows:
        label = bool(row["label"])
        old_wrong = (row["probabilities"][BASELINE_MODEL] >= .5) != label
        new_wrong = (row["probabilities"][PRIMARY_MODEL] >= .5) != label
        avoided += old_wrong and not new_wrong
        introduced += not old_wrong and new_wrong
    labels = [row["label"] for row in aligned_rows]
    stop_metrics = calibration_metrics(labels, [row["probabilities"][BASELINE_MODEL] for row in aligned_rows])
    zoom_metrics = calibration_metrics(labels, [row["probabilities"][PRIMARY_MODEL] for row in aligned_rows])
    count = len(aligned_rows)
    error_improvement = stop["error"] / count - zoom["error"] / count
    break_even = error_improvement / LOGICAL_ACTION_COST
    grid = []
    for penalty in LAMBDA_GRID:
        stop_loss = stop["error"] / count
        zoom_loss = zoom["error"] / count + LOGICAL_ACTION_COST * penalty
        grid.append({
            "lambda": penalty,
            "stop_loss": stop_loss,
            "always_zoom_loss": zoom_loss,
            "always_zoom_minus_stop": zoom_loss - stop_loss,
            "preferred": "always_zoom" if zoom_loss < stop_loss else "stop_only" if zoom_loss > stop_loss else "tie",
        })
    return {
        "schema_version": COST_VERSION,
        "status": "OFFLINE_OBSERVED_DECISION_DIAGNOSTIC_NOT_A_POLICY",
        "candidate_count": count,
        "stop_only": {
            "decision_counts": stop,
            "metrics": stop_metrics,
            "incremental_logical_calls": 0,
        },
        "always_zoom": {
            "decision_counts": zoom,
            "metrics": zoom_metrics,
            "incremental_logical_calls": count * LOGICAL_ACTION_COST,
            "logical_calls_per_candidate": LOGICAL_ACTION_COST,
        },
        "paired_decision_changes": {
            "errors_avoided": int(avoided),
            "new_errors_introduced": int(introduced),
            "net_error_change": zoom["error"] - stop["error"],
        },
        "cost_sensitivity": {
            "hypothetical_lambda_grid": grid,
            "break_even_lambda_per_logical_call": break_even,
            "nonnegative_break_even_exists": break_even >= 0,
            "lambda_was_tuned": False,
            "latency_or_monetary_cost_measured": False,
        },
        "limitations": [
            "fixed original-candidate correctness label",
            "observed development branches rather than a validated observation distribution",
            "not end-to-end agent-task loss",
            "not a deployed action rule or planner",
        ],
    }
