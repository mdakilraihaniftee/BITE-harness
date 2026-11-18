"""Explicit coordinator answer state: no estimate, provisional, revised, unresolved, final.

The tracker records only assessments the coordinator actually produced. It never
derives an estimate from worker answers, never initializes a value, and never
sees benchmark labels. A revision event is emitted only when the coordinator's
recorded state genuinely changes; a reassessment that keeps the same value is
recorded as a retained assessment without a new revision number.
"""

from __future__ import annotations

import copy
import json
import re
import threading
from pathlib import Path
from typing import Any

from .schemas import utc_now

ESTIMATE_SCHEMA = "studio.coordinator_estimate.v1"
_INTEGER = re.compile(r"^\s*[+-]?\d+\s*$")


def estimate_type(value: str | None) -> str | None:
    if value is None:
        return None
    return "integer" if _INTEGER.fullmatch(value) else "text"


def canonical(value: str | None) -> Any:
    """Deterministic identity used only to decide whether a value changed.

    This is not answer evaluation: correctness is computed separately by the
    authorized evaluator with the benchmark's own normalization rule.
    """
    if value is None:
        return None
    if _INTEGER.fullmatch(value):
        return int(value)
    return " ".join(value.split()).casefold()


def clean_estimate(value: Any) -> str | None:
    """Coerce a coordinator-reported estimate to a short string, or None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"null", "none", "unknown", "n/a", "-"}:
            return None
        return text[:400]
    return None


class EstimateTracker:
    """Thread-safe coordinator provisional-answer state with persisted history."""

    def __init__(self, emit, path: Path | None = None) -> None:
        self._emit = emit
        self._path = path
        self._lock = threading.Lock()
        self.revision = 0
        self.state: dict[str, Any] = {
            "revision": 0,
            "estimate": None,
            "estimate_type": None,
            "status": "none",
        }
        self.history: list[dict[str, Any]] = []
        self.assessments = 0

    def current(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self.state)

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {"schema_version": ESTIMATE_SCHEMA, "history": self.history},
                indent=2,
                ensure_ascii=False,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )

    def assess(
        self,
        *,
        estimate: Any,
        status: str,
        summary: str | None,
        reason: str | None,
        evidence: list[dict[str, Any]],
        round_index: int,
        source: str = "reassessment",
        model_requests: int = 1,
    ) -> dict[str, Any] | None:
        """Record one coordinator reassessment.

        ``status`` is what the coordinator declared: ``provisional`` (it holds a
        current best answer) or ``unresolved`` (it does not consider any value
        supported). Returns the revision event, or None when the state did not
        change (a retained-assessment event is still recorded).
        """
        value = clean_estimate(estimate)
        declared = "unresolved" if status == "unresolved" or value is None else "provisional"
        if declared == "unresolved":
            value = None
        evidence_refs = list(
            dict.fromkeys(
                ref
                for item in evidence
                for ref in (item.get("report_event_id"), item.get("delivered_event_id"))
                if ref
            )
        )
        with self._lock:
            self.assessments += 1
            previous = copy.deepcopy(self.state)
            had_value = previous["estimate"] is not None
            same_value = canonical(previous["estimate"]) == canonical(value)
            if declared == "provisional":
                if not had_value and previous["status"] in {"none", "unresolved"}:
                    change = "initial" if previous["status"] == "none" else "restored"
                elif not same_value:
                    change = "revised"
                else:
                    change = None
            else:
                change = "withdrawn" if had_value else None
            if change is None:
                payload = {
                    "schema": ESTIMATE_SCHEMA,
                    "outcome": "retained",
                    "round": round_index,
                    "current_revision": previous["revision"],
                    "estimate": previous["estimate"],
                    "status": previous["status"],
                    "declared_status": declared,
                    "assessment_summary": summary,
                    "evidence": evidence,
                    "evidence_refs": evidence_refs,
                    "model_requests": model_requests,
                }
                state_note = (
                    f"kept its estimate {previous['estimate']!r}"
                    if had_value
                    else "still has no estimate"
                )
                self._emit(
                    "coordinator",
                    "COORDINATOR_REASSESSMENT_RECORDED",
                    payload,
                    summary=f"Coordinator reviewed new evidence and {state_note}.",
                    causal_refs=evidence_refs,
                )
                return None
            self.revision += 1
            status_label = {
                "initial": "provisional",
                "restored": "provisional",
                "revised": "revised",
                "withdrawn": "unresolved",
            }[change]
            self.state = {
                "revision": self.revision,
                "estimate": value,
                "estimate_type": estimate_type(value),
                "status": status_label,
                "summary": summary,
                "revision_reason": reason,
                "evidence_refs": evidence_refs,
                "round": round_index,
                "source": source,
                "timestamp": utc_now(),
            }
            record = {
                "schema": ESTIMATE_SCHEMA,
                "agent_id": "coordinator",
                **self.state,
                "change_kind": change,
                "value_changed": not same_value,
                "previous_estimate": previous["estimate"],
                "previous_status": previous["status"],
                "previous_revision": previous["revision"],
                "evidence": evidence,
                "model_requests": model_requests,
            }
            text = {
                "initial": f"Coordinator formed a provisional estimate: {value}.",
                "restored": f"Coordinator restored a provisional estimate: {value}.",
                "revised": f"Coordinator revised its estimate from {previous['estimate']} to {value}.",
                "withdrawn": f"Coordinator withdrew its estimate {previous['estimate']}; the answer is unresolved.",
            }[change]
            event = self._emit(
                "coordinator",
                "COORDINATOR_ESTIMATE_UPDATED",
                record,
                summary=text,
                causal_refs=evidence_refs,
            )
            record["event_id"] = (event or {}).get("event_id")
            self.history.append(record)
            self._persist()
            return event

    def finalize(
        self,
        answer: Any,
        *,
        evidence: list[dict[str, Any]],
        summary: str | None = None,
    ) -> dict[str, Any] | None:
        """Record the coordinator's final answer as the terminal answer state."""
        value = clean_estimate(answer)
        evidence_refs = list(
            dict.fromkeys(
                ref
                for item in evidence
                for ref in (item.get("report_event_id"), item.get("delivered_event_id"))
                if ref
            )
        )
        with self._lock:
            previous = copy.deepcopy(self.state)
            self.revision += 1
            status = "final" if value is not None else "abstained"
            self.state = {
                "revision": self.revision,
                "estimate": value,
                "estimate_type": estimate_type(value),
                "status": status,
                "summary": summary,
                "revision_reason": "Coordinator synthesis recorded the final answer.",
                "evidence_refs": evidence_refs,
                "source": "synthesis",
                "timestamp": utc_now(),
            }
            value_changed = canonical(previous["estimate"]) != canonical(value)
            record = {
                "schema": ESTIMATE_SCHEMA,
                "agent_id": "coordinator",
                **self.state,
                "change_kind": "finalized",
                "value_changed": value_changed,
                "previous_estimate": previous["estimate"],
                "previous_status": previous["status"],
                "previous_revision": previous["revision"],
                "evidence": evidence,
                "model_requests": 0,
            }
            if value is None:
                text = "Coordinator finalized without an answer (abstained)."
            elif previous["estimate"] is not None and not value_changed:
                text = f"Coordinator finalized its estimate {value} as the final answer."
            elif previous["estimate"] is not None:
                text = f"Coordinator finalized {value}, changing from its provisional {previous['estimate']}."
            else:
                text = f"Coordinator recorded final answer {value} (no provisional estimate preceded it)."
            event = self._emit(
                "coordinator",
                "COORDINATOR_ESTIMATE_UPDATED",
                record,
                summary=text,
                causal_refs=evidence_refs,
            )
            record["event_id"] = (event or {}).get("event_id")
            self.history.append(record)
            self._persist()
            return event
