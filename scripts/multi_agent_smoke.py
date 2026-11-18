#!/usr/bin/env python3
"""Run a deterministic two-worker multi-agent smoke test without model servers."""

from __future__ import annotations

import argparse
import base64
import json
import time
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from openvlharness.multi_agent import (
    AgentFactory,
    MultiAgentOrchestrator,
    load_multi_agent_config,
)


class FixtureAgent:
    def __init__(
        self, actor_id: str, crop_base64: str, step_delay: float = 0.0
    ) -> None:
        self.actor_id = actor_id
        self.budget_guard = None
        self.event_sink = None
        self.calls = 0
        self.crop_base64 = crop_base64
        self.step_delay = step_delay
        # Honest Studio topology: a deterministic policy stands in for the model,
        # so no model service exists; each worker exercises one fixture tool.
        fixture_tool = {
            "worker_01": "Visual_Grounding_Tool",
            "worker_02": "Zoom_In_Tool",
        }.get(actor_id)
        self.studio_topology = {
            "model_client": {
                "kind": "fixture",
                "model_id": "deterministic fixture policy",
            },
            "tools": [{"name": fixture_tool, "backend": "deterministic_fixture"}]
            if fixture_tool
            else [],
            "memory_modules": ["run_memory"],
        }

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
        review = self.calls > 1
        if tool == "Visual_Grounding_Tool":
            arguments = {"query": "marked circular objects", "image_index": 0}
            result = {
                "boxes": [[30, 55, 95, 120], [125, 32, 195, 102], [220, 70, 290, 140]],
                "scores": [0.97, 0.94, 0.96],
                "labels": ["marked object", "marked object", "marked object"],
                "orig_img_w": 320,
                "orig_img_h": 180,
                "coordinate_system": "source_pixels",
            }
            answer = "3"
        else:
            arguments = {
                "bbox": [220, 70, 290, 140],
                "image_index": 0,
                "purpose": "verify the third candidate",
            }
            result = {
                "crop_bounds": [220, 70, 290, 140],
                "orig_img_w": 320,
                "orig_img_h": 180,
                "coordinate_system": "source_pixels",
                "rendered_image_b64": self.crop_base64,
                "observation": "The crop contains one complete marked circle.",
            }
            answer = "3" if review else "2 (the third region needs verification)"
        tool_call_id = f"call_{self.actor_id}_{self.calls:02d}"
        self._emit_tool(tool, tool_call_id, arguments, result, review=review)
        return self._result(
            answer,
            tool=tool,
            tool_call_id=tool_call_id,
            arguments=arguments,
            tool_result=result,
        )

    def _emit_tool(
        self,
        tool: str,
        tool_call_id: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        *,
        review: bool,
    ) -> None:
        if self.event_sink is None:
            return
        invocation_id = f"inv_{self.actor_id}_{tool_call_id}"
        decision = self._event(
            "DECISION_SUMMARY_RECORDED",
            {
                "current_goal": "Recheck the disputed count"
                if review
                else "Establish the number of marked objects",
                "observation_basis": ["peer candidate" if review else "original image"],
                "action_intent": f"Use {tool} to obtain directly inspectable visual evidence.",
                "expected_information": "A localized count or a higher-resolution crop.",
                "uncertainty": "The third candidate is ambiguous."
                if self.actor_id == "worker_02"
                else "Object boundaries need localization.",
                "tool_call_id": tool_call_id,
                "invocation_id": invocation_id,
            },
            summary=f"{self.actor_id} recorded why {tool} could resolve the current evidence gap.",
        )
        requested = self._event(
            "TOOL_CALL_REQUESTED",
            {
                "tool_call_id": tool_call_id,
                "invocation_id": invocation_id,
                "arguments": arguments,
            },
            tool_name=tool,
            status="planned",
            parent_event_id=decision["event_id"],
            summary=f"{self.actor_id} requested {tool}.",
        )
        started = self._event(
            "TOOL_CALL_STARTED",
            {
                "tool_call_id": tool_call_id,
                "invocation_id": invocation_id,
                "arguments": arguments,
            },
            tool_name=tool,
            status="running",
            parent_event_id=requested["event_id"],
            summary=f"{tool} started for {self.actor_id}.",
        )
        completed = self._event(
            "TOOL_CALL_COMPLETED",
            {
                "tool_call_id": tool_call_id,
                "invocation_id": invocation_id,
                "arguments": arguments,
                "canonical_result": result,
            },
            tool_name=tool,
            parent_event_id=started["event_id"],
            summary=f"{tool} returned recorded visual evidence.",
        )
        observed = self._event(
            "EVIDENCE_OBSERVED",
            {
                "observed_result": result.get(
                    "observation", "Three candidate regions were localized."
                ),
                "tool_call_id": tool_call_id,
                "invocation_id": invocation_id,
                "supported_findings": "The image supports a count of three marked objects.",
                "remaining_uncertainties": "None after independent review."
                if review
                else "The third region still needs an independent check.",
                "decision_to_continue_or_stop": "stop after reporting"
                if review
                else "share for peer verification",
            },
            tool_name=tool,
            parent_event_id=completed["event_id"],
            artifact_refs=completed["artifact_refs"],
            summary=f"{self.actor_id} incorporated the tool evidence without claiming hidden reasoning.",
        )
        self._event(
            "MEMORY_WRITTEN",
            {
                "memory_kind": "tool_evidence_reference",
                "event_id": observed["event_id"],
                "tool_call_id": tool_call_id,
                "invocation_id": invocation_id,
            },
            parent_event_id=observed["event_id"],
            artifact_refs=completed["artifact_refs"],
            summary=f"{self.actor_id} stored the evidence reference in its run memory.",
        )

    def _event(self, event_type: str, payload: dict[str, Any], **metadata: Any):
        event = self.event_sink(event_type, payload, **metadata)
        if self.step_delay:
            time.sleep(self.step_delay)
        return event

    @staticmethod
    def _result(
        answer: str,
        *,
        tool: str | None = None,
        tool_call_id: str | None = None,
        arguments: dict[str, Any] | None = None,
        tool_result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        turn: dict[str, Any] = {
            "assistant": {"content": answer, "tool_calls": []},
            "tool_responses": [],
        }
        if tool:
            tool_call_id = tool_call_id or f"call_{tool}"
            turn["assistant"]["tool_calls"] = [
                {"id": tool_call_id, "name": tool, "args": arguments or {}}
            ]
            turn["tool_responses"] = [
                {"ok": True, "tool_name": tool, "canonical_result": tool_result or {}}
            ]
            turn["memory_outputs"] = [{"tool_call_id": tool_call_id, "image_refs": []}]
        trajectory = {"chat_history": [turn], "final_answer": answer}
        if error:
            trajectory["error"] = error
        return {"prediction": answer, "extra_records": {"trajectory": trajectory}}


def create_demo_image(path: Path) -> str:
    image = Image.new("RGB", (320, 180), "#172521")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 145, 320, 180), fill="#243b34")
    for box, color in [
        ((30, 55, 95, 120), "#6ee7a4"),
        ((125, 32, 195, 102), "#64b5f6"),
        ((220, 70, 290, 140), "#f1b95b"),
    ]:
        draw.ellipse(box, fill=color, outline="white", width=3)
    draw.text((12, 155), "Deterministic fixture: three marked objects", fill="white")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    crop = image.crop((220, 70, 290, 140))
    buffer = BytesIO()
    crop.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/multi_agent"))
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--step-delay",
        type=float,
        default=0.0,
        help="Optional seconds between fixture lifecycle events for live UI demos.",
    )
    args = parser.parse_args()
    if args.step_delay < 0:
        parser.error("--step-delay must be nonnegative")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or f"studio_demo_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    image_path = args.output_dir / "studio_demo_source.png"
    crop_base64 = create_demo_image(image_path)
    config = load_multi_agent_config("configs/multi_agent.yaml")
    config["execution"]["mode"] = "cooperative"
    config["output"]["directory"] = str(args.output_dir)
    factory = AgentFactory(
        lambda _config, actor_id, _tool_access: FixtureAgent(
            actor_id, crop_base64, args.step_delay
        )
    )
    run = MultiAgentOrchestrator(config, factory=factory, run_id=run_id)
    result = run.run(
        "How many marked objects are present?",
        [
            {"type": "image", "value": str(image_path.resolve())},
            {
                "type": "text",
                "value": "A deterministic fixture with three marked objects.",
            },
        ],
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return (
        0
        if result["prediction"] == "3"
        and result["extra_records"]["status"] == "COMPLETED"
        and all(
            worker["status"] == "COMPLETED"
            for worker in result["extra_records"]["multi_agent"]["worker_results"]
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
