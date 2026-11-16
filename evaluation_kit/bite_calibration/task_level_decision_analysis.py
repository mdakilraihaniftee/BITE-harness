"""Decision transitions, combined-evidence diagnostics, measured costs and the
predeclared go/no-go screen for Phase 4C-1G.

B3 combines two observations that are both anchored to the original candidate.
Neither action enables the other, so B3 is a *combined-evidence* condition. It
is not a test of sequential enabling dependencies or of non-myopic planning, and
nothing here computes or claims an interaction or synergy value.
"""

from __future__ import annotations

import statistics as stats
from collections import Counter

from .task_level_probe_protocol import BRANCHES, INCREMENTAL_LOGICAL_COST

ORACLE_HEADROOM_MINIMUM = 0.05
RECOVERY_SUFFICIENT = 0.5
RECOVERY_MINIMUM_LEARNABLE = 0.1
RESIDUAL_MINIMUM = 0.05
MINIMUM_VALID_RATE = 0.8
ZERO_COUNT_DOMINANCE = 0.8
DECISION_RULE = {
    "schema_version": "bite.phase04c1g_decision_rule.v1",
    "status": "screening heuristics fixed before any final-answer data; not significance thresholds",
    "E_EXPERIMENT_INSUFFICIENT_OR_INVALID": (
        "execution not authorized/complete, branch tables incomplete, or any branch valid-answer rate < "
        f"{MINIMUM_VALID_RATE}"),
    "A_LOW_OBSERVED_ORACLE_HEADROOM": f"zero-cost oracle adaptivity gap < {ORACLE_HEADROOM_MINIMUM}",
    "C_SIMPLE_POLICY_SUFFICIENT": (
        f"some simple LOGO selector (P1, P2 or P3) recovers >= {RECOVERY_SUFFICIENT} of the hindsight headroom"),
    "B_ORACLE_HEADROOM_NOT_LEARNABLE": (
        f"no selector recovers >= {RECOVERY_MINIMUM_LEARNABLE}, or the best selector's gain over P1 has a "
        "bootstrap lower bound <= 0, or its LOGO influence changes sign, or it vanishes at lambda=0.01"),
    "D_PROMISING_PREDICTABLE_HEADROOM": (
        f"a selector recovers between {RECOVERY_MINIMUM_LEARNABLE} and {RECOVERY_SUFFICIENT}, its gain over P1 "
        "has a bootstrap lower bound > 0, there are no LOGO sign changes, it survives lambda=0.01, and the "
        f"residual oracle gap is >= {RESIDUAL_MINIMUM}"),
    "qualifiers_always_reported": [
        f"zero-count dominance (>= {ZERO_COUNT_DOMINANCE} of oracle-improving cases have official count 0)",
        "presentation-length confound not separable (no length-matched control branch)",
        "15 groups; development-only; hindsight selection of the best fixed branch",
    ],
}


def _correct(row, branch):
    return bool(row["branches"][branch]["correct"])


