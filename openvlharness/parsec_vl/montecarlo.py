"""Monte Carlo evaluation of candidate plans on real CPU processes.

A plan is compiled into a compact, picklable *simulation spec*: per action its
resource pool, dependencies, duration model, and probability of producing
usable evidence; per branch its goal action. One rollout draws every action's
duration and outcome, then runs a discrete-event list-scheduling simulation of
the plan under one *option* (which alternative branches start speculatively)
with the given worker slots and pool capacities. It returns:

* latency    — time until a branch's goal is satisfied or every branch has failed;
* cost       — tool calls started (started work is charged, used or not);
* success    — the operational goal was reached (e.g. "a readable OCR result");
* wasted     — calls and busy seconds spent on work whose result was not needed.

These are estimates of an *operational* condition under a declared outcome
model, not probabilities that a final answer is correct.

Parallelism: rollouts are split into fixed-size batches executed by a persistent
``ProcessPoolExecutor`` (spawn start method: safe with the runtime's threads).
The batch layout and each rollout's seed depend only on (base seed, rollout
index), never on the number of processes, and partial sums are combined in
batch order, so 1, 2, 4, or 8 processes produce bitwise-identical estimates.
Candidates share rollout seeds (common random numbers), so they are compared on
the same draws. ``processes=0`` runs the identical batches in-process.
"""

from __future__ import annotations

import heapq
import math
import multiprocessing
import atexit
import os
import random
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from typing import Any

# ---- simulation ------------------------------------------------------------------------------


def _draw(model: tuple, rng: random.Random) -> float:
    kind = model[0]
    if kind == "fixed":
        return float(model[1])
    if kind == "lognormal":  # (median, sigma)
        return model[1] * math.exp(model[2] * rng.gauss(0.0, 1.0))
    if kind == "empirical":  # (samples,)
        return model[1][int(rng.random() * len(model[1]))]
    if kind == "uniform":
        return rng.uniform(model[1], model[2])
    raise ValueError(f"unknown duration model {kind!r}")


def rollout(spec: dict, option: tuple[int, ...], rng: random.Random) -> tuple[float, int, bool, int, float]:
    """Simulate one execution; returns (latency, cost, success, wasted_calls, wasted_seconds).

    Branch 0 is necessary from the start; branches in ``option`` start as
    speculation (lower priority). When every necessary branch has failed, the
    next alternative becomes necessary; if it already finished speculatively,
    its result is adopted at that moment. Running work cannot be cancelled, so a
    started speculative action costs its full duration.
    """
    actions = spec["actions"]
    branches = spec["branches"]
    children = spec["children"]
    duration, ok = {}, {}
    for aid in spec["order"]:  # fixed draw order: common random numbers across options
        duration[aid] = _draw(actions[aid]["duration"], rng)
        ok[aid] = rng.random() < actions[aid]["p_ok"]
    in_use = {pool: 0 for pool in spec["capacities"]}
    slots, budget = spec["workers"], spec.get("budget")
    necessary = [0]
    started: dict[str, float] = {}
    done: set[str] = set()
    failed: set[str] = set()
    running: list[tuple[float, int, str]] = []
    now, cost, seq, winner = 0.0, 0, 0, None

    def fail(aid: str) -> None:  # the action and every unstarted dependent are finished, failed
        stack = [aid]
        while stack:
            node = stack.pop()
            done.add(node)
            failed.add(node)
            stack.extend(c for c in children[node] if c not in started and c not in done)

    def state(b: int) -> bool | None:
        goal = branches[b]["goal"]
        return None if goal not in done else goal not in failed

    while True:
        while True:  # promote alternatives while every necessary branch has failed
            states = [state(b) for b in necessary]
            if True in states:
                winner = necessary[states.index(True)]
                break
            if all(s is False for s in states) and len(necessary) < len(branches):
                necessary.append(next(b for b in range(len(branches)) if b not in necessary))
                continue
            break
        if winner is not None or all(state(b) is False for b in necessary):
            break
        queue = [a for b in necessary for a in branches[b]["actions"]]
        queue += [a for b in option if b not in necessary for a in branches[b]["actions"]]
        for aid in queue:
            if slots == 0:
                break
            if aid in started or aid in done or not all(d in done and d not in failed for d in actions[aid]["deps"]):
                continue
            pool = actions[aid]["pool"]
            if in_use[pool] >= spec["capacities"][pool]:
                continue
            if budget is not None and cost >= budget:
                fail(aid)  # denied by the budget: never starts
                continue
            in_use[pool] += 1
            slots -= 1
            cost += 1
            started[aid] = now
            seq += 1
            heapq.heappush(running, (now + duration[aid], seq, aid))
        if not running:
            if any(state(b) is None for b in necessary):
                break  # nothing can make progress (defensive; unreachable for valid specs)
            continue
        now, _, aid = heapq.heappop(running)
        in_use[actions[aid]["pool"]] -= 1
        slots += 1
        if ok[aid]:
            done.add(aid)
        else:
            fail(aid)
    branch_of = spec["branch_of"]
    wasted = [aid for aid in started if branch_of[aid] not in necessary]
    return now, cost, winner is not None, len(wasted), sum(duration[a] for a in wasted)


