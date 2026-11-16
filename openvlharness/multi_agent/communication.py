"""Bounded, typed communication with explicit actor identities."""

from __future__ import annotations

import json
import threading
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from .budget import BudgetManager
from .events import EventLog
from .schemas import Message


class CommunicationError(ValueError):
    pass


class CommunicationBus:
    def __init__(
        self,
        *,
        actors: set[str],
        coordinator_id: str,
        enabled: bool,
        peer_to_peer: bool,
        max_inbox: int,
        budget: BudgetManager,
        events: EventLog,
        message_path: Path,
    ) -> None:
        self.actors = set(actors)
        self.coordinator_id = coordinator_id
        self.enabled = enabled
        self.peer_to_peer = peer_to_peer
        self.max_inbox = max_inbox
        self.budget = budget
        self.events = events
        self.message_path = message_path
        self._inboxes: dict[str, deque[Message]] = defaultdict(deque)
        self._seen: set[str] = set()
        self._messages: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        message_path.parent.mkdir(parents=True, exist_ok=True)
        message_path.write_text("")

    def send(self, message: Message) -> str:
        if not self.enabled and message.message_type != "TASK_ASSIGNMENT":
            return "disabled"
        if (
            message.sender_id not in self.actors
            or message.recipient_id not in self.actors
        ):
            raise CommunicationError("Unknown sender or recipient")
        if any(
            not ref
            or ref.startswith(("/", "\\"))
            or ".." in ref.replace("\\", "/").split("/")
            for ref in message.artifact_refs
        ):
            raise CommunicationError(
                "Artifact references must be nonempty logical IDs without path traversal"
            )
        if (
            message.sender_id != self.coordinator_id
            and message.recipient_id != self.coordinator_id
            and not self.peer_to_peer
        ):
            raise CommunicationError("Worker-to-worker communication is disabled")
        with self._lock:
            if message.message_id in self._seen:
                self.events.emit(
                    message.sender_id,
                    "MESSAGE_DUPLICATE",
                    {"message_id": message.message_id},
                )
                return "duplicate"
            if len(self._inboxes[message.recipient_id]) >= self.max_inbox:
                self.events.emit(
                    message.sender_id,
                    "MESSAGE_REJECTED",
                    {
                        "message_id": message.message_id,
                        "reason": "recipient_inbox_full",
                    },
                )
                return "inbox_full"
            if not self.budget.reserve(message.sender_id, "messages").granted:
                self.events.emit(
                    message.sender_id,
                    "MESSAGE_REJECTED",
                    {"message_id": message.message_id, "reason": "budget_denied"},
                )
                return "budget_denied"
            self._seen.add(message.message_id)
            self._inboxes[message.recipient_id].append(message)
            record = message.to_dict()
            self._messages.append(record)
            with self.message_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.events.emit(
            message.sender_id,
            "MESSAGE_SENT",
            {
                "message_id": message.message_id,
                "recipient_id": message.recipient_id,
                "message_type": message.message_type,
            },
        )
        return "delivered"

    def receive(self, agent_id: str) -> list[Message]:
        if agent_id not in self.actors:
            raise CommunicationError(f"Unknown recipient: {agent_id}")
        with self._lock:
            messages = list(self._inboxes[agent_id])
            self._inboxes[agent_id].clear()
        for message in messages:
            self.events.emit(
                agent_id,
                "MESSAGE_RECEIVED",
                {
                    "message_id": message.message_id,
                    "sender_id": message.sender_id,
                    "message_type": message.message_type,
                },
            )
        return messages

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._messages)
