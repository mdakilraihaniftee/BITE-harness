#!/usr/bin/env python3
"""Write a deterministic three-worker protocol fixture for Studio validation.

No model or tool inference happens. The fixture drives the production event
log, communication bus, budget manager, and artifact store through protocol
paths the default orchestration does not exercise on its own:

* two workers calling the same tool concurrently (interleaved lifecycles);
* a worker question answered by a correlated reply (``correlation_id``);
* a failed tool call and a budget-denied tool call;
* recorded model request/response boundaries and private-memory reads.

Every model "response" and tool "result" here is a scripted constant. The run
manifest marks the run as a fixture and its model service as ``fixture``.
"""

from __future__ import annotations

import argparse
import base64
import json
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from openvlharness.multi_agent.budget import BudgetManager
from openvlharness.multi_agent.communication import CommunicationBus
from openvlharness.multi_agent.events import EventLog
from openvlharness.multi_agent.schemas import Message, utc_now
from openvlharness.studio.artifacts import ArtifactStore

WORKERS = ("worker_01", "worker_02", "worker_03")
TASK = "Deterministic protocol fixture: how many marked tiles are visible?"


def _image(path: Path) -> str:
    image = Image.new("RGB", (360, 200), "#dfe7e4")
    draw = ImageDraw.Draw(image)
    for box in ((24, 40, 104, 120), (140, 30, 220, 110), (256, 64, 336, 144)):
        draw.rectangle(box, fill="#2f7d63", outline="#0f2f25", width=3)
    draw.text((12, 176), "Protocol fixture (no inference)", fill="#0f2f25")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    crop = image.crop((256, 64, 336, 144))
    buffer = BytesIO()
    crop.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def build(output_dir: Path, run_id: str) -> Path:
    run = output_dir / run_id
    run.mkdir(parents=True, exist_ok=False)
    crop_b64 = _image(output_dir / f"{run_id}_source.png")
    artifacts = ArtifactStore(run)
    events = EventLog(run_id, "task_001", run / "events.jsonl", artifacts)
    actors = ("coordinator", *WORKERS)
    limits = {
        "coordinator": {"tool_calls": 0, "model_requests": 4, "messages": 20},
        "worker_01": {"tool_calls": 3, "model_requests": 6, "messages": 20},
        "worker_02": {"tool_calls": 3, "model_requests": 6, "messages": 20},
        "worker_03": {"tool_calls": 1, "model_requests": 6, "messages": 20},
    }
    budget = BudgetManager(
        {"tool_calls": 12, "model_requests": 40, "messages": 60}, limits, events.emit
    )
    bus = CommunicationBus(
        actors=set(actors),
        coordinator_id="coordinator",
        enabled=True,
        peer_to_peer=True,
        max_inbox=20,
        budget=budget,
        events=events,
        message_path=run / "messages.jsonl",
    )
    tools = {
        "worker_01": ["Visual_Grounding_Tool", "Zoom_In_Tool"],
        "worker_02": ["Visual_Grounding_Tool", "OCR_Tool"],
        "worker_03": ["Zoom_In_Tool"],
    }
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "task_id": "task_001",
        "created_at": utc_now(),
        "original_task": TASK,
        "worker_count": len(WORKERS),
        "coordinator_count": 1,
        "execution_mode": "deterministic_protocol_fixture",
        "fixture": True,
        "topology": {
            "schema_version": "studio.topology_manifest.v1",
            "worker_ids": list(WORKERS),
            "communication": {"enabled": True, "peer_to_peer": True},
            "budget": {"tool_calls": 12, "model_requests": 40, "messages": 60},
            "actors": {
                actor: {
                    "role": "coordinator"
                    if actor == "coordinator"
                    else "fixture worker",
                    "tool_access": actor != "coordinator",
                    "harness": {"implementation": "ProtocolFixture"},
                    "model_client": {
                        "kind": "fixture",
                        "model_id": "scripted fixture responses",
                    },
                    "memory": {"modules": ["image", "tool_context"]},
                    "tools": [
                        {"name": name, "backend": "deterministic_fixture"}
                        for name in tools.get(actor, [])
                    ],
                }
                for actor in actors
            },
        },
    }
    (run / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    def model_round(actor: str, index: int) -> None:
        budget.reserve(actor, "model_requests")
        started = events.emit(
            actor,
            "MODEL_REQUEST_STARTED",
            {
                "request_id": f"mreq_{actor}_{index}",
                "iteration": index,
                "phase": "fixture",
            },
            summary=f"Sent scripted inference request {index + 1}.",
            status="running",
        )
        events.emit(
            actor,
            "MODEL_RESPONSE_RECEIVED",
            {"request_id": f"mreq_{actor}_{index}", "usage": {}},
            summary="Scripted fixture response returned.",
            parent_event_id=started["event_id"],
        )

    def tool_open(
        actor: str, tool: str, call: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        invocation = f"inv_{actor}_{call}"
        decision = events.emit(
            actor,
            "DECISION_SUMMARY_RECORDED",
            {
                "action_intent": f"Use {tool}.",
                "tool_call_id": call,
                "invocation_id": invocation,
            },
            summary=f"{actor} selected {tool}.",
            tool_name=tool,
        )
        requested = events.emit(
            actor,
            "TOOL_CALL_REQUESTED",
            {"tool_call_id": call, "invocation_id": invocation, "arguments": args},
            summary=f"Requested {tool}.",
            status="planned",
            parent_event_id=decision["event_id"],
            tool_name=tool,
        )
        return {
            "actor": actor,
            "tool": tool,
            "call": call,
            "invocation": invocation,
            "requested": requested,
        }

    def tool_start(handle: dict[str, Any]) -> bool:
        granted = budget.reserve(handle["actor"], "tool_calls").granted
        if granted:
            handle["started"] = events.emit(
                handle["actor"],
                "TOOL_CALL_STARTED",
                {"tool_call_id": handle["call"], "invocation_id": handle["invocation"]},
                summary=f"Started {handle['tool']}.",
                status="running",
                parent_event_id=handle["requested"]["event_id"],
                tool_name=handle["tool"],
            )
        return granted

    def tool_close(
        handle: dict[str, Any], result: dict[str, Any] | None, error: dict | None
    ) -> None:
        parent = (handle.get("started") or handle["requested"])["event_id"]
        closed = events.emit(
            handle["actor"],
            "TOOL_CALL_COMPLETED" if error is None else "TOOL_CALL_FAILED",
            {
                "tool_call_id": handle["call"],
                "invocation_id": handle["invocation"],
                "ok": error is None,
                "canonical_result": result,
                "error": error,
                "latency_seconds": 0.0,
            },
            summary=(
                f"{handle['tool']} returned scripted evidence."
                if error is None
                else f"{handle['tool']} failed: {error['code']}."
            ),
            status="completed" if error is None else "failed",
            parent_event_id=parent,
            tool_name=handle["tool"],
        )
        if error is None:
            events.emit(
                handle["actor"],
                "EVIDENCE_OBSERVED",
                {"tool_call_id": handle["call"], "invocation_id": handle["invocation"]},
                parent_event_id=closed["event_id"],
                tool_name=handle["tool"],
                artifact_refs=closed["artifact_refs"],
            )
            events.emit(
                handle["actor"],
                "MEMORY_WRITTEN",
                {
                    "tool_call_id": handle["call"],
                    "invocation_id": handle["invocation"],
                    "memory_scope": "private",
                },
                summary=f"{handle['actor']} stored {handle['tool']} evidence in private memory.",
                parent_event_id=closed["event_id"],
                tool_name=handle["tool"],
            )

    def send(
        sender: str,
        recipient: str,
        kind: str,
        content: str,
        correlation: str | None = None,
        refs: tuple[str, ...] = (),
    ) -> Message:
        message = Message.create(
            run_id=run_id,
            task_id="task_001",
            sender_id=sender,
            recipient_id=recipient,
            message_type=kind,
            content=content,
            correlation_id=correlation,
            artifact_refs=refs,
        )
        assert bus.send(message) == "delivered"
        return message

    started = events.emit(
        "orchestrator", "RUN_STARTED", {"worker_count": 3}, status="running"
    )
    source = artifacts.register_file(
        output_dir / f"{run_id}_source.png",
        source_event_id="evt_fixture_task",
        alias="input_image_1",
    )
    events.emit(
        "orchestrator",
        "TASK_RECEIVED",
        {"original_task": TASK},
        parent_event_id=started["event_id"],
        artifact_refs=[source],
        event_id="evt_fixture_task",
    )
    events.emit(
        "orchestrator", "RUN_STATE_CHANGED", {"from": "INITIALIZING", "to": "PLANNING"}
    )
    model_round("coordinator", 0)
    assignments = [
        {"worker_id": "worker_01", "scope": "Localize marked tiles."},
        {"worker_id": "worker_02", "scope": "Localize independently and read labels."},
        {
            "worker_id": "worker_03",
            "scope": "Inspect the rightmost tile at higher zoom.",
        },
    ]
    events.emit(
        "coordinator",
        "COORDINATOR_PLAN_RECORDED",
        {"assignments": assignments},
        summary="Coordinator recorded assignments for 3 workers.",
    )
    for item in assignments:
        send("coordinator", item["worker_id"], "TASK_ASSIGNMENT", json.dumps(item))
    events.emit(
        "orchestrator", "RUN_STATE_CHANGED", {"from": "ASSIGNING", "to": "RUNNING"}
    )
    for worker in WORKERS:
        bus.receive(worker)
        events.emit(
            worker, "WORKER_STARTED", {"role": "fixture worker"}, status="running"
        )
        events.emit(
            worker,
            "MEMORY_READ",
            {"memory_scope": "private", "read_kind": "initial_inventory"},
            summary="Initial memory inventory entered the model context.",
        )
        model_round(worker, 0)

    boxes = {
        "boxes": [[24, 40, 104, 120], [140, 30, 220, 110], [256, 64, 336, 144]],
        "scores": [0.98, 0.97, 0.95],
        "orig_img_w": 360,
        "orig_img_h": 200,
        "coordinate_system": "source_pixels",
    }
    # Concurrent same-tool calls: both workers request before either returns.
    first = tool_open(
        "worker_01", "Visual_Grounding_Tool", "call_a", {"query": "marked tile"}
    )
    second = tool_open(
        "worker_02", "Visual_Grounding_Tool", "call_a", {"query": "marked tile"}
    )
    tool_start(first)
    tool_start(second)
    tool_close(second, boxes, None)
    zoom = tool_open(
        "worker_03", "Zoom_In_Tool", "call_z1", {"bbox": [256, 64, 336, 144]}
    )
    tool_start(zoom)
    tool_close(first, boxes, None)
    tool_close(
        zoom, None, {"code": "fixture_timeout", "message": "Scripted tool failure."}
    )
    events.emit(
        "worker_03",
        "MEMORY_READ",
        {"memory_scope": "private", "read_kind": "environment_update"},
        summary="Private memory inventory entered the model context.",
    )
    model_round("worker_03", 1)
    retry = tool_open(
        "worker_03", "Zoom_In_Tool", "call_z2", {"bbox": [256, 64, 336, 144]}
    )
    if not tool_start(retry):
        tool_close(
            retry,
            None,
            {
                "code": "budget_denied",
                "message": "The actor tool-call budget is exhausted.",
            },
        )
    ocr = tool_open("worker_02", "OCR_Tool", "call_o1", {"image_id": "input_image_1"})
    tool_start(ocr)
    tool_close(ocr, {"text": [], "observation": "No text labels are present."}, None)
    zoom_ok = tool_open(
        "worker_01", "Zoom_In_Tool", "call_z3", {"bbox": [256, 64, 336, 144]}
    )
    tool_start(zoom_ok)
    tool_close(
        zoom_ok,
        {
            "crop_bounds": [256, 64, 336, 144],
            "orig_img_w": 360,
            "orig_img_h": 200,
            "coordinate_system": "source_pixels",
            "rendered_image_b64": crop_b64,
        },
        None,
    )

    # A worker question and its correlated reply.
    question = send(
        "worker_01",
        "worker_03",
        "QUESTION",
        "Can you confirm the rightmost region is one complete tile?",
    )
    bus.receive("worker_03")
    reply = send(
        "worker_03",
        "worker_01",
        "EVIDENCE",
        "Unable to zoom (tool failure and budget limit); I cannot confirm it independently.",
        correlation=question.message_id,
    )
    del reply
    bus.receive("worker_01")
    for worker, answer in (
        ("worker_01", "3"),
        ("worker_02", "3"),
        ("worker_03", "unknown"),
    ):
        model_round(worker, 2)
        events.emit(
            worker,
            "HYPOTHESIS_UPDATED",
            {"hypothesis": answer},
            summary=f"{worker} reported candidate answer {answer!r}.",
        )
        send(
            worker,
            "coordinator",
            "CANDIDATE_ANSWER",
            json.dumps({"candidate_answer": answer}),
        )
        events.emit(
            worker,
            "WORKER_FINISHED",
            {"status": "COMPLETED", "candidate_answer": answer},
            summary=f"{worker} finished with status completed.",
        )
    send(
        "coordinator",
        "worker_03",
        "VERIFICATION_REQUEST",
        "Re-check the rightmost tile if budget allows.",
    )
    events.emit(
        "coordinator",
        "VERIFICATION_REQUESTED",
        {"worker_id": "worker_03"},
        summary="Coordinator requested independent verification from worker_03.",
    )
    bus.receive("coordinator")
    model_round("coordinator", 1)
    events.emit(
        "coordinator",
        "COORDINATOR_SYNTHESIS",
        {"candidate_answers": ["3", "unknown"]},
        summary="Coordinator compared worker evidence and completed synthesis.",
    )
    events.emit(
        "coordinator",
        "FINAL_ANSWER_RECORDED",
        {"final_answer": "3"},
        summary="Coordinator recorded final answer '3'.",
    )
    events.emit("orchestrator", "RUN_COMPLETED", {"final_answer": "3"})

    (run / "run_state.json").write_text(
        json.dumps({"run_id": run_id, "status": "COMPLETED"})
    )
    (run / "final_result.json").write_text(
        json.dumps(
            {
                "final_answer": "3",
                "final_status": "COMPLETED",
                "run_status": "COMPLETED",
                "fixture": True,
            }
        )
    )
    (run / "budgets.json").write_text(json.dumps(budget.snapshot()))
    for worker in WORKERS:
        directory = run / "workers" / worker
        directory.mkdir(parents=True)
        (directory / "result.json").write_text(
            json.dumps({"agent_id": worker, "status": "COMPLETED"})
        )
        (directory / "private_memory.json").write_text(
            json.dumps(
                [
                    {
                        "agent_id": worker,
                        "status": "COMPLETED",
                        "candidate_answer": "fixture",
                    }
                ]
            )
        )
    (run / "coordinator").mkdir()
    (run / "coordinator" / "memory.json").write_text("[]")
    return run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/multi_agent"))
    parser.add_argument("--run-id", default="studio_protocol_fixture")
    args = parser.parse_args()
    run = build(args.output_dir, args.run_id)
    print(f"Protocol fixture written to {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
