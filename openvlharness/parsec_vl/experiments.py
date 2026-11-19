"""Experiment drivers (called by ``scripts/parsec.py``; small versions run in tests).

Labels used in every result: SYNTHETIC (declared outcome/duration models, real
scheduler and real wall clock), FIXTURE (real agent loop and capabilities with a
scripted model and local transports), REAL (live services). Nothing here
touches ground-truth labels: the plan fixture's answer is only in its reference
file, which no experiment reads.
"""

from __future__ import annotations

import math
import random
import statistics
import time
from pathlib import Path
from typing import Any

from .controller import PlanExecutor, PlanningConfig, SyntheticRuntime
from .montecarlo import OutcomeModel, PlanEvaluator, finalize_spec
from .plans import ActionPlan, Branch, PlanAction
from .resources import BudgetAdapter
from .scheduler import Scheduler


def _mean_sd(values: list[float]) -> tuple[float, float]:
    return (statistics.fmean(values), statistics.stdev(values) if len(values) > 1 else 0.0)


# ---- Experiment 1: multicore Monte Carlo --------------------------------------------------------


def benchmark_spec() -> dict:
    """A fixed visual-reasoning plan: OCR on the original, two alternatives (crop OCR; depth-guided crop OCR)."""
    actions = {
        "ocr": ("ocr", (), ("lognormal", 0.23, 0.3), 0.35),
        "g": ("gpu", (), ("lognormal", 0.93, 0.3), 0.9), "z": ("cpu", ("g",), ("lognormal", 0.064, 0.3), 1.0),
        "o2": ("ocr", ("z",), ("lognormal", 0.23, 0.3), 0.85),
        "d": ("depth", (), ("lognormal", 0.34, 0.3), 0.95), "g3": ("gpu", ("d",), ("lognormal", 0.93, 0.3), 0.8),
        "z3": ("cpu", ("g3",), ("lognormal", 0.064, 0.3), 1.0), "o3": ("ocr", ("z3",), ("lognormal", 0.23, 0.3), 0.85),
    }
    return finalize_spec({
        "workers": 4, "budget": 12, "capacities": {"ocr": 1, "gpu": 1, "depth": 1, "cpu": 4},
        "actions": {k: {"pool": p, "deps": d, "duration": m, "p_ok": q} for k, (p, d, m, q) in actions.items()},
        "branches": [{"actions": ["ocr"], "goal": "ocr"}, {"actions": ["g", "z", "o2"], "goal": "o2"},
                     {"actions": ["d", "g3", "z3", "o3"], "goal": "o3"}]})


def benchmark_candidates() -> list[tuple[dict, tuple[int, ...]]]:
    spec = benchmark_spec()
    reordered = {**spec, "branches": [spec["branches"][1], spec["branches"][0], spec["branches"][2]]}
    reordered = finalize_spec({k: v for k, v in reordered.items() if k not in ("order", "children", "branch_of")})
    return [(spec, ()), (spec, (1,)), (spec, (2,)), (spec, (1, 2)), (reordered, ()), (reordered, (1,))]


