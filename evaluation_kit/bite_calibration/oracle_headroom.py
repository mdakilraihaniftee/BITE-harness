"""Stage A of Phase 4C-1G: hindsight oracle headroom over the tested branch set.

The per-case oracle selects branches after seeing correctness. It is an upper
bound on what any selector could achieve within the tested set; it is not a
policy. The "best fixed branch" is also chosen in hindsight, so it is a
descriptive comparator rather than a trained policy.

Input rows come from ``task_level_branch_runner.join_outcomes``:
``{"task_id", "source_group_id", "query", "official_count", "features",
"branches": {"B0": {"correct": 0|1, "valid": bool, ...}, ...}}``.
"""

from __future__ import annotations

import hashlib
import random
from collections import defaultdict

import numpy as np

from .action_utility_screen import ERROR_LAMBDA_GRID
from .task_level_probe_protocol import (
    BRANCHES,
    INCREMENTAL_LOGICAL_COST,
    SINGLE_ACTION_BRANCHES,
)

BOOTSTRAP_SEED = 467
BOOTSTRAP_REPLICATES = 2000
LAMBDA_GRID = ERROR_LAMBDA_GRID
COST_CONVENTION = ("incremental logical dispatches only; the shared initial SAM 3 call and the single "
                   "final-answer call are common to every branch and excluded from C_b")


def utility(row, branch, penalty=0.0):
    """U_{i,b}(lambda) = -L_{i,b} - lambda * C_b with exact-count 0/1 loss."""
    return -(1 - row["branches"][branch]["correct"]) - penalty * INCREMENTAL_LOGICAL_COST[branch]


def group_mean(rows, value, *, group_balanced=False):
    if not rows:
        raise ValueError("No rows")
    if not group_balanced:
        return sum(value(row) for row in rows) / len(rows)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["source_group_id"]].append(value(row))
    return sum(sum(v) / len(v) for v in grouped.values()) / len(grouped)


def accuracy(rows, branch, *, group_balanced=False):
    return group_mean(rows, lambda r: r["branches"][branch]["correct"], group_balanced=group_balanced)


def fixed_values(rows, penalty=0.0, branches=BRANCHES, *, group_balanced=False):
    return {b: group_mean(rows, lambda r, b=b: utility(r, b, penalty), group_balanced=group_balanced)
            for b in branches}


def best_fixed(rows, penalty=0.0, branches=BRANCHES, *, group_balanced=False):
    """Best branch in hindsight; ties go to the cheaper branch, then branch order."""
    values = fixed_values(rows, penalty, branches, group_balanced=group_balanced)
    best = max(values.values())
    tied = [b for b in branches if values[b] == best]
    choice = min(tied, key=lambda b: (INCREMENTAL_LOGICAL_COST[b], branches.index(b)))
    return choice, best, tied


def oracle_value(rows, penalty=0.0, branches=BRANCHES, *, group_balanced=False):
    return group_mean(rows, lambda r: max(utility(r, b, penalty) for b in branches), group_balanced=group_balanced)


def oracle_choice(row, penalty=0.0, branches=BRANCHES):
    """Hindsight choice for diagnostics only: max utility, ties to the cheaper branch."""
    values = {b: utility(row, b, penalty) for b in branches}
    best = max(values.values())
    return min((b for b in branches if values[b] == best), key=lambda b: (INCREMENTAL_LOGICAL_COST[b], branches.index(b)))


def headroom_statistics(rows, penalty=0.0, *, group_balanced=False):
    """Scalars used both for the observed summary and for every bootstrap replicate."""
    choice, fixed, _ = best_fixed(rows, penalty, group_balanced=group_balanced)
    oracle = oracle_value(rows, penalty, group_balanced=group_balanced)
    oracle_single = oracle_value(rows, penalty, SINGLE_ACTION_BRANCHES, group_balanced=group_balanced)
    return {
        "best_fixed_value": fixed,
        "oracle_value": oracle,
        "oracle_adaptivity_gap": oracle - fixed,
        "single_action_oracle_value": oracle_single,
        "combined_evidence_oracle_gap": oracle - oracle_single,
        "oracle_minus_stop_only": oracle - fixed_values(rows, penalty, ("B0",), group_balanced=group_balanced)["B0"],
        "best_fixed_branch": choice,
    }


