"""Stage B of Phase 4C-1G: can a pre-call selector exploit branch differences?

All selectors are fitted with leave-one-source-group-out (LOGO) cross-fitting.
Preprocessing, thresholds and coefficients come from the 14 training groups
only. The selected branch is then evaluated on the held-out group. Features are
the frozen pre-call set (``PRECALL_FEATURES``); identifiers, labels, future tool
outputs and oracle choices are never available to a selector.

Policies (all predeclared):

* ``P0_stop_only``: always B0.
* ``P1_training_fixed``: the branch with the best training-fold mean utility.
* ``P2_score_threshold``: B0 if initial_score >= tau, otherwise action a; (tau, a)
  maximize training-fold utility over a fixed grid.
* ``P3_action_value``: per-branch ridge logistic models of P(correct | x); the
  selector picks argmax_b p_b - lambda C_b.

Optional P4 (direct VLM tool choice) is not implemented: it needs separate
inference authorization.
"""

from __future__ import annotations

import math

import numpy as np

from .oracle_headroom import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    LAMBDA_GRID,
    best_fixed,
    group_bootstrap,
    group_mean,
    oracle_value,
    utility,
)
from .task_level_probe_protocol import (
    BRANCHES,
    FORBIDDEN_FEATURE_NAMES,
    INCREMENTAL_LOGICAL_COST,
    PRECALL_FEATURES,
)

POLICIES = ("P0_stop_only", "P1_training_fixed", "P2_score_threshold", "P3_action_value")
THRESHOLD_GRID = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
L2_PENALTY = 1.0
MAX_ITERATIONS = 100
CONVERGENCE_TOLERANCE = 1e-9
RECOVERY_MINIMUM_DENOMINATOR = 0.02
SELECTOR_SPEC = {
    "schema_version": "bite.phase04c1g_selector_spec.v1",
    "policies": list(POLICIES),
    "features": list(PRECALL_FEATURES),
    "threshold_grid": list(THRESHOLD_GRID),
    "threshold_feature": "initial_score",
    "ridge_l2_penalty": L2_PENALTY,
    "standardization": "training-fold mean and population standard deviation",
    "tie_break": "higher training utility, then lower incremental cost, then branch order",
    "constant_training_target": "intercept-only model (training mean); recorded as non-estimable slope",
    "cross_fitting": "leave-one-source-group-out",
    "P4_direct_vlm_selector": "not run (requires separate inference authorization)",
}


def validate_features(rows):
    for row in rows:
        names = set(row["features"])
        if names != set(PRECALL_FEATURES):
            raise ValueError(f"Feature set differs from the frozen pre-call set: {sorted(names)}")
        if names & FORBIDDEN_FEATURE_NAMES:
            raise ValueError("Forbidden feature present")
        for name in PRECALL_FEATURES:
            if not isinstance(row["features"][name], (int, float)) or not math.isfinite(row["features"][name]):
                raise ValueError(f"Feature {name} must be finite")
    return True


def _tie_key(branch):
    return (INCREMENTAL_LOGICAL_COST[branch], BRANCHES.index(branch))


def _matrix(rows, preprocessing):
    raw = np.asarray([[row["features"][n] for n in PRECALL_FEATURES] for row in rows], dtype=np.float64)
    mean = np.asarray(preprocessing["mean"])
    scale = np.asarray(preprocessing["scale"])
    return np.column_stack([np.ones(len(rows)), (raw - mean) / scale])


def fit_preprocessing(rows):
    raw = np.asarray([[row["features"][n] for n in PRECALL_FEATURES] for row in rows], dtype=np.float64)
    scale = raw.std(axis=0)
    return {"mean": raw.mean(axis=0).tolist(), "scale": np.where(scale < 1e-12, 1.0, scale).tolist()}


