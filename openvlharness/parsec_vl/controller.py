"""Plan execution with selective speculation and event-driven replanning (E3/E4/E5).

One ``PlanExecutor`` drives one validated ``ActionPlan`` through the existing
``Scheduler`` (E2 ordering). It never runs tools itself: an ``ActionRuntime``
knows how to prepare, execute, and commit an action (``HarnessRuntime`` uses the
real capabilities and agent memory; ``SyntheticRuntime`` replays declared
outcomes for controlled experiments).

Lifecycle of a branch::

    planned ── necessary ──────────────────────────────> satisfied | unsatisfied
       └──── speculative ──┬── adopted (results replayed into the active memory)
                           └── pruned  (pending tasks cancelled, reservation released;
                                        running tasks finish physically, are charged,
                                        and their results are discarded)

* The primary branch is necessary from the start; its results commit straight
  into the agent's memory (one writer: the calling thread), in a deterministic
  topological order per branch.
* Alternatives commit into an isolated copy of the memory taken at plan start.
  Nothing from them reaches the agent unless the branch is adopted.
* Speculation policy: S0 none; S1 the first K speculation-safe alternatives;
  S2 those whose expected benefit beats their cost (Monte Carlo when an
  evaluator is attached, otherwise the closed-form rule below), subject to the
  speculative budget limit and headroom for necessary work.
* Replanning happens only on a meaningful event — every necessary branch has
  failed — and at most ``max_replans`` times.

S2 closed-form rule (declared heuristic, consistent units: seconds and tool calls):
speculate on branch s when ``q_s * lam * dT_s > (1 - q_s) * c_s * (mu + nu_B)``,
with q_s the probability the primary misses its goal, dT_s the latency hidden
(median duration of s's critical path), c_s its tool calls, lam per second, mu
per tool call, and nu_B = mu * used / remaining budget (budget pressure).
"""

from __future__ import annotations

import copy
import itertools
import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from .dag import Task, TaskStatus
from .montecarlo import OutcomeModel, PlanEvaluator, finalize_spec
from .plans import ActionPlan, Branch, PlanAction
from .scheduler import Scheduler

SPECULATION_MODES = ("S0", "S1", "S2")
EXECUTION_MODES = {"e3": "S0", "e4": "S1", "e5": "S2"}
_task_ids = itertools.count(1)