def group_bootstrap(rows, statistics, *, replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED):
    """Paired percentile bootstrap over whole source groups.

    ``statistics`` maps names to ``fn(rows) -> float``. Every statistic is computed
    on the same resampled groups. A replicate whose statistic raises or returns
    None is counted as invalid for that statistic, never silently dropped.
    """
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["source_group_id"]].append(row)
    groups = sorted(grouped)
    if len(groups) < 2:
        raise ValueError("Group bootstrap requires at least two source groups")
    rng = random.Random(seed)
    samples = {name: [] for name in statistics}
    invalid = {name: 0 for name in statistics}
    hashes = []
    for replicate in range(replicates):
        selected = [rng.choice(groups) for _ in groups]
        if replicate < 10:
            hashes.append(hashlib.sha256("\n".join(selected).encode()).hexdigest())
        drawn = [{**row, "source_group_id": f"{i}:{g}"} for i, g in enumerate(selected) for row in grouped[g]]
        for name, fn in statistics.items():
            try:
                value = fn(drawn)
            except (ValueError, ZeroDivisionError):
                value = None
            if value is None or not np.isfinite(value):
                invalid[name] += 1
            else:
                samples[name].append(float(value))
    output = {}
    for name, fn in statistics.items():
        values = np.asarray(samples[name])
        observed = fn(rows)
        output[name] = {
            "observed": observed,
            "lower_2_5": float(np.quantile(values, .025)) if len(values) else None,
            "upper_97_5": float(np.quantile(values, .975)) if len(values) else None,
            "bootstrap_standard_error": float(np.std(values, ddof=1)) if len(values) > 1 else None,
            "replicate_fraction_strictly_positive": float(np.mean(values > 0)) if len(values) else None,
            "invalid_replicates": invalid[name],
        }
    return {
        "method": "paired percentile source-group bootstrap; rows never resampled independently",
        "seed": seed, "replicates": replicates, "source_group_count": len(groups),
        "candidate_rows_resampled_iid": False, "refit_inside_bootstrap": False,
        "first_ten_draw_sha256": hashes,
        "note": ("hindsight quantities (best fixed, oracle) are re-maximized inside each replicate; "
                 "intervals describe sampling variability of the plug-in statistic, not significance"),
        "statistics": output,
    }


def _case_ids(rows, predicate):
    return sorted(row["task_id"] for row in rows if predicate(row))


def oracle_contributors(rows, penalty=0.0):
    """Cases where the oracle beats the hindsight best fixed branch, and where B3 is uniquely needed."""
    choice, _, _ = best_fixed(rows, penalty)
    improving = [row for row in rows
                 if max(utility(row, b, penalty) for b in BRANCHES) > utility(row, choice, penalty)]
    b3_unique = [row for row in rows
                 if max(utility(row, b, penalty) for b in BRANCHES)
                 > max(utility(row, b, penalty) for b in SINGLE_ACTION_BRANCHES)]

    def describe(subset):
        groups = defaultdict(int)
        queries = defaultdict(int)
        for row in subset:
            groups[row["source_group_id"]] += 1
            queries[row["query"]] += 1
        return {"case_count": len(subset), "task_ids": sorted(row["task_id"] for row in subset),
                "source_group_count": len(groups), "cases_per_group": dict(sorted(groups.items())),
                "cases_per_query": dict(sorted(queries.items())),
                "zero_count_cases": sum(row["official_count"] == 0 for row in subset)}

    return {"best_fixed_branch": choice, "oracle_improves_over_best_fixed": describe(improving),
            "b3_uniquely_needed_by_oracle": describe(b3_unique)}


def leave_one_group_out(rows, penalty=0.0):
    groups = sorted({row["source_group_id"] for row in rows})
    full = headroom_statistics(rows, penalty)
    entries = []
    for group in groups:
        kept = [row for row in rows if row["source_group_id"] != group]
        stats = headroom_statistics(kept, penalty)
        entries.append({"dropped_source_group_id": group, "remaining_cases": len(kept),
                        **{k: v for k, v in stats.items()}})
    summary = {}
    for name in ("oracle_adaptivity_gap", "combined_evidence_oracle_gap"):
        values = [entry[name] for entry in entries]
        summary[name] = {"full": full[name], "minimum": min(values), "maximum": max(values),
                         "largest_single_group_drop": full[name] - min(values)}
    summary["best_fixed_branch_changes"] = sorted({e["best_fixed_branch"] for e in entries} - {full["best_fixed_branch"]})
    return {"per_group": entries, "summary": summary}


