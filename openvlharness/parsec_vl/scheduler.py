"""Dependency-aware task scheduler with three policies on one engine.

* ``e0`` sequential FIFO     — one task at a time, in the order tasks became ready.
* ``e1`` parallel FIFO       — up to ``workers`` tasks at once, ready order.
* ``e2`` critical path first — up to ``workers`` tasks at once, highest bottom
  level first (estimated remaining downstream work, ``dag.bottom_levels``),
  ready order breaks ties. Estimates come from ``Task.estimated_cost``; when
  missing, every task counts 1 (longest downstream chain length).

A task is dispatched only when (1) every prerequisite COMPLETED, (2) a worker
slot is free, (3) its resource pool has capacity, and (4) its budget cost was
reserved. Worker slots are threads: suitable for I/O-bound work (HTTP tool
services, model servers) where the GIL is released while waiting. Pure-Python
CPU work does not speed up on threads; CPU-parallel planning is Phase 2.

The engine is long-lived: several agents may submit tasks concurrently and a
new task may depend on any earlier task. All state changes happen under one
condition variable; task bodies and telemetry callbacks run outside it.
"""

from __future__ import annotations

import itertools
import statistics
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from .dag import TERMINAL, Task, TaskOutput, TaskStatus, bottom_levels, successors, validate_graph
from .resources import BudgetAdapter, ResourcePools

POLICIES = {
    "e0": "sequential_fifo",
    "e1": "parallel_fifo",
    "e2": "critical_path",
}
_ALIASES = {"sequential": "e0", "sequential_fifo": "e0", "fifo": "e1", "parallel_fifo": "e1",
            "critical_path": "e2", "cp": "e2"}


def normalize_policy(policy: str) -> str:
    key = str(policy).lower()
    key = _ALIASES.get(key, key)
    if key not in POLICIES:
        raise ValueError(f"unknown scheduling policy {policy!r}; use one of {sorted(POLICIES)}")
    return key


def _wall(epoch_wall: float, offset: float) -> str:
    return datetime.fromtimestamp(epoch_wall + offset, tz=timezone.utc).isoformat()


