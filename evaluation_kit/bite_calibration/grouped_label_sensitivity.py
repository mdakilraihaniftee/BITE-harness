"""Exact group-budget and combined group/candidate label-sensitivity bounds."""

from __future__ import annotations

from collections import defaultdict

from .label_sensitivity import _validated

GROUPED_SENSITIVITY_VERSION = "bite.fixed_prediction_grouped_label_sensitivity.v1"


def exact_group_budget_bounds(rows, model, baseline, *, eligible=lambda row: True, group_budget=0):
    values = _validated(rows, model, baseline, eligible)
    denominator = sum(row["weight"] for row in values)
    observed_total = sum(row["weighted_difference"] for row in values)
    grouped = defaultdict(list)
    for row in values:
        if row["eligible"]:
            grouped[row["source_group_id"]].append(row)
    effective = min(max(int(group_budget), 0), len(grouped))
    group_min = []
    group_max = []
    for group, items in grouped.items():
        decreasing = sum(min(0.0, item["weighted_flip_effect"]) for item in items)
        increasing = sum(max(0.0, item["weighted_flip_effect"]) for item in items)
        group_min.append((decreasing, group, [x["state_id"] for x in items if x["weighted_flip_effect"] < 0]))
        group_max.append((increasing, group, [x["state_id"] for x in items if x["weighted_flip_effect"] > 0]))
    selected_min = sorted((x for x in group_min if x[0] < 0), key=lambda x: (x[0], x[1]))[:effective]
    selected_max = sorted((x for x in group_max if x[0] > 0), key=lambda x: (-x[0], x[1]))[:effective]
    minimum = (observed_total + sum(x[0] for x in selected_min)) / denominator
    maximum = (observed_total + sum(x[0] for x in selected_max)) / denominator
    return {
        "requested_group_budget": int(group_budget),
        "effective_group_budget": effective,
        "eligible_group_count": len(grouped),
        "observed_difference": observed_total / denominator,
        "minimum_difference": minimum,
        "maximum_difference": maximum,
        "includes_zero": minimum <= 0 <= maximum,
        "minimum_selected_groups": [x[1] for x in selected_min],
        "maximum_selected_groups": [x[1] for x in selected_max],
        "minimum_selected_state_ids": [state for x in selected_min for state in x[2]],
        "maximum_selected_state_ids": [state for x in selected_max for state in x[2]],
    }


def exact_combined_bounds(rows, model, baseline, *, eligible=lambda row: True,
                          candidate_budget=0, group_budget=0):
    """Exact dynamic program with simultaneous candidate and source-group caps."""
    values = _validated(rows, model, baseline, eligible)
    denominator = sum(row["weight"] for row in values)
    observed_total = sum(row["weighted_difference"] for row in values)
    grouped = defaultdict(list)
    for row in values:
        if row["eligible"]:
            grouped[row["source_group_id"]].append(row)
    max_candidates = min(max(int(candidate_budget), 0), sum(map(len, grouped.values())))
    max_groups = min(max(int(group_budget), 0), len(grouped))

    def solve(direction):
        # State (used candidates, used groups) -> (effect, selected ids/groups).
        dp = {(0, 0): (0.0, (), ())}
        for group, items in sorted(grouped.items()):
            beneficial = sorted(
                (item for item in items if direction * item["weighted_flip_effect"] > 0),
                key=lambda item: (-direction * item["weighted_flip_effect"], item["state_id"]),
            )
            options = [(0, 0.0, ())]
            running = 0.0
            selected = []
            for count, item in enumerate(beneficial[:max_candidates], 1):
                running += item["weighted_flip_effect"]
                selected.append(item["state_id"])
                options.append((count, running, tuple(selected)))
            next_dp = dict(dp)
            for (used_c, used_g), current in dp.items():
                for count, effect, ids in options[1:]:
                    key = (used_c + count, used_g + 1)
                    if key[0] > max_candidates or key[1] > max_groups:
                        continue
                    candidate = (current[0] + effect, current[1] + ids, current[2] + (group,))
                    previous = next_dp.get(key)
                    if previous is None or direction * candidate[0] > direction * previous[0]:
                        next_dp[key] = candidate
            dp = next_dp
        best = max(dp.values(), key=lambda value: direction * value[0])
        return best

    minimum = solve(-1)
    maximum = solve(1)
    low = (observed_total + minimum[0]) / denominator
    high = (observed_total + maximum[0]) / denominator
    return {
        "requested_candidate_budget": int(candidate_budget),
        "requested_group_budget": int(group_budget),
        "effective_candidate_budget": max_candidates,
        "effective_group_budget": max_groups,
        "observed_difference": observed_total / denominator,
        "minimum_difference": low,
        "maximum_difference": high,
        "includes_zero": low <= 0 <= high,
        "minimum_selected_state_ids": list(minimum[1]),
        "minimum_selected_groups": list(minimum[2]),
        "maximum_selected_state_ids": list(maximum[1]),
        "maximum_selected_groups": list(maximum[2]),
        "solver": "exact dynamic programming over source groups, candidate count and group count",
        "heuristic": False,
    }


def analyze_grouped(rows, model, baseline, *, eligible, group_budgets=(0, 1, 2, 5, 10, 20, 40),
                    combined_budgets=((1, 1), (2, 1), (5, 2), (10, 5), (20, 10), (40, 20))):
    group_count = len({row["source_group_id"] for row in rows if eligible(row)})
    complete = [
        exact_group_budget_bounds(
            rows, model, baseline, eligible=eligible, group_budget=budget,
        ) for budget in range(group_count + 1)
    ]
    observed = complete[0]["observed_difference"]
    reversal = next((
        row for row in complete
        if (observed < 0 and row["maximum_difference"] >= 0)
        or (observed > 0 and row["minimum_difference"] <= 0)
        or observed == 0
    ), None)
    return {
        "schema_version": GROUPED_SENSITIVITY_VERSION,
        "group_budget_bounds": [
            exact_group_budget_bounds(
                rows, model, baseline, eligible=eligible, group_budget=budget,
            ) for budget in group_budgets
        ],
        "combined_budget_bounds": [
            exact_combined_bounds(
                rows, model, baseline, eligible=eligible,
                candidate_budget=candidate_budget, group_budget=group_budget,
            ) for candidate_budget, group_budget in combined_budgets
        ],
        "minimum_group_ranking_reversal": {
            "possible": reversal is not None,
            "minimum_groups": reversal["effective_group_budget"] if reversal else None,
            "bound_at_reversal": reversal if reversal else None,
        },
        "errors_within_group_assumed_independent": False,
        "actual_error_clustering_inferred": False,
    }