def multicore(processes: list[int], rollouts: int, trials: int, batch_size: int = 500, seed: int = 654) -> dict[str, Any]:
    candidates = benchmark_candidates()
    rows, reference, raw_trials = [], None, []
    for p in [0, *processes]:
        walls, cpus, cold = [], [], None
        for trial in range(trials):
            trial_started = time.perf_counter()
            evaluator = PlanEvaluator(processes=p, batch_size=batch_size)
            cold_start = 0.0
            if p:
                began = time.perf_counter()
                evaluator.start()
                cold_start = time.perf_counter() - began
                cold = cold_start if cold is None else cold
            result = evaluator.evaluate(candidates, rollouts, seed)
            evaluator.shutdown()
            estimates = [e.to_dict() for e in result.estimates]
            if reference is None:
                reference = estimates
            identical = estimates == reference
            walls.append(result.wall_seconds)
            cpus.append(result.cpu_seconds)
            raw_trials.append({"processes": p, "trial": trial, "seed": seed,
                               "rollouts_per_candidate": rollouts, "wall_seconds": result.wall_seconds,
                               "cpu_seconds": result.cpu_seconds, "cold_start_seconds": cold_start,
                               "total_wall_seconds": time.perf_counter() - trial_started,
                               "worker_pids": result.worker_pids, "complete": result.complete,
                               "batches": result.batches, "batches_done": result.batches_done,
                               "timing": result.timing, "estimates": estimates})
            if not identical:
                raise AssertionError(f"estimates differ with {p} processes")
        mean, sd = _mean_sd(walls)
        rows.append({"processes": p, "mode": "in-process sequential" if p == 0 else "process pool (warm)",
                     "rollouts_total": rollouts * len(candidates), "trials": trials, "wall_mean": mean, "wall_sd": sd,
                     "cpu_seconds_mean": statistics.fmean(cpus), "cold_start_seconds": cold,
                     "cpu_utilization": statistics.fmean(cpus) / (mean * max(1, p)), "identical_estimates": True})
    base_inproc = rows[0]["wall_mean"]
    base_p1 = next((r["wall_mean"] for r in rows if r["processes"] == 1), None)
    for row in rows:
        row["speedup_vs_in_process"] = base_inproc / row["wall_mean"]
        row["speedup_vs_1_process"] = (base_p1 / row["wall_mean"]) if base_p1 else None
        row["efficiency"] = (row["speedup_vs_1_process"] / row["processes"]) if row["processes"] and base_p1 else None
        if row["processes"]:
            row["overhead_seconds"] = row["wall_mean"] - row["cpu_seconds_mean"] / row["processes"]
    best = min(range(len(candidates)), key=lambda i: reference[i]["latency_mean"] + 0.25 * reference[i]["cost_mean"])
    return {"label": "SYNTHETIC (CPU-bound Monte Carlo over a declared plan model)", "candidates": len(candidates),
            "rollouts_per_candidate": rollouts, "batch_size": batch_size, "estimates": reference,
            "selected_candidate": best, "seed": seed, "rows": rows, "raw_trials": raw_trials}


def _random_problem(rng: random.Random) -> list[tuple[dict, tuple[int, ...]]]:
    medians = {"ocr": 0.23, "gpu": 0.93, "depth": 0.34, "cpu": 0.064}
    actions, branches = {}, []
    for b in range(3):
        length = 1 if b == 0 else rng.randint(2, 3)
        ids = []
        for k in range(length):
            pool = rng.choice(["ocr", "gpu", "depth", "cpu"]) if k < length - 1 else "ocr"
            aid = f"b{b}a{k}"
            actions[aid] = {"pool": pool, "deps": (ids[-1],) if ids else (),
                            "duration": ("lognormal", medians[pool] * rng.uniform(0.5, 2.0), 0.4),
                            "p_ok": rng.uniform(0.15, 0.95) if k == length - 1 else rng.uniform(0.8, 1.0)}
            ids.append(aid)
        branches.append({"actions": ids, "goal": ids[-1]})
    base = {"workers": rng.choice([2, 4]), "budget": None, "capacities": {"ocr": 1, "gpu": 1, "depth": 1, "cpu": 4},
            "actions": actions}
    candidates = []
    for lead in range(3):
        order = [branches[lead]] + [branches[i] for i in range(3) if i != lead]
        spec = finalize_spec({**base, "branches": order})
        candidates += [(spec, ()), (spec, (1,))]
    return candidates


def _heuristic_score(spec: dict, option: tuple[int, ...], weight: float) -> float:
    """Declared closed-form heuristic: medians, independence, no contention."""
    def chain(branch):
        total, p = 0.0, 1.0
        for aid in branch["actions"]:
            model = spec["actions"][aid]["duration"]
            total += model[1] if model[0] in ("lognormal", "fixed") else statistics.median(model[1])
            p *= spec["actions"][aid]["p_ok"]
        return total, p
    reach, latency, cost = 1.0, 0.0, 0.0
    for index, branch in enumerate(spec["branches"]):
        duration, p = chain(branch)
        speculative = index in option
        latency += reach * (duration if not speculative else max(0.0, duration - latency))
        cost += (1.0 if speculative else reach) * len(branch["actions"])
        reach *= 1 - p
    return latency + weight * cost