class Scheduler:
    def __init__(
        self,
        *,
        policy: str = "e1",
        workers: int = 4,
        capacities: Mapping[str, int] | None = None,
        budget: BudgetAdapter | None = None,
        run_id: str = "",
        event_sink: Callable[[str, dict[str, Any]], Any] | None = None,
        task_timeout: float | None = None,
        default_cost: float = 1.0,
        speculative_limits: Mapping[str, int] | None = None,
        necessary_slot_reserve: int = 0,
    ) -> None:
        self.policy = normalize_policy(policy)
        if type(workers) is not int or workers < 1:
            raise ValueError("workers must be a positive integer")
        # E0 is the fixed-workload reference: exactly one task at a time.
        self.workers = 1 if self.policy == "e0" else workers
        self.requested_workers = workers
        self.run_id = run_id
        self.pools = ResourcePools(dict(capacities or {"cpu": workers}))
        self.budget = budget
        self.event_sink = event_sink
        self.task_timeout = task_timeout
        # Speculation (Phase 2): tasks with metadata["speculative"] always queue behind
        # necessary ones, may use at most speculative_limits[pool] units of a pool, and
        # never take the last necessary_slot_reserve free worker slots.
        self.speculative_limits = dict(speculative_limits or {})
        self.necessary_slot_reserve = necessary_slot_reserve
        self._spec_in_use: dict[str, int] = {}
        self.default_cost = default_cost
        self._cond = threading.Condition()
        self._tasks: dict[str, Task] = {}
        self._succ: dict[str, list[str]] = {}
        self._ready: list[str] = []
        self._ready_counter = itertools.count()
        self._running: set[str] = set()
        self._free_slots = list(range(self.workers))
        self._closed = False
        self._epoch = time.monotonic()
        self._epoch_wall = time.time()
        self._admit_seconds = 0.0
        self._physical_invocations = 0
        self._concurrency_samples: list[tuple[float, int]] = []
        self._executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="parsec-worker")
        self._dispatcher = threading.Thread(target=self._dispatch_loop, name="parsec-dispatcher", daemon=True)
        self._dispatcher.start()

    # ---- clock -----------------------------------------------------------------------------
    def _now(self) -> float:
        return time.monotonic() - self._epoch

    # ---- submission ------------------------------------------------------------------------
    def submit(self, tasks: Iterable[Task]) -> list[str]:
        """Validate and enqueue tasks; returns their IDs in topological order."""
        tasks = list(tasks)
        with self._cond:
            if self._closed:
                raise RuntimeError("scheduler is shut down")
            order = validate_graph(tasks, self._tasks)
            for task in order:
                if task.resource_type not in self.pools:
                    raise ValueError(f"task {task.task_id} needs unknown resource pool {task.resource_type!r}")
                if task.status is not TaskStatus.CREATED:
                    raise ValueError(f"task {task.task_id} was already scheduled")
            now = self._now()
            for task in order:
                task.run_id = task.run_id or self.run_id
                self._tasks[task.task_id] = task
                self._succ.setdefault(task.task_id, [])
                for dep in task.dependency_ids:
                    self._succ.setdefault(dep, []).append(task.task_id)
                task.timing.update(created_time=now)
            if self.policy == "e2":
                live = {tid: t for tid, t in self._tasks.items() if not t.terminal}
                for tid, level in bottom_levels(live, self.default_cost).items():
                    live[tid].priority = level
            skipped: list[Task] = []
            for task in order:
                deps = [self._tasks[d] for d in task.dependency_ids]
                bad = next((d for d in deps if d.terminal and d.status is not TaskStatus.COMPLETED), None)
                if bad is not None:
                    task.transition(TaskStatus.SKIPPED)
                    task.failure_reason = f"dependency {bad.task_id} {bad.status.value.lower()}"
                    task.timing["finish_time"] = now
                    skipped.append(task)
                elif all(d.status is TaskStatus.COMPLETED for d in deps):
                    self._make_ready(task, now)
                else:
                    task.transition(TaskStatus.BLOCKED)
            # Admit in the submitting thread: one thread hand-off fewer than waking the dispatcher.
            launched, failed = self._admit()
            self._cond.notify_all()
        for task in skipped + failed:
            self._emit("SCHEDULER_TASK_FINISHED", task)
        self._launch(launched)
        return [task.task_id for task in order]

    def _launch(self, launched: list[tuple[Task, int]]) -> None:
        for task, slot in launched:
            self._executor.submit(self._execute, task, slot)

    def _make_ready(self, task: Task, now: float) -> None:
        task.transition(TaskStatus.READY)
        task.timing["enqueue_time"] = now
        task.timing["_ready_order"] = next(self._ready_counter)
        self._ready.append(task.task_id)

    # ---- dispatch --------------------------------------------------------------------------
    def _policy_key(self, task: Task) -> tuple:
        order = task.timing["_ready_order"]
        speculative = bool(task.metadata.get("speculative"))
        if self.policy == "e2":
            return (speculative, -task.priority, order)
        return (speculative, order)

    def _admit(self) -> tuple[list[tuple[Task, int]], list[Task]]:
        """Choose tasks to start now. Called with the condition held."""
        began = time.perf_counter()
        launched: list[tuple[Task, int]] = []
        failed: list[Task] = []
        for tid in sorted(self._ready, key=lambda t: self._policy_key(self._tasks[t])):
            if not self._free_slots:
                break
            task = self._tasks[tid]
            if self.pools.available(task.resource_type) <= 0:
                if self.policy == "e0":
                    break  # strict FIFO: never overtake the head of the queue
                continue  # work-conserving: tasks for other pools may start
            speculative = bool(task.metadata.get("speculative"))
            if speculative and (
                len(self._free_slots) <= self.necessary_slot_reserve
                or self._spec_in_use.get(task.resource_type, 0)
                >= self.speculative_limits.get(task.resource_type, self.pools.capacities[task.resource_type])
            ):
                continue  # keep capacity for necessary work
            if self.budget is not None:
                granted, reason = self.budget.reserve(task)
                if not granted:
                    self._ready.remove(tid)
                    task.transition(TaskStatus.FAILED)
                    task.failure_reason = f"budget_denied:{reason}"
                    task.timing["finish_time"] = self._now()
                    failed.append(task)
                    failed.extend(self._propagate(task))
                    continue
            if not self.pools.try_acquire(task.resource_type):  # cannot happen: checked above under the lock
                raise RuntimeError("resource accounting inconsistency")
            self._ready.remove(tid)
            slot = self._free_slots.pop(0)
            if speculative:
                self._spec_in_use[task.resource_type] = self._spec_in_use.get(task.resource_type, 0) + 1
            task.transition(TaskStatus.RESERVED)
            task.timing.update(reserved_time=self._now(), worker_id=slot)
            self._running.add(tid)
            launched.append((task, slot))
        if launched:
            self._concurrency_samples.append((self._now(), len(self._running)))
        self._admit_seconds += time.perf_counter() - began
        return launched, failed

    def _dispatch_loop(self) -> None:
        while True:
            with self._cond:
                timed_out = self._check_timeouts()
                launched, failed = self._admit()
                if failed or timed_out:
                    self._cond.notify_all()  # wake wait() callers: these tasks are terminal now
                if not launched and not failed and not timed_out:
                    if self._closed and not self._running and not self._ready:
                        return
                    self._cond.wait(timeout=self._next_deadline())
                    continue
            for task in failed + timed_out:
                self._emit("SCHEDULER_TASK_FINISHED", task)
            self._launch(launched)

    def _next_deadline(self) -> float | None:
        deadlines = [self._tasks[t].timing.get("deadline") for t in self._running]
        deadlines = [d for d in deadlines if d is not None]
        if not deadlines:
            return None if not self._closed else 0.05
        return max(0.0, min(deadlines) - self._now()) + 1e-3

    def _check_timeouts(self) -> list[Task]:
        now = self._now()
        expired = []
        for tid in list(self._running):
            task = self._tasks[tid]
            deadline = task.timing.get("deadline")
            if task.status is TaskStatus.RUNNING and deadline is not None and now >= deadline:
                # The worker thread cannot be killed: the task fails now, its slot and
                # resource stay occupied until the body returns, and that late result
                # is discarded (never published).
                task.transition(TaskStatus.FAILED)
                task.failure_reason = "timeout"
                task.timing.update(finish_time=now, abandoned=True)
                expired.append(task)
                expired.extend(self._propagate(task))
        return expired

    # ---- execution -------------------------------------------------------------------------
    def _execute(self, task: Task, slot: int) -> None:
        with self._cond:
            if task.status is TaskStatus.CANCELLED:  # cancelled after admission, before start
                return
            task.transition(TaskStatus.RUNNING)
            now = self._now()
            timeout = task.metadata.get("timeout_seconds", self.task_timeout) if task.metadata else self.task_timeout
            task.timing.update(start_time=now, start_wall=_wall(self._epoch_wall, now))
            if timeout is not None:
                task.timing["deadline"] = now + timeout
            if self.budget is not None:
                self.budget.settle(task)
            self._physical_invocations += 1
            inputs = {dep: self._tasks[dep].result for dep in task.dependency_ids}
            self._cond.notify_all()
        self._emit("SCHEDULER_TASK_STARTED", task)
        hook = task.metadata.get("on_start") if task.metadata else None
        error: BaseException | None = None
        value: Any = None
        try:
            if callable(hook):
                hook(task)
            value = task.body(inputs) if task.body is not None else None
        except BaseException as exc:  # noqa: BLE001 - isolate arbitrary task failures
            error = exc
        finished: list[Task] = []
        with self._cond:
            now = self._now()
            self.pools.release(task.resource_type)
            self._release_speculative(task)
            self._free_slots.append(slot)
            self._free_slots.sort()
            self._running.discard(task.task_id)
            if self.budget is not None:
                self.budget.finish(task)
            if task.status is TaskStatus.FAILED and task.timing.get("abandoned"):
                task.timing["returned_time"] = now  # late return after timeout: discarded
            elif error is not None:
                task.transition(TaskStatus.FAILED)
                task.failure_reason = f"{type(error).__name__}: {error}"
                task.timing["finish_time"] = now
                finished.append(task)
                finished.extend(self._propagate(task))
            else:
                if isinstance(value, TaskOutput):
                    task.result, task.result_artifact_refs = value.value, tuple(value.artifact_refs)
                else:
                    task.result = value
                # Publish before successors can see it: state change and result are atomic.
                task.transition(TaskStatus.COMPLETED)
                task.timing["finish_time"] = now
                finished.append(task)
                for child_id in self._succ.get(task.task_id, []):
                    child = self._tasks.get(child_id)
                    if child is not None and child.status is TaskStatus.BLOCKED and all(
                        self._tasks[d].status is TaskStatus.COMPLETED for d in child.dependency_ids
                    ):
                        self._make_ready(child, now)
            task.timing["finish_wall"] = _wall(self._epoch_wall, task.timing.get("finish_time", now))
            self._concurrency_samples.append((now, len(self._running)))
            # The freed slot/resource is reused immediately from this thread.
            launched, failed = self._admit() if not self._closed or self._ready else ([], [])
            finished.extend(failed)
            self._cond.notify_all()
        for item in finished:
            self._emit("SCHEDULER_TASK_FINISHED", item)
        self._launch(launched)

    def _release_speculative(self, task: Task) -> None:
        if task.metadata.get("speculative"):
            self._spec_in_use[task.resource_type] -= 1

    def _propagate(self, failed: Task) -> list[Task]:
        """Skip every transitive dependent that has not started. Condition held."""
        skipped = []
        stack = list(self._succ.get(failed.task_id, []))
        now = self._now()
        while stack:
            child = self._tasks.get(stack.pop())
            if child is None or child.terminal:
                continue
            if child.status is TaskStatus.READY:
                self._ready.remove(child.task_id)
            child.transition(TaskStatus.SKIPPED)
            child.failure_reason = f"dependency {failed.task_id} {failed.status.value.lower()}"
            child.timing["finish_time"] = now
            skipped.append(child)
            stack.extend(self._succ.get(child.task_id, []))
        return skipped

    # ---- control ---------------------------------------------------------------------------
    def cancel(self, task_ids: Iterable[str]) -> list[str]:
        """Withdraw tasks that have not started; dependents are skipped."""
        changed: list[Task] = []
        with self._cond:
            for tid in task_ids:
                task = self._tasks[tid]
                if task.status in (TaskStatus.CREATED, TaskStatus.BLOCKED, TaskStatus.READY, TaskStatus.RESERVED):
                    changed.extend(self._cancel_one(task))
            self._cond.notify_all()
        for task in changed:
            self._emit("SCHEDULER_TASK_FINISHED", task)
        return [t.task_id for t in changed]

    def _cancel_one(self, task: Task) -> list[Task]:
        now = self._now()
        if task.status is TaskStatus.READY:
            self._ready.remove(task.task_id)
        if task.status is TaskStatus.RESERVED:
            # Admitted but not started: return budget, resource and slot.
            if self.budget is not None:
                self.budget.release(task)
            self.pools.release(task.resource_type)
            self._release_speculative(task)
            self._free_slots.append(task.timing["worker_id"])
            self._free_slots.sort()
            self._running.discard(task.task_id)
        task.transition(TaskStatus.CANCELLED)
        task.failure_reason = task.failure_reason or "cancelled"
        task.timing["finish_time"] = now
        return [task, *self._propagate(task)]

    def wait(self, task_ids: Iterable[str] | None = None, timeout: float | None = None) -> bool:
        """Block until the given (default: all) tasks are terminal. False on timeout."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            ids = list(task_ids) if task_ids is not None else None
            while True:
                pending = [t for t in (ids if ids is not None else self._tasks) if not self._tasks[t].terminal]
                if not pending:
                    return True
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._cond.wait(timeout=remaining)

    def shutdown(self, *, cancel_pending: bool = True, wait: bool = True) -> None:
        changed: list[Task] = []
        with self._cond:
            if self._closed and not cancel_pending:
                return
            self._closed = True
            if cancel_pending:
                for task in sorted(self._tasks.values(), key=lambda t: t.sequence):
                    if task.status in (TaskStatus.CREATED, TaskStatus.BLOCKED, TaskStatus.READY, TaskStatus.RESERVED):
                        task.failure_reason = "scheduler_shutdown"
                        changed.extend(self._cancel_one(task))
            self._cond.notify_all()
        for task in changed:
            self._emit("SCHEDULER_TASK_FINISHED", task)
        if wait:
            self._dispatcher.join()
            self._executor.shutdown(wait=True)

    def __enter__(self) -> "Scheduler":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.shutdown(cancel_pending=True, wait=True)

    # ---- telemetry -------------------------------------------------------------------------
    def _emit(self, event_type: str, task: Task) -> None:
        hook = task.metadata.get("on_finish") if event_type == "SCHEDULER_TASK_FINISHED" else None
        if callable(hook):  # per-task completion callback (used by the plan controller)
            try:
                hook(task)
            except Exception:  # noqa: BLE001 - a callback must never break execution
                pass
        if self.event_sink is None:
            return
        try:
            self.event_sink(event_type, self._record(task))
        except Exception:  # noqa: BLE001 - telemetry must never break execution
            pass

    def _record(self, task: Task) -> dict[str, Any]:
        record = task.record()
        record.pop("_ready_order", None)
        record.pop("deadline", None)
        meta = record.get("metadata")
        if meta:
            record["metadata"] = {k: v for k, v in meta.items() if not callable(v)}
        record["policy"] = self.policy
        return record

    def task(self, task_id: str) -> Task:
        with self._cond:
            return self._tasks[task_id]

    def records(self) -> list[dict[str, Any]]:
        with self._cond:
            return [self._record(t) for t in sorted(self._tasks.values(), key=lambda t: t.sequence)]

    def summary(self) -> dict[str, Any]:
        """Measured makespan, concurrency, waiting, utilization, and budget."""
        records = self.records()
        with self._cond:
            admit_seconds = self._admit_seconds
            physical = self._physical_invocations
            samples = list(self._concurrency_samples)
        ran = [r for r in records if r.get("start_time") is not None]
        starts = [r["created_time"] for r in records if r.get("created_time") is not None]
        finishes = [r["finish_time"] for r in records if r.get("finish_time") is not None]
        begin = min(starts) if starts else 0.0
        end = max(finishes) if finishes else begin
        makespan = end - begin
        durations = [r["finish_time"] - r["start_time"] for r in ran if r.get("finish_time") is not None]
        # Peak concurrency from the actual execution intervals (sweep line).
        edges = sorted([(r["start_time"], 1) for r in ran if r.get("finish_time") is not None]
                       + [(r["finish_time"], -1) for r in ran if r.get("finish_time") is not None],
                       key=lambda e: (e[0], e[1]))
        level = peak = 0
        for _, delta in edges:
            level += delta
            peak = max(peak, level)
        busy_by_slot: dict[int, float] = {}
        for r in ran:
            if r.get("finish_time") is not None:
                busy_by_slot[r["worker_id"]] = busy_by_slot.get(r["worker_id"], 0.0) + r["finish_time"] - r["start_time"]
        queue_waits = [r["start_time"] - r["enqueue_time"] for r in ran]
        dep_waits = [r["enqueue_time"] - r["created_time"] for r in records if r.get("enqueue_time") is not None]
        dispatch_lat = [r["start_time"] - r["reserved_time"] for r in ran]
        status_counts: dict[str, int] = {}
        for r in records:
            status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

        def stats(values: list[float]) -> dict[str, float | None]:
            if not values:
                return {"mean": None, "max": None}
            return {"mean": round(statistics.fmean(values), 6), "max": round(max(values), 6)}

        return {
            "policy": self.policy,
            "workers": self.workers,
            "tasks": len(records),
            "status": status_counts,
            "makespan": round(makespan, 6),
            "busy_seconds": round(sum(durations), 6),
            "peak_concurrency": peak,
            "worker_idle_seconds": round(sum(max(0.0, makespan - busy_by_slot.get(s, 0.0)) for s in range(self.workers)), 6),
            "queue_wait": stats(queue_waits),
            "dependency_wait": stats(dep_waits),
            "dispatch_latency": stats(dispatch_lat),
            "scheduler_decision_seconds": round(admit_seconds, 6),
            "resources": self.pools.usage(self._epoch + begin, self._epoch + end) if records else {},
            "logical_requests": len(records),
            "physical_invocations": physical,
            "budget": self.budget.snapshot() if self.budget is not None else None,
            "budget_used": sum(r.get("budget_used", 0) or 0 for r in records),
        }
