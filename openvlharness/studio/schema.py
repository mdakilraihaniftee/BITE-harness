"""Versioned event validation shared by live delivery and replay."""

from __future__ import annotations

from typing import Any

from jsonschema import validate  # noqa: F401 - kept for callers importing it here
from jsonschema.exceptions import best_match
from jsonschema.validators import validator_for

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


# Compiled once: jsonschema.validate() re-checks the schema itself on every call,
# which cost ~4 ms per event (97% of EventLog.emit). Same checks, same errors.
_EVENT_VALIDATOR = validator_for(EVENT_SCHEMA)(EVENT_SCHEMA)
validator_for(EVENT_SCHEMA).check_schema(EVENT_SCHEMA)


def validate_event(event: dict[str, Any]) -> None:
    error = best_match(_EVENT_VALIDATOR.iter_errors(event))
    if error is not None:
        raise error