def decision_quality(instances: int, budgets: list[float], parallel: int, reference_rollouts: int, seed: int = 99,
                     weight: float = 0.25) -> dict[str, Any]:
    """Same planning time budget: heuristic vs sequential Monte Carlo vs parallel Monte Carlo."""
    rng = random.Random(seed)
    problems = [_random_problem(rng) for _ in range(instances)]
    score = lambda e: e.latency_mean + weight * e.cost_mean  # noqa: E731
    with PlanEvaluator(processes=max(parallel, 8), batch_size=1000) as reference_pool:
        truth = [[score(e) for e in reference_pool.evaluate(c, reference_rollouts, seed + 1).estimates] for c in problems]
    pool = PlanEvaluator(processes=parallel, batch_size=50)
    pool.start()
    sequential = PlanEvaluator(processes=0, batch_size=50)
    rows = []
    from .controller import PlanningConfig as _Config, choose_planning_backend

    for budget in budgets:
        methods = [("sequential MC", sequential), (f"parallel MC ({parallel} processes)", pool), ("overhead-aware gate", None)]
        for name, evaluator in methods:
            regrets, hits, done, spent, backends = [], 0, [], [], {}
            for problem, true in zip(problems, truth):
                began = time.perf_counter()
                chosen = evaluator
                if evaluator is None:  # the Phase 3 gate picks heuristic / sequential / pool per decision
                    config = _Config.for_mode("e5", rollouts=10**6, planning_time_budget=budget,
                                              planning_processes=parallel, cost_weight=weight)
                    backend, _ = choose_planning_backend(problem, config, pool)
                    backends[backend] = backends.get(backend, 0) + 1
                    chosen = {"heuristic": None, "sequential": sequential, "parallel": pool}[backend]
                rollouts_done = 0
                if chosen is not None:
                    result = chosen.evaluate(problem, 1_000_000, seed + 2, time_budget=budget)
                    rollouts_done = result.estimates[0].rollouts
                if not rollouts_done:
                    choice = min(range(len(problem)), key=lambda i: _heuristic_score(*problem[i], weight))
                else:
                    choice = min(range(len(problem)), key=lambda i: score(result.estimates[i]))
                spent.append(time.perf_counter() - began)
                done.append(rollouts_done)
                regrets.append(true[choice] - min(true))
                hits += true[choice] == min(true)
            rows.append({"method": name, "time_budget_s": budget, "instances": instances,
                         "rollouts_per_candidate_mean": statistics.fmean(done), "best_choice_rate": hits / instances,
                         "regret_mean": statistics.fmean(regrets), "regret_max": max(regrets),
                         "planning_seconds_mean": statistics.fmean(spent), "backends": backends or None})
    heuristic_regrets, hits, spent = [], 0, []
    for problem, true in zip(problems, truth):
        began = time.perf_counter()
        choice = min(range(len(problem)), key=lambda i: _heuristic_score(*problem[i], weight))
        spent.append(time.perf_counter() - began)
        heuristic_regrets.append(true[choice] - min(true))
        hits += true[choice] == min(true)
    rows.insert(0, {"method": "closed-form heuristic", "time_budget_s": 0.0, "instances": instances,
                    "rollouts_per_candidate_mean": 0, "best_choice_rate": hits / instances,
                    "regret_mean": statistics.fmean(heuristic_regrets), "regret_max": max(heuristic_regrets),
                    "planning_seconds_mean": statistics.fmean(spent), "backends": None})
    pool.shutdown()
    return {"label": "SYNTHETIC (random declared plan problems; reference = "
                     f"{reference_rollouts} rollouts per candidate)", "score": f"latency + {weight} x tool calls",
            "rows": rows}


# ---- Experiment 3: speculation scenarios --------------------------------------------------------

POOLS = {"OCR_Tool": "ocr", "Visual_Grounding_Tool": "gpu", "Zoom_In_Tool": "cpu", "Depth_Estimation_Tool": "gpu"}


