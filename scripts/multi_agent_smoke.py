#!/usr/bin/env python3
"""Run a deterministic two-worker multi-agent smoke test without model servers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from openvlharness.multi_agent import (
    AgentFactory,
    MultiAgentOrchestrator,
    load_multi_agent_config,
)


class FixtureAgent:
    def __init__(self, actor_id: str) -> None:
        self.actor_id = actor_id
        self.budget_guard = None
        self.calls = 0

    def generate(self, message: Any, **_: Any) -> dict[str, Any]:
        self.calls += 1
        if not self.budget_guard.reserve("model_requests"):
            return self._result(
                "Error: model budget exhausted", error="budget exhausted"
            )
        text = json.dumps(message, default=str)
        if self.actor_id == "coordinator":
            if "Decompose" in text:
                return self._result(
                    json.dumps(
                        {
                            "assignments": [
                                {
                                    "worker_id": "worker_01",
                                    "scope": "Count with object grounding.",
                                },
                                {
                                    "worker_id": "worker_02",
                                    "scope": "Verify independently with zoom inspection.",
                                },
                            ]
                        }
                    )
                )
            return self._result("3")
        tool = (
            "Visual_Grounding_Tool" if self.actor_id == "worker_01" else "Zoom_In_Tool"
        )
        if not self.budget_guard.reserve("tool_calls"):
            return self._result(
                "Error: tool budget exhausted", error="budget exhausted"
            )
        return self._result("3", tool=tool)

    @staticmethod
    def _result(
        answer: str, *, tool: str | None = None, error: str | None = None
    ) -> dict[str, Any]:
        turn: dict[str, Any] = {
            "assistant": {"content": answer, "tool_calls": []},
            "tool_responses": [],
        }
        if tool:
            turn["assistant"]["tool_calls"] = [
                {"id": f"call_{tool}", "name": tool, "args": {}}
            ]
            turn["tool_responses"] = [{"ok": True, "tool_name": tool}]
            turn["memory_outputs"] = [
                {"tool_call_id": f"call_{tool}", "image_refs": []}
            ]
        trajectory = {"chat_history": [turn], "final_answer": answer}
        if error:
            trajectory["error"] = error
        return {"prediction": answer, "extra_records": {"trajectory": trajectory}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/multi-agent-smoke")
    )
    args = parser.parse_args()
    config = load_multi_agent_config("configs/multi_agent.yaml")
    config["execution"]["mode"] = "cooperative"
    config["output"]["directory"] = str(args.output_dir)
    factory = AgentFactory(
        lambda _config, actor_id, _tool_access: FixtureAgent(actor_id)
    )
    run = MultiAgentOrchestrator(config, factory=factory)
    result = run.run(
        "How many marked objects are present?",
        [{"type": "text", "value": "A deterministic fixture with three objects."}],
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return (
        0
        if result["prediction"] == "3"
        and result["extra_records"]["status"] == "COMPLETED"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