def fit_ridge_logistic(design, target):
    """Newton ridge logistic (intercept unpenalized); returns coefficient or None if constant target."""
    if len(set(target.tolist())) < 2:
        return None
    penalty = np.r_[0.0, np.full(design.shape[1] - 1, L2_PENALTY)]
    coefficient = np.zeros(design.shape[1])
    for _ in range(MAX_ITERATIONS):
        probability = 1 / (1 + np.exp(-np.clip(design @ coefficient, -35, 35)))
        gradient = design.T @ (probability - target) + penalty * coefficient
        hessian = design.T @ (design * (probability * (1 - probability))[:, None]) + np.diag(penalty)
        step = np.linalg.solve(hessian + 1e-10 * np.eye(len(coefficient)), gradient)
        coefficient -= step
        if float(np.max(np.abs(step))) < CONVERGENCE_TOLERANCE:
            return coefficient
    raise ValueError("Ridge logistic did not converge under frozen settings")


def train_p1(train, penalty):
    choice, _, _ = best_fixed(train, penalty)
    return {"branch": choice}


def train_p2(train, penalty):
    candidates = []
    for tau in THRESHOLD_GRID:
        for action in BRANCHES[1:]:
            value = group_mean(train, lambda r, t=tau, a=action: utility(
                r, "B0" if r["features"]["initial_score"] >= t else a, penalty))
            mean_cost = group_mean(train, lambda r, t=tau, a=action: INCREMENTAL_LOGICAL_COST[
                "B0" if r["features"]["initial_score"] >= t else a])
            candidates.append((-value, mean_cost, -tau, BRANCHES.index(action), tau, action, value))
    best = min(candidates)
    return {"tau": best[4], "action": best[5], "training_utility": best[6]}


def select_p2(model, row):
    return "B0" if row["features"]["initial_score"] >= model["tau"] else model["action"]


def train_p3(train):
    preprocessing = fit_preprocessing(train)
    design = _matrix(train, preprocessing)
    models = {}
    for branch in BRANCHES:
        target = np.asarray([row["branches"][branch]["correct"] for row in train], dtype=np.float64)
        coefficient = fit_ridge_logistic(design, target)
        models[branch] = ({"intercept_only": True, "mean": float(target.mean())} if coefficient is None
                          else {"intercept_only": False, "coefficient": coefficient.tolist()})
    return {"preprocessing": preprocessing, "models": models}


def predict_p3(model, rows):
    design = _matrix(rows, model["preprocessing"])
    output = {}
    for branch, spec in model["models"].items():
        if spec["intercept_only"]:
            output[branch] = np.full(len(rows), spec["mean"])
        else:
            output[branch] = 1 / (1 + np.exp(-np.clip(design @ np.asarray(spec["coefficient"]), -35, 35)))
    return output


def select_p3(predictions, index, penalty):
    values = {b: float(predictions[b][index]) - penalty * INCREMENTAL_LOGICAL_COST[b] for b in BRANCHES}
    best = max(values.values())
    return min((b for b in BRANCHES if values[b] == best), key=_tie_key), values


def logo_selections(rows, penalty):
    """Out-of-group branch choice for every row and policy."""
    validate_features(rows)
    groups = sorted({row["source_group_id"] for row in rows})
    selections = {row["task_id"]: {} for row in rows}
    folds = []
    for group in groups:
        train = [row for row in rows if row["source_group_id"] != group]
        test = [row for row in rows if row["source_group_id"] == group]
        p1 = train_p1(train, penalty)
        p2 = train_p2(train, penalty)
        p3 = train_p3(train)
        p3_predictions = predict_p3(p3, test)
        for index, row in enumerate(test):
            choice, values = select_p3(p3_predictions, index, penalty)
            selections[row["task_id"]] = {
                "P0_stop_only": "B0", "P1_training_fixed": p1["branch"], "P2_score_threshold": select_p2(p2, row),
                "P3_action_value": choice,
                "P3_estimated_values": values,
            }
        folds.append({"held_out_source_group_id": group, "training_groups": len(groups) - 1,
                      "training_cases": len(train), "test_cases": len(test), "P1_branch": p1["branch"],
                      "P2_tau": p2["tau"], "P2_action": p2["action"],
                      "P3_intercept_only_branches": sorted(b for b, s in p3["models"].items() if s["intercept_only"])})
    return selections, folds


def policy_value(rows, selections, policy, penalty, *, group_balanced=False):
    return group_mean(rows, lambda r: utility(r, selections[r["task_id"]][policy], penalty), group_balanced=group_balanced)


