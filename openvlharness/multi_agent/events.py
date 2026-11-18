"""Thread-safe, versioned event provenance for multi-agent runs and the Studio."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..studio.schema import validate_event
from .schemas import utc_now

SUMMARY_TEMPLATES = {
    "RUN_STARTED": "Investigation run started.",
    "TASK_RECEIVED": "The original task and authorized inputs were recorded.",
    "WORKER_STARTED": "Worker began its assigned investigation.",
    "WORKER_FINISHED": "Worker completed its current investigation.",
    "TOOL_CALL_REQUESTED": "Agent selected a tool action.",
    "TOOL_CALL_STARTED": "Tool execution started.",
    "TOOL_CALL_COMPLETED": "Tool returned evidence.",
    "TOOL_CALL_FAILED": "Tool execution failed without producing usable evidence.",
    "EVIDENCE_OBSERVED": "Tool evidence was added to the agent context.",
    "MEMORY_WRITTEN": "Agent memory recorded a tool-result reference.",
    "MEMORY_READ": "Private memory inventory entered the agent's model context.",
    "MODEL_REQUEST_STARTED": "Agent sent an inference request to its model client.",
    "MODEL_RESPONSE_RECEIVED": "Model response returned to the agent harness.",
    "MODEL_REQUEST_FAILED": "Inference request failed.",
    "HYPOTHESIS_UPDATED": "Agent reported a candidate conclusion.",
    "FINAL_ANSWER_RECORDED": "Coordinator recorded the final answer.",
    "RUN_CONFIGURATION_RECORDED": "The effective run configuration was recorded.",
    "COORDINATOR_ESTIMATE_UPDATED": "Coordinator recorded a new answer state.",
    "COORDINATOR_REASSESSMENT_RECORDED": "Coordinator reassessed without changing its answer state.",
    "OPTIONAL_MEMORY_WRITTEN": "Worker wrote to its optional private notebook.",
    "OPTIONAL_MEMORY_READ": "Worker retrieved its optional private notebook.",
    "FOLLOW_UP_ASSIGNED": "Coordinator delegated follow-up work.",
    "INVESTIGATION_ROUND_STARTED": "An investigation round started.",
    "INVESTIGATION_ROUND_COMPLETED": "An investigation round finished.",
}


class EventLog:
    def __init__(self, run_id: str, task_id: str, path: Path, artifacts=None) -> None:
        self.run_id = run_id
        self.task_id = task_id
        self.path = path
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.artifacts = artifacts
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")

    def emit(
        self,
        agent_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        summary: str | None = None,
        status: str | None = None,
        parent_event_id: str | None = None,
        causal_refs: list[str] | None = None,
        tool_name: str | None = None,
        artifact_refs: list[str] | None = None,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            event_id = event_id or f"evt_{uuid4().hex}"
            cleaned = payload or {}
            extracted_refs: list[str] = []
            if self.artifacts is not None:
                cleaned, extracted_refs = self.artifacts.extract(
                    cleaned, source_agent_id=agent_id, source_event_id=event_id
                )
            event = {
                "schema_version": "studio.event.v1",
                "run_id": self.run_id,
                "task_id": self.task_id,
                "agent_id": agent_id,
                "event_id": event_id,
                "sequence": len(self.events),
                "timestamp": utc_now(),
                "event_type": event_type,
                "parent_event_id": parent_event_id,
                "causal_refs": causal_refs or [],
                "tool_name": tool_name,
                "status": status or "completed",
                "summary": summary
                or SUMMARY_TEMPLATES.get(
                    event_type, event_type.replace("_", " ").capitalize()
                ),
                "artifact_refs": list(
                    dict.fromkeys([*(artifact_refs or []), *extracted_refs])
                ),
                "payload": cleaned,
            }
            validate_event(event)
            self.events.append(event)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            return event