def transitions(rows):
    output = {"relative_to_B0": {}}
    for branch in BRANCHES[1:]:
        table = Counter()
        for row in rows:
            table[(_correct(row, "B0"), _correct(row, branch))] += 1
        output["relative_to_B0"][branch] = {
            "correct_to_correct": table[(True, True)], "correct_to_incorrect": table[(True, False)],
            "incorrect_to_correct": table[(False, True)], "incorrect_to_incorrect": table[(False, False)],
            "net_rescued": table[(False, True)] - table[(True, False)],
            "invalid_answers_in_branch": sum(not row["branches"][branch]["valid"] for row in rows),
        }
    extra = BRANCHES[1:]
    unique = {b: sorted(r["task_id"] for r in rows if _correct(r, b)
                        and not any(_correct(r, o) for o in BRANCHES if o != b)) for b in BRANCHES}
    output["cross_branch"] = {
        "uniquely_correct_branch_counts": {b: len(v) for b, v in unique.items()},
        "uniquely_correct_task_ids": unique,
        "rescued_by_B1_only_among_extra": sum(not _correct(r, "B0") and _correct(r, "B1")
                                              and not _correct(r, "B2") and not _correct(r, "B3") for r in rows),
        "rescued_by_B2_only_among_extra": sum(not _correct(r, "B0") and _correct(r, "B2")
                                              and not _correct(r, "B1") and not _correct(r, "B3") for r in rows),
        "B3_only_success": len(unique["B3"]),
        "B3_failure_when_B1_or_B2_correct": sum(not _correct(r, "B3") and (_correct(r, "B1") or _correct(r, "B2"))
                                                for r in rows),
        "all_branches_fail": sum(not any(_correct(r, b) for b in BRANCHES) for r in rows),
        "all_branches_correct": sum(all(_correct(r, b) for b in BRANCHES) for r in rows),
        "B0_correct_and_every_extra_branch_correct": sum(_correct(r, "B0") and all(_correct(r, b) for b in extra)
                                                         for r in rows),
        "B0_correct_but_some_extra_branch_incorrect": sum(_correct(r, "B0") and not all(_correct(r, b) for b in extra)
                                                          for r in rows),
        "invalid_or_unparsed_answers": {b: sum(not r["branches"][b]["valid"] for r in rows) for b in BRANCHES},
        "abstentions": "not offered by the protocol",
    }
    return output


def combined_evidence(rows):
    """Six per-case questions answered programmatically (no interaction value)."""
    per_case = []
    for row in rows:
        b1, b2, b3 = (_correct(row, b) for b in ("B1", "B2", "B3"))
        per_case.append({
            "task_id": row["task_id"], "source_group_id": row["source_group_id"], "query": row["query"],
            "official_count_zero": row["official_count"] == 0,
            "B1_success": b1, "B2_success": b2, "B3_success": b3,
            "B3_only_successful_branch": b3 and not any(_correct(row, b) for b in ("B0", "B1", "B2")),
            "B3_success_not_worth_extra_cost": b3 and (_correct(row, "B0") or b1 or b2),
            "B3_breaks_single_evidence_success": (not b3) and (b1 or b2),
        })
    count = Counter()
    for case in per_case:
        for key, value in case.items():
            if isinstance(value, bool) and value:
                count[key] += 1
    return {"schema_version": "bite.phase04c1g_combined_evidence.v1",
            "interpretation": "combined-evidence condition; not a sequential-dependency or synergy test",
            "counts": dict(sorted(count.items())), "per_case": per_case}


def _summary(values):
    values = [v for v in values if v is not None]
    if not values:
        return {"count": 0}
    return {"count": len(values), "median": stats.median(values), "mean": sum(values) / len(values),
            "total": sum(values), "maximum": max(values)}


def measured_costs(outcome_rows, manifest, semantic_observations=None):
    """Logical, latency and token costs reported separately (never summed across units)."""
    zoom = {t["task_id"]: (t["zoom"]["crop"]["latency_ms"] or 0) + (t["zoom"]["focused"]["latency_ms"] or 0)
            for t in manifest["tasks"]}
    semantic = {}
    if semantic_observations:
        for task in manifest["tasks"]:
            observation = semantic_observations[task["semantic_case_id"]]
            semantic[task["task_id"]] = observation["execution"]
    output = {"schema_version": "bite.phase04c1g_costs.v1",
              "logical_incremental_dispatches_per_case": dict(INCREMENTAL_LOGICAL_COST), "final_answer": {}}
    for branch in BRANCHES:
        rows = [r for r in outcome_rows if r["branch"] == branch]
        output["final_answer"][branch] = {
            "latency_ms": _summary([r["latency_ms"] for r in rows]),
            "prompt_tokens": _summary([r["prompt_tokens"] for r in rows]),
            "completion_tokens": _summary([r["completion_tokens"] for r in rows]),
            "evidence_characters": _summary([r["evidence_characters"] for r in rows]),
            "images_per_request": _summary([r["image_count"] for r in rows]),
        }
    output["recorded_zoom_tool_latency_ms_4b2b3"] = _summary(list(zoom.values()))
    if semantic:
        output["semantic_action_latency_ms"] = _summary([e["latency_ms"] for e in semantic.values()])
        output["semantic_action_tokens"] = {
            key: _summary([(e.get("token_usage") or {}).get(key) for e in semantic.values()])
            for key in ("prompt_tokens", "completion_tokens")}
    output["comparability"] = ("logical dispatches, wall-clock latency, tokens and GPU time are different units; "
                               "Zoom latencies were recorded in 4B-2B-3 on a different service and date; no "
                               "monetary cost or GPU-seconds were measured")
    return output


