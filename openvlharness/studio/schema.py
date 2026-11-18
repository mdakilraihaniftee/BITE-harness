"""Versioned event validation shared by live delivery and replay."""

from __future__ import annotations

from typing import Any

from jsonschema import validate

EVENT_SCHEMA = {
    "type": "object",
    "required": [
        "schema_version",
        "run_id",
        "task_id",
        "agent_id",
        "event_id",
        "sequence",
        "timestamp",
        "event_type",
        "causal_refs",
        "status",
        "summary",
        "artifact_refs",
        "payload",
    ],
    "properties": {
        "schema_version": {"const": "studio.event.v1"},
        "run_id": {"type": "string", "minLength": 1},
        "task_id": {"type": "string", "minLength": 1},
        "agent_id": {"type": "string", "minLength": 1},
        "event_id": {"type": "string", "minLength": 1},
        "sequence": {"type": "integer", "minimum": 0},
        "timestamp": {"type": "string", "minLength": 1},
        "event_type": {"type": "string", "minLength": 1},
        "parent_event_id": {"type": ["string", "null"]},
        "causal_refs": {"type": "array", "items": {"type": "string"}},
        "tool_name": {"type": ["string", "null"]},
        "status": {"enum": ["planned", "running", "completed", "failed", "cancelled"]},
        "summary": {"type": "string"},
        "artifact_refs": {"type": "array", "items": {"type": "string"}},
        "payload": {"type": "object"},
    },
    "additionalProperties": False,
}


def validate_event(event: dict[str, Any]) -> None:
    validate(event, EVENT_SCHEMA)