def _branch(pid, name, steps, origin="fixture"):
    actions, prev = [], None
    for aid, tool in steps:
        actions.append(PlanAction(aid, tool, {}, (prev,) if prev else (), "text" if tool == "OCR_Tool" else None))
        prev = aid
    return Branch(f"{pid}.{name}", name, actions, actions[-1].action_id, origin)


SCENARIOS: dict[str, dict[str, Any]] = {
    # name: primary success prob (true), believed by the planner, alternatives, durations, budget, extra necessary work
    "A_speculation_helps": {"p_primary": 0.2, "believed": 0.2, "alts": 1, "primary_s": 0.12, "budget": 20,
                            "about": "the primary OCR is usually unreadable; the crop path is usually needed"},
    "B_speculation_wastes": {"p_primary": 0.9, "believed": 0.9, "alts": 1, "primary_s": 0.12, "budget": 20,
                             "about": "the primary usually succeeds; alternatives are rarely needed"},
    "C_limited_resources": {"p_primary": 0.5, "believed": 0.5, "alts": 1, "primary_s": 0.12, "budget": 20,
                            "necessary_gpu": True,
                            "about": "the primary path also needs the capacity-1 GPU after a short CPU step"},
    "D_wrong_estimates": {"p_primary": 0.9, "believed": 0.1, "alts": 1, "primary_s": 0.12, "budget": 20,
                          "about": "the planner believes the primary fails 90% of the time; it usually succeeds"},
    "E_small_budget": {"p_primary": 0.3, "believed": 0.3, "alts": 2, "primary_s": 0.12, "budget": 4, "alt_ok": 0.5,
                       "about": "budget 4: primary (1) + one alternative (3); two alternatives cannot both be afforded"},
}
DURATIONS = {"OCR_Tool": 0.1, "Visual_Grounding_Tool": 0.2, "Zoom_In_Tool": 0.04, "Depth_Estimation_Tool": 0.15}


def _scenario_plan(name: str, conf: dict, trial: int) -> ActionPlan:
    pid = f"{name}.t{trial}"
    if conf.get("necessary_gpu"):
        primary = _branch(pid, "primary", [("p_prep", "Zoom_In_Tool"), ("p_gpu", "Depth_Estimation_Tool"), ("p_ocr", "OCR_Tool")])
    else:
        primary = _branch(pid, "primary", [("p_ocr", "OCR_Tool")])
    branches = [primary]
    for k in range(1, conf["alts"] + 1):
        branches.append(_branch(pid, f"alt{k}", [(f"a{k}_g", "Visual_Grounding_Tool"), (f"a{k}_z", "Zoom_In_Tool"),
                                                 (f"a{k}_o", "OCR_Tool")]))
    return ActionPlan(pid, "agent", "fixture", branches)


def _scenario_outcomes(conf: dict, plan: ActionPlan, rng: random.Random) -> dict[str, tuple[float, bool]]:
    outcomes = {}
    for branch in plan.branches:
        for action in branch.actions:
            seconds = DURATIONS[action.tool] * math.exp(0.25 * rng.gauss(0, 1))
            if action.action_id == branch.goal:
                p = conf["p_primary"] if branch.name == "primary" else conf.get("alt_ok", 0.9)
            else:
                p = 1.0
            outcomes[action.action_id] = (seconds, rng.random() < p)
    return outcomes


