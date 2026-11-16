from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from openvlharness.multi_agent import (
    AgentFactory,
    BudgetManager,
    MultiAgentOrchestrator,
)
from openvlharness.multi_agent.communication import CommunicationBus, CommunicationError
from openvlharness.multi_agent.config import load_multi_agent_config
from openvlharness.multi_agent.events import EventLog
from openvlharness.multi_agent.schemas import Message, MessageType


class FakeAgent:
    def __init__(
        self, actor_id: str, instances: dict[str, FakeAgent], *, fail: bool = False
    ) -> None:
        self.actor_id = actor_id
        self.instances = instances
        self.instances[actor_id] = self
        self.fail = fail
        self.budget_guard = None
        self.conversations: list[Any] = []

    def generate(self, message: Any, **_: Any) -> dict[str, Any]:
        self.conversations.append(message)
        assert self.budget_guard.reserve("model_requests")
        if self.fail:
            raise RuntimeError("fixture worker failure")
        rendered = json.dumps(message, default=str)
        if self.actor_id == "coordinator":
            if "Decompose" in rendered:
                assignments = [
                    {
                        "worker_id": worker_id,
                        "scope": f"Independent scope for {worker_id}",
                    }
                    for worker_id in sorted(
                        key for key in self.instances if key.startswith("worker_")
                    )
                ]
                return self.result(json.dumps({"assignments": assignments}))
            return self.result("4")
        assert self.budget_guard.reserve("tool_calls")
        tool = (
            "Visual_Grounding_Tool" if self.actor_id.endswith("01") else "Zoom_In_Tool"
        )
        return self.result("4", tool=tool)

    @staticmethod
    def result(answer: str, tool: str | None = None) -> dict[str, Any]:
        assistant = {"content": answer, "tool_calls": []}
        turn: dict[str, Any] = {
            "assistant": assistant,
            "tool_responses": [],
            "memory_outputs": [],
        }
        if tool:
            assistant["tool_calls"] = [{"id": f"call-{tool}", "name": tool, "args": {}}]
            turn["tool_responses"] = [{"ok": True, "tool_name": tool}]
            turn["memory_outputs"] = [
                {"tool_call_id": f"call-{tool}", "image_refs": []}
            ]
        return {
            "prediction": answer,
            "extra_records": {
                "trajectory": {"chat_history": [turn], "final_answer": answer}
            },
        }


def config(tmp_path: Path, count: int = 2) -> dict[str, Any]:
    return load_multi_agent_config(
        {
            "multi_agent": {
                "num_agents": count,
                "max_agents": 4,
                "execution": {
                    "mode": "concurrent",
                    "max_concurrent_workers": 4,
                    "task_timeout_seconds": 10,
                    "peer_review_rounds": 1,
                },
                "coordinator": {
                    "agent_config": "unused.yaml",
                    "tool_access": False,
                    "max_rounds": 2,
                    "model_requests": 4,
                },
                "workers": {
                    "default": {
                        "agent_config": "unused.yaml",
                        "role": "investigator",
                        "tool_calls": 4,
                        "model_requests": 4,
                    },
                    "overrides": {},
                },
                "communication": {
                    "enabled": True,
                    "peer_to_peer": True,
                    "max_messages_per_actor": 20,
                    "max_inbox_per_actor": 20,
                },
                "budget": {
                    "global_tool_calls": 20,
                    "global_model_requests": 40,
                    "global_messages": 100,
                },
                "output": {"directory": str(tmp_path)},
            }
        }
    )


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_worker_counts_and_isolation(tmp_path: Path, count: int) -> None:
    instances: dict[str, FakeAgent] = {}
    factory = AgentFactory(lambda _config, actor, _tools: FakeAgent(actor, instances))
    result = MultiAgentOrchestrator(config(tmp_path, count), factory=factory).run(
        "Count the objects", [{"type": "text", "value": "fixture"}]
    )
    assert result["prediction"] == "4"
    assert result["extra_records"]["status"] == "COMPLETED"
    assert len(instances) == count + 1
    assert len({id(agent) for agent in instances.values()}) == count + 1
    assert len({id(agent.conversations) for agent in instances.values()}) == count + 1
    if count > 1:
        assert len(instances["worker_01"].conversations) == 2
        assert len(instances["worker_02"].conversations) == 2


