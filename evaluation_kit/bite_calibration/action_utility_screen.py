"""Empirical net-utility screen for an already-observed action over frozen predictions.

Two loss families are kept separate and never summed:

* error utility  u_i(lambda)   = 1[d0_i != H_i] - 1[dz_i != H_i] - lambda * c_i
* Brier utility  u^B_i(lambda) = (p0_i - H_i)^2 - (pz_i - H_i)^2 - lambda_B * c_i

Positive utility favors acting. Lambda is expressed in the loss unit of its own
family per logical call. Nothing here is a policy value: the labels, folds and
action outcomes are fixed development observations.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict

import numpy as np

SCREEN_VERSION = "bite.action_utility_screen.v1"
ERROR_LAMBDA_GRID = (0.0, 0.001, 0.0025, 0.005, 0.01)
DECISION_THRESHOLD = 0.5
INFLUENCE_DROP_COUNTS = (1, 2, 3)


def _decision(probability):
    return probability >= DECISION_THRESHOLD


def candidate_utilities(aligned, *, baseline, treatment, action_cost):
    """Per-candidate gross utilities (lambda = 0) for both loss families."""
    if not aligned:
        raise ValueError("Utility screen requires aligned predictions")
    if not isinstance(action_cost, (int, float)) or action_cost <= 0:
        raise ValueError("Action cost must be a positive logical-call count")
    rows = []
    for row in aligned:
        label = int(row["label"])
        if label not in {0, 1}:
            raise ValueError("Utility screen requires binary labels")
        p0 = float(row["probabilities"][baseline])
        pz = float(row["probabilities"][treatment])
        if not all(math.isfinite(p) and 0 <= p <= 1 for p in (p0, pz)):
            raise ValueError("Invalid probability in utility screen")
        rows.append({
            "state_id": row["state_id"],
            "source_group_id": row["source_group_id"],
            "query": row["query"],
            "label": label,
            "baseline_probability": p0,
            "treatment_probability": pz,
            "error_utility_gross": float(_decision(p0) != bool(label)) - float(_decision(pz) != bool(label)),
            "brier_utility_gross": (p0 - label) ** 2 - (pz - label) ** 2,
            "logical_cost": float(action_cost),
        })
    return rows


def _mean(rows, field, *, group_balanced=False):
    if not group_balanced:
        return sum(row[field] for row in rows) / len(rows)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["source_group_id"]].append(row[field])
    return sum(sum(values) / len(values) for values in grouped.values()) / len(grouped)


def grouped_utility_bootstrap(rows, *, replicates=2000, seed=463):
    """Paired percentile bootstrap that resamples whole source groups."""
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["source_group_id"]].append(row)
    groups = sorted(grouped)
    if len(groups) < 2:
        raise ValueError("Grouped bootstrap requires at least two source groups")
    rng = random.Random(seed)
    samples = {
        (field, scope): []
        for field in ("error_utility_gross", "brier_utility_gross")
        for scope in ("case_level", "group_balanced")
    }
    draw_hashes = []
    for replicate in range(replicates):
        selected = [rng.choice(groups) for _ in groups]
        if replicate < 10:
            draw_hashes.append(hashlib.sha256("\n".join(selected).encode()).hexdigest())
        drawn = [
            {**row, "source_group_id": f"{index}:{group}"}
            for index, group in enumerate(selected) for row in grouped[group]
        ]
        for (field, scope), values in samples.items():
            values.append(_mean(drawn, field, group_balanced=scope == "group_balanced"))
    summary = {}
    for (field, scope), values in samples.items():
        values = np.asarray(values)
        summary.setdefault(field, {})[scope] = {
            "observed": _mean(rows, field, group_balanced=scope == "group_balanced"),
            "lower_2_5": float(np.quantile(values, .025)),
            "upper_97_5": float(np.quantile(values, .975)),
            "bootstrap_standard_error": float(np.std(values, ddof=1)),
            "replicate_fraction_strictly_positive": float(np.mean(values > 0)),
        }
    return {
        "method": "paired percentile source-group bootstrap; candidate rows never resampled iid",
        "seed": seed,
        "replicates": replicates,
        "source_group_count": len(groups),
        "candidate_rows_resampled_iid": False,
        "refit_inside_bootstrap": False,
        "first_ten_draw_sha256": draw_hashes,
        "replicate_fraction_is_posterior_probability": False,
        "gross_utility": summary,
    }


def _net(gross_interval, cost, penalty):
    shift = cost * penalty
    return {
        "observed": gross_interval["observed"] - shift,
        "lower_2_5": gross_interval["lower_2_5"] - shift,
        "upper_97_5": gross_interval["upper_97_5"] - shift,
    }


def _break_even(gross, cost):
    """Largest per-call penalty at which acting is not worse; None if gross <= 0."""
    return gross / cost if gross > 0 else None


def group_contributions(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["source_group_id"]].append(row)
    total = len(rows)
    output = []
    for group, members in sorted(grouped.items()):
        output.append({
            "source_group_id": group,
            "candidate_count": len(members),
            "errors_avoided": sum(row["error_utility_gross"] > 0 for row in members),
            "errors_introduced": sum(row["error_utility_gross"] < 0 for row in members),
            "error_utility_sum": sum(row["error_utility_gross"] for row in members),
            "brier_utility_sum": sum(row["brier_utility_gross"] for row in members),
            "contribution_to_mean_error_utility": sum(row["error_utility_gross"] for row in members) / total,
            "contribution_to_mean_brier_utility": sum(row["brier_utility_gross"] for row in members) / total,
        })
    return output


def influence_sensitivity(rows):
    """Leave-one-group-out and drop-most-favorable-groups recomputation."""
    contributions = group_contributions(rows)
    loo = {"error_utility_gross": [], "brier_utility_gross": []}
    for item in contributions:
        kept = [row for row in rows if row["source_group_id"] != item["source_group_id"]]
        for field, values in loo.items():
            values.append(_mean(kept, field))
    full = {field: _mean(rows, field) for field in loo}
    output = {"full_sample": full, "leave_one_group_out": {}, "drop_most_favorable_groups": {}}
    for field, values in loo.items():
        output["leave_one_group_out"][field] = {
            "minimum": min(values),
            "maximum": max(values),
            "sign_changes_from_full_sample": sum(
                (value > 0) != (full[field] > 0) or (value == 0) != (full[field] == 0) for value in values
            ),
        }
        sum_field = "error_utility_sum" if field == "error_utility_gross" else "brier_utility_sum"
        ordered = sorted(contributions, key=lambda item: (-item[sum_field], item["source_group_id"]))
        output["drop_most_favorable_groups"][field] = []
        for count in (count for count in INFLUENCE_DROP_COUNTS if count < len(contributions)):
            dropped = {item["source_group_id"] for item in ordered[:count]}
            kept = [row for row in rows if row["source_group_id"] not in dropped]
            output["drop_most_favorable_groups"][field].append({
                "dropped_group_count": count,
                "dropped_source_group_ids": sorted(dropped),
                "remaining_candidate_count": len(kept),
                "mean_gross_utility": _mean(kept, field),
            })
    return output


def futility_projection(observed, standard_error, current_groups):
    """Planning heuristic: groups needed for a 95% interval to exclude zero if the
    observed mean were the true effect and SE scaled as 1/sqrt(groups)."""
    if observed <= 0:
        return {
            "observed_effect_favors_action": False,
            "projected_groups_for_interval_excluding_zero": None,
            "reason": "observed gross utility is not positive; more data of the same kind cannot demonstrate a benefit it does not show",
        }
    if standard_error <= 0:
        return {"observed_effect_favors_action": True, "projected_groups_for_interval_excluding_zero": current_groups}
    ratio = 1.959963984540054 * standard_error / observed
    return {
        "observed_effect_favors_action": True,
        "projected_groups_for_interval_excluding_zero": math.ceil(current_groups * ratio * ratio),
        "assumes_observed_effect_is_true": True,
        "assumes_standard_error_scales_inverse_sqrt_groups": True,
    }


def screen_action(aligned, *, baseline, treatment, action_cost, endpoint,
                  replicates=2000, seed=463, unused_fit_groups=None):
    rows = candidate_utilities(aligned, baseline=baseline, treatment=treatment, action_cost=action_cost)
    bootstrap = grouped_utility_bootstrap(rows, replicates=replicates, seed=seed)
    gross_error = bootstrap["gross_utility"]["error_utility_gross"]["case_level"]
    gross_brier = bootstrap["gross_utility"]["brier_utility_gross"]["case_level"]
    group_count = bootstrap["source_group_count"]
    error_grid = [{
        "lambda_error_units_per_logical_call": penalty,
        "mean_net_error_utility": _net(gross_error, action_cost, penalty),
        "preferred_on_observed_mean": (
            "act" if gross_error["observed"] - action_cost * penalty > 0
            else "stop" if gross_error["observed"] - action_cost * penalty < 0 else "tie"
        ),
        "interval_excludes_zero": (
            gross_error["lower_2_5"] - action_cost * penalty > 0
            or gross_error["upper_97_5"] - action_cost * penalty < 0
        ),
    } for penalty in ERROR_LAMBDA_GRID]
    projections = {
        "error_utility": futility_projection(
            gross_error["observed"], gross_error["bootstrap_standard_error"], group_count),
        "brier_utility": futility_projection(
            gross_brier["observed"], gross_brier["bootstrap_standard_error"], group_count),
    }
    for projection in projections.values():
        needed = projection.get("projected_groups_for_interval_excluding_zero")
        projection["unused_calibration_fit_groups_available"] = unused_fit_groups
        projection["feasible_within_unused_fit_groups"] = (
            needed is not None and unused_fit_groups is not None and needed - group_count <= unused_fit_groups
        )
    return {
        "schema_version": SCREEN_VERSION,
        "status": "EXPLORATORY_DEVELOPMENT_SCREEN_NOT_A_POLICY_OR_GUARANTEE",
        "endpoint": endpoint,
        "baseline_model": baseline,
        "treatment_model": treatment,
        "candidate_count": len(rows),
        "source_group_count": group_count,
        "positive_count": sum(row["label"] for row in rows),
        "decision_threshold": DECISION_THRESHOLD,
        "logical_cost_per_candidate": action_cost,
        "additional_logical_calls": action_cost * len(rows),
        "errors_avoided": sum(row["error_utility_gross"] > 0 for row in rows),
        "errors_introduced": sum(row["error_utility_gross"] < 0 for row in rows),
        "sign_convention": "baseline loss minus treatment loss minus cost; positive favors acting",
        "error_loss": {
            "unit": "binary decision error per candidate",
            "gross_utility": bootstrap["gross_utility"]["error_utility_gross"],
            "break_even_lambda_per_logical_call": _break_even(gross_error["observed"], action_cost),
            "lambda_grid": error_grid,
        },
        "brier_loss": {
            "unit": "squared probability error per candidate",
            "gross_utility": bootstrap["gross_utility"]["brier_utility_gross"],
            "break_even_lambda_brier_per_logical_call": _break_even(gross_brier["observed"], action_cost),
            "not_comparable_to_error_lambda": True,
        },
        "net_interval_construction": "constant per-candidate cost shifts gross interval endpoints exactly",
        "bootstrap": {key: value for key, value in bootstrap.items() if key != "gross_utility"},
        "group_contributions": group_contributions(rows),
        "influence_sensitivity": influence_sensitivity(rows),
        "futility_projection": projections,
        "limitations": [
            "fixed original-candidate annotation-proxy labels",
            "frozen out-of-fold development predictions, not held-out validation",
            "constant logical cost; latency and monetary cost not measured",
            "not an online policy value or end-to-end agent result",
            "percentile intervals are exploratory and carry no coverage guarantee",
        ],
    }


def squared_loss_identity_diagnostic(aligned, *, baseline, treatment):
    """Exact per-case decomposition of the Brier gain.

    (p0-H)^2 - (pz-H)^2 = (pz-p0)^2 + 2 (pz-p0)(H-pz). If pz were the true
    conditional expectation given (S, O), the cross term would have mean zero and
    the gain would equal the mean squared movement. A negative cross term means
    the treatment moves probabilities in directions the labels do not support.
    """
    count = len(aligned)
    movement = cross = 0.0
    for row in aligned:
        p0 = row["probabilities"][baseline]
        pz = row["probabilities"][treatment]
        movement += (pz - p0) ** 2
        cross += 2 * (pz - p0) * (row["label"] - pz)
    return {
        "observed_brier_gain": (movement + cross) / count,
        "mean_squared_probability_movement": movement / count,
        "calibration_cross_term": cross / count,
        "identity": "gain = movement + cross; cross has mean 0 under correct specification",
        "correct_specification_assumed": False,
    }


def sample_size_sensitivity(group_values, *, precisions=(0.005, 0.05, 0.1), delta=0.05, value_range=2.0):
    """Groups needed for a one-sided (1 - delta) radius <= epsilon under three bounds.

    Hoeffding uses only the range; empirical Bernstein (Maurer & Pontil) uses the
    observed group-level variance plus a range term; the normal approximation has
    no finite-sample guarantee. All treat source groups as the independent units.
    """
    if len(group_values) < 2:
        raise ValueError("Sample-size sensitivity requires at least two groups")
    sd = float(np.std(group_values, ddof=1))
    log_term = math.log(1 / delta)
    rows = []
    for epsilon in precisions:
        bernstein = 2
        while (math.sqrt(2 * sd * sd * math.log(2 / delta) / bernstein)
               + 7 * value_range * math.log(2 / delta) / (3 * (bernstein - 1))) > epsilon:
            bernstein += 1
        rows.append({
            "epsilon": epsilon,
            "hoeffding_groups": math.ceil(value_range ** 2 * log_term / (2 * epsilon ** 2)),
            "empirical_bernstein_groups_at_observed_sd": bernstein,
            "normal_approximation_groups_at_observed_sd": max(1, math.ceil((1.6448536269514722 * sd / epsilon) ** 2)),
        })
    return {
        "delta": delta,
        "value_range": value_range,
        "observed_group_sd": sd,
        "observed_group_count": len(group_values),
        "nonzero_groups": sum(value != 0 for value in group_values),
        "precision_grid": rows,
        "normal_approximation_has_finite_sample_guarantee": False,
        "universal_requirement_claimed": False,
    }


def classify_zoom_collection(screens):
    """Prespecified rule for whether another Zoom-only fit collection is justified.

    Justified only if, at every endpoint, both gross utilities are positive on the
    observed sample and the error-utility futility projection is feasible within
    the unused calibration-fit groups.
    """
    reasons = []
    for endpoint, screen in sorted(screens.items()):
        error = screen["error_loss"]["gross_utility"]["case_level"]["observed"]
        brier = screen["brier_loss"]["gross_utility"]["case_level"]["observed"]
        if error <= 0:
            reasons.append(f"IoU {endpoint}: observed gross error utility {error:+.6f} is not positive")
        if brier <= 0:
            reasons.append(f"IoU {endpoint}: observed gross Brier utility {brier:+.6f} is not positive")
        if not screen["futility_projection"]["error_utility"]["feasible_within_unused_fit_groups"]:
            reasons.append(f"IoU {endpoint}: error-utility projection not feasible within unused fit groups")
    return {
        "decision": (
            "ZOOM_ONLY_COLLECTION_NOT_JUSTIFIED_FOR_TASK_V_VERIFICATION" if reasons
            else "ZOOM_ONLY_COLLECTION_MAY_BE_JUSTIFIED"
        ),
        "reasons": reasons,
        "rule": "positive observed gross error and Brier utility at every endpoint and feasible error-utility projection",
        "rule_specified_after_phase04c1d_results_were_known": True,
        "zoom_declared_universally_useless": False,
        "statistical_action_dominance_claimed": False,
    }