def speculation(trials: int, policies: list[tuple[str, dict]], processes: int = 4, seed: int = 7,
                scenarios: list[str] | None = None, budgets: list[int] | None = None,
                capacities: dict[str, int] | None = None) -> dict[str, Any]:
    """Each scenario × policy, with the same per-trial outcomes for every policy (common random numbers)."""
    evaluator = PlanEvaluator(processes=processes, batch_size=100)
    evaluator.start()
    caps = {"ocr": 1, "gpu": 1, "cpu": 4, **(capacities or {})}
    rows, raw_trials = [], []
    cases = [(name, dict(SCENARIOS[name])) for name in scenarios or list(SCENARIOS)]
    if budgets:
        cases = [(name, {**conf, "budget": b}) for name, conf in cases for b in budgets]
    for name, conf in cases:
        believed = OutcomeModel(durations={t: ("lognormal", s, 0.25) for t, s in DURATIONS.items()},
                                p_ok={"OCR_Tool": conf["believed"], "Visual_Grounding_Tool": 1.0, "Zoom_In_Tool": 1.0,
                                      "Depth_Estimation_Tool": 1.0}, source="declared")
        draws = [random.Random(seed * 7919 + trial) for trial in range(trials)]
        draw_sets = [_scenario_outcomes(conf, _scenario_plan(name, conf, t), draws[t]) for t in range(trials)]
        for label, overrides in policies:
            latency, cost, wasted_calls, wasted_s, done, queue_wait, planning, denied, spec_calls = [], [], [], [], 0, [], [], [], []
            for trial in range(trials):
                plan = _scenario_plan(name, conf, trial)
                ledger = BudgetAdapter.with_limit(conf["budget"])
                mode = overrides.get("mode", "e3")
                capacities = dict(caps)
                selective = mode == "e5"  # same protections the orchestrator applies for E5
                scheduler = Scheduler(policy="e2", workers=4, capacities=capacities, budget=ledger,
                                      speculative_limits={p: max(1, c - 1) for p, c in capacities.items()} if selective else None,
                                      necessary_slot_reserve=1 if selective else 0)
                config = PlanningConfig.for_mode(mode, plan_selection=False, rollouts=overrides.get("rollouts", 300),
                                                 planning_time_budget=0.25,
                                                 max_speculative_branches=overrides.get("k", 1),
                                                 speculative_budget_limit=overrides.get("spec_limit", 6))
                executor = PlanExecutor(scheduler, SyntheticRuntime(draw_sets[trial], POOLS, believed), config,
                                        agent_id="agent", model=believed, budget=ledger.manager,
                                        evaluator=evaluator if mode == "e5" else None)
                report = executor.execute(plan)
                settled = executor.settle()
                records = scheduler.records()
                scheduler.shutdown()
                latency.append(report["decision_latency_s"])
                cost.append(ledger.snapshot()["ledger"]["global"]["tool_calls"]["used"])
                wasted_calls.append(settled["wasted_calls"])
                wasted_s.append(settled["wasted_seconds"])
                done += report["satisfied"]
                planning.append(report["planning"]["wall_seconds"])
                denied.append(sum(1 for r in records if str(r.get("failure_reason") or "").startswith("budget_denied")))
                spec_calls.append(report["speculative_tool_calls"])
                raw_trials.append({"scenario": name, "policy": label, "trial": trial, "seed": seed,
                                   "budget": conf["budget"], "latency": report["decision_latency_s"],
                                   "tool_calls": cost[-1], "wasted_calls": settled["wasted_calls"],
                                   "wasted_seconds": settled["wasted_seconds"], "satisfied": report["satisfied"],
                                   "planning_seconds": planning[-1], "outcomes": draw_sets[trial],
                                   "budget_snapshot": ledger.snapshot(), "records": records})
                queue_wait += [r["start_time"] - r["enqueue_time"] for r in records
                               if r.get("start_time") is not None and not (r.get("metadata") or {}).get("speculative")]
            lat, lat_sd = _mean_sd(latency)
            rows.append({"scenario": name, "policy": label, "trials": trials, "latency_mean": lat, "latency_sd": lat_sd,
                         "latency_p90": sorted(latency)[int(0.9 * (trials - 1))], "tool_calls_mean": statistics.fmean(cost),
                         "wasted_calls_mean": statistics.fmean(wasted_calls), "wasted_seconds_mean": statistics.fmean(wasted_s),
                         "completion_rate": done / trials, "planning_seconds_mean": statistics.fmean(planning),
                         "necessary_queue_wait_mean": statistics.fmean(queue_wait) if queue_wait else 0.0,
                         "budget": conf["budget"], "about": conf["about"],
                         "admission_denials_mean": statistics.fmean(denied), "speculative_calls_mean": statistics.fmean(spec_calls),
                         "unused_budget_mean": conf["budget"] - statistics.fmean(cost), "capacities": dict(caps)})
    evaluator.shutdown()
    return {"label": "SYNTHETIC (declared outcome distributions; real scheduler, real wall clock; "
                     "same per-trial outcomes for every policy)", "seed": seed, "rows": rows, "raw_trials": raw_trials}