def run_batch(spec: dict, option: tuple[int, ...], seed: int, start: int, count: int) -> tuple:
    """Rollouts [start, start+count) — the unit of work sent to a process."""
    cpu0 = time.process_time()
    n = s_t = s_t2 = s_c = s_ok = s_wc = s_ws = 0.0
    latencies = []
    for index in range(start, start + count):
        rng = random.Random(seed * 1_000_003 + index)
        latency, cost, success, wasted_calls, wasted_seconds = rollout(spec, option, rng)
        n += 1
        s_t += latency
        s_t2 += latency * latency
        s_c += cost
        s_ok += success
        s_wc += wasted_calls
        s_ws += wasted_seconds
        latencies.append(latency)
    return (n, s_t, s_t2, s_c, s_ok, s_wc, s_ws, tuple(latencies), time.process_time() - cpu0, os.getpid())


# ---- evaluation ------------------------------------------------------------------------------


@dataclass
class Estimate:
    candidate: int
    rollouts: int
    latency_mean: float
    latency_sd: float
    latency_p90: float
    cost_mean: float
    p_operational: float
    wasted_calls_mean: float
    wasted_seconds_mean: float

    def to_dict(self) -> dict[str, Any]:
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


@dataclass
class Evaluation:
    estimates: list[Estimate]
    complete: bool
    wall_seconds: float
    cpu_seconds: float
    processes: int
    batches: int
    batches_done: int
    worker_pids: list[int] = field(default_factory=list)
    timing: dict[str, float] = field(default_factory=dict)


class PlanEvaluator:
    """Persistent process pool for Monte Carlo plan evaluation.

    The pool is created lazily on the first evaluation (or by an explicit
    ``start()``), exactly once even if several agent threads ask at the same
    time, and reused for every later evaluation until ``shutdown()``.
    ``on_start(seconds)`` is called once with the measured cold-start time.
    """

    _shared: dict[int, "PlanEvaluator"] = {}
    _shared_lock = threading.Lock()

    def __init__(self, processes: int = 4, batch_size: int = 250, start_method: str = "spawn", on_start=None) -> None:
        self.processes = processes
        self.batch_size = batch_size
        self.start_method = start_method
        self.on_start = on_start
        self._pool: ProcessPoolExecutor | None = None
        self._lock = threading.Lock()
        self.startup_seconds = 0.0
        self.starts = 0
        self.restarts = 0

    @property
    def started(self) -> bool:
        return self._pool is not None

    @classmethod
    def shared(cls, processes: int) -> "PlanEvaluator":
        """A process-wide warm pool reused across runs (explicit opt-in; see ``shutdown_shared``)."""
        with cls._shared_lock:
            evaluator = cls._shared.get(processes)
            if evaluator is None:
                evaluator = cls._shared[processes] = cls(processes=processes)
            return evaluator

    @classmethod
    def shutdown_shared(cls) -> None:
        with cls._shared_lock:
            for evaluator in cls._shared.values():
                evaluator.shutdown()
            cls._shared.clear()

    def start(self) -> float:
        """Create the pool and make every worker import this module (cold start), once."""
        if self.processes <= 0:
            return 0.0
        with self._lock:
            if self._pool is not None:
                return 0.0
            began = time.perf_counter()
            context = multiprocessing.get_context(self.start_method)
            pool = ProcessPoolExecutor(max_workers=self.processes, mp_context=context)
            # Touch every worker so later timings measure warm execution only.
            list(pool.map(_warm, range(self.processes * 2)))
            self._pool = pool
            self.startup_seconds = time.perf_counter() - began
            self.starts += 1
        if callable(self.on_start):
            try:
                self.on_start(self.startup_seconds)
            except Exception:  # noqa: BLE001 - telemetry only
                pass
        return self.startup_seconds

    def shutdown(self) -> None:
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)

    def __enter__(self) -> "PlanEvaluator":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.shutdown()

    def evaluate(self, candidates: list[tuple[dict, tuple[int, ...]]], rollouts: int, seed: int,
                 time_budget: float | None = None) -> Evaluation:
        """Estimate every (spec, option) candidate with the same ``rollouts`` seeds."""
        began = time.perf_counter()
        units = []
        for start in range(0, rollouts, self.batch_size):  # round-robin: partial results cover every candidate
            for index, (spec, option) in enumerate(candidates):
                units.append((index, start, min(self.batch_size, rollouts - start)))
        results: dict[tuple[int, int], tuple] = {}
        timing = {"submit": 0.0, "execute": 0.0, "aggregate": 0.0}
        if self.processes <= 0:
            for index, start, count in units:
                if time_budget is not None and time.perf_counter() - began > time_budget:
                    break
                spec, option = candidates[index]
                results[(index, start)] = run_batch(spec, option, seed, start, count)
        else:
            for attempt in (1, 2):  # a crashed worker breaks the pool: restart it once and redo missing batches
                try:
                    self._run_pool(units, candidates, seed, results, timing, began, time_budget)
                    break
                except BrokenProcessPool:
                    self.restarts += 1
                    self._pool = None
                    if attempt == 2:
                        raise
        timing["execute"] = time.perf_counter() - began - timing["submit"]
        t_agg = time.perf_counter()
        # Workers finish out of order. Equal sample counts alone do not guarantee
        # equal seeds: stop at the first batch missing for any candidate, including
        # batch zero. Later completed batches remain charged CPU work but cannot
        # enter this comparison.
        common_starts = []
        for start in range(0, rollouts, self.batch_size):
            if not all((index, start) in results for index in range(len(candidates))):
                break
            common_starts.append(start)
        estimates = [_combine(index, [results[(index, start)] for start in common_starts])
                     for index in range(len(candidates))]
        timing["aggregate"] = time.perf_counter() - t_agg
        cpu = sum(r[8] for r in results.values())
        return Evaluation(estimates, len(results) == len(units), time.perf_counter() - began, cpu,
                          self.processes, len(units), len(results), sorted({r[9] for r in results.values()}), timing)


