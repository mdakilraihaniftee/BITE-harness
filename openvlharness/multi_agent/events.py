"""Thread-safe event provenance for a multi-agent run."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from .schemas import utc_now


class EventLog:
    def __init__(self, run_id: str, task_id: str, path: Path) -> None:
        self.run_id = run_id
        self.task_id = task_id
        self.path = path
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")

    def emit(
        self, agent_id: str, event_type: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with self._lock:
            event = {
                "run_id": self.run_id,
                "task_id": self.task_id,
                "agent_id": agent_id,
                "event_id": f"evt_{uuid4().hex}",
                "sequence": len(self.events),
                "timestamp": utc_now(),
                "event_type": event_type,
                "payload": payload or {},
            }
            self.events.append(event)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            return event