def recovery_fraction(selector_value, fixed_value, oracle):
    denominator = oracle - fixed_value
    if denominator < RECOVERY_MINIMUM_DENOMINATOR:
        return {"value": None, "status": "UNDEFINED_SMALL_OR_ZERO_HEADROOM", "denominator": denominator}
    return {"value": (selector_value - fixed_value) / denominator, "status": "DESCRIPTIVE", "denominator": denominator}


def learnable_headroom(rows, *, replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED):
    output = {"schema_version": "bite.phase04c1g_learnable_headroom.v1", "selector_spec": SELECTOR_SPEC,
              "case_count": len(rows), "by_penalty": {}}
    validate_features(rows)
    for penalty in LAMBDA_GRID:
        selections, folds = logo_selections(rows, penalty)
        fixed_branch, fixed, _ = best_fixed(rows, penalty)
        oracle = oracle_value(rows, penalty)
        policies = {}
        for policy in POLICIES:
            value = policy_value(rows, selections, policy, penalty)
            chosen = [selections[r["task_id"]][policy] for r in rows]
            policies[policy] = {
                "utility": value,
                "accuracy": group_mean(rows, lambda r, p=policy, s=selections: r["branches"][s[r["task_id"]][p]]["correct"]),
                "group_balanced_utility": policy_value(rows, selections, policy, penalty, group_balanced=True),
                "mean_incremental_logical_cost": sum(INCREMENTAL_LOGICAL_COST[b] for b in chosen) / len(chosen),
                "branch_distribution": {b: chosen.count(b) for b in BRANCHES},
                "minus_P0": value - policy_value(rows, selections, "P0_stop_only", penalty),
                "minus_P1": value - policy_value(rows, selections, "P1_training_fixed", penalty),
                "minus_hindsight_best_fixed": value - fixed,
                "recovery_fraction": recovery_fraction(value, fixed, oracle),
            }
        statistics = {}
        for policy in POLICIES[1:]:
            statistics[f"{policy}_minus_P0"] = (lambda rs, p=policy, s=selections, lam=penalty:
                                                policy_value(rs, s, p, lam) - policy_value(rs, s, "P0_stop_only", lam))
            statistics[f"{policy}_minus_P1"] = (lambda rs, p=policy, s=selections, lam=penalty:
                                                policy_value(rs, s, p, lam) - policy_value(rs, s, "P1_training_fixed", lam))
        statistics["P3_action_value_minus_P2"] = (lambda rs, s=selections, lam=penalty:
                                                  policy_value(rs, s, "P3_action_value", lam)
                                                  - policy_value(rs, s, "P2_score_threshold", lam))
        influence = {}
        for policy in ("P2_score_threshold", "P3_action_value"):
            values = []
            for group in sorted({r["source_group_id"] for r in rows}):
                kept = [r for r in rows if r["source_group_id"] != group]
                values.append(policy_value(kept, selections, policy, penalty)
                              - policy_value(kept, selections, "P1_training_fixed", penalty))
            full = policies[policy]["minus_P1"]
            influence[policy] = {"minus_P1_full": full, "leave_one_group_out_minimum": min(values),
                                 "leave_one_group_out_maximum": max(values),
                                 "sign_changes": sum((v > 0) != (full > 0) for v in values),
                                 "predictions_held_fixed": True}
        output["by_penalty"][str(penalty)] = {
            "hindsight_best_fixed_branch": fixed_branch, "hindsight_best_fixed_utility": fixed,
            "hindsight_oracle_utility": oracle, "oracle_label": "UNATTAINABLE_HINDSIGHT_ORACLE",
            "policies": policies, "folds": folds, "leave_one_group_out_influence": influence,
            "bootstrap": group_bootstrap(rows, statistics, replicates=replicates, seed=seed),
            "selections": {tid: {k: v for k, v in sel.items() if k != "P3_estimated_values"}
                           for tid, sel in sorted(selections.items())},
        }
    zero = output["by_penalty"]["0.0"]
    output["p3_non_estimable_fraction"] = (
        sum(len(f["P3_intercept_only_branches"]) for f in zero["folds"]) / (len(zero["folds"]) * len(BRANCHES)))
    output["p3_status"] = "NON_ESTIMABLE" if output["p3_non_estimable_fraction"] > 0.5 else "ESTIMATED"
    return output