def valid_rates(rows):
    return {b: sum(r["branches"][b]["valid"] for r in rows) / len(rows) for b in BRANCHES}


def classify(oracle, learnable, rows, *, executed=True):
    """Apply the predeclared screen; returns the outcome and every check used."""
    checks = {"executed": executed}
    if not executed or not rows:
        return {"outcome": "EXPERIMENT_INSUFFICIENT_OR_INVALID", "checks": checks, "rule": DECISION_RULE}
    rates = valid_rates(rows)
    checks["valid_rates"] = rates
    improving = oracle["contributors"]["oracle_improves_over_best_fixed"]
    checks["zero_count_dominated"] = (improving["case_count"] > 0 and
                                      improving["zero_count_cases"] / improving["case_count"] >= ZERO_COUNT_DOMINANCE)
    if min(rates.values()) < MINIMUM_VALID_RATE:
        return {"outcome": "EXPERIMENT_INSUFFICIENT_OR_INVALID", "checks": checks, "rule": DECISION_RULE}
    gap = oracle["zero_cost"]["oracle_adaptivity_gap"]
    checks["oracle_adaptivity_gap"] = gap
    if gap < ORACLE_HEADROOM_MINIMUM:
        return {"outcome": "LOW_OBSERVED_ORACLE_HEADROOM", "checks": checks, "rule": DECISION_RULE}
    zero = learnable["by_penalty"]["0.0"]
    fractions = {p: v["recovery_fraction"]["value"] for p, v in zero["policies"].items() if p != "P0_stop_only"}
    checks["recovery_fractions"] = fractions
    defined = {p: f for p, f in fractions.items() if f is not None}
    if defined and max(defined.values()) >= RECOVERY_SUFFICIENT:
        checks["sufficient_policy"] = max(defined, key=defined.get)
        return {"outcome": "SIMPLE_POLICY_SUFFICIENT", "checks": checks, "rule": DECISION_RULE}
    learned = {p: defined.get(p) for p in ("P2_score_threshold", "P3_action_value")}
    candidates = [p for p, f in learned.items() if f is not None and f >= RECOVERY_MINIMUM_LEARNABLE]
    promising = []
    for policy in candidates:
        lower = zero["bootstrap"]["statistics"][f"{policy}_minus_P1"]["lower_2_5"]
        influence = zero["leave_one_group_out_influence"][policy]
        at_high = learnable["by_penalty"]["0.01"]["policies"][policy]["minus_P1"]
        residual = zero["hindsight_oracle_utility"] - zero["policies"][policy]["utility"]
        detail = {"policy": policy, "bootstrap_lower_minus_P1": lower, "loo_sign_changes": influence["sign_changes"],
                  "minus_P1_at_lambda_0.01": at_high, "residual_oracle_gap": residual}
        checks.setdefault("learnability_details", []).append(detail)
        if (lower is not None and lower > 0 and influence["sign_changes"] == 0 and at_high > 0
                and residual >= RESIDUAL_MINIMUM):
            promising.append(policy)
    if promising:
        checks["presentation_length_confound_separable"] = False
        return {"outcome": "PROMISING_PREDICTABLE_HEADROOM", "checks": checks, "rule": DECISION_RULE}
    return {"outcome": "ORACLE_HEADROOM_NOT_LEARNABLE", "checks": checks, "rule": DECISION_RULE}
