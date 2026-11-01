"""Exact finite-sample sensitivity of paired Brier comparisons to label flips."""

from __future__ import annotations

import itertools
from collections import Counter

LABEL_SENSITIVITY_VERSION = "bite.fixed_prediction_label_sensitivity.v1"
DEFAULT_BUDGETS = (0, 1, 2, 5, 10, 20, 40)


def brier_difference(label, model_probability, baseline_probability):
    return (model_probability - label) ** 2 - (baseline_probability - label) ** 2


def flip_effect(label, model_probability, baseline_probability):
    """Exact change d(1-y)-d(y)."""
    return -2 * (1 - 2 * label) * (model_probability - baseline_probability)


def _validated(rows, model, baseline, eligible):
    values = []
    for row in rows:
        label = row["label"]
        if label not in {0, 1}:
            raise ValueError("Sensitivity labels must be binary")
        p_model = row["probabilities"][model]
        p_baseline = row["probabilities"][baseline]
        weight = float(row.get("weight", 1.0))
        if weight <= 0:
            raise ValueError("Sensitivity weights must be positive")
        values.append({
            "state_id": row["state_id"],
            "candidate_id": row.get("candidate_id"),
            "source_group_id": row["source_group_id"],
            "query": row.get("query"),
            "label": label,
            "eligible": bool(eligible(row)),
            "weighted_difference": weight * brier_difference(label, p_model, p_baseline),
            "weighted_flip_effect": weight * flip_effect(label, p_model, p_baseline),
            "weight": weight,
        })
    return values


def exact_cardinality_bounds(rows, model, baseline, *, eligible=lambda row: True, budget=0):
    """Exact extrema with at most ``budget`` flips under additive fixed predictions."""
    values = _validated(rows, model, baseline, eligible)
    denominator = sum(row["weight"] for row in values)
    observed = sum(row["weighted_difference"] for row in values) / denominator
    candidates = [row for row in values if row["eligible"]]
    effective_budget = min(max(int(budget), 0), len(candidates))
    decreasing = sorted(
        (row for row in candidates if row["weighted_flip_effect"] < 0),
        key=lambda row: (row["weighted_flip_effect"], row["state_id"]),
    )[:effective_budget]
    increasing = sorted(
        (row for row in candidates if row["weighted_flip_effect"] > 0),
        key=lambda row: (-row["weighted_flip_effect"], row["state_id"]),
    )[:effective_budget]
    return {
        "requested_budget": int(budget),
        "effective_budget": effective_budget,
        "eligible_count": len(candidates),
        "eligible_percentage": (100 * effective_budget / len(candidates)) if candidates else 0.0,
        "observed_difference": observed,
        "minimum_difference": observed + sum(row["weighted_flip_effect"] for row in decreasing) / denominator,
        "maximum_difference": observed + sum(row["weighted_flip_effect"] for row in increasing) / denominator,
        "includes_zero": (
            observed + sum(row["weighted_flip_effect"] for row in decreasing) / denominator <= 0
            <= observed + sum(row["weighted_flip_effect"] for row in increasing) / denominator
        ),
        "minimum_selected": [row["state_id"] for row in decreasing],
        "maximum_selected": [row["state_id"] for row in increasing],
        "minimum_selected_details": decreasing,
        "maximum_selected_details": increasing,
    }


def minimal_ranking_reversal(rows, model, baseline, *, eligible=lambda row: True):
    values = _validated(rows, model, baseline, eligible)
    denominator = sum(row["weight"] for row in values)
    total = sum(row["weighted_difference"] for row in values)
    direction = 1 if total < 0 else -1 if total > 0 else 0
    if direction == 0:
        return {"possible": True, "minimum_flips": 0, "selected_state_ids": []}
    effects = sorted(
        (row for row in values if row["eligible"] and direction * row["weighted_flip_effect"] > 0),
        key=lambda row: (-direction * row["weighted_flip_effect"], row["state_id"]),
    )
    selected = []
    changed = total
    for row in effects:
        selected.append(row)
        changed += row["weighted_flip_effect"]
        if (total < 0 and changed >= 0) or (total > 0 and changed <= 0):
            return {
                "possible": True,
                "minimum_flips": len(selected),
                "selected_state_ids": [item["state_id"] for item in selected],
                "difference_after_flips": changed / denominator,
            }
    return {"possible": False, "minimum_flips": None, "selected_state_ids": [],
            "difference_after_flips": changed / denominator}


def brute_force_bounds(rows, model, baseline, *, eligible=lambda row: True, budget=0):
    """Reference implementation for small test worlds only."""
    values = _validated(rows, model, baseline, eligible)
    denominator = sum(row["weight"] for row in values)
    original = sum(row["weighted_difference"] for row in values)
    candidates = [row for row in values if row["eligible"]]
    totals = [original]
    for count in range(1, min(budget, len(candidates)) + 1):
        totals.extend(
            original + sum(row["weighted_flip_effect"] for row in selected)
            for selected in itertools.combinations(candidates, count)
        )
    return min(totals) / denominator, max(totals) / denominator


def scenario_predicates():
    return {
        "suspected_missing_annotations": lambda row: (
            row["label"] == 0
            and row.get("annotation_scope_audit") == "no_annotated_queried_class_instance"
        ),
        "all_annotation_negatives": lambda row: row["label"] == 0,
        "two_sided_all_labels": lambda row: True,
    }


def with_group_balanced_weights(rows):
    """Weight each source group equally while retaining all candidate rows."""
    counts = Counter(row["source_group_id"] for row in rows)
    return [{**row, "weight": 1 / counts[row["source_group_id"]]} for row in rows]


def analyze_scenarios(rows, model="score_only_logistic", baseline="constant_prevalence",
                      *, budgets=DEFAULT_BUDGETS):
    scenarios = {}
    for name, predicate in scenario_predicates().items():
        bounds = [
            exact_cardinality_bounds(rows, model, baseline, eligible=predicate, budget=budget)
            for budget in budgets
        ]
        scenarios[name] = {
            "eligible_count": bounds[0]["eligible_count"],
            "budgets": bounds,
            "minimum_ranking_reversal": minimal_ranking_reversal(
                rows, model, baseline, eligible=predicate,
            ),
        }
    return {
        "schema_version": LABEL_SENSITIVITY_VERSION,
        "model": model,
        "baseline": baseline,
        "predictions_refit": False,
        "interpretation": "conditional finite-sample robustness of frozen paired evaluation",
        "not_an_empirical_annotation_error_rate": True,
        "scenarios": scenarios,
    }