@dataclass(frozen=True)
class PlanningConfig:
    mode: str = "e5"
    speculation: str = "S2"
    max_speculative_branches: int = 1     # K for S1; cap for S2
    speculative_budget_limit: int = 4     # tool calls charged to speculation per plan
    candidate_plan_limit: int = 6
    beam_width: int = 4
    max_plan_depth: int = 3
    rollouts: int = 2000
    planning_processes: int = 4
    planning_time_budget: float = 0.5     # seconds per evaluation
    random_seed: int = 0
    latency_weight: float = 1.0           # lam, per second
    cost_weight: float = 0.25             # mu, per tool call
    max_replans: int = 2
    heuristic_alternatives: bool = True
    plan_selection: bool = True           # E3/E5: choose which branch leads via Monte Carlo
    replanning: bool = True               # E5: re-evaluate alternatives after a failure
    # Phase 3: overhead-aware planning. "auto" decides per evaluation between the
    # closed-form heuristic, in-process sequential Monte Carlo, and the process pool;
    # "off" always uses the pool (Phase 2 behaviour). Cost constants are the Phase 2
    # measurements on this machine (outputs/parsec_vl/phase2/planning/multicore.json).
    planning_gate: str = "auto"
    planning_pool: str = "lazy"           # eager | lazy | shared (process-wide warm pool)
    rollout_cost_s: float = 24e-6         # in-process seconds per rollout
    pool_overhead_s: float = 0.12         # fixed pool cost per evaluation (submission, IPC, stragglers)
    pool_startup_s: float = 0.25          # cold start of a 4-process spawn pool
    min_stakes_s: float = 0.05            # below this closed-form score spread, simulation is not worth it

    @classmethod
    def for_mode(cls, mode: str, **overrides: Any) -> "PlanningConfig":
        mode = mode.lower()
        if mode not in EXECUTION_MODES:
            raise ValueError(f"planning mode must be one of {sorted(EXECUTION_MODES)}")
        defaults = {"e3": dict(plan_selection=True, replanning=False),
                    "e4": dict(plan_selection=False, replanning=False),
                    "e5": dict(plan_selection=True, replanning=True)}[mode]
        config = cls(mode=mode, speculation=EXECUTION_MODES[mode], **{**defaults, **overrides})
        config.validate()
        return config

    def validate(self) -> None:
        if self.speculation not in SPECULATION_MODES:
            raise ValueError(f"speculation must be one of {SPECULATION_MODES}")
        for name in ("max_speculative_branches", "speculative_budget_limit", "max_replans"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        for name in ("candidate_plan_limit", "beam_width", "max_plan_depth", "rollouts"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.planning_processes) is not int or self.planning_processes < 0:
            raise ValueError("planning_processes must be >= 0 (0 = in-process sequential evaluation)")
        if self.planning_time_budget <= 0:
            raise ValueError("planning_time_budget must be positive")
        if self.planning_gate not in ("auto", "off"):
            raise ValueError("planning_gate must be auto or off")
        if self.planning_pool not in ("eager", "lazy", "shared"):
            raise ValueError("planning_pool must be eager, lazy, or shared")


def choose_planning_backend(candidates: list[tuple[dict, tuple[int, ...]]], config: "PlanningConfig",
                        pool: "PlanEvaluator | None") -> tuple[str, dict[str, Any]]:
    """Decide whether simulation can pay for itself: heuristic | sequential | parallel.

    stakes = spread of closed-form scores across candidates (an upper estimate of
    what a better choice could save); cost = predicted planning wall time per
    backend from the measured constants. Simulate only when the cheaper backend
    costs less than the stakes.
    """
    from .montecarlo import heuristic_estimate

    c = config
    scores = [c.latency_weight * t + c.cost_weight * k for t, k in (heuristic_estimate(sp, o) for sp, o in candidates)]
    stakes = max(scores) - min(scores) if scores else 0.0
    work = len(candidates) * c.rollouts * c.rollout_cost_s
    sequential = min(work, c.planning_time_budget)
    parallel = float("inf")
    if pool is not None and pool.processes > 0:
        parallel = min(work / pool.processes, c.planning_time_budget) + c.pool_overhead_s + \
            (0.0 if getattr(pool, "started", False) else c.pool_startup_s)
    terms = {"candidates": len(candidates), "stakes_s": round(stakes, 4), "predicted_sequential_s": round(sequential, 4),
             "predicted_parallel_s": round(parallel, 4) if parallel != float("inf") else None,
             "pool_warm": bool(getattr(pool, "started", False)), "heuristic_scores": [round(x, 4) for x in scores]}
    if len(candidates) < 2:
        return "heuristic", {**terms, "reason": "single candidate"}
    if stakes < c.min_stakes_s:
        return "heuristic", {**terms, "reason": "candidates nearly equivalent under the closed form"}
    backend, cost = ("sequential", sequential) if sequential <= parallel else ("parallel", parallel)
    if cost > stakes:
        return "heuristic", {**terms, "reason": "predicted planning time exceeds the potential gain"}
    return backend, {**terms, "reason": f"{backend} simulation predicted cheaper than the potential gain"}


# ---- runtimes ----------------------------------------------------------------------------------


@dataclass
class BranchContext:
    memory: Any = None
    results: dict[str, Any] = field(default_factory=dict)  # action_id -> committed result
    isolated: bool = False


class SyntheticRuntime:
    """Declared outcomes for controlled experiments: action_id -> (seconds, produces usable evidence)."""

    def __init__(self, outcomes: Mapping[str, tuple[float, bool]], pools: Mapping[str, str],
                 model: OutcomeModel | None = None) -> None:
        self.outcomes = dict(outcomes)
        self.pools = dict(pools)
        self.model = model or OutcomeModel(source="declared")

    def context(self, isolated: bool) -> BranchContext:
        return BranchContext(isolated=isolated)

    def bind(self, action, ctx):
        return dict(action.arguments)

    def prepare(self, action, args, ctx, call_id):
        return {"call_id": call_id}

    def backend(self, action, prepared, ctx):
        seconds, ok = self.outcomes[action.action_id]
        time.sleep(seconds)
        return {"ok": ok}

    def commit(self, action, prepared, payload, ctx, announce=None):
        return _Outcome(bool(payload.get("ok")))

    def adopt(self, action, prepared, payload, result, active, announce=None):
        return result

    def failed(self, action, reason):
        return _Outcome(False, reason)

    def satisfied(self, action, result) -> bool:
        return bool(result.ok)

    def pool(self, action) -> str:
        return self.pools.get(action.tool, "io")

    def estimate(self, action) -> float | None:
        return self.model.median(action.tool)


@dataclass
class _Outcome:
    ok: bool
    error: str | None = None
    data: dict = field(default_factory=dict)


# ---- executor ----------------------------------------------------------------------------------


@dataclass
class _Run:
    branch: Branch
    index: int
    ctx: BranchContext
    order: list[str]
    role: str = "planned"                 # necessary | speculative | planned
    tasks: dict[str, str] = field(default_factory=dict)      # action -> scheduler task id
    prepared: dict[str, Any] = field(default_factory=dict)
    payloads: dict[str, Any] = field(default_factory=dict)   # finished, awaiting commit
    committed: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    outcome: bool | None = None
    speculated: bool = False              # started as speculation (results adopted, not requested)


class PlanExecutor:
    def __init__(self, scheduler: Scheduler, runtime, config: PlanningConfig, *, agent_id: str,
                 emit: Callable[[str, dict], Any] | None = None, evaluator: PlanEvaluator | None = None,
                 model: OutcomeModel | None = None, budget=None) -> None:
        self.scheduler = scheduler
        self.runtime = runtime
        self.config = config
        self.agent_id = agent_id
        self._emit_fn = emit
        self.evaluator = evaluator
        self.model = model or getattr(runtime, "model", None) or OutcomeModel()
        self.budget = budget  # BudgetManager (shared ledger), read-only here: headroom checks
        self._events: queue.Queue = queue.Queue()

    def emit(self, event_type: str, payload: dict) -> None:
        if self._emit_fn is not None:
            self._emit_fn(event_type, payload)

    # ---- planning ----------------------------------------------------------------------------
    def _spec(self, branches: list[Branch], workers: int | None = None) -> dict:
        actions, spec_branches = {}, []
        for branch in branches:
            for action in branch.actions:
                actions[action.action_id] = {"pool": self.runtime.pool(action), "deps": tuple(action.depends_on),
                                             "duration": self.model.duration(action.tool), "p_ok": self.model.success(action.tool)}
            spec_branches.append({"actions": [a.action_id for a in branch.actions], "goal": branch.goal})
        capacities = dict(self.scheduler.pools.capacities)
        remaining = self._remaining_budget()
        return finalize_spec({"actions": actions, "workers": workers or self.scheduler.workers, "budget": remaining,
                              "capacities": capacities, "branches": spec_branches})

    def _remaining_budget(self) -> int | None:
        if self.budget is None:
            return None
        return self.budget.remaining(self.agent_id, "tool_calls")

    def _score(self, estimate) -> float:
        return self.config.latency_weight * estimate.latency_mean + self.config.cost_weight * estimate.cost_mean

    def _gate(self, candidates: list[tuple[dict, tuple[int, ...]]]) -> tuple[str, dict[str, Any]]:
        return choose_planning_backend(candidates, self.config, self.evaluator)

    def _evaluate(self, label: str, candidates: list[tuple[dict, tuple[int, ...]]], plan: ActionPlan) -> list | None:
        if not candidates or (self.evaluator is None and self.config.planning_gate == "off"):
            return None
        evaluator = self.evaluator
        gate: dict[str, Any] = {"backend": "parallel" if evaluator is not None and evaluator.processes else "sequential"}
        if self.config.planning_gate == "auto":
            backend, terms = self._gate(candidates)
            gate = {"backend": backend, **terms}
            self._planning.setdefault("gate", []).append({"purpose": label, **gate})
            if backend == "heuristic":
                self._planning["skipped"] = self._planning.get("skipped", 0) + 1
                self.emit("PLAN_EVALUATION_SKIPPED", {"plan_id": plan.plan_id, "purpose": label, **gate})
                return None
            if backend == "sequential":
                evaluator = PlanEvaluator(processes=0, batch_size=getattr(self.evaluator, "batch_size", 250))
        if evaluator is None:
            return None
        self.emit("PLAN_EVALUATION_STARTED", {"plan_id": plan.plan_id, "purpose": label, "candidates": len(candidates),
                                              "rollouts": self.config.rollouts, "processes": evaluator.processes,
                                              "time_budget_s": self.config.planning_time_budget,
                                              "outcome_model": self.model.source, "gate": gate})
        try:
            result = evaluator.evaluate(candidates, self.config.rollouts, self.config.random_seed,
                                        self.config.planning_time_budget)
        except Exception as exc:  # noqa: BLE001 - a planning failure falls back, never stops execution
            self.emit("PLAN_EVALUATION_COMPLETED", {"plan_id": plan.plan_id, "purpose": label, "complete": False,
                                                    "error": f"{type(exc).__name__}: {exc}", "fallback": True})
            return None
        self._planning["wall_seconds"] += result.wall_seconds
        self._planning["cpu_seconds"] += result.cpu_seconds
        self._planning["evaluations"] += 1
        self.emit("PLAN_EVALUATION_COMPLETED", {
            "plan_id": plan.plan_id, "purpose": label, "complete": result.complete, "wall_seconds": result.wall_seconds,
            "cpu_seconds": result.cpu_seconds, "processes": result.processes, "batches": result.batches,
            "batches_done": result.batches_done, "outcome_model": self.model.source,
            "estimates": [e.to_dict() for e in result.estimates]})
        if not result.estimates or min(e.rollouts for e in result.estimates) == 0:
            return None  # over the planning time budget with no usable estimate: fall back
        return result.estimates

    def _select_leader(self, plan: ActionPlan) -> ActionPlan:
        """E3/E5: choose which branch leads (Monte Carlo, S0 semantics); others keep their order."""
        if not self.config.plan_selection or not plan.alternatives:
            return plan
        width = min(len(plan.branches), self.config.beam_width)
        variants = []
        for lead in range(width):
            order = [plan.branches[lead]] + [b for i, b in enumerate(plan.branches) if i != lead]
            variants.append(order)
        candidates = [(self._spec(v), ()) for v in variants]
        estimates = self._evaluate("plan_selection", candidates, plan)
        if estimates is None:
            from .montecarlo import heuristic_estimate

            scores = [self.config.latency_weight * t + self.config.cost_weight * k
                      for t, k in (heuristic_estimate(sp, o) for sp, o in candidates)]
            best = min(range(len(variants)), key=lambda i: (scores[i], i))
            self._decision["selection"] = {"method": "closed_form", "lead": variants[best][0].name,
                                           "scores": {variants[i][0].name: round(scores[i], 4) for i in range(len(variants))}}
            return plan if best == 0 else replace(plan, branches=variants[best])
        best = min(range(len(variants)), key=lambda i: (self._score(estimates[i]), i))
        self._decision["selection"] = {"method": "monte_carlo", "lead": variants[best][0].name,
                                       "scores": {variants[i][0].name: round(self._score(estimates[i]), 4) for i in range(len(variants))}}
        if best == 0:
            return plan
        reordered = replace(plan, branches=variants[best])
        return reordered

    def _choose_speculation(self, plan: ActionPlan) -> list[int]:
        eligible = [i for i, b in enumerate(plan.branches) if i > 0 and b.speculation_safe][: self.config.beam_width]
        mode = self.config.speculation
        if mode == "S0" or not eligible or self.config.max_speculative_branches == 0:
            self._decision["speculation"] = {"policy": mode, "chosen": [], "eligible": len(eligible)}
            return []
        if mode == "S1":
            chosen = eligible[: self.config.max_speculative_branches]
            self._decision["speculation"] = {"policy": "S1", "chosen": [plan.branches[i].name for i in chosen]}
            return chosen
        # S2: expected benefit vs cost, with headroom for necessary work in the shared budget.
        remaining = self._remaining_budget()
        necessary_cost = len(plan.primary.actions)
        options: list[tuple[int, ...]] = [()] + [(i,) for i in eligible]
        estimates = self._evaluate("speculation", [(self._spec(plan.branches), o) for o in options], plan)
        terms: dict[str, Any] = {}
        chosen: list[int] = []
        if estimates is not None:
            base = estimates[0]
            for option, est in zip(options[1:], estimates[1:]):
                name = plan.branches[option[0]].name
                terms[name] = {"latency_s": round(est.latency_mean, 4), "cost": round(est.cost_mean, 4),
                               "score": round(self._score(est), 4), "baseline_score": round(self._score(base), 4),
                               "p_operational": round(est.p_operational, 4), "wasted_calls": round(est.wasted_calls_mean, 4)}
            ranked = sorted(((self._score(est), opt[0]) for opt, est in zip(options[1:], estimates[1:])
                             if self._score(est) < self._score(base)))
            chosen = [b for _, b in ranked][: self.config.max_speculative_branches]
            method = "monte_carlo"
        else:
            q = 1.0
            for action in plan.primary.actions:
                q *= self.model.success(action.tool)
            q = 1.0 - q
            used = 0 if self.budget is None else self.budget.used(self.agent_id, "tool_calls")
            nu = 0.0 if remaining in (None, 0) else self.config.cost_weight * used / remaining
            for i in eligible:
                branch = plan.branches[i]
                hidden = sum(self.model.median(a.tool) for a in branch.actions)  # chain upper bound
                cost = len(branch.actions)
                gain = q * self.config.latency_weight * hidden
                loss = (1 - q) * cost * (self.config.cost_weight + nu)
                terms[branch.name] = {"q": round(q, 4), "hidden_s": round(hidden, 4), "cost": cost,
                                      "gain": round(gain, 4), "loss": round(loss, 4)}
                if gain > loss:
                    chosen.append(i)
            chosen = chosen[: self.config.max_speculative_branches]
            method = "closed_form"
        # Headroom: speculation may not consume budget that necessary work is expected to need.
        kept = []
        spend = 0
        for i in chosen:
            extra = len(plan.branches[i].actions)
            if remaining is not None and remaining - spend - extra < necessary_cost:
                terms.setdefault(plan.branches[i].name, {})["rejected"] = "budget headroom"
                continue
            kept.append(i)
            spend += extra
        self._decision["speculation"] = {"policy": "S2", "method": method, "chosen": [plan.branches[i].name for i in kept],
                                         "terms": terms, "remaining_budget": remaining}
        return kept

    # ---- execution ---------------------------------------------------------------------------
    def execute(self, plan: ActionPlan) -> dict[str, Any]:
        began = time.perf_counter()
        self._planning = {"wall_seconds": 0.0, "cpu_seconds": 0.0, "evaluations": 0}
        self._decision: dict[str, Any] = {}
        self._spec_spent = 0
        self._replans = 0
        self._records: list[dict[str, Any]] = []
        self._cancel_requested: set[str] = set()
        self.emit("PLAN_CANDIDATES_GENERATED", {"plan": plan.to_dict(), "mode": self.config.mode})
        plan = self._select_leader(plan)
        speculate = self._choose_speculation(plan)
        self.emit("PLAN_SELECTED", {"plan_id": plan.plan_id, "lead_branch": plan.primary.branch_id,
                                    "decision": self._decision, "mode": self.config.mode,
                                    "planning_wall_s": round(self._planning["wall_seconds"], 6)})
        runs = [_Run(b, i, self.runtime.context(isolated=i > 0), _topological(b)) for i, b in enumerate(plan.branches)]
        self._runs = runs
        self._plan = plan
        necessary = [0]
        runs[0].role = "necessary"
        for i in speculate:
            runs[i].role = "speculative"
            runs[i].speculated = True
            plan.branches[i].status = "speculative"
        plan.branches[0].status = "running"
        winner = None
        self._submit_ready(runs[0])
        for i in speculate:
            self._submit_ready(runs[i])
        while True:
            states = [runs[i].outcome for i in necessary]
            if True in states:
                winner = necessary[states.index(True)]
                break
            if all(s is False for s in states):
                nxt = self._replan(plan, runs, necessary)
                if nxt is None:
                    break
                necessary.append(nxt)
                self._activate(runs[nxt])
                continue
            task_id = self._events.get()
            self._on_finished(task_id)
        latency = time.perf_counter() - began
        self._prune(runs, set(necessary), winner)
        for i in necessary:
            plan.branches[i].status = ("satisfied" if runs[i].outcome else "unsatisfied") if i == 0 else \
                ("adopted" if runs[i].role == "necessary" and i in speculate else ("satisfied" if runs[i].outcome else "unsatisfied"))
        observations = [(runs[i].branch, aid, runs[i].ctx.results[aid]) for i in necessary for aid in runs[i].committed]
        report = {
            "plan_id": plan.plan_id, "mode": self.config.mode, "speculation_policy": self.config.speculation,
            "satisfied": winner is not None, "winning_branch": plan.branches[winner].name if winner is not None else None,
            "decision_latency_s": latency, "planning": dict(self._planning), "decision": self._decision,
            "replans": self._replans, "branches": [b.to_dict() for b in plan.branches], "tasks": self._records,
            "speculative_tool_calls": self._spec_spent,
        }
        self.emit("PLAN_EXECUTION_COMPLETED", {k: v for k, v in report.items() if k != "tasks"})
        report["observations"] = observations
        return report

    def _replan(self, plan: ActionPlan, runs: list[_Run], necessary: list[int]) -> int | None:
        remaining = [i for i in range(len(runs)) if i not in necessary]
        if not remaining:
            return None
        reason = f"{runs[necessary[-1]].branch.name} did not reach its goal"
        self.emit("REPLAN_TRIGGERED", {"plan_id": plan.plan_id, "reason": reason, "remaining": [runs[i].branch.name for i in remaining],
                                       "replans_so_far": self._replans})
        choice, method = remaining[0], "proposed order"
        if self.config.replanning and self._replans < self.config.max_replans and len(remaining) > 1:
            self._replans += 1
            variants = [[runs[i].branch] for i in remaining]
            estimates = self._evaluate("replan", [(self._spec(v), ()) for v in variants], plan)
            if estimates is not None:
                # Already-started speculative branches have a head start the simulation ignores; prefer them on ties.
                choice = min(remaining, key=lambda i: (self._score(estimates[remaining.index(i)]), runs[i].role != "speculative", i))
                method = "monte_carlo"
        self.emit("REPLAN_COMPLETED", {"plan_id": plan.plan_id, "next_branch": runs[choice].branch.name, "method": method,
                                       "was_speculative": runs[choice].role == "speculative"})
        return choice

    def _activate(self, run: _Run) -> None:
        """Make a branch necessary: adopt its speculative progress, or start it now."""
        if run.role == "speculative":
            active = self._runs[0].ctx
            for aid in list(run.committed):
                action = _action(run.branch, aid)
                adopted = self.runtime.adopt(action, run.prepared.get(aid), run.payloads.get(aid), run.ctx.results[aid], active,
                                             announce=self._announcer(run, aid))
                run.ctx.results[aid] = adopted
            run.ctx = BranchContext(active.memory, {**run.ctx.results}, isolated=False)
            self.emit("SPECULATIVE_RESULT_ADOPTED", {"plan_id": self._plan.plan_id, "branch_id": run.branch.branch_id,
                                                     "adopted_actions": list(run.committed),
                                                     "in_flight": [a for a in run.tasks if a not in run.committed]})
            # Queued speculative tasks of this branch become necessary work (cancel + resubmit).
            queued = [tid for aid, tid in run.tasks.items() if self.scheduler.task(tid).status in (TaskStatus.READY, TaskStatus.BLOCKED)]
            for aid in [a for a, t in run.tasks.items() if t in set(self.scheduler.cancel(queued))]:
                del run.tasks[aid]
            run.role = "necessary"
        else:
            # Started only now as necessary work: it commits straight into the agent's memory.
            active = self._runs[0].ctx
            run.ctx = BranchContext(active.memory, dict(run.ctx.results), isolated=False)
            run.role = "necessary"
            run.branch.status = "running"
        self._submit_ready(run)
        if run.outcome is None:
            self._resolve(run)

    def _submit_ready(self, run: _Run) -> None:
        tasks = []
        speculative = run.role == "speculative"
        for aid in run.order:
            if aid in run.tasks or aid in run.skipped or aid in run.ctx.results:
                continue
            action = _action(run.branch, aid)
            if not all(d in run.ctx.results for d in action.depends_on):
                continue
            if speculative and self._spec_spent >= self.config.speculative_budget_limit:
                continue  # speculative budget limit reached: stays unsubmitted
            call_id = f"{self._plan.plan_id}.{run.branch.name}.{aid}"
            args = self.runtime.bind(action, run.ctx)
            if isinstance(args, str):
                self._skip(run, aid, args)
                continue
            prepared = self.runtime.prepare(action, args, run.ctx, call_id)
            if not isinstance(prepared, dict) or prepared.get("failure") is not None:
                result = prepared["failure"] if isinstance(prepared, dict) else self.runtime.failed(action, "prepare failed")
                run.ctx.results[aid] = result
                run.committed.append(aid)
                self._after_commit(run, aid)
                continue
            run.prepared[aid] = prepared
            task_id = f"{self.agent_id}.{run.branch.name}.{aid}.t{next(_task_ids):05d}"
            meta: dict[str, Any] = {"plan_id": self._plan.plan_id, "branch_id": run.branch.branch_id,
                                    "action_id": aid, "logical_request_id": call_id, "speculative": speculative,
                                    "on_finish": lambda task, q=self._events: q.put(task.task_id)}
            if speculative:
                meta["on_start"] = lambda task, rb=run.branch: self.emit(
                    "SPECULATIVE_TASK_STARTED", {"plan_id": self._plan.plan_id, "branch_id": rb.branch_id, "task_id": task.task_id})
                self._spec_spent += 1
            announce = getattr(self.runtime, "on_submit", None)
            if callable(announce) and not speculative:
                announce(action, prepared, meta)
            tasks.append(Task(task_id=task_id, operation=action.tool,
                              body=lambda inputs, a=action, p=prepared, c=run.ctx: self.runtime.backend(a, p, c),
                              agent_id=self.agent_id, arguments=dict(action.arguments), resource_type=self.runtime.pool(action),
                              estimated_cost=self.runtime.estimate(action), metadata=meta))
            run.tasks[aid] = task_id
            if speculative:
                self.emit("SPECULATIVE_TASK_ADMITTED", {"plan_id": self._plan.plan_id, "branch_id": run.branch.branch_id,
                                                        "task_id": task_id, "action_id": aid, "tool": action.tool,
                                                        "speculative_spent": self._spec_spent})
        if tasks:
            self.scheduler.submit(tasks)
        self._resolve(run)

    def _on_finished(self, task_id: str) -> None:
        for run in self._runs:
            aid = next((a for a, t in run.tasks.items() if t == task_id), None)
            if aid is None:
                continue
            task = self.scheduler.task(task_id)
            self._record(run, aid, task)
            if task_id in self._cancel_requested or aid in run.ctx.results:
                return
            if task.status is TaskStatus.COMPLETED:
                run.payloads[aid] = task.result
            elif task.status is TaskStatus.CANCELLED:
                return  # re-submitted elsewhere or pruned
            else:
                reason = task.failure_reason or task.status.value.lower()
                run.payloads[aid] = {"__failure__": reason}
            if run.role == "speculative":
                self.emit("SPECULATIVE_TASK_COMPLETED", {"plan_id": self._plan.plan_id, "branch_id": run.branch.branch_id,
                                                         "task_id": task_id, "status": task.status.value})
            self._commit_ready(run)
            self._submit_ready(run)
            return

    def _commit_ready(self, run: _Run) -> None:
        """Commit finished actions in the branch's fixed topological order (deterministic memory IDs)."""
        for aid in run.order:
            if aid in run.ctx.results or aid in run.skipped:
                continue
            if aid not in run.payloads:
                return
            action = _action(run.branch, aid)
            payload = run.payloads[aid]
            if isinstance(payload, dict) and "__failure__" in payload:
                result = self.runtime.failed(action, payload["__failure__"])
            else:
                result = self.runtime.commit(action, run.prepared[aid], payload, run.ctx,
                                             announce=None if run.ctx.isolated else self._announcer(run, aid))
            run.ctx.results[aid] = result
            run.committed.append(aid)
            self._after_commit(run, aid)

    def _announcer(self, run: _Run, aid: str):
        task_id = run.tasks.get(aid)
        return {"task": self.scheduler.task(task_id) if task_id else None, "branch": run.branch, "action_id": aid,
                "plan_id": self._plan.plan_id, "adopted": run.speculated}

    def _after_commit(self, run: _Run, aid: str) -> None:
        result = run.ctx.results[aid]
        if not getattr(result, "ok", False):
            for child in _descendants(run.branch, aid):
                self._skip(run, child, f"dependency {aid} failed")
        self._resolve(run)

    def _skip(self, run: _Run, aid: str, reason: str) -> None:
        if aid in run.ctx.results or aid in run.skipped:
            return
        run.skipped[aid] = reason
        for child in _descendants(run.branch, aid):
            run.skipped.setdefault(child, f"dependency {aid} skipped")
        self._resolve(run)

    def _resolve(self, run: _Run) -> None:
        if run.outcome is not None:
            return
        goal = run.branch.goal
        if goal in run.ctx.results:
            run.outcome = self.runtime.satisfied(_action(run.branch, goal), run.ctx.results[goal])
        elif goal in run.skipped:
            run.outcome = False

    def _prune(self, runs: list[_Run], necessary: set[int], winner: int | None) -> None:
        """Stop work that is no longer needed. Started work stays charged."""
        for run in runs:
            if run.index in necessary and (winner is None or run.index == winner or run.outcome is not None):
                pending_unneeded = [t for a, t in run.tasks.items() if a not in run.ctx.results]
                if not pending_unneeded:
                    continue
            ids = [t for a, t in run.tasks.items() if not self.scheduler.task(t).terminal]
            if not ids:
                if run.index not in necessary:
                    run.branch.status = "pruned"
                    run.branch.pruning_reason = run.branch.pruning_reason or ("not needed" if winner is not None else "plan ended")
                continue
            cancelled = set(self.scheduler.cancel(ids))
            for tid in ids:
                if tid in cancelled:
                    self.emit("SPECULATIVE_TASK_PRUNED" if run.role == "speculative" else "PLAN_TASK_PRUNED",
                              {"plan_id": self._plan.plan_id, "branch_id": run.branch.branch_id, "task_id": tid,
                               "refund": "reservation released (never dispatched)"})
                else:
                    self._cancel_requested.add(tid)
                    self.emit("SPECULATIVE_TASK_CANCEL_REQUESTED", {
                        "plan_id": self._plan.plan_id, "branch_id": run.branch.branch_id, "task_id": tid,
                        "backend_cancelled": False,
                        "note": "already running: the backend call cannot be cancelled; it is charged and its result discarded"})
            if run.index not in necessary:
                run.branch.status = "pruned"
                run.branch.pruning_reason = "not needed: another branch reached the goal" if winner is not None else "plan ended"

    def _record(self, run: _Run, aid: str, task: Task) -> None:
        self._records.append({"task_id": task.task_id, "branch": run.branch.name, "action_id": aid, "tool": task.operation,
                              "speculative": bool(task.metadata.get("speculative")), "status": task.status.value,
                              "start_time": task.timing.get("start_time"), "finish_time": task.timing.get("finish_time"),
                              "budget_used": task.timing.get("budget_charged", 0)})

    def settle(self, timeout: float = 30.0) -> dict[str, Any]:
        """Wait for cancel-requested work to finish physically; return wasted-work accounting."""
        ids = list(self._cancel_requested)
        self.scheduler.wait(ids, timeout=timeout)
        wasted = []
        used_branches = {r.index for r in self._runs if r.role == "necessary"}
        for run in self._runs:
            for aid, tid in run.tasks.items():
                task = self.scheduler.task(tid)
                if run.index not in used_branches and task.timing.get("start_time") is not None:
                    wasted.append(task)
        return {"wasted_calls": len(wasted),
                "wasted_seconds": sum((t.timing.get("finish_time") or t.timing.get("returned_time") or 0) - t.timing["start_time"]
                                      for t in wasted if (t.timing.get("finish_time") or t.timing.get("returned_time")) is not None),
                "cancel_requested": len(ids)}


def _action(branch: Branch, aid: str) -> PlanAction:
    return next(a for a in branch.actions if a.action_id == aid)


def _topological(branch: Branch) -> list[str]:
    order, placed = [], set()
    pending = [a.action_id for a in branch.actions]
    while pending:
        for aid in pending:
            if all(d in placed for d in _action(branch, aid).depends_on):
                order.append(aid)
                placed.add(aid)
                pending.remove(aid)
                break
    return order


def _descendants(branch: Branch, aid: str) -> list[str]:
    found, stack = [], [aid]
    while stack:
        node = stack.pop()
        for action in branch.actions:
            if node in action.depends_on and action.action_id not in found:
                found.append(action.action_id)
                stack.append(action.action_id)
    return found
