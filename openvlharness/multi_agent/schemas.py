"""Validated public records for coordinated multi-agent execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from jsonschema import validate


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MessageType(str, Enum):
    TASK_ASSIGNMENT = "TASK_ASSIGNMENT"
    STATUS_UPDATE = "STATUS_UPDATE"
    QUESTION = "QUESTION"
    HYPOTHESIS = "HYPOTHESIS"
    EVIDENCE = "EVIDENCE"
    CONTRADICTION = "CONTRADICTION"
    VERIFICATION_REQUEST = "VERIFICATION_REQUEST"
    CANDIDATE_ANSWER = "CANDIDATE_ANSWER"
    FINAL_RESULT = "FINAL_RESULT"
    ERROR = "ERROR"
    CANCELLATION = "CANCELLATION"


class RunStatus(str, Enum):
    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    PLANNING = "PLANNING"
    ASSIGNING = "ASSIGNING"
    RUNNING = "RUNNING"
    SYNTHESIZING = "SYNTHESIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


class WorkerStatus(str, Enum):
    IDLE = "IDLE"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    WAITING_FOR_MESSAGE = "WAITING_FOR_MESSAGE"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


MESSAGE_SCHEMA = {
    "type": "object",
    "required": [
        "message_id",
        "run_id",
        "task_id",
        "sender_id",
        "recipient_id",
        "message_type",
        "content",
        "artifact_refs",
        "created_at",
        "sequence",
    ],
    "properties": {
        "message_id": {"type": "string", "minLength": 1},
        "run_id": {"type": "string", "minLength": 1},
        "task_id": {"type": "string", "minLength": 1},
        "sender_id": {"type": "string", "minLength": 1},
        "recipient_id": {"type": "string", "minLength": 1},
        "message_type": {"enum": [item.value for item in MessageType]},
        "content": {"type": "string"},
        "artifact_refs": {"type": "array", "items": {"type": "string"}},
        "correlation_id": {"type": ["string", "null"]},
        "created_at": {"type": "string", "minLength": 1},
        "sequence": {"type": "integer", "minimum": 0},
        "metadata": {"type": "object"},
    },
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Message:
    message_id: str
    run_id: str
    task_id: str
    sender_id: str
    recipient_id: str
    message_type: str
    content: str
    artifact_refs: tuple[str, ...] = ()
    correlation_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    sequence: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, **kwargs: Any) -> Message:
        kwargs.setdefault("message_id", f"msg_{uuid4().hex}")
        kwargs.setdefault("artifact_refs", ())
        message = cls(**kwargs)
        validate(message.to_dict(), MESSAGE_SCHEMA)
        return message

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["artifact_refs"] = list(self.artifact_refs)
        return value


@dataclass(frozen=True)
class Assignment:
    assignment_id: str
    task_id: str
    worker_id: str
    scope: str
    required_output: str
    tool_budget: int
    deadline_seconds: float
    shared_evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["shared_evidence"] = list(self.shared_evidence)
        return value


@dataclass
class WorkerResult:
    agent_id: str
    task_id: str
    assigned_scope: str
    status: str
    candidate_answer: str | None = None
    evidence_references: list[str] = field(default_factory=list)
    uncertainty_or_limitations: str | None = None
    tool_calls: int = 0
    messages_sent: int = 0
    messages_received: int = 0
    execution_cost: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None
    trajectory: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
