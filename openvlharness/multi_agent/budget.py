"""Concurrency-safe global and actor-local resource accounting."""

from __future__ import annotations

import threading
from collections.abc import Callable
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
        if self._event_sink:
            self._event_sink(
                agent_id,
                "BUDGET_RESERVATION",
                {
                    "resource": resource,
                    "amount": amount,
                    "granted": result.granted,
                    "reason": result.reason,
                },
            )
        return result

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
            }


class AgentBudgetGuard:
    def __init__(self, manager: BudgetManager, agent_id: str) -> None:
        self.manager = manager
        self.agent_id = agent_id

    def reserve(self, resource: str) -> bool:
        return self.manager.reserve(self.agent_id, resource).granted
