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
    },
    "coordinator": {
        "agent_config": "configs/local_qwen.yaml",
        "tool_access": False,
        "max_rounds": 2,
        "model_requests": 4,
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
        },
        "coordinator": {"agent_config", "tool_access", "max_rounds", "model_requests"},
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


def worker_config(config: dict[str, Any], worker_id: str) -> dict[str, Any]:
    return _merge(
        config["workers"]["default"], config["workers"]["overrides"].get(worker_id, {})
    )
