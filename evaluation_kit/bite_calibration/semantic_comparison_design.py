"""Frozen paired comparison M0 / MZ / MS / MZS for the semantic-verification pilot.

All four models are refit with identical leave-one-source-group-out folds on the
same pilot candidate rows, so baseline and treatment predictions come from a
compatible protocol. The frozen full-fit prior and the Phase 4C-1A out-of-fold
predictions are not used as the primary baseline. Fitting settings match the
earlier phases: L2 lambda 1, unpenalized intercept, Newton steps, fold-local
standardization and training-mean imputation with explicit missingness.
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from .action_utility_screen import candidate_utilities, grouped_utility_bootstrap
from .semantic_observation_schema import canonical_sha256

DESIGN_VERSION = "bite.semantic_paired_comparison_design.v1"
L2_PENALTY = 1.0
MAX_ITERATIONS = 100
CONVERGENCE_TOLERANCE = 1e-9
BOOTSTRAP_SEED = 467
BASELINE = "m0_initial_score"
MODEL_SPECS = {
    BASELINE: {"continuous": ["initial_score"], "binary": []},
    "mz_zoom": {
        "continuous": ["initial_score", "score_difference"],
        "binary": ["score_change_observed", "association_ambiguous", "association_no_alignment"],
    },
    "ms_semantic": {
        "continuous": ["initial_score"],
        "binary": ["semantic_compat_match", "semantic_nonsupport", "semantic_observation_unavailable"],
    },
    "mzs_zoom_semantic": {
        "continuous": ["initial_score", "score_difference"],
        "binary": ["score_change_observed", "association_ambiguous", "association_no_alignment",
                   "semantic_compat_match", "semantic_nonsupport", "semantic_observation_unavailable"],
    },
    "ms_semantic_localization_secondary": {
        "continuous": ["initial_score"],
        "binary": ["semantic_compat_match", "semantic_nonsupport", "semantic_observation_unavailable",
                   "semantic_region_localization_adequate"],
    },
}
COMPARISONS = (
    ("ms_semantic", BASELINE, "primary"),
    ("mz_zoom", BASELINE, "secondary"),
    ("mzs_zoom_semantic", "mz_zoom", "secondary_complementarity"),
    ("mzs_zoom_semantic", "ms_semantic", "secondary_complementarity"),
    ("ms_semantic_localization_secondary", "ms_semantic", "secondary_localization"),
)
VALIDITY_THRESHOLD = 0.9


def design_record():
    record = {
        "schema_version": DESIGN_VERSION,
        "status": "FROZEN_BEFORE_SEMANTIC_INFERENCE",
        "target": "original selected candidate annotation-proxy correctness H_tau, tau in {0.5, 0.75}",
        "primary_estimand": "D_semantic = Brier(ms_semantic) - Brier(m0_initial_score); negative favors semantic evidence",
        "models": MODEL_SPECS,
        "reference_semantic_categories": ["unclear", "taxonomic_overlap"],
        "comparisons": [{"model": m, "baseline": b, "role": r} for m, b, r in COMPARISONS],
        "fitting": {
            "folds": "leave-one-source-group-out over the pilot groups; identical for every model",
            "l2_lambda": L2_PENALTY,
            "intercept_penalized": False,
            "standardization": "fold-local mean/std of continuous features",
            "missing_continuous": "fold-local observed mean plus explicit observed/missing indicator",
            "non_estimable_rule": "a training fold lacking either class makes the endpoint NON_ESTIMABLE; folds are not altered",
            "frozen_full_fit_prior_used_as_oof_baseline": False,
            "phase04c1a_oof_m0_role": "secondary reference only",
        },
        "uncertainty": {
            "method": "paired percentile source-group bootstrap over fixed LOGO predictions",
            "seed": BOOTSTRAP_SEED,
            "replicates": 2000,
            "refit_inside_bootstrap": False,
        },
        "cost_accounting": {
            "semantic_logical_dispatches_per_candidate": 1,
            "zoom_logical_dispatches_per_candidate": 2,
            "record": ["logical dispatches", "VLM input/output tokens", "latency_ms"],
            "sam3_and_vlm_calls_treated_as_equal_resource_cost": False,
            "cross_action_comparison_requires_declared_normalization": True,
        },
        "pilot_decision_rule": {
            "PROCEED_TO_LARGER_FIT_COLLECTION": (
                f"valid-response rate >= {VALIDITY_THRESHOLD} and observed D_semantic < 0 at IoU 0.50 and 0.75"
            ),
            "REVISE_CONTRACT_AS_NEW_VERSION": f"valid-response rate < {VALIDITY_THRESHOLD}",
            "STOP_SEMANTIC_ACTION_FOR_TASK_V": "observed D_semantic >= 0 at both endpoints",
            "INCONCLUSIVE": "otherwise",
            "pilot_establishes_calibrated_model": False,
            "pilot_establishes_significance": False,
        },
        "prohibited": [
            "changing prompt, ontology or features after observing labels",
            "selecting groups or cases by labels or model performance",
            "using validation or internal-test data",
            "multiplying semantic and SAM 3 likelihoods as independent",
        ],
    }
    record["design_sha256"] = canonical_sha256(record)
    return record


def _value(row, name):
    value = row.get(name)
    if name == "semantic_observation_unavailable":
        return float(not row["semantic_observation_available"])
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def _fit_preprocessing(rows, spec):
    output = {}
    for name in spec["continuous"]:
        values = [_value(row, name) for row in rows]
        observed = [value for value in values if value is not None]
        if name == "initial_score" and len(observed) != len(rows):
            raise ValueError("Initial score must be complete")
        if not observed:
            raise ValueError(f"Training fold has no observed {name}")
        scale = float(np.std(observed))
        output[name] = {"mean": float(np.mean(observed)), "scale": scale if scale >= 1e-12 else 1.0}
    return output


def _design(rows, spec, preprocessing):
    matrix = []
    for row in rows:
        values = []
        for name in spec["continuous"]:
            raw = _value(row, name)
            if raw is None:
                raw = preprocessing[name]["mean"]
            values.append((raw - preprocessing[name]["mean"]) / preprocessing[name]["scale"])
        for name in spec["binary"]:
            raw = _value(row, name)
            if raw is None:
                raise ValueError(f"Binary feature {name} is missing")
            values.append(raw)
        matrix.append(values)
    raw = np.asarray(matrix, dtype=np.float64)
    return np.column_stack([np.ones(len(raw)), raw])


def fit_model(rows, model_name):
    if {int(row["label"]) for row in rows} != {0, 1}:
        raise ValueError("Training fold must contain both target classes")
    spec = MODEL_SPECS[model_name]
    preprocessing = _fit_preprocessing(rows, spec)
    design = _design(rows, spec, preprocessing)
    target = np.asarray([row["label"] for row in rows], dtype=np.float64)
    penalty = np.r_[0.0, np.full(design.shape[1] - 1, L2_PENALTY)]
    coefficient = np.zeros(design.shape[1])
    for iteration in range(1, MAX_ITERATIONS + 1):
        probability = 1 / (1 + np.exp(-np.clip(design @ coefficient, -35, 35)))
        gradient = design.T @ (probability - target) + penalty * coefficient
        hessian = design.T @ (design * (probability * (1 - probability))[:, None]) + np.diag(penalty)
        step = np.linalg.solve(hessian, gradient)
        coefficient -= step
        if float(np.max(np.abs(step))) < CONVERGENCE_TOLERANCE:
            return {"model_name": model_name, "preprocessing": preprocessing,
                    "coefficient": coefficient.tolist(), "iterations": iteration}
    raise ValueError("Logistic fit did not converge under frozen settings")


def predict_model(model, rows):
    design = _design(rows, MODEL_SPECS[model["model_name"]], model["preprocessing"])
    linear = np.clip(design @ np.asarray(model["coefficient"]), -35, 35)
    return (1 / (1 + np.exp(-linear))).tolist()


def logo_crossfit(rows, model_names=tuple(MODEL_SPECS)):
    """Leave-one-source-group-out predictions with identical folds for every model."""
    groups = sorted({row["source_group_id"] for row in rows})
    if len(groups) < 3:
        raise ValueError("LOGO cross-fitting requires at least three source groups")
    if len({row["state_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate candidate state in comparison rows")
    probabilities = defaultdict(dict)
    for group in groups:
        train = [row for row in rows if row["source_group_id"] != group]
        held = [row for row in rows if row["source_group_id"] == group]
        for name in model_names:
            model = fit_model(train, name)
            for row, probability in zip(held, predict_model(model, held), strict=True):
                probabilities[row["state_id"]][name] = probability
    return [{
        "state_id": row["state_id"],
        "source_group_id": row["source_group_id"],
        "query": row["query"],
        "label": int(row["label"]),
        "probabilities": dict(probabilities[row["state_id"]]),
    } for row in sorted(rows, key=lambda row: row["state_id"])]


def evaluate_comparisons(aligned, *, replicates=2000, seed=BOOTSTRAP_SEED):
    output = {}
    for model, baseline, role in COMPARISONS:
        if model not in aligned[0]["probabilities"] or baseline not in aligned[0]["probabilities"]:
            continue
        rows = candidate_utilities(aligned, baseline=baseline, treatment=model, action_cost=1)
        bootstrap = grouped_utility_bootstrap(rows, replicates=replicates, seed=seed)
        brier = bootstrap["gross_utility"]["brier_utility_gross"]["case_level"]
        output[f"{model}_minus_{baseline}"] = {
            "role": role,
            "brier_difference": -brier["observed"],
            "brier_difference_lower_2_5": -brier["upper_97_5"],
            "brier_difference_upper_97_5": -brier["lower_2_5"],
            "sign_convention": "model Brier minus baseline Brier; negative favors model",
            "decision_errors_avoided": sum(row["error_utility_gross"] > 0 for row in rows),
            "decision_errors_introduced": sum(row["error_utility_gross"] < 0 for row in rows),
            "source_group_count": bootstrap["source_group_count"],
        }
    return output


def classify_pilot(valid_rate, primary_by_endpoint):
    if valid_rate < VALIDITY_THRESHOLD:
        return "REVISE_CONTRACT_AS_NEW_VERSION"
    differences = [primary_by_endpoint[endpoint] for endpoint in ("0.5", "0.75")]
    if any(value is None for value in differences):
        return "INCONCLUSIVE"
    if all(value < 0 for value in differences):
        return "PROCEED_TO_LARGER_FIT_COLLECTION"
    if all(value >= 0 for value in differences):
        return "STOP_SEMANTIC_ACTION_FOR_TASK_V"
    return "INCONCLUSIVE"