def _run_pool_impl(self, units, candidates, seed, results, timing, began, time_budget) -> None:
    """Keep at most 2 x processes batches in flight, submitted in unit order; stop at the time budget."""
    self.start()
    todo = iter([u for u in units if (u[0], u[1]) not in results])
    window = 2 * self.processes
    in_flight: dict = {}

    def submit_next() -> bool:
        unit = next(todo, None)
        if unit is None:
            return False
        i, s, c = unit
        t = time.perf_counter()
        in_flight[self._pool.submit(run_batch, candidates[i][0], candidates[i][1], seed, s, c)] = (i, s)
        timing["submit"] += time.perf_counter() - t
        return True

    try:
        while len(in_flight) < window and submit_next():
            pass
        while in_flight:
            remaining = None if time_budget is None else time_budget - (time.perf_counter() - began)
            if remaining is not None and remaining <= 0:
                break
            finished, _ = wait(list(in_flight), timeout=remaining, return_when=FIRST_COMPLETED)
            for future in finished:
                results[in_flight.pop(future)] = future.result()
                if remaining is None or time.perf_counter() - began < time_budget:
                    submit_next()
    finally:
        for future in in_flight:  # over the time budget: queued batches are dropped
            future.cancel()


PlanEvaluator._run_pool = _run_pool_impl


def _warm(_: int) -> int:
    return os.getpid()


def _combine(index: int, parts: list[tuple]) -> Estimate:
    n = sum(p[0] for p in parts)
    if not n:
        return Estimate(index, 0, math.inf, 0.0, math.inf, math.inf, 0.0, 0.0, 0.0)
    s_t = sum(p[1] for p in parts)
    s_t2 = sum(p[2] for p in parts)
    latencies = sorted(x for p in parts for x in p[7])
    mean = s_t / n
    variance = max(0.0, s_t2 / n - mean * mean)
    return Estimate(index, int(n), mean, math.sqrt(variance), latencies[min(len(latencies) - 1, int(0.9 * len(latencies)))],
                    sum(p[3] for p in parts) / n, sum(p[4] for p in parts) / n,
                    sum(p[5] for p in parts) / n, sum(p[6] for p in parts) / n)


# ---- plan -> spec ----------------------------------------------------------------------------


