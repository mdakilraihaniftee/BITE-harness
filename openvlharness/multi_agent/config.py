"""Configuration loading and validation for multi-agent execution."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml
from jsonschema import validate

from ..bootstrap import expand_environment

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["multi_agent"],
    "properties": {
        "multi_agent": {
            "type": "object",
            "required": ["num_agents", "coordinator", "workers"],
            "properties": {
                "num_agents": {"type": "integer", "minimum": 1},
                "max_agents": {"type": "integer", "minimum": 1},
                "execution": {"type": "object"},
                "coordinator": {"type": "object"},
                "workers": {"type": "object"},
                "communication": {"type": "object"},
                "memory": {"type": "object"},
                "budget": {"type": "object"},
                "output": {"type": "object"},
            },
            "additionalProperties": False,
        }
    },
    "additionalProperties": False,
}


DEFAULTS = {
    "max_agents": 4,
    "execution": {
        "mode": "concurrent",
        "max_concurrent_workers": 4,
        "task_timeout_seconds": 600,
        "peer_review_rounds": 1,
        # PARSEC-VL tool scheduler (openvlharness/parsec_vl). "off" keeps the
        # original behaviour: each agent runs its tool calls one by one in its
        # own thread. e0/e1/e2 route every tool call through one shared
        # scheduler with typed resource pools and the run's budget ledger.
        "scheduler": {
            "policy": "off",
            "workers": 4,
            "service_capacity": 1,   # concurrent requests per GPU tool server (unverified -> 1)
            "capacities": {},        # explicit pool capacities, e.g. {"cpu": 4}
            "task_timeout_seconds": None,
            "plan_dispatch": "e2",   # e3-e5: dispatch order for plan actions (e0 = same plan, one at a time)
        },
        # PARSEC-VL Phase 2 (used when scheduler.policy is e3, e4 or e5): workers may call
        # Execute_Action_Plan (declared multi-action plans); E3 selects plans by Monte Carlo,
        # E4 adds fixed-width speculation, E5 selective speculation + event-driven replanning.
        "planning": {
            "candidate_plan_limit": 6,
            "max_plan_depth": 3,
            "beam_width": 4,
            "planning_processes": 4,      # CPU processes for Monte Carlo evaluation (0 = in-process)
            "rollouts": 2000,
            "planning_time_budget": 0.5,  # seconds per evaluation
            "max_speculative_branches": 1,
            "speculative_budget_limit": 4,
            "random_seed": 0,
            "latency_weight": 1.0,
            "cost_weight": 0.25,
            "max_replans": 2,
            "heuristic_alternatives": True,
            "outcome_model": None,        # JSON from `scripts/parsec.py outcome-model`; None = probe priors
            "planning_gate": "auto",      # auto: skip/sequential/pool by predicted cost; off: always the pool
            "planning_pool": "lazy",      # lazy (first use) | eager (run start) | shared (warm across runs)
            "plan_schema": "current",     # model-facing Execute_Action_Plan schema: current | simple (flat steps; Phase 3 probe: no measured difference)
        },
    },
    "coordinator": {
        "agent_config": "configs/local_qwen.yaml",
        "tool_access": False,
        "max_rounds": 2,
        "model_requests": 4,
        # Explicit provisional-answer state. Disabled by default so existing
        # configurations keep their model-call pattern; each reassessment is one
        # additional coordinator model request charged to the normal budgets.
        "estimate_updates": {
            "enabled": False,
            "trigger": "meaningful_evidence",
            "max_reassessments": 2,
        },
        # Additional delegation rounds the coordinator may request during a
        # reassessment. Zero keeps the original single assignment round.
        "max_follow_up_rounds": 0,
    },
    "workers": {
        "default": {
            "agent_config": "configs/local_qwen.yaml",
            "role": "general visual investigator",
            "tool_calls": 12,
            "model_requests": 20,
        },
        "overrides": {},
    },
    "communication": {
        "enabled": True,
        "peer_to_peer": True,
        "max_messages_per_actor": 20,
        "max_inbox_per_actor": 40,
    },
    # Optional worker memory: a private, cross-phase episodic notebook that a
    # worker writes after each investigation phase and retrieves at the start of
    # later phases (peer review, follow-up). It is separate from the per-question
    # working context (conversation and image registry), which tool use requires
    # and which is never disabled.
    "memory": {"optional_worker_memory": True},
    "budget": {
        "global_tool_calls": 40,
        "global_model_requests": 80,
        "global_messages": 100,
    },
    "output": {"directory": "outputs/multi_agent"},
}


def _merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _reject_unknown(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"Unknown {label} options: {sorted(unknown)}")


def load_multi_agent_config(config: str | Path | dict[str, Any]) -> dict[str, Any]:
    source_dir = Path.cwd()
    source = ""
    if isinstance(config, (str, Path)):
        path = Path(config).resolve()
        source = f" {path}"
        source_dir = path.parent
        with path.open(encoding="utf-8") as stream:
            config = yaml.safe_load(stream)
    config = expand_environment(
        config, label="multi-agent configuration", source=source
    )
    validate(config, CONFIG_SCHEMA)
    raw = config["multi_agent"]
    for key, allowed in {
        "execution": {
            "mode",
            "max_concurrent_workers",
            "task_timeout_seconds",
            "peer_review_rounds",
            "scheduler",
            "planning",
        },
        "coordinator": {
            "agent_config",
            "tool_access",
            "max_rounds",
            "model_requests",
            "estimate_updates",
            "max_follow_up_rounds",
        },
        "memory": {"optional_worker_memory"},
        "communication": {
            "enabled",
            "peer_to_peer",
            "max_messages_per_actor",
            "max_inbox_per_actor",
        },
        "budget": {"global_tool_calls", "global_model_requests", "global_messages"},
        "output": {"directory"},
    }.items():
        _reject_unknown(raw.get(key, {}), allowed, f"multi_agent.{key}")
    workers_raw = raw.get("workers", {})
    _reject_unknown(workers_raw, {"default", "overrides"}, "multi_agent.workers")
    worker_allowed = {"agent_config", "role", "tool_calls", "model_requests"}
    _reject_unknown(
        workers_raw.get("default", {}), worker_allowed, "multi_agent.workers.default"
    )
    for worker_id, override in workers_raw.get("overrides", {}).items():
        if not isinstance(override, dict):
            raise TypeError(
                f"multi_agent.workers.overrides.{worker_id} must be a mapping"
            )
        _reject_unknown(
            override, worker_allowed, f"multi_agent.workers.overrides.{worker_id}"
        )
    _reject_unknown(
        (raw.get("coordinator") or {}).get("estimate_updates") or {},
        {"enabled", "trigger", "max_reassessments"},
        "multi_agent.coordinator.estimate_updates",
    )
    merged = _merge(DEFAULTS, raw)
    count = merged["num_agents"]
    ceiling = merged["max_agents"]
    if count > ceiling:
        raise ValueError(f"num_agents ({count}) exceeds max_agents ({ceiling})")
    execution = merged["execution"]
    if execution["mode"] not in {"concurrent", "cooperative"}:
        raise ValueError("execution.mode must be concurrent or cooperative")
    for key in ("max_concurrent_workers", "peer_review_rounds"):
        if type(execution[key]) is not int or execution[key] < (
            1 if key == "max_concurrent_workers" else 0
        ):
            raise ValueError(f"execution.{key} has an invalid value")
    if (
        type(execution["task_timeout_seconds"]) not in (int, float)
        or execution["task_timeout_seconds"] <= 0
    ):
        raise ValueError("execution.task_timeout_seconds must be positive")
    validate_scheduler(execution["scheduler"])
    validate_planning(execution["planning"])
    communication = merged["communication"]
    if type(merged["coordinator"]["tool_access"]) is not bool:
        raise ValueError("coordinator.tool_access must be boolean")
    if (
        type(merged["coordinator"]["max_rounds"]) is not int
        or merged["coordinator"]["max_rounds"] < 1
    ):
        raise ValueError("coordinator.max_rounds must be a positive integer")
    for key in ("enabled", "peer_to_peer"):
        if type(communication[key]) is not bool:
            raise ValueError(f"communication.{key} must be boolean")
    if type(merged["memory"]["optional_worker_memory"]) is not bool:
        raise ValueError("memory.optional_worker_memory must be boolean")
    validate_coordinator_policy(merged["coordinator"])
    for section, keys in (
        (communication, ("max_messages_per_actor", "max_inbox_per_actor")),
        (
            merged["budget"],
            ("global_tool_calls", "global_model_requests", "global_messages"),
        ),
    ):
        for key in keys:
            if type(section[key]) is not int or section[key] < 0:
                raise ValueError(f"{key} must be a nonnegative integer")
    for actor in [
        merged["coordinator"],
        merged["workers"]["default"],
        *merged["workers"]["overrides"].values(),
    ]:
        for key in ("tool_calls", "model_requests"):
            if key in actor and (type(actor[key]) is not int or actor[key] < 0):
                raise ValueError(f"Actor {key} must be a nonnegative integer")
        if "role" in actor and (
            not isinstance(actor["role"], str) or not actor["role"].strip()
        ):
            raise ValueError("Worker role must be a nonempty string")
        if "agent_config" in actor:
            path = Path(actor["agent_config"])
            if not path.is_absolute():
                candidate = (source_dir / path).resolve()
                # Repository-relative paths are conventional in checked-in examples.
                actor["agent_config"] = str(
                    candidate if candidate.exists() else path.resolve()
                )
    return merged


SCHEDULER_POLICIES = ("off", "e0", "e1", "e2", "e3", "e4", "e5")
PLANNING_KEYS = {"candidate_plan_limit", "max_plan_depth", "beam_width", "planning_processes", "rollouts",
                 "planning_time_budget", "max_speculative_branches", "speculative_budget_limit", "random_seed",
                 "latency_weight", "cost_weight", "max_replans", "heuristic_alternatives", "outcome_model",
                 "planning_gate", "planning_pool", "min_stakes_s", "plan_schema"}


def validate_planning(planning: dict[str, Any]) -> None:
    _reject_unknown(planning, PLANNING_KEYS, "execution.planning")
    from ..parsec_vl.controller import PlanningConfig

    if planning.get("plan_schema", "current") not in ("simple", "current"):
        raise ValueError("execution.planning.plan_schema must be simple or current")
    keys = {k: v for k, v in planning.items() if k not in ("outcome_model", "plan_schema")}
    PlanningConfig.for_mode("e5", **keys)  # raises ValueError on invalid values
    model = planning.get("outcome_model")
    if model is not None and not isinstance(model, str):
        raise ValueError("execution.planning.outcome_model must be a file path or null")


def validate_scheduler(scheduler: dict[str, Any]) -> None:
    _reject_unknown(scheduler, {"policy", "workers", "service_capacity", "capacities", "task_timeout_seconds", "plan_dispatch"},
                    "execution.scheduler")
    if scheduler.get("plan_dispatch", "e2") not in ("e0", "e1", "e2"):
        raise ValueError("execution.scheduler.plan_dispatch must be e0, e1 or e2")
    if scheduler["policy"] not in SCHEDULER_POLICIES:
        raise ValueError(f"execution.scheduler.policy must be one of {', '.join(SCHEDULER_POLICIES)}")
    for key in ("workers", "service_capacity"):
        if type(scheduler[key]) is not int or scheduler[key] < 1:
            raise ValueError(f"execution.scheduler.{key} must be a positive integer")
    capacities = scheduler["capacities"]
    if not isinstance(capacities, dict) or any(type(v) is not int or v < 1 for v in capacities.values()):
        raise ValueError("execution.scheduler.capacities must map pool names to positive integers")
    timeout = scheduler["task_timeout_seconds"]
    if timeout is not None and (type(timeout) not in (int, float) or timeout <= 0):
        raise ValueError("execution.scheduler.task_timeout_seconds must be positive or null")


def validate_coordinator_policy(coordinator: dict[str, Any]) -> None:
    updates = coordinator["estimate_updates"]
    if type(updates.get("enabled")) is not bool:
        raise ValueError("coordinator.estimate_updates.enabled must be boolean")
    if updates.get("trigger") not in {"meaningful_evidence", "every_round"}:
        raise ValueError(
            "coordinator.estimate_updates.trigger must be meaningful_evidence or every_round"
        )
    if type(updates.get("max_reassessments")) is not int or not (
        0 <= updates["max_reassessments"] <= 8
    ):
        raise ValueError(
            "coordinator.estimate_updates.max_reassessments must be an integer in 0..8"
        )
    rounds = coordinator["max_follow_up_rounds"]
    if type(rounds) is not int or not 0 <= rounds <= 4:
        raise ValueError("coordinator.max_follow_up_rounds must be an integer in 0..4")


def apply_run_options(
    config: dict[str, Any],
    *,
    num_agents: int | None = None,
    worker_memory: bool | None = None,
    peer_communication: bool | None = None,
    communication: bool | None = None,
    mode: str | None = None,
    estimate_updates: bool | None = None,
    max_reassessments: int | None = None,
    follow_up_rounds: int | None = None,
    tool_scheduler: str | None = None,
    scheduler_workers: int | None = None,
    planning_processes: int | None = None,
) -> dict[str, Any]:
    """Apply CLI/UI run options to a loaded configuration and re-validate it.

    Every runner uses this one function so the command line, the Studio's
    generated launch commands, and the persisted effective configuration all
    describe the same canonical keys. Unsupported values raise instead of
    being silently ignored.
    """
    result = copy.deepcopy(config)
    if num_agents is not None:
        if type(num_agents) is not int or not 1 <= num_agents <= result["max_agents"]:
            raise ValueError(f"num_agents must be in 1..{result['max_agents']}")
        result["num_agents"] = num_agents
    if worker_memory is not None:
        result["memory"]["optional_worker_memory"] = bool(worker_memory)
    if communication is not None:
        result["communication"]["enabled"] = bool(communication)
    if peer_communication is not None:
        result["communication"]["peer_to_peer"] = bool(peer_communication)
    if mode is not None:
        if mode not in {"concurrent", "cooperative"}:
            raise ValueError("mode must be concurrent or cooperative")
        result["execution"]["mode"] = mode
    if estimate_updates is not None:
        result["coordinator"]["estimate_updates"]["enabled"] = bool(estimate_updates)
    if max_reassessments is not None:
        result["coordinator"]["estimate_updates"]["max_reassessments"] = max_reassessments
    if follow_up_rounds is not None:
        result["coordinator"]["max_follow_up_rounds"] = follow_up_rounds
    if tool_scheduler is not None:
        result["execution"]["scheduler"]["policy"] = tool_scheduler
    if scheduler_workers is not None:
        result["execution"]["scheduler"]["workers"] = scheduler_workers
    if planning_processes is not None:
        result["execution"]["planning"]["planning_processes"] = planning_processes
    validate_coordinator_policy(result["coordinator"])
    validate_scheduler(result["execution"]["scheduler"])
    validate_planning(result["execution"]["planning"])
    return result


def effective_run_config(config: dict[str, Any]) -> dict[str, Any]:
    """Canonical, display-safe description of the settings a run executes with."""
    communication = config["communication"]
    updates = config["coordinator"]["estimate_updates"]
    return {
        "schema_version": "studio.run_config.v1",
        "num_workers": config["num_agents"],
        "coordinator_enabled": True,
        "optional_worker_memory_enabled": bool(
            config["memory"]["optional_worker_memory"]
        ),
        # Peer messaging needs the bus and the peer policy. Coordinator
        # assignment is always delivered; worker reports need the bus.
        "peer_communication_enabled": bool(
            communication["enabled"] and communication["peer_to_peer"]
        ),
        "communication_enabled": bool(communication["enabled"]),
        "coordinator_assignment_enabled": True,
        "coordinator_reporting_channel": (
            "message_bus" if communication["enabled"] else "direct_result_handoff"
        ),
        "execution_mode": config["execution"]["mode"],
        "max_concurrent_workers": config["execution"]["max_concurrent_workers"],
        "peer_review_rounds": config["execution"]["peer_review_rounds"],
        "tool_scheduler": {
            "policy": config["execution"]["scheduler"]["policy"],
            "workers": config["execution"]["scheduler"]["workers"],
            "service_capacity": config["execution"]["scheduler"]["service_capacity"],
            "plan_dispatch": config["execution"]["scheduler"].get("plan_dispatch", "e2"),
            "decision_protocol": ("declared_multi_action_plan" if config["execution"]["scheduler"]["policy"] in ("e3", "e4", "e5")
                                  else "legacy_single_call"),
            **({"planning": {k: v for k, v in config["execution"]["planning"].items()}}
               if config["execution"]["scheduler"]["policy"] in ("e3", "e4", "e5") else {}),
        },
        "coordinator_estimate_updates": {
            "enabled": bool(updates["enabled"]),
            "trigger": updates["trigger"],
            "max_reassessments": updates["max_reassessments"],
            "additional_model_requests_max": (
                updates["max_reassessments"] if updates["enabled"] else 0
            ),
        },
        "max_follow_up_rounds": config["coordinator"]["max_follow_up_rounds"],
        "budgets": {
            "global_tool_calls": config["budget"]["global_tool_calls"],
            "global_model_requests": config["budget"]["global_model_requests"],
            "global_messages": config["budget"]["global_messages"],
            "coordinator_model_requests": config["coordinator"]["model_requests"],
        },
    }


def worker_config(config: dict[str, Any], worker_id: str) -> dict[str, Any]:
    return _merge(
        config["workers"]["default"], config["workers"]["overrides"].get(worker_id, {})
    )