def test_global_budget_reservation_is_atomic() -> None:
    budget = BudgetManager(
        {"tool_calls": 1},
        {"worker_01": {"tool_calls": 1}, "worker_02": {"tool_calls": 1}},
    )
    barrier = threading.Barrier(2)
    results: list[bool] = []

    def reserve(worker: str) -> None:
        barrier.wait()
        results.append(budget.reserve(worker, "tool_calls").granted)

    threads = [
        threading.Thread(target=reserve, args=(worker,))
        for worker in ("worker_01", "worker_02")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [False, True]
    assert budget.snapshot()["global"]["tool_calls"] == {
        "limit": 1,
        "used": 1,
        "remaining": 0,
    }


def test_bus_validation_duplicate_and_peer_policy(tmp_path: Path) -> None:
    events = EventLog("run", "task", tmp_path / "events.jsonl")
    budget = BudgetManager(
        {"messages": 5},
        {actor: {"messages": 5} for actor in ("coordinator", "worker_01", "worker_02")},
    )
    bus = CommunicationBus(
        actors={"coordinator", "worker_01", "worker_02"},
        coordinator_id="coordinator",
        enabled=True,
        peer_to_peer=False,
        max_inbox=2,
        budget=budget,
        events=events,
        message_path=tmp_path / "messages.jsonl",
    )
    message = Message.create(
        message_id="one",
        run_id="run",
        task_id="task",
        sender_id="worker_01",
        recipient_id="coordinator",
        message_type=MessageType.EVIDENCE.value,
        content="claim",
        sequence=0,
    )
    assert bus.send(message) == "delivered"
    assert bus.send(message) == "duplicate"
    assert len(bus.receive("coordinator")) == 1
    with pytest.raises(CommunicationError):
        bus.send(
            Message.create(
                run_id="run",
                task_id="task",
                sender_id="worker_01",
                recipient_id="worker_02",
                message_type=MessageType.QUESTION.value,
                content="check",
                sequence=1,
            )
        )


def test_worker_failure_is_isolated_and_artifacts_persist(tmp_path: Path) -> None:
    instances: dict[str, FakeAgent] = {}
    factory = AgentFactory(
        lambda _config, actor, _tools: FakeAgent(
            actor, instances, fail=actor == "worker_02"
        )
    )
    result = MultiAgentOrchestrator(config(tmp_path), factory=factory).run(
        "Count", [{"type": "text", "value": "fixture"}]
    )
    assert result["extra_records"]["status"] == "COMPLETED"
    records = result["extra_records"]["multi_agent"]["worker_results"]
    assert {record["agent_id"]: record["status"] for record in records} == {
        "worker_01": "COMPLETED",
        "worker_02": "FAILED",
    }
    run_dir = Path(result["extra_records"]["run_directory"])
    assert (run_dir / "final_result.json").is_file()
    assert (run_dir / "workers" / "worker_02" / "result.json").is_file()


def test_communication_and_peer_exchange_can_be_disabled(tmp_path: Path) -> None:
    settings = config(tmp_path)
    settings["communication"]["enabled"] = False
    settings["communication"]["peer_to_peer"] = False
    instances: dict[str, FakeAgent] = {}
    result = MultiAgentOrchestrator(
        settings,
        factory=AgentFactory(
            lambda _config, actor, _tools: FakeAgent(actor, instances)
        ),
    ).run("Count", [{"type": "text", "value": "fixture"}])
    assert result["extra_records"]["status"] == "COMPLETED"
    assert len(instances["worker_01"].conversations) == 1
    assert len(instances["worker_02"].conversations) == 1


def test_artifact_path_traversal_is_rejected(tmp_path: Path) -> None:
    events = EventLog("run", "task", tmp_path / "events.jsonl")
    budget = BudgetManager(
        {"messages": 2},
        {actor: {"messages": 2} for actor in ("coordinator", "worker_01")},
    )
    bus = CommunicationBus(
        actors={"coordinator", "worker_01"},
        coordinator_id="coordinator",
        enabled=True,
        peer_to_peer=True,
        max_inbox=2,
        budget=budget,
        events=events,
        message_path=tmp_path / "messages.jsonl",
    )
    with pytest.raises(CommunicationError, match="Artifact references"):
        bus.send(
            Message.create(
                run_id="run",
                task_id="task",
                sender_id="worker_01",
                recipient_id="coordinator",
                message_type=MessageType.EVIDENCE.value,
                content="claim",
                artifact_refs=("../../secret",),
                sequence=0,
            )
        )


def test_invalid_agent_count_rejected() -> None:
    with pytest.raises(ValueError, match="exceeds max_agents"):
        load_multi_agent_config(
            {
                "multi_agent": {
                    "num_agents": 5,
                    "max_agents": 4,
                    "coordinator": {},
                    "workers": {},
                }
            }
        )


def test_unknown_nested_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown multi_agent.execution options"):
        load_multi_agent_config(
            {
                "multi_agent": {
                    "num_agents": 1,
                    "coordinator": {},
                    "workers": {},
                    "execution": {"pretend_parallel": True},
                }
            }
        )