SPECULATION_POLICIES = [
    ("S0 (E3: no speculation)", {"mode": "e3"}),
    ("S1 K=1 (E4)", {"mode": "e4", "k": 1}),
    ("S1 K=2 (E4)", {"mode": "e4", "k": 2}),
    ("S2 (E5: selective, Monte Carlo)", {"mode": "e5", "k": 2}),
]


# ---- Experiments 2 and 4: harness fixture runs ---------------------------------------------------


def fixed_plan_actions(policies: list[str], trials: int, tool_delay: float, workdir: Path) -> dict[str, Any]:
    """One agent, the same declared parallel plan, dispatched by E0/E1/E2 (FIXTURE)."""
    from .fixture import PlanAgentBuilder, create_sign_scene
    from .harness import PlanController, ToolScheduling, attach_plan_mode, pools_for

    scene = create_sign_scene(workdir / "sign_scene.png")
    rows, traces = [], {}
    for policy in policies:
        spans, walls, overlaps, answers = [], [], [], set()
        for trial in range(trials):
            builder = PlanAgentBuilder(scene, plan="parallel", tool_delay=tool_delay)
            agent = builder(None, "worker_01", True)
            events = []
            agent.event_sink = lambda t, p, **m: (events.append((t, p)), {"event_id": f"e{len(events)}"})[1]
            scheduler = Scheduler(policy=policy, workers=4, capacities=pools_for([agent]))
            agent.tool_scheduler = ToolScheduling(scheduler, "worker_01")
            attach_plan_mode(agent, PlanController(scheduler, "worker_01", PlanningConfig.for_mode("e3", plan_selection=False)))
            began = time.perf_counter()
            out = agent.generate([{"type": "image", "value": str(scene)}, {"type": "text", "value": "What does the sign say?"}])
            walls.append(time.perf_counter() - began)
            scheduler.shutdown()
            log = sorted(builder.log, key=lambda r: r["start"])
            spans.append(log[-1]["end"] - log[0]["start"])
            overlaps.append(sum(1 for i, a in enumerate(log) for b in log[i + 1:] if a["start"] < b["end"] and b["start"] < a["end"]))
            answers.add(out["prediction"])
            if trial == 0:
                t0 = log[0]["start"]
                traces[policy] = [{"tool": r["tool"], "call": r["call"], "start": round(r["start"] - t0, 4),
                                   "end": round(r["end"] - t0, 4)} for r in log]
        span, span_sd = _mean_sd(spans)
        wall, wall_sd = _mean_sd(walls)
        rows.append({"policy": policy.upper(), "trials": trials, "tool_span_mean": span, "tool_span_sd": span_sd,
                     "answer_wall_mean": wall, "answer_wall_sd": wall_sd, "overlapping_pairs_mean": statistics.fmean(overlaps),
                     "answers": sorted(answers)})
    base = rows[0]["tool_span_mean"]
    for row in rows:
        row["speedup_vs_first"] = base / row["tool_span_mean"]
    return {"label": f"FIXTURE (real agent loop and capabilities; scripted model; {tool_delay}s injected tool latency)",
            "rows": rows, "traces": traces}