@dataclass
class OutcomeModel:
    """Per-tool duration models and success probabilities, with their provenance.

    ``source`` says where the numbers come from: ``empirical`` (prior recorded
    runs, never the current task), ``declared`` (a fixture's stated model), or
    ``heuristic`` (fallback priors). Nothing here is calibrated answer accuracy.
    """

    durations: dict[str, tuple] = field(default_factory=dict)
    p_ok: dict[str, float] = field(default_factory=dict)
    source: str = "heuristic"
    default_duration: tuple = ("lognormal", 1.0, 0.5)
    default_p_ok: float = 0.5

    def duration(self, tool: str) -> tuple:
        return self.durations.get(tool, self.default_duration)

    def success(self, tool: str) -> float:
        return self.p_ok.get(tool, self.default_p_ok)

    def median(self, tool: str) -> float:
        model = self.duration(tool)
        if model[0] == "empirical":
            values = sorted(model[1])
            return values[len(values) // 2]
        return float(model[1])

    @classmethod
    def load(cls, path: str) -> "OutcomeModel":
        import json

        data = json.loads(open(path, encoding="utf-8").read())
        return cls(durations={k: tuple(x if not isinstance(x, list) else tuple(x) for x in val)
                              for k, val in data["durations"].items()},
                   p_ok=data.get("p_ok", {}), source=data.get("source", "empirical"))

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "p_ok": self.p_ok,
                "durations": {k: (v[0], len(v[1])) if v[0] == "empirical" else v for k, v in self.durations.items()}}


# Heuristic priors: medians from the Phase 1 probe of this machine's services
# (outputs/parsec_vl/probe); success rates are uninformed 0.5 unless measured.
PROBE_PRIORS = OutcomeModel(
    durations={"Visual_Grounding_Tool": ("lognormal", 0.93, 0.3), "OCR_Tool": ("lognormal", 0.23, 0.3),
               "Depth_Estimation_Tool": ("lognormal", 0.34, 0.3), "Zoom_In_Tool": ("lognormal", 0.064, 0.3)},
    p_ok={}, source="heuristic")


def compile_spec(branches: list[list[tuple[str, str, tuple[str, ...]]]], goals: list[str], model: OutcomeModel,
                 pools: dict[str, str], capacities: dict[str, int], workers: int, budget: int | None = None) -> dict:
    """Simulation spec from branches of (action_id, tool, depends_on); ``pools`` maps tool -> pool."""
    actions = {}
    for branch in branches:
        for aid, tool, deps in branch:
            pool = pools.get(tool, "cpu")
            actions[aid] = {"pool": pool, "deps": tuple(deps), "duration": model.duration(tool), "p_ok": model.success(tool)}
    return finalize_spec({"actions": actions, "workers": workers, "budget": budget, "capacities": capacities,
                          "branches": [{"actions": [a for a, _, _ in branch], "goal": goal} for branch, goal in zip(branches, goals)]})


def finalize_spec(spec: dict) -> dict:
    """Add derived fields (draw order, children, branch of each action, used pool capacities)."""
    actions = spec["actions"]
    children = {aid: [] for aid in actions}
    for aid, action in actions.items():
        for dep in action["deps"]:
            children[dep].append(aid)
    used = {a["pool"] for a in actions.values()}
    return {**spec, "order": sorted(actions), "children": children,
            "branch_of": {aid: b for b, branch in enumerate(spec["branches"]) for aid in branch["actions"]},
            "capacities": {p: spec["capacities"].get(p, 1) for p in used}}


atexit.register(PlanEvaluator.shutdown_shared)


# ---- closed-form heuristic (no simulation) ---------------------------------------------------


def _median(model: tuple) -> float:
    if model[0] in ("lognormal", "fixed"):
        return float(model[1])
    if model[0] == "uniform":
        return (model[1] + model[2]) / 2
    values = sorted(model[1])
    return values[len(values) // 2]


def heuristic_estimate(spec: dict, option: tuple[int, ...]) -> tuple[float, float]:
    """Declared closed form (medians, independent outcomes, no contention): (latency, tool calls).

    Branches are tried in order; a branch is reached with the probability that
    every earlier one missed its goal. Speculative branches start at time 0, so
    only their remaining time counts when they are reached.
    """
    reach, latency, cost, elapsed = 1.0, 0.0, 0.0, 0.0
    for index, branch in enumerate(spec["branches"]):
        duration, p = 0.0, 1.0
        for aid in branch["actions"]:
            duration += _median(spec["actions"][aid]["duration"])
            p *= spec["actions"][aid]["p_ok"]
        speculative = index in option
        own = max(0.0, duration - elapsed) if speculative else duration
        latency += reach * own
        cost += (1.0 if speculative else reach) * len(branch["actions"])
        elapsed += own if index == 0 else 0.0
        reach *= 1 - p
    return latency, cost
