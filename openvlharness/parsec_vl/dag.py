"""Executable task model and dependency graph for PARSEC-VL.

A ``Task`` is one unit of validated work (for example one tool call whose
arguments were already validated by the harness). Tasks form a DAG through
``dependency_ids``; the scheduler (``scheduler.py``) only runs a task after
every prerequisite has COMPLETED and published its result.

Graph quantities used for fixed-workload analysis (Brent/Graham style):

* ``T1``     total work: sum of task durations;
* ``Tinf``   critical path: longest duration-weighted dependency path;
* ``T1 / Tinf`` available parallelism.

They are exact only for a fixed DAG with known durations. Adaptive agent
trajectories decide their future work online, so these numbers describe the
recorded or declared graph, never a bound on unknown future work.
"""

from __future__ import annotations

import enum
import itertools
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


class TaskStatus(str, enum.Enum):
    CREATED = "CREATED"
    BLOCKED = "BLOCKED"        # waiting for prerequisites
    READY = "READY"            # prerequisites complete; waiting for a worker/resource/budget
    RESERVED = "RESERVED"      # budget and resource held; handed to a worker
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"    # withdrawn before it ran (e.g. shutdown)
    SKIPPED = "SKIPPED"        # cannot run because a prerequisite did not complete


TERMINAL = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.SKIPPED})

TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.BLOCKED, TaskStatus.READY, TaskStatus.CANCELLED, TaskStatus.SKIPPED}),
    TaskStatus.BLOCKED: frozenset({TaskStatus.READY, TaskStatus.CANCELLED, TaskStatus.SKIPPED}),
    # READY -> FAILED: admission refused (budget denied); nothing was charged or run.
    TaskStatus.READY: frozenset({TaskStatus.RESERVED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.SKIPPED}),
    # RESERVED -> CANCELLED releases the budget reservation (never dispatched).
    TaskStatus.RESERVED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    # A running task is never cancelled: its backend call is already in flight.
    TaskStatus.RUNNING: frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.SKIPPED: frozenset(),
}


class InvalidTransition(RuntimeError):
    pass


class GraphError(ValueError):
    """Invalid task graph: duplicate IDs, missing dependencies, or a cycle."""


@dataclass
class TaskOutput:
    """Optional richer return value of a task body."""

    value: Any = None
    artifact_refs: tuple[str, ...] = ()


_sequence = itertools.count()


@dataclass
class Task:
    """One executable unit of validated work.

    ``body(inputs)`` receives ``{dependency_id: result}`` for completed
    prerequisites only and returns the result (or a ``TaskOutput``).
    ``estimated_cost`` is the declared or measured duration estimate in
    seconds used by the critical-path policy (E2); ``None`` means unknown.
    ``budget_resource``/``budget_amount`` are charged against the run's
    existing budget ledger when the task is admitted.
    """

    task_id: str
    operation: str
    body: Callable[[dict[str, Any]], Any] | None = None
    dependency_ids: tuple[str, ...] = ()
    run_id: str = ""
    agent_id: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)
    input_artifact_refs: tuple[str, ...] = ()
    resource_type: str = "cpu"
    estimated_cost: float | None = None
    budget_resource: str | None = "tool_calls"
    budget_amount: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
    # Runtime state (owned by the scheduler).
    status: TaskStatus = TaskStatus.CREATED
    priority: float = 0.0
    result: Any = None
    result_artifact_refs: tuple[str, ...] = ()
    failure_reason: str | None = None
    timing: dict[str, Any] = field(default_factory=dict)
    sequence: int = field(default_factory=lambda: next(_sequence))

    def __post_init__(self) -> None:
        if not self.task_id or not isinstance(self.task_id, str):
            raise GraphError("task_id must be a non-empty string")
        self.dependency_ids = tuple(dict.fromkeys(self.dependency_ids))
        if self.task_id in self.dependency_ids:
            raise GraphError(f"task {self.task_id} depends on itself")
        if self.estimated_cost is not None and self.estimated_cost < 0:
            raise GraphError("estimated_cost must be nonnegative")
        if type(self.budget_amount) is not int or self.budget_amount < 0:
            raise GraphError("budget_amount must be a nonnegative integer")

    def transition(self, target: TaskStatus) -> None:
        if target not in TRANSITIONS[self.status]:
            raise InvalidTransition(f"{self.task_id}: {self.status.value} -> {target.value}")
        self.status = target

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL

    def record(self) -> dict[str, Any]:
        """JSON-safe telemetry record (no body, no raw result)."""
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "operation": self.operation,
            "dependency_ids": list(self.dependency_ids),
            "input_artifact_refs": list(self.input_artifact_refs),
            "resource_pool": self.resource_type,
            "estimated_cost": self.estimated_cost,
            "priority": self.priority,
            "status": self.status.value,
            "failure_reason": self.failure_reason,
            "result_artifact_refs": list(self.result_artifact_refs),
            "budget_resource": self.budget_resource,
            "budget_used": self.timing.get("budget_charged", 0),
            **{k: v for k, v in self.timing.items() if k != "budget_charged"},
            **({"metadata": self.metadata} if self.metadata else {}),
        }