def multi_agent_matrix(workers: list[int], policies: list[str], trials: int, tool_delay: float, workdir: Path,
                       plan: str = "fallback", **kwargs: Any) -> dict[str, Any]:
    """Whole coordinator + worker runs of the sign task (FIXTURE)."""
    import json
    from datetime import datetime

    from .fixture import run_plan_fixture

    rows = []
    for n in workers:
        for policy in policies:
            walls, calls, spec, wasted, answers, statuses, planning = [], [], [], [], set(), set(), []
            for trial in range(trials):
                orchestrator, _, result, events = run_plan_fixture(workdir / f"n{n}_{policy}", policy=policy, workers=n,
                                                                   plan=plan, tool_delay=tool_delay, **kwargs)
                stamps = [datetime.fromisoformat(e["timestamp"]).timestamp() for e in events]
                walls.append(stamps[-1] - stamps[0])
                final = json.loads((orchestrator.run_dir / "final_result.json").read_text())
                calls.append(final["budgets"]["global"]["tool_calls"]["used"])
                reports = [r for a in (final.get("planning") or {}).values() for r in a["plans"]]
                spec.append(sum(r["speculative_tool_calls"] for r in reports))
                planning.append(sum(r["planning"]["wall_seconds"] for r in reports))
                adopted = sum(1 for e in events if e["event_type"] == "SPECULATIVE_RESULT_ADOPTED")
                wasted.append(sum(1 for e in events if e["event_type"] in ("SPECULATIVE_TASK_CANCEL_REQUESTED",)) )
                answers.add(result["prediction"])
                statuses.add(result["extra_records"]["status"])
            wall, sd = _mean_sd(walls)
            rows.append({"workers": n, "policy": policy.upper(), "trials": trials, "wall_mean": wall, "wall_sd": sd,
                         "tool_calls_mean": statistics.fmean(calls), "speculative_calls_mean": statistics.fmean(spec),
                         "cancel_requested_mean": statistics.fmean(wasted), "planning_seconds_mean": statistics.fmean(planning),
                         "answers": sorted(answers), "statuses": sorted(statuses)})
    return {"label": f"FIXTURE (coordinator + workers; scripted model; {tool_delay}s injected tool latency; plan '{plan}')",
            "rows": rows}


def run_variants(variants: list[tuple[str, str, dict[str, Any]]], workers: list[int], trials: int, tool_delay: float,
                 workdir: Path, plan: str = "fallback") -> dict[str, Any]:
    """Whole coordinator + worker runs (FIXTURE) for labelled (policy, settings) variants."""
    import json
    from datetime import datetime

    from .fixture import run_plan_fixture
    from .montecarlo import PlanEvaluator

    rows = []
    for n in workers:
        for label, policy, settings in variants:
            PlanEvaluator.shutdown_shared()  # every variant starts cold; "shared" then stays warm across its trials
            walls, calls, planning, startups, started, answers, statuses, spec, backends = [], [], [], [], [], set(), set(), [], {}
            for trial in range(trials):
                orchestrator, _, result, events = run_plan_fixture(workdir / (f"n{n}_" + "".join(ch if ch.isalnum() else "_" for ch in label)[:48]), policy=policy,
                                                                   workers=n, plan=plan, tool_delay=tool_delay, **settings)
                stamps = [datetime.fromisoformat(e["timestamp"]).timestamp() for e in events]
                walls.append(stamps[-1] - stamps[0])
                final = json.loads((orchestrator.run_dir / "final_result.json").read_text())
                calls.append(final["budgets"]["global"]["tool_calls"]["used"])
                reports = [r for a in (final.get("planning") or {}).values() for r in a["plans"]]
                planning.append(sum(r["planning"]["wall_seconds"] for r in reports))
                spec.append(sum(r["speculative_tool_calls"] for r in reports))
                for r in reports:
                    for g in r["planning"].get("gate", []):
                        backends[g["backend"]] = backends.get(g["backend"], 0) + 1
                pool_events = [e["payload"]["startup_seconds"] for e in events if e["event_type"] == "PLANNING_POOL_STARTED"]
                startups.append(sum(pool_events))
                started.append(bool(pool_events))
                answers.add(result["prediction"])
                statuses.add(result["extra_records"]["status"])
            wall, sd = _mean_sd(walls)
            rows.append({"workers": n, "variant": label, "policy": policy.upper(), "trials": trials, "wall_mean": wall,
                         "wall_sd": sd, "wall_first": walls[0],
                         "wall_rest_mean": statistics.fmean(walls[1:]) if trials > 1 else None,
                         "tool_calls_mean": statistics.fmean(calls), "speculative_calls_mean": statistics.fmean(spec),
                         "planning_seconds_mean": statistics.fmean(planning),
                         "pool_startup_seconds_mean": statistics.fmean(startups),
                         "runs_with_pool_start": sum(started), "gate_backends": backends or None,
                         "answers": sorted(answers), "statuses": sorted(statuses), "settings": settings})
    PlanEvaluator.shutdown_shared()
    return {"label": f"FIXTURE (coordinator + workers; scripted model; {tool_delay}s injected tool latency; plan '{plan}')",
            "rows": rows}


