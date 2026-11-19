"""Typed resource capacities and the scheduler's view of the run budget.

``ResourcePools`` holds integer capacities per pool (``cpu``, one pool per GPU
tool service, ``remote_io``, ...). A task occupies one unit of its pool from
dispatch until its body returns. Capacities are conservative by default: a
GPU service whose concurrent-request behaviour has not been verified gets
capacity 1.

``BudgetAdapter`` does not keep a second ledger. It reserves through the
run's existing ``BudgetManager`` (atomic under one lock) and only tracks
which granted reservations are still pending dispatch, so it can return them
if the task is cancelled before it runs. Invariant, enforced by the manager:
spent + reserved <= total for every limited resource.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from typing import Any

from ..multi_agent.budget import BudgetManager
from .dag import Task


class ResourcePools:
    def __init__(self, capacities: Mapping[str, int], clock=time.monotonic) -> None:
        for pool, capacity in capacities.items():
            if type(capacity) is not int or capacity < 1:
                raise ValueError(f"resource pool {pool!r} needs an integer capacity >= 1")
        self.capacities = dict(capacities)
        self.in_use = {pool: 0 for pool in capacities}
        self.peak = {pool: 0 for pool in capacities}
        self._busy = {pool: 0.0 for pool in capacities}  # integral of in_use dt
        self._clock = clock
        self._changed = {pool: clock() for pool in capacities}
        self._lock = threading.Lock()

    def __contains__(self, pool: str) -> bool:
        return pool in self.capacities

    def _accumulate(self, pool: str, now: float) -> None:
        self._busy[pool] += self.in_use[pool] * (now - self._changed[pool])
        self._changed[pool] = now

    def available(self, pool: str) -> int:
        with self._lock:
            return self.capacities[pool] - self.in_use[pool]

    def try_acquire(self, pool: str) -> bool:
        with self._lock:
            if self.in_use[pool] >= self.capacities[pool]:
                return False
            self._accumulate(pool, self._clock())
            self.in_use[pool] += 1
            self.peak[pool] = max(self.peak[pool], self.in_use[pool])
            return True

    def release(self, pool: str) -> None:
        with self._lock:
            if self.in_use[pool] <= 0:
                raise RuntimeError(f"resource pool {pool!r} released more often than acquired")
            self._accumulate(pool, self._clock())
            self.in_use[pool] -= 1

    def usage(self, start: float, end: float) -> dict[str, dict[str, Any]]:
        """Busy capacity-seconds and saturation (busy / (capacity * span)) per pool."""
        with self._lock:
            now = self._clock()
            for pool in self.capacities:
                self._accumulate(pool, now)
            span = max(end - start, 1e-9)
            return {
                pool: {
                    "capacity": capacity,
                    "peak_in_use": self.peak[pool],
                    "busy_seconds": round(self._busy[pool], 6),
                    "saturation": round(self._busy[pool] / (capacity * span), 4),
                }
                for pool, capacity in self.capacities.items()
            }


class BudgetAdapter:
    """Reserve/settle/release task costs through the existing BudgetManager."""

    DEFAULT_AGENT = "scheduler"

    def __init__(self, manager: BudgetManager) -> None:
        self.manager = manager
        self._lock = threading.Lock()
        self.pending: dict[str, int] = {}  # reserved, not yet dispatched
        self.charged: dict[str, int] = {}  # dispatched (non-refundable)
        self.in_flight = 0
        self.denied = 0
        self.released = 0

    @classmethod
    def with_limit(cls, total: int, resource: str = "tool_calls") -> "BudgetAdapter":
        """Standalone ledger for benchmarks: one global limit, no actor limits."""
        return cls(BudgetManager({resource: total}, {}))

    def _key(self, task: Task) -> str | None:
        if not task.budget_resource or task.budget_amount == 0:
            return None
        return task.budget_resource

    def reserve(self, task: Task) -> tuple[bool, str | None]:
        resource = self._key(task)
        if resource is None:
            return True, None
        result = self.manager.reserve(task.agent_id or self.DEFAULT_AGENT, resource, task.budget_amount)
        with self._lock:
            if result.granted:
                self.pending[resource] = self.pending.get(resource, 0) + task.budget_amount
            else:
                self.denied += 1
        return result.granted, result.reason

    def settle(self, task: Task) -> None:
        """The task is being dispatched: its reservation becomes a charge."""
        resource = self._key(task)
        with self._lock:
            self.in_flight += 1
            if resource is not None:
                self.pending[resource] -= task.budget_amount
                self.charged[resource] = self.charged.get(resource, 0) + task.budget_amount
                task.timing["budget_charged"] = task.budget_amount

    def finish(self, task: Task) -> None:
        with self._lock:
            self.in_flight -= 1

    def release(self, task: Task) -> None:
        """Return the reservation of a task cancelled before dispatch."""
        resource = self._key(task)
        if resource is None:
            return
        self.manager.release(task.agent_id or self.DEFAULT_AGENT, resource, task.budget_amount, reason="cancelled_before_dispatch")
        with self._lock:
            self.pending[resource] -= task.budget_amount
            self.released += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            local = {"pending": dict(self.pending), "charged": dict(self.charged), "in_flight": self.in_flight,
                     "denied_tasks": self.denied, "released_tasks": self.released}
        return {"scheduler": local, "ledger": self.manager.snapshot()}
