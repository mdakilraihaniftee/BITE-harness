"""Concurrency-safe global and actor-local resource accounting."""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Reservation:
    granted: bool
    resource: str
    agent_id: str
    amount: int
    reason: str | None = None


class BudgetManager:
    """Atomically reserve model, tool, and communication resources."""

    def __init__(
        self,
        global_limits: dict[str, int],
        actor_limits: dict[str, dict[str, int]],
        event_sink: Callable[..., Any] | None = None,
    ) -> None:
        self.global_limits = dict(global_limits)
        self.actor_limits = {key: dict(value) for key, value in actor_limits.items()}
        self.global_used = {key: 0 for key in self.global_limits}
        self.actor_used = {
            actor: {key: 0 for key in limits}
            for actor, limits in self.actor_limits.items()
        }
        self.measured = {"generated_tokens": 0, "estimated_cost": None}
        # Accounting counters (per resource): refused reservations, and
        # reservations returned before the work was dispatched.
        self.rejected: dict[str, int] = {}
        self.released: dict[str, int] = {}
        self._lock = threading.Lock()
        self._event_sink = event_sink

    def reserve(self, agent_id: str, resource: str, amount: int = 1) -> Reservation:
        if type(amount) is not int or amount <= 0:
            raise ValueError("Budget reservation amount must be a positive integer")
        with self._lock:
            global_limit = self.global_limits.get(resource)
            actor_limit = self.actor_limits.get(agent_id, {}).get(resource)
            if (
                global_limit is not None
                and self.global_used.get(resource, 0) + amount > global_limit
            ):
                result = Reservation(False, resource, agent_id, amount, "global_limit")
            elif (
                actor_limit is not None
                and self.actor_used[agent_id].get(resource, 0) + amount > actor_limit
            ):
                result = Reservation(False, resource, agent_id, amount, "actor_limit")
            else:
                if global_limit is not None:
                    self.global_used[resource] = (
                        self.global_used.get(resource, 0) + amount
                    )
                if actor_limit is not None:
                    self.actor_used[agent_id][resource] = (
                        self.actor_used[agent_id].get(resource, 0) + amount
                    )
                result = Reservation(True, resource, agent_id, amount)
            if not result.granted:
                self.rejected[resource] = self.rejected.get(resource, 0) + amount
            global_remaining = (
                global_limit - self.global_used.get(resource, 0)
                if global_limit is not None
                else None
            )
            actor_remaining = (
                actor_limit - self.actor_used.get(agent_id, {}).get(resource, 0)
                if actor_limit is not None
                else None
            )
        if self._event_sink:
            self._event_sink(
                agent_id,
                "BUDGET_UPDATED",
                {
                    "resource": resource,
                    "amount": amount,
                    "granted": result.granted,
                    "reason": result.reason,
                    "global_remaining": global_remaining,
                    "actor_remaining": actor_remaining,
                },
                summary=(
                    f"Reserved {amount} {resource.replace('_', ' ')}."
                    if result.granted
                    else f"Denied {resource.replace('_', ' ')} reservation: {result.reason}."
                ),
                status="completed" if result.granted else "failed",
            )
        return result

    def release(self, agent_id: str, resource: str, amount: int = 1, *, reason: str = "not_dispatched") -> None:
        """Return a granted reservation whose work was never dispatched.

        Only for work that did not start (e.g. cancelled while queued). Work
        that was dispatched keeps its charge, including failed calls; this is
        the runtime's non-refundable cost policy.
        """
        if type(amount) is not int or amount <= 0:
            raise ValueError("Budget release amount must be a positive integer")
        with self._lock:
            global_limit = self.global_limits.get(resource)
            actor_limit = self.actor_limits.get(agent_id, {}).get(resource)
            if global_limit is not None:
                if self.global_used.get(resource, 0) < amount:
                    raise RuntimeError(f"release of {amount} {resource} exceeds the reserved global amount")
            if actor_limit is not None:
                if self.actor_used[agent_id].get(resource, 0) < amount:
                    raise RuntimeError(f"release of {amount} {resource} exceeds {agent_id}'s reserved amount")
            # Validate both balances before mutating either: a rejected actor
            # release must not silently refund another actor's global charge.
            if global_limit is not None:
                self.global_used[resource] -= amount
            if actor_limit is not None:
                self.actor_used[agent_id][resource] -= amount
            self.released[resource] = self.released.get(resource, 0) + amount
            global_remaining = global_limit - self.global_used.get(resource, 0) if global_limit is not None else None
        if self._event_sink:
            self._event_sink(
                agent_id,
                "BUDGET_UPDATED",
                {"resource": resource, "amount": amount, "granted": True, "released": True,
                 "reason": reason, "global_remaining": global_remaining},
                summary=f"Released {amount} unused {resource.replace('_', ' ')} reservation.",
                status="completed",
            )

    def remaining(self, agent_id: str, resource: str) -> int | None:
        """Smallest remaining global/actor allowance for a resource (None = unlimited)."""
        with self._lock:
            values = []
            if resource in self.global_limits:
                values.append(
                    self.global_limits[resource] - self.global_used.get(resource, 0)
                )
            actor_limit = self.actor_limits.get(agent_id, {}).get(resource)
            if actor_limit is not None:
                values.append(
                    actor_limit - self.actor_used.get(agent_id, {}).get(resource, 0)
                )
            return min(values) if values else None

    def used(self, agent_id: str, resource: str) -> int:
        with self._lock:
            return self.actor_used.get(agent_id, {}).get(resource, 0)

    def record_usage(self, usage: dict[str, Any]) -> None:
        def token_total(value: Any) -> int:
            if not isinstance(value, dict):
                return 0
            total = 0
            for key, item in value.items():
                if key in {
                    "completion_tokens",
                    "output_tokens",
                    "generated_tokens",
                } and isinstance(item, int):
                    total += item
                elif isinstance(item, dict):
                    total += token_total(item)
            return total

        with self._lock:
            self.measured["generated_tokens"] += token_total(usage)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "global": {
                    key: {
                        "limit": limit,
                        "used": self.global_used.get(key, 0),
                        "remaining": limit - self.global_used.get(key, 0),
                    }
                    for key, limit in self.global_limits.items()
                },
                "actors": {
                    actor: {
                        key: {
                            "limit": limit,
                            "used": self.actor_used[actor].get(key, 0),
                            "remaining": limit - self.actor_used[actor].get(key, 0),
                        }
                        for key, limit in limits.items()
                    }
                    for actor, limits in self.actor_limits.items()
                },
                "measured": dict(self.measured),
                "counters": {"rejected": dict(self.rejected), "released": dict(self.released)},
            }


class AgentBudgetGuard:
    def __init__(self, manager: BudgetManager, agent_id: str) -> None:
        self.manager = manager
        self.agent_id = agent_id
        # Optional per-call ceiling on model requests (e.g. one bounded
        # coordinator reassessment), applied on top of actor/global limits.
        self._call_cap: int | None = None
        self._call_used = 0

    def reserve(self, resource: str) -> bool:
        if resource == "model_requests" and self._call_cap is not None:
            if self._call_used >= self._call_cap:
                return False
            granted = self.manager.reserve(self.agent_id, resource).granted
            self._call_used += int(granted)
            return granted
        return self.manager.reserve(self.agent_id, resource).granted

    @contextmanager
    def capped(self, model_requests: int):
        """Limit the model requests one bounded call may use."""
        self._call_cap, self._call_used = max(0, model_requests), 0
        try:
            yield self
        finally:
            self._call_cap, self._call_used = None, 0