PLANNING_VARIANTS = [
    ("OFF (original)", "off", {}),
    ("E4 fixed speculation", "e4", {}),
    ("E5 eager pool, always simulate", "e5", {"planning": {"planning_pool": "eager", "planning_gate": "off"}}),
    ("E5 lazy pool, always simulate", "e5", {"planning": {"planning_pool": "lazy", "planning_gate": "off"}}),
    ("E5 shared warm pool, always simulate", "e5", {"planning": {"planning_pool": "shared", "planning_gate": "off"}}),
    ("E5 sequential MC (0 processes)", "e5", {"planning_processes": 0, "planning": {"planning_gate": "off"}}),
    ("E5 heuristic only", "e5", {"planning": {"planning_gate": "auto", "min_stakes_s": 1e9}}),
    ("E5 overhead-aware gate, lazy pool (default)", "e5", {"planning": {"planning_gate": "auto", "planning_pool": "lazy"}}),
    ("E5 with legacy model (no plan proposed)", "e5", {"legacy": True}),
]

WHOLE_HARNESS_VARIANTS = [
    ("OFF (original)", "off", {}),
    ("E0 sequential FIFO", "e0", {}),
    ("E1 parallel FIFO", "e1", {}),
    ("E2 critical path", "e2", {}),
    ("E3 plans + plan selection", "e3", {}),
    ("E4 plans + fixed speculation", "e4", {}),
    ("E5 plans + selective speculation", "e5", {}),
]


def config_matrix(policy: str, workdir: Path, tool_delay: float = 0.02) -> dict[str, Any]:
    """1-4 workers x memory on/off x peer on/off (16 deterministic runs) with the plan fixture."""
    import json

    from .fixture import run_plan_fixture

    rows = []
    for n in (1, 2, 3, 4):
        for memory in (True, False):
            for peer in (True, False):
                orchestrator, _, result, events = run_plan_fixture(workdir / f"n{n}_m{int(memory)}_p{int(peer)}", policy=policy,
                                                                   workers=n, memory=memory, peer=peer, tool_delay=tool_delay,
                                                                   planning_processes=0)
                config = next(e for e in events if e["event_type"] == "RUN_CONFIGURATION_RECORDED")["payload"]["effective_config"]
                final = json.loads((orchestrator.run_dir / "final_result.json").read_text())
                rows.append({"workers": n, "memory": memory, "peer": peer, "status": result["extra_records"]["status"],
                             "answer": result["prediction"], "max_concurrent_workers": config["max_concurrent_workers"],
                             "recorded_memory": config["optional_worker_memory_enabled"],
                             "recorded_peer": config["peer_communication_enabled"],
                             "tool_calls": final["budgets"]["global"]["tool_calls"]["used"],
                             "messages": sum(1 for e in events if e["event_type"] == "MESSAGE_SENT")})
    return {"label": "FIXTURE (deterministic validation matrix)", "policy": policy, "rows": rows}


CONTENTION_VARIANTS = [
    ("E2, 1 scheduler slot", "e2", {"scheduler_workers": 1}),
    ("E2, 4 scheduler slots", "e2", {"scheduler_workers": 4}),
    ("E2, tool pool capacity 1", "e2", {"capacities": {"cpu": 1}}),
    ("E4, 4 slots, capacity 4", "e4", {}),
    ("E4, tool pool capacity 1", "e4", {"capacities": {"cpu": 1}}),
    ("E5, tool pool capacity 1", "e5", {"capacities": {"cpu": 1}}),
]
VARIANT_SETS = {"whole": WHOLE_HARNESS_VARIANTS, "overhead": PLANNING_VARIANTS, "contention": CONTENTION_VARIANTS}