def validate_graph(tasks: Iterable[Task], existing: Mapping[str, Task] | None = None) -> list[Task]:
    """Validate new tasks against themselves and already-known tasks.

    Rejects duplicate IDs, dependencies that name no known task, and cycles.
    Returns the new tasks in a topological order (stable by creation order).
    """
    existing = existing or {}
    new = list(tasks)
    ids = [task.task_id for task in new]
    duplicates = {i for i in ids if ids.count(i) > 1} | (set(ids) & set(existing))
    if duplicates:
        raise GraphError(f"duplicate task id(s): {sorted(duplicates)}")
    known = set(ids) | set(existing)
    for task in new:
        missing = [dep for dep in task.dependency_ids if dep not in known]
        if missing:
            raise GraphError(f"task {task.task_id} depends on unknown task(s): {missing}")
    # Kahn's algorithm over the new tasks (existing tasks cannot depend on new ones).
    by_id = {task.task_id: task for task in new}
    indegree = {task.task_id: sum(dep in by_id for dep in task.dependency_ids) for task in new}
    children: dict[str, list[str]] = {task.task_id: [] for task in new}
    for task in new:
        for dep in task.dependency_ids:
            if dep in by_id:
                children[dep].append(task.task_id)
    frontier = sorted((t for t in new if indegree[t.task_id] == 0), key=lambda t: t.sequence)
    order: list[Task] = []
    while frontier:
        task = frontier.pop(0)
        order.append(task)
        for child in children[task.task_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                frontier.append(by_id[child])
                frontier.sort(key=lambda t: t.sequence)
    if len(order) != len(new):
        cyclic = sorted(tid for tid, deg in indegree.items() if deg > 0)
        raise GraphError(f"dependency cycle among: {cyclic}")
    return order


def successors(tasks: Mapping[str, Task]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {tid: [] for tid in tasks}
    for task in tasks.values():
        for dep in task.dependency_ids:
            if dep in result:
                result[dep].append(task.task_id)
    return result


def bottom_levels(tasks: Mapping[str, Task], default_cost: float = 1.0) -> dict[str, float]:
    """Longest duration-weighted path from each task to a sink, including itself.

    Uses ``estimated_cost``; tasks without an estimate count ``default_cost``
    (with every estimate missing this is the number of tasks on the longest
    downstream chain). Only tasks currently in the graph are considered: the
    scheduler never looks at work that has not been submitted yet.
    """
    succ = successors(tasks)
    levels: dict[str, float] = {}

    def cost(task: Task) -> float:
        return default_cost if task.estimated_cost is None else float(task.estimated_cost)

    # Reverse topological order via DFS with memoization (graph is acyclic).
    def visit(tid: str) -> float:
        if tid in levels:
            return levels[tid]
        stack = [(tid, False)]
        while stack:
            node, expanded = stack.pop()
            if node in levels:
                continue
            if expanded:
                levels[node] = cost(tasks[node]) + max((levels[c] for c in succ[node]), default=0.0)
            else:
                stack.append((node, True))
                stack.extend((c, False) for c in succ[node] if c not in levels)
        return levels[tid]

    for tid in tasks:
        visit(tid)
    return levels


def graph_metrics(tasks: Mapping[str, Task] | Iterable[Task], durations: Mapping[str, float] | None = None) -> dict[str, Any]:
    """T1, Tinf, available parallelism, and per-resource work for a fixed DAG.

    ``durations`` (measured) override ``estimated_cost`` (declared). Tasks with
    neither are reported as unknown and excluded, and the result says so.
    """
    if not isinstance(tasks, Mapping):
        tasks = {task.task_id: task for task in tasks}
    durations = dict(durations or {})
    known = {tid: durations.get(tid, task.estimated_cost) for tid, task in tasks.items()}
    unknown = sorted(tid for tid, d in known.items() if d is None)
    weighted = {
        tid: Task(task_id=tid, operation=task.operation, dependency_ids=task.dependency_ids,
                  resource_type=task.resource_type, estimated_cost=known[tid] or 0.0)
        for tid, task in tasks.items()
    }
    levels = bottom_levels(weighted, default_cost=0.0)
    t1 = sum(d for d in known.values() if d is not None)
    tinf = max(levels.values(), default=0.0)
    per_resource: dict[str, float] = {}
    for tid, task in tasks.items():
        if known[tid] is not None:
            per_resource[task.resource_type] = per_resource.get(task.resource_type, 0.0) + known[tid]
    return {
        "tasks": len(tasks),
        "T1": t1,
        "Tinf": tinf,
        "available_parallelism": (t1 / tinf) if tinf > 0 else None,
        "work_by_resource": per_resource,
        "unknown_durations": unknown,
    }


def lower_bound(metrics: Mapping[str, Any], capacities: Mapping[str, int], workers: int | None = None) -> dict[str, Any]:
    """T_LB = max(T_critical_path, max_r W_r / m_r[, T1 / p]) for a fixed DAG.

    Assumes fixed task durations, no preemption, and that a task occupies one
    unit of its resource pool and one worker for its whole duration.
    """
    terms = {"critical_path": metrics["Tinf"]}
    for resource, work in metrics["work_by_resource"].items():
        capacity = capacities.get(resource)
        if capacity:
            terms[f"resource:{resource}"] = work / capacity
    if workers:
        terms["workers"] = metrics["T1"] / workers
    binding = max(terms, key=terms.get)
    return {"T_LB": terms[binding], "binding_term": binding, "terms": terms}