def strata(rows):
    """Branch accuracy and oracle gap by count stratum and by query class."""
    def block(subset):
        if not subset:
            return {"case_count": 0}
        stats = headroom_statistics(subset)
        return {"case_count": len(subset), "source_group_count": len({r["source_group_id"] for r in subset}),
                "accuracy": {b: accuracy(subset, b) for b in BRANCHES},
                "correct_counts": {b: sum(r["branches"][b]["correct"] for r in subset) for b in BRANCHES},
                **{k: stats[k] for k in ("best_fixed_branch", "oracle_value", "oracle_adaptivity_gap",
                                         "combined_evidence_oracle_gap")}}

    output = {"count_zero": block([r for r in rows if r["official_count"] == 0]),
              "count_positive": block([r for r in rows if r["official_count"] > 0]),
              "by_query": {q: block([r for r in rows if r["query"] == q]) for q in sorted({r["query"] for r in rows})}}
    return output


def oracle_headroom(rows, *, replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED):
    """Full Stage A record."""
    n = len(rows)
    branch_table = {}
    for b in BRANCHES:
        correct = sum(r["branches"][b]["correct"] for r in rows)
        branch_table[b] = {
            "evaluated_cases": n, "correct": correct, "accuracy": correct / n,
            "group_balanced_accuracy": accuracy(rows, b, group_balanced=True),
            "invalid_answers": sum(not r["branches"][b]["valid"] for r in rows),
            "presence_accuracy": sum(r["branches"][b]["presence_correct"] for r in rows) / n,
            "incremental_logical_cost_per_case": INCREMENTAL_LOGICAL_COST[b],
        }
    by_penalty = {}
    for penalty in LAMBDA_GRID:
        stats = headroom_statistics(rows, penalty)
        by_penalty[str(penalty)] = {
            **stats,
            "fixed_branch_values": fixed_values(rows, penalty),
            "group_balanced": {k: v for k, v in headroom_statistics(rows, penalty, group_balanced=True).items()},
        }
    zero = by_penalty["0.0"]
    statistics = {f"accuracy_{b}_minus_B0": (lambda rs, b=b: accuracy(rs, b) - accuracy(rs, "B0"))
                  for b in BRANCHES if b != "B0"}
    for penalty in LAMBDA_GRID:
        statistics[f"oracle_adaptivity_gap@{penalty}"] = (
            lambda rs, p=penalty: headroom_statistics(rs, p)["oracle_adaptivity_gap"])
        statistics[f"combined_evidence_oracle_gap@{penalty}"] = (
            lambda rs, p=penalty: headroom_statistics(rs, p)["combined_evidence_oracle_gap"])
    statistics["oracle_adaptivity_gap_group_balanced@0.0"] = (
        lambda rs: headroom_statistics(rs, 0.0, group_balanced=True)["oracle_adaptivity_gap"])
    return {
        "schema_version": "bite.phase04c1g_oracle_headroom.v1",
        "oracle_is_deployable": False,
        "best_fixed_is_trained_policy": False,
        "cost_convention": COST_CONVENTION,
        "case_count": n,
        "source_group_count": len({r["source_group_id"] for r in rows}),
        "branches": branch_table,
        "zero_cost": {
            "best_fixed_branch": zero["best_fixed_branch"],
            "best_fixed_accuracy": 1 + zero["best_fixed_value"],
            "oracle_accuracy": 1 + zero["oracle_value"],
            "oracle_adaptivity_gap": zero["oracle_adaptivity_gap"],
            "oracle_adaptivity_gap_cases": round(zero["oracle_adaptivity_gap"] * n),
            "single_action_oracle_accuracy": 1 + zero["single_action_oracle_value"],
            "combined_evidence_oracle_gap": zero["combined_evidence_oracle_gap"],
            "combined_evidence_oracle_gap_cases": round(zero["combined_evidence_oracle_gap"] * n),
        },
        "by_penalty": by_penalty,
        "contributors": oracle_contributors(rows),
        "leave_one_group_out": leave_one_group_out(rows),
        "strata": strata(rows),
        "bootstrap": group_bootstrap(rows, statistics, replicates=replicates, seed=seed),
    }
