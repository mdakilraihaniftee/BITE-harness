"""Resolve recorded runtime identities onto the six logical ARGUS forensic roles.

The console shows four peer visual investigators, one ToolDF audio
investigator, and one judge. Traces keep their native ``agent_role`` values;
this module only maps them for display. It never creates activity: an agent
with no recorded event is reported as ``not_invoked`` and a tool, message, or
reinspection edge exists only when a matching trace event exists.
"""

from __future__ import annotations

from typing import Any, Iterable

from .story import SUBSTANTIVE_TOOLS, event_modality, event_sequence


VISUAL_AGENT_IDS = tuple(f"visual_investigator_{index}" for index in range(1, 5))
AUDIO_AGENT_ID = "audio_investigator"
JUDGE_AGENT_ID = "judge"
LOGICAL_AGENT_IDS = (*VISUAL_AGENT_IDS, AUDIO_AGENT_ID, JUDGE_AGENT_ID)
AGENT_STATES = (
    "not_invoked", "queued", "active", "waiting_for_tool", "waiting_for_peer",
    "completed", "failed", "cancelled",
)

LOGICAL_AGENTS: dict[str, dict[str, str]] = {
    **{
        agent_id: {
            "label": f"Visual Agent {index}", "short": f"V{index}", "team": "visual",
            "role": "Generic visual investigator",
            "backend": "Shared Qwen2.5-VL base model · own session, tools, and hypotheses",
        }
        for index, agent_id in enumerate(VISUAL_AGENT_IDS, start=1)
    },
    AUDIO_AGENT_ID: {
        "label": "Audio Agent 5", "short": "A5", "team": "audio",
        "role": "Specialized audio investigator",
        "backend": "ToolDF Qwen-Omni planner · XLSR-AASIST detectors · supplementary verification",
    },
    JUDGE_AGENT_ID: {
        "label": "Judge Agent 6", "short": "J6", "team": "case_review",
        "role": "Case review and judge",
        "backend": "Original trained ARGUS visual judge · rule-based case review",
    },
}

_GENERIC_ALIASES = {
    **{f"investigator_{index}": agent for index, agent in enumerate(VISUAL_AGENT_IDS, start=1)},
    **{f"visual_agent_{index}": agent for index, agent in enumerate(VISUAL_AGENT_IDS, start=1)},
    **{agent: agent for agent in VISUAL_AGENT_IDS},
}
# Older specialized runs had four role-named observers acting as the visual
# team. In generic runs the same roles only produce trained-judge inputs.
_LEGACY_SPECIALIZED = {
    "texture_agent": VISUAL_AGENT_IDS[0], "lighting_agent": VISUAL_AGENT_IDS[1],
    "motion_agent": VISUAL_AGENT_IDS[2], "physics_agent": VISUAL_AGENT_IDS[3],
}
_AUDIO_COMPONENTS = {
    "audio_investigator": "ToolDF audio investigator",
    "audio_agent": "ToolDF audio investigator",
    "tooldf_planner": "ToolDF planner",
    "independent_audio_reviewer": "independent-corroboration check",
}
_JUDGE_COMPONENTS = {
    "judge_coordinator": "Judge coordinator",
    "judge": "Judge coordinator",
    "audio_case_coordinator": "ClawTeam audio case coordinator",
    "audiovisual_reviewer": "rule-based case review",
}
_INFRASTRUCTURE = {
    "system": "ARGUS runtime",
    "clawteam_coordinator": "ClawTeam coordination",
    "direct_demo": "Scripted tool demo (not an agent)",
    "unknown": "Native runtime",
}

ROUTINE_TOOLS = frozenset({
    "get_video_metadata", "get_frame_manifest", "get_observation_status",
    "list_forensic_tools", "list_evidence", "get_final_result", "get_reinspection_status",
    "list_hypotheses", "list_investigation_questions",
})
MODEL_TOOLS = {
    "analyze_general": "Qwen2.5-VL base observation",
    "analyze_texture": "Trained texture LoRA observer",
    "analyze_lighting": "Trained lighting LoRA observer",
    "analyze_motion": "Trained motion LoRA observer",
    "analyze_physics": "Trained physics LoRA observer",
    "analyze_judge": "Original trained ARGUS visual judge",
    "analyze_augmented_judge": "Experimental evidence-augmented judge",
    "consult_trained_argus_observer": "Trained ARGUS observer consultation",
    "run_tooldf_investigation": "ToolDF investigation",
    "get_audio_result": "Read ToolDF audio result",
}
TOOLDF_INTERNAL_TOOLS = frozenset({
    "source_separator", "speech_deepfake_detector", "singing_deepfake_detector",
    "music_deepfake_detector", "sound_deepfake_detector",
})
_DISPLAYED_TOOLS = frozenset((*SUBSTANTIVE_TOOLS, *MODEL_TOOLS))


def _short(value: Any, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _pretty(value: Any) -> str:
    return str(value or "").replace("_", " ").title()


def _result(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("result") if isinstance(event.get("result"), dict) else {}


def _metadata(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("metadata") if isinstance(event.get("metadata"), dict) else {}


def model_provenance(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Resolve adapter use from recorded reproducibility metadata."""
    modes: set[str] = set()
    for row in rows:
        if row.get("surface") != "harness_configuration_resolved":
            continue
        reproducibility = _result(row).get("reproducibility")
        identifiers = reproducibility.get("model_identifiers") if isinstance(reproducibility, dict) else None
        if not isinstance(identifiers, dict):
            continue
        adapters = identifiers.get("observer_loras")
        judge = identifiers.get("judge_lora")
        modes.add("lora" if bool(adapters) or bool(judge) else "base_no_lora")
    mode = next(iter(modes)) if len(modes) == 1 else "mixed" if modes else "unknown"
    return {"mode": mode, "recorded": bool(modes)}


def global_event_id(event: dict[str, Any]) -> str:
    return str(event.get("global_event_id") or f"{event.get('run_id', '')}:{event.get('event_id') or event.get('sequence_num', 0)}")


def run_investigator_modes(rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Return ``generic`` or ``specialized`` per run from recorded evidence only."""
    explicit: dict[str, str] = {}
    generic: set[str] = set()
    seen: set[str] = set()
    for row in rows:
        run_id = str(row.get("run_id", ""))
        seen.add(run_id)
        mode = str(_metadata(row).get("investigator_mode", ""))
        if row.get("surface") == "case_opened" and mode in {"generic", "specialized"}:
            explicit[run_id] = mode
        if str(row.get("agent_role", "")) in _GENERIC_ALIASES:
            generic.add(run_id)
    return {run_id: explicit.get(run_id, "generic" if run_id in generic else "specialized") for run_id in seen}


def resolve_identity(role: str, *, investigator_mode: str = "specialized",
                     explicit: str = "") -> dict[str, Any]:
    """Map one native runtime role to a logical role without matching display names."""
    role = str(role or "unknown")
    if explicit in LOGICAL_AGENT_IDS:
        return {"logical_agent_id": explicit, "component": _pretty(role), "mapping_basis": "explicit_trace_field", "infrastructure": False}
    if role in _GENERIC_ALIASES:
        return {"logical_agent_id": _GENERIC_ALIASES[role], "component": "Generic visual investigator",
                "mapping_basis": "runtime_role", "infrastructure": False}
    if role in _LEGACY_SPECIALIZED:
        if investigator_mode == "generic":
            return {"logical_agent_id": JUDGE_AGENT_ID,
                    "component": f"trained {role.removesuffix('_agent')} observer (judge input)",
                    "mapping_basis": "generic_run_trained_judge_input", "infrastructure": False}
        return {"logical_agent_id": _LEGACY_SPECIALIZED[role],
                "component": f"legacy {role}",
                "mapping_basis": "legacy_specialized_alias", "infrastructure": False}
    if role in _AUDIO_COMPONENTS:
        return {"logical_agent_id": AUDIO_AGENT_ID, "component": _AUDIO_COMPONENTS[role],
                "mapping_basis": "runtime_role", "infrastructure": False}
    if role in _JUDGE_COMPONENTS:
        return {"logical_agent_id": JUDGE_AGENT_ID, "component": _JUDGE_COMPONENTS[role],
                "mapping_basis": "runtime_role", "infrastructure": False}
    return {"logical_agent_id": "", "component": _INFRASTRUCTURE.get(role, _pretty(role)),
            "mapping_basis": "infrastructure" if role in _INFRASTRUCTURE else "unmapped", "infrastructure": True}


def tool_group(event: dict[str, Any]) -> str:
    name = str(event.get("tool_name", ""))
    metadata = _metadata(event)
    if metadata.get("outer_controller"):
        return "supplementary_verification"
    if metadata.get("internal_tooldf_call") or name in TOOLDF_INTERNAL_TOOLS:
        return "tooldf"
    if name in MODEL_TOOLS:
        return "model"
    return "forensic"


def tool_node_id(agent_id: str, tool_name: str) -> str:
    return f"tool:{agent_id}:{tool_name}"


class _Resolver:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.modes = run_investigator_modes(rows)
        self.sessions: dict[tuple[str, str], str] = {}
        for row in rows:
            task_id = _metadata(row).get("task_id")
            if row.get("surface") == "task_assigned" and task_id:
                self.sessions.setdefault((str(row.get("run_id", "")), str(row.get("agent_role", ""))), f"clawteam-task:{task_id}")

    def identity(self, row: dict[str, Any], role: str | None = None) -> dict[str, Any]:
        native = str(row.get("agent_role", "unknown") if role is None else role)
        metadata = _metadata(row)
        explicit = str(metadata.get("logical_agent_id", "")) if role is None else str(metadata.get("target_logical_agent_id", ""))
        identity = resolve_identity(native, investigator_mode=self.modes.get(str(row.get("run_id", "")), "specialized"), explicit=explicit)
        identity["agent_role"] = native
        run_id = str(row.get("run_id", ""))
        session = metadata.get("agent_session_id") if role is None else ""
        identity["agent_session_id"] = str(session or self.sessions.get((run_id, native)) or f"{run_id}:{native}")
        identity["session_basis"] = "recorded" if session else "clawteam_task" if (run_id, native) in self.sessions else "run_and_role"
        return identity


def classify_edge(row: dict[str, Any], source: dict[str, Any], target: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the one recorded interaction an event represents, or ``None``."""
    surface = str(row.get("surface", ""))
    agent = source.get("logical_agent_id", "")
    target_agent = (target or {}).get("logical_agent_id", "")
    tool = str(row.get("tool_name", ""))
    result = _result(row)
    status = "failed" if row.get("status") == "error" else "recorded"
    if not agent:
        return None
    if surface.startswith("crossmodal_request_") and target_agent:
        return {"kind": "reinspection_request" if surface.endswith("assigned") else "finding_report" if surface.endswith("completed") else "agent_message",
                "source": agent, "target": target_agent, "status": status,
                "request_id": _metadata(row).get("request_id", "")}
    if surface in {"tool_call", "audio_tool_called", "crossmodal_tool_call"} and tool in _DISPLAYED_TOOLS:
        kind = "model_evaluation" if tool in MODEL_TOOLS else "tool_request"
        return {"kind": kind, "phase": "request", "source": agent, "target": tool_node_id(agent, tool),
                "tool_name": tool, "tool_group": tool_group(row), "status": status}
    if surface in {"tool_result", "audio_tool_result", "crossmodal_tool_result"} and tool in _DISPLAYED_TOOLS:
        kind = "model_evaluation" if tool in MODEL_TOOLS else "tool_result"
        return {"kind": kind, "phase": "result", "source": tool_node_id(agent, tool), "target": agent,
                "tool_name": tool, "tool_group": tool_group(row), "status": status}
    if surface == "forensic_tool_completed" and not row.get("tool_call_id") and tool:
        return {"kind": "tool_result", "phase": "result", "source": tool_node_id(agent, tool), "target": agent,
                "tool_name": tool, "tool_group": tool_group(row), "status": status, "legacy_link": True}
    if surface == "memory_shared" and target_agent and target_agent != agent:
        return {"kind": "finding_report", "source": agent, "target": target_agent, "status": status}
    if surface == "reinspection_requested" and target_agent:
        return {"kind": "reinspection_request", "source": agent, "target": target_agent, "tool_name": tool,
                "request_id": str(result.get("request_id") or row.get("reinspection_request_id") or ""), "status": status}
    if surface == "reinspection_completed":
        return {"kind": "reinspection_return", "source": agent, "target": target_agent or JUDGE_AGENT_ID,
                "request_id": str(result.get("request_id") or row.get("reinspection_request_id") or ""), "status": status}
    if surface in {"peer_review_requested", "peer_review_completed", "audio_peer_review_requested", "audio_peer_review_completed"} and target_agent:
        internal = target_agent == agent
        return {"kind": "internal_check" if internal else "agent_message", "source": agent, "target": target_agent,
                "status": status, "internal": internal}
    if surface == "audiovisual_case_review" and result.get("audio_prediction") is not None:
        return {"kind": "case_review_input", "source": AUDIO_AGENT_ID, "target": agent,
                "status": status, "consumed_field": "audio_investigation_assessment"}
    return None


def _action(row: dict[str, Any], identity: dict[str, Any], labels: dict[str, str]) -> str:
    surface = str(row.get("surface", ""))
    result, metadata = _result(row), _metadata(row)
    tool = _pretty(row.get("tool_name") or result.get("next_tool"))
    content = row.get("content", "")
    target = labels.get(str(row.get("_target_logical", "")), _pretty(row.get("target_role")))
    base_no_lora = bool(row.get("_base_no_lora"))
    if surface == "task_assigned":
        blockers = metadata.get("blocked_by") or []
        return f"ClawTeam task assigned{f'; blocked by {len(blockers)} investigator task(s)' if blockers else ''}: {_short(metadata.get('assignment', ''), 80)}".rstrip(": ")
    if surface == "agent_started":
        return "Started"
    if surface == "observation_generated":
        prefix = "Base-model" if base_no_lora else "Trained LoRA"
        return f"{prefix} {identity['agent_role'].removesuffix('_agent')} observation recorded (judge input)"
    if surface == "general_observation_generated":
        return f"Recorded base-VLM observation: {_short(content, 80)}"
    if surface in {"hypothesis_created", "audio_hypothesis_created"}:
        return f"Registered hypothesis {result.get('hypothesis_id', '')}: {_short(content, 80)}"
    if surface == "investigation_decision":
        return f"Selected {tool}: {_short(result.get('suspicion'), 80)}"
    if surface in {"tool_call", "audio_tool_called"}:
        return f"Calling {MODEL_TOOLS.get(str(row.get('tool_name')), tool)}"
    if surface in {"tool_result", "audio_tool_result"}:
        tool = MODEL_TOOLS.get(str(row.get("tool_name")), tool)
        if row.get("status") == "error":
            return f"{tool} failed"
        ids = ", ".join(str(item) for item in row.get("evidence_ids") or [])
        return f"{tool} returned {ids or 'a result'}"
    if surface in {"evidence_interpreted", "audio_evidence_interpreted"}:
        assessment = result.get("assessment")
        return f"Interpreted evidence{f' as {_pretty(assessment)}' if assessment else ''}: {_short(result.get('finding') or content, 70)}"
    if surface == "memory_shared":
        return f"Shared finding with {target}"
    if surface == "hypothesis_updated":
        if result.get("claim_id"):
            return f"Registered evidence claim {result['claim_id']}"
        return f"{result.get('hypothesis_id', 'Hypothesis')} → {_pretty(result.get('status'))}"
    if surface == "reinspection_requested":
        return f"Requested reinspection from {target} ({tool})"
    if surface == "reinspection_completed":
        return "Returned reinspection evidence"
    if surface == "judge_invoked":
        return f"Invoked {MODEL_TOOLS.get(str(row.get('tool_name')), tool)}"
    if surface == "judge_completed":
        label = "Base-model visual judge" if base_no_lora else "Original trained visual judge"
        return f"{label} returned {str(result.get('answer', 'unknown')).upper()}"
    if surface == "augmented_verdict_created":
        return f"Experimental augmented judge returned {str(result.get('answer', 'unknown')).upper()}"
    if surface == "audio_scene_analyzed":
        return f"ToolDF scene analysis: {_short(content, 80)}"
    if surface == "audio_tool_planned":
        return f"Planned: {_short(content, 90)}"
    if surface == "audio_verdict_generated":
        return f"ToolDF original prediction {str(result.get('tooldf_original_prediction', 'unknown')).upper()}"
    if surface == "audio_finding_published":
        return "Published audio finding"
    if surface == "audiovisual_case_review":
        return f"Rule-based case review: {_pretty(result.get('case_assessment'))}"
    if surface in {"peer_review_requested", "audio_peer_review_requested"}:
        return f"Requested review from {target}"
    if surface in {"peer_review_completed", "audio_peer_review_completed"}:
        return f"Completed review for {target}"
    if surface == "task_completed":
        return "ClawTeam task completed" if row.get("harness") in {"codex", "claude", "openclaw"} else "Investigator task completed"
    if surface == "run_completed":
        return "Run completed"
    simple = {
        "memory_read": "Read case notebook", "memory_written": "Wrote private notebook entry",
        "investigation_question_opened": "Opened case question", "investigation_question_claimed": "Claimed case question",
        "investigation_question_resolved": "Resolved case question", "tool_request_adjusted": "MCP gateway adjusted the request",
        "forensic_tool_requested": "Forensic tool request authorized", "forensic_tool_completed": "Forensic tool completed",
        "evidence_created": "Evidence record stored", "audio_evidence_created": "Audio evidence record stored",
        "evidence_reviewed": "Evidence provenance reviewed", "claim_verified": "Claim provenance verified",
        "next_action_planned": f"Planned next: {_short(result.get('next_action') or content, 80)}",
        "next_action_started": "Started planned next action", "audio_inference_started": "ToolDF inference started",
        "audio_verification_planned": "Planned supplementary verification", "audio_investigation_stopped": "Stopped supplementary verification",
        "global_scan_started": "Global scan started", "global_scan_completed": "Global scan completed",
    }
    if surface in simple:
        return simple[surface]
    if surface in {"agent_failed", "audio_analysis_failed"}:
        return f"Failed: {_short(result.get('error') or content, 90)}"
    return _pretty(surface)


_FAILURE_SURFACES = frozenset({"agent_failed", "audio_analysis_failed", "crossmodal_request_failed"})
_CANCEL_SURFACES = frozenset({"agent_cancelled", "task_cancelled"})
_SKIPPED_SURFACES = frozenset({"native_event"})


def assemble_agent_model(rows: Iterable[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    """Build the six-role view used identically by live streaming and replay."""
    events = sorted(rows, key=event_sequence)
    provenance = model_provenance(events)
    base_no_lora = provenance["mode"] == "base_no_lora"
    resolver = _Resolver(events)
    labels = {agent_id: info["label"] for agent_id, info in LOGICAL_AGENTS.items()}
    claims = {str(item.get("claim_id")): item for item in context.get("claims", []) if isinstance(item, dict)}
    agents: dict[str, dict[str, Any]] = {
        agent_id: {
            "agent_id": agent_id, **info, "executed": False, "configured": False, "configured_basis": "",
            "runtime_identities": {}, "snapshots": [], "tools": [], "hypotheses": [], "evidence": [],
            "interpretations": [], "findings": [], "model_evaluations": [], "reinspections": [],
            "received": [], "next_actions": [], "observations": [], "scene": [], "verdicts": [], "failures": [],
            "first_sequence": None, "last_sequence": None, "completion_recorded": False,
        }
        for agent_id, info in LOGICAL_AGENTS.items()
    }
    runtime: dict[str, dict[str, Any]] = {
        agent_id: {"state": "not_invoked", "pending_calls": {}, "blockers": set(), "awaiting_requests": set(),
                   "tool_calls": 0, "evidence": set(), "finding_status": "No finding recorded", "current_tool": "",
                   "reopen_requests": set()}
        for agent_id in LOGICAL_AGENTS
    }
    role_map: dict[tuple[str, str], dict[str, Any]] = {}
    communications: list[dict[str, Any]] = []
    annotations: dict[str, dict[str, Any]] = {}
    task_owner: dict[str, str] = {}
    infrastructure = {"clawteam_tasks": 0, "mcp_calls": 0, "runtime_failures": [], "harnesses": set()}
    ended_runs: set[str] = set()

    def snapshot(agent_id: str, row: dict[str, Any], action: str) -> None:
        item = runtime[agent_id]
        pending = list(item["pending_calls"].values())
        agents[agent_id]["snapshots"].append({
            "sequence": event_sequence(row), "global_event_id": global_event_id(row),
            "timestamp": row.get("timestamp", ""), "state": item["state"],
            "current_tool": pending[-1] if pending else "", "last_tool": item["current_tool"],
            "action": action, "tool_calls": item["tool_calls"], "evidence_count": len(item["evidence"]),
            "finding_status": item["finding_status"],
            "awaiting_reinspection": sorted(item["awaiting_requests"]),
            "outstanding_blockers": len(item["blockers"]),
        })

    for row in events:
        surface = str(row.get("surface", ""))
        if surface in _SKIPPED_SURFACES:
            continue
        sequence = event_sequence(row)
        infrastructure["harnesses"].add(str(row.get("harness", "")))
        identity = resolver.identity(row)
        target = resolver.identity(row, str(row.get("target_role"))) if row.get("target_role") else None
        agent_id = identity["logical_agent_id"]
        key = (str(row.get("run_id", "")), identity["agent_role"])
        role_map.setdefault(key, {
            "run_id": key[0], "agent_role": key[1], "logical_agent_id": agent_id,
            "component": identity["component"], "mapping_basis": identity["mapping_basis"],
            "agent_session_id": identity["agent_session_id"], "session_basis": identity["session_basis"],
        })
        if surface == "task_assigned":
            infrastructure["clawteam_tasks"] += 1
            task_id = str(_metadata(row).get("task_id", ""))
            if task_id:
                task_owner[task_id] = agent_id
        if surface in {"tool_call", "tool_result"}:
            infrastructure["mcp_calls"] += int(surface == "tool_call")
        if surface == "run_completed":
            ended_runs.add(str(row.get("run_id", "")))
        if surface in _FAILURE_SURFACES and not agent_id:
            infrastructure["runtime_failures"].append({"sequence": sequence, "error": _short(_result(row).get("error") or row.get("content"), 240)})
        edge = classify_edge(row, identity, target)
        row_with_target = {**row, "_target_logical": (target or {}).get("logical_agent_id", ""),
                           "_base_no_lora": base_no_lora}
        annotation = {
            "logical_agent_id": agent_id, "logical_component": identity["component"],
            "mapping_basis": identity["mapping_basis"], "agent_session_id": identity["agent_session_id"],
            "logical_target_id": (target or {}).get("logical_agent_id", ""), "modality": event_modality(row),
            "edge": edge,
        }
        annotations[global_event_id(row)] = annotation
        if edge and edge["kind"] in {"finding_report", "reinspection_request", "reinspection_return", "agent_message", "case_review_input", "internal_check"}:
            communications.append({
                **edge, "sequence": sequence, "global_event_id": global_event_id(row),
                "event_id": row.get("event_id", ""), "timestamp": row.get("timestamp", ""),
                "content": _short(row.get("content"), 400), "evidence_ids": list(row.get("evidence_ids") or []),
                "native_source": identity["agent_role"], "native_target": str(row.get("target_role", "")),
            })
        # Task completion can unblock the judge even though the judge itself
        # records nothing until its next own event.
        if surface == "task_completed":
            task_id = str(_metadata(row).get("task_id", ""))
            for item in runtime.values():
                item["blockers"].discard(task_id)
        if not agent_id:
            continue
        agent = agents[agent_id]
        state = runtime[agent_id]
        # Generic runs precompute the four trained LoRA observer reports before
        # any agent starts; they are judge inputs, not judge execution.
        precomputed_input = identity["mapping_basis"] == "generic_run_trained_judge_input"
        agent["executed"] = agent["executed"] or (surface != "task_assigned" and not precomputed_input)
        agent["first_sequence"] = sequence if agent["first_sequence"] is None else agent["first_sequence"]
        agent["last_sequence"] = sequence
        identity_record = agent["runtime_identities"].setdefault(identity["agent_role"], {
            "agent_role": identity["agent_role"], "component": identity["component"],
            "mapping_basis": identity["mapping_basis"], "agent_session_ids": [], "run_ids": [],
            "harness": str(row.get("harness", "")), "event_count": 0, "first_sequence": sequence,
        })
        identity_record["event_count"] += 1
        for field, value in (("agent_session_ids", identity["agent_session_id"]), ("run_ids", str(row.get("run_id", "")))):
            if value not in identity_record[field]:
                identity_record[field].append(value)
        result, metadata = _result(row), _metadata(row)
        tool = str(row.get("tool_name", ""))
        call_id = str(row.get("tool_call_id") or "")
        call_key = (str(row.get("run_id", "")), call_id or f"seq:{sequence}")
        is_call = surface in {"tool_call", "audio_tool_called", "crossmodal_tool_call"}
        is_result = surface in {"tool_result", "audio_tool_result", "crossmodal_tool_result"}
        if (is_call or is_result) and tool not in _DISPLAYED_TOOLS:
            # Routine reads and MCP bookkeeping (create_hypothesis, ...) have
            # their own domain events; they do not change execution state.
            continue
        if surface in {"crossmodal_request_started", "agent_started"} and state["state"] == "completed":
            state["state"] = "active"
        if state["state"] == "completed" and state["reopen_requests"] and surface not in {"task_completed", "run_completed"}:
            # A judge reinspection request reopens a finished investigator, but
            # only once that investigator records new work of its own.
            state["state"] = "active"
        terminal = state["state"] in {"completed", "failed", "cancelled"}
        waiting = bool(state["blockers"] or state["awaiting_requests"])
        if precomputed_input:
            pass
        elif surface == "task_assigned":
            agent["configured"] = True
            agent["configured_basis"] = "clawteam_task_assigned"
            if state["state"] == "not_invoked":
                state["state"] = "queued"
            state["blockers"].update(str(item) for item in metadata.get("blocked_by") or [])
        elif surface in _FAILURE_SURFACES:
            state["state"] = "failed"
        elif surface in _CANCEL_SURFACES or row.get("status") == "cancelled":
            state["state"] = "cancelled"
        elif surface in {"task_completed", "run_completed", "crossmodal_request_completed"}:
            # Closing a trace does not undo a recorded failure/cancellation.
            if state["state"] not in {"failed", "cancelled"}:
                state["state"] = "failed" if row.get("status") == "error" else "completed"
            agent["completion_recorded"] = True
        elif terminal:
            pass  # Later records stay visible but do not reopen a finished agent.
        elif is_call:
            state["pending_calls"][call_key] = tool
            state["current_tool"] = tool
            state["state"] = "waiting_for_tool"
        elif is_result:
            state["pending_calls"].pop(call_key, None)
            if not state["pending_calls"]:
                state["state"] = "waiting_for_peer" if waiting else "active"
        elif surface == "reinspection_requested":
            state["awaiting_requests"].add(str(result.get("request_id") or row.get("reinspection_request_id") or f"seq:{sequence}"))
            state["state"] = "waiting_for_peer"
        elif not state["pending_calls"]:
            state["state"] = "waiting_for_peer" if waiting else "active"
        if is_result and not precomputed_input:
            if row.get("status") != "error":
                state["tool_calls"] += 1

        # Evidence-linked per-agent record, bounded by sequence in the browser.
        common = {"sequence": sequence, "global_event_id": global_event_id(row), "timestamp": row.get("timestamp", ""),
                  "run_id": str(row.get("run_id", ""))}
        if surface in _FAILURE_SURFACES or (surface in {"task_completed", "run_completed"} and row.get("status") == "error"):
            agent["failures"].append({**common, "surface": surface,
                                      "error": _short(result.get("error") or row.get("content") or "Execution ended with an error", 600)})
        if is_call:
            agent["tools"].append({**common, "call_sequence": sequence, "result_sequence": None, "tool_name": tool,
                                   "tool_label": MODEL_TOOLS.get(tool, _pretty(tool)), "tool_group": tool_group(row),
                                   "tool_call_id": call_id, "decision_id": str(row.get("decision_id", "")),
                                   "status": "running", "evidence_ids": [], "native_role": identity["agent_role"],
                                   "component": identity["component"]})
        elif is_result:
            match = next((item for item in reversed(agent["tools"])
                          if call_id and item["tool_call_id"] == call_id and item["run_id"] == common["run_id"]), None)
            if match is None:
                match = {**common, "call_sequence": None, "tool_name": tool, "tool_label": MODEL_TOOLS.get(tool, _pretty(tool)),
                         "tool_group": tool_group(row), "tool_call_id": call_id, "decision_id": str(row.get("decision_id", "")),
                         "native_role": identity["agent_role"], "component": identity["component"],
                         "call_link": "result_without_recorded_call"}
                agent["tools"].append(match)
            match.update(result_sequence=sequence, status="failed" if row.get("status") == "error" else "completed",
                         evidence_ids=[str(item) for item in row.get("evidence_ids") or []])
        for evidence_id in row.get("evidence_ids") or []:
            if surface in {"tool_result", "audio_tool_result", "crossmodal_tool_result", "forensic_tool_completed", "evidence_created", "audio_evidence_created"} and not any(
                item["evidence_id"] == evidence_id and item["run_id"] == common["run_id"] for item in agent["evidence"]
            ):
                agent["evidence"].append({**common, "evidence_id": str(evidence_id), "tool_name": tool, "tool_call_id": call_id})
                if not precomputed_input:
                    state["evidence"].add((common["run_id"], str(evidence_id)))
        if surface in {"hypothesis_created", "audio_hypothesis_created"} or (surface in {"hypothesis_updated", "audio_hypothesis_updated", "crossmodal_hypothesis_updated"} and result.get("hypothesis_id")):
            agent["hypotheses"].append({**common, "hypothesis_id": str(result.get("hypothesis_id") or row.get("hypothesis_id") or ""),
                                        "text": _short(result.get("candidate_explanation") or row.get("content"), 400),
                                        "status": str(result.get("status") or ("open" if surface.endswith("created") else "")),
                                        "evidence_ids": list(row.get("evidence_ids") or [])})
        if surface in {"evidence_interpreted", "audio_evidence_interpreted"}:
            agent["interpretations"].append({**common, "text": _short(result.get("finding") or row.get("content"), 600),
                                             "assessment": str(result.get("assessment", "")),
                                             "limitations": [str(item) for item in result.get("limitations") or []],
                                             "evidence_ids": list(row.get("evidence_ids") or []), "tool_call_id": call_id})
        if surface in {"next_action_planned"} or (surface in {"evidence_interpreted", "audio_evidence_interpreted"} and result.get("next_action")):
            agent["next_actions"].append({**common, "action": _short(result.get("next_action") or row.get("content"), 300),
                                          "action_type": str(result.get("next_action_type", "")), "tool": str(result.get("next_tool", "")),
                                          "status": str(result.get("status", "planned"))})
        if surface in {"observation_generated", "general_observation_generated"}:
            agent["observations"].append({**common, "text": _short(row.get("content"), 600), "component": identity["component"],
                                          "kind": (("base_role_observer" if base_no_lora else "trained_observer")
                                                   if surface == "observation_generated" else "base_vlm")})
        if surface == "memory_shared":
            agent["findings"].append({**common, "kind": "finding_report", "text": _short(row.get("content"), 600),
                                      "evidence_ids": list(row.get("evidence_ids") or []), "target": (target or {}).get("logical_agent_id", ""),
                                      "memory_entry_id": str(row.get("memory_entry_id", "")), "confidence": result.get("confidence"),
                                      "limitations": []})
            state["finding_status"] = f"Finding shared with {labels.get((target or {}).get('logical_agent_id', ''), 'recorded recipient')}"
        if surface == "hypothesis_updated" and result.get("claim_id"):
            claim = claims.get(str(result["claim_id"]), {})
            agent["findings"].append({**common, "kind": "evidence_claim", "text": _short(row.get("content"), 600),
                                      "evidence_ids": list(result.get("supporting_evidence_ids") or []),
                                      "target": "evidence_store", "claim_id": str(result["claim_id"]),
                                      "provenance_valid": result.get("provenance_valid"), "confidence": claim.get("confidence"),
                                      "limitations": [str(item) for item in claim.get("limitations") or []]})
            if state["finding_status"] == "No finding recorded":
                state["finding_status"] = "Evidence claim registered"
        if surface == "audio_scene_analyzed":
            agent["scene"].append({**common, "text": _short(row.get("content") or result.get("summary"), 600)})
        if surface in {"audio_finding_published", "audio_verdict_generated"}:
            agent["verdicts" if surface == "audio_verdict_generated" else "findings"].append({
                **common, "kind": "audio_finding" if surface == "audio_finding_published" else "tooldf_verdict",
                "text": _short(row.get("content"), 600), "evidence_ids": list(row.get("evidence_ids") or []),
                "tooldf_original_prediction": result.get("tooldf_original_prediction"),
                "audio_investigation_assessment": result.get("audio_investigation_assessment"),
                "target": "", "limitations": [], "confidence": None,
            })
            state["finding_status"] = ("ToolDF verdict recorded" if surface == "audio_verdict_generated" else "Audio finding published")
        if surface in {"judge_completed", "augmented_verdict_created", "audiovisual_case_review", "observation_generated"} and agent_id == JUDGE_AGENT_ID:
            kind = {"judge_completed": "original_trained_visual_judge", "augmented_verdict_created": "experimental_augmented_judge",
                    "audiovisual_case_review": "rule_based_case_review", "observation_generated": "trained_observer_input"}[surface]
            agent["model_evaluations"].append({
                **common, "kind": kind, "component": identity["component"], "answer": result.get("answer"),
                "adapter": result.get("adapter", ""), "explanation": _short(row.get("content") or result.get("explanation"), 900),
                "adapter_mode": provenance["mode"],
                "case_assessment": result.get("case_assessment"), "visual_prediction": result.get("visual_prediction"),
                "audio_prediction": result.get("audio_prediction"), "fusion_method": result.get("fusion_method"),
            })
            state["finding_status"] = {
                "original_trained_visual_judge": ("Base-model visual judge result recorded" if base_no_lora else "Trained visual judge result recorded"),
                "experimental_augmented_judge": "Experimental augmented result recorded",
                "rule_based_case_review": "Case assessment published",
                "trained_observer_input": state["finding_status"],
            }[kind]
        if surface == "reinspection_requested":
            agent["reinspections"].append({**common, "request_id": str(result.get("request_id") or row.get("reinspection_request_id") or ""),
                                           "target": (target or {}).get("logical_agent_id", ""), "native_target": str(row.get("target_role", "")),
                                           "tool_name": tool, "frame_indices": list(result.get("frame_indices") or []),
                                           "reason": _short(row.get("content"), 500), "completed_sequence": None,
                                           "returned_evidence_ids": []})
            if target and target.get("logical_agent_id") in runtime:
                target_state = runtime[target["logical_agent_id"]]
                target_state["finding_status"] = "Reinspection requested by Judge Agent 6"
                target_state["reopen_requests"].add(agent["reinspections"][-1]["request_id"])
        snapshot(agent_id, row, _action(row_with_target, identity, labels))

        if surface == "reinspection_completed":
            request_id = str(result.get("request_id") or row.get("reinspection_request_id") or "")
            judge_state = runtime[JUDGE_AGENT_ID]
            judge_state["awaiting_requests"].discard(request_id)
            for request in agents[JUDGE_AGENT_ID]["reinspections"]:
                if request["request_id"] == request_id:
                    request.update(completed_sequence=sequence, returned_evidence_ids=list(result.get("evidence_ids") or []))
            state["finding_status"] = "Reinspection evidence returned"
            agent["snapshots"][-1]["finding_status"] = state["finding_status"]
            if request_id in state["reopen_requests"]:
                state["reopen_requests"].discard(request_id)
                if agent["completion_recorded"] and not state["pending_calls"]:
                    state["state"] = "completed"
                    agent["snapshots"][-1]["state"] = "completed"
            if judge_state["state"] == "waiting_for_peer" and not judge_state["awaiting_requests"] and not judge_state["blockers"]:
                # The return is the recorded event that ends the judge's wait.
                judge_state["state"] = "active"
                snapshot(JUDGE_AGENT_ID, row, f"Received reinspection return {request_id}")

    for communication in communications:
        if communication["target"] in agents and not communication.get("internal"):
            agents[communication["target"]]["received"].append(communication)

    dashboard_mode = str(context.get("dashboard_mode") or "")
    investigator_mode = str(context.get("investigator_mode") or "")
    visual_branch = dashboard_mode in {"combined", "visual"} or (not dashboard_mode and investigator_mode not in {"direct_demo"} and not (context.get("audio_enabled") and not context.get("video_available") and not any(a["executed"] for a in (agents[v] for v in VISUAL_AGENT_IDS))))
    if investigator_mode in {"generic", "specialized"} and visual_branch:
        for agent_id in VISUAL_AGENT_IDS:
            if not agents[agent_id]["configured"]:
                agents[agent_id]["configured"] = True
                agents[agent_id]["configured_basis"] = f"{investigator_mode}_investigator_mode"
    if context.get("audio_enabled") and not agents[AUDIO_AGENT_ID]["configured"]:
        agents[AUDIO_AGENT_ID]["configured"] = True
        agents[AUDIO_AGENT_ID]["configured_basis"] = "audio_branch_present"
    for agent in agents.values():
        if agent["executed"] and not agent["configured"]:
            agent["configured"] = True
            agent["configured_basis"] = "observed_in_trace"
        agent["runtime_identities"] = list(agent["runtime_identities"].values())
        agent["final_state"] = agent["snapshots"][-1]["state"] if agent["snapshots"] else "not_invoked"
        agent_runs = {run_id for identity in agent["runtime_identities"] for run_id in identity["run_ids"]}
        agent["unresolved_at_run_end"] = bool(
            agent["executed"] and not agent["completion_recorded"] and agent_runs and agent_runs <= ended_runs
        )

    harnesses = sorted(item for item in infrastructure["harnesses"] if item)
    return {
        "agents": [agents[agent_id] for agent_id in LOGICAL_AGENT_IDS],
        "role_map": list(role_map.values()),
        "communications": communications,
        "annotations": annotations,
        "model_provenance": provenance,
        "execution_topology": execution_topology(events, context, infrastructure["clawteam_tasks"]),
        "infrastructure": {
            "clawteam_tasks": infrastructure["clawteam_tasks"], "mcp_calls": infrastructure["mcp_calls"],
            "runtime_failures": infrastructure["runtime_failures"], "harnesses": harnesses,
        },
        "unmapped_roles": sorted({item["agent_role"] for item in role_map.values() if item["mapping_basis"] == "unmapped"}),
        "states": list(AGENT_STATES),
    }


def execution_topology(rows: list[dict[str, Any]], context: dict[str, Any], clawteam_tasks: int) -> dict[str, Any]:
    """Describe how the recorded run actually executed, without inferring more."""
    harnesses = {str(row.get("harness", "")).lower() for row in rows}
    roles = {str(row.get("agent_role", "")) for row in rows}
    if context.get("simulation_fixture") or harnesses & {"fixture", "simulation", "simulated_fixture"}:
        return {"kind": "simulated_fixture", "label": "Simulated fixture — deterministic test data, not model or ClawTeam execution", "multi_agent_runtime": False}
    if "direct_demo" in roles:
        return {"kind": "direct_demo", "label": "Direct scripted tool demo — not multi-agent execution", "multi_agent_runtime": False}
    if clawteam_tasks or "audio_case_coordinator" in roles:
        runtime = ", ".join(sorted(harnesses & {"codex", "claude", "openclaw"})) or "native harness"
        return {"kind": "clawteam", "label": f"ClawTeam multi-agent execution ({runtime})", "multi_agent_runtime": True}
    if "local_qwen" in harnesses:
        return {"kind": "local_harness", "label": "Local enhanced harness — in-process base-Qwen planner, four investigator contexts (no external CLI)", "multi_agent_runtime": True}
    if harnesses & {"codex", "claude", "openclaw"}:
        return {"kind": "clawteam_partial", "label": "Native harness run without recorded ClawTeam task assignment", "multi_agent_runtime": False}
    if "none" in harnesses:
        return {"kind": "original_framework", "label": "Original ARGUS framework — in-process, sequential agent roles (no ClawTeam)", "multi_agent_runtime": False}
    if "direct" in harnesses:
        return {"kind": "direct", "label": "Direct execution (no ClawTeam coordination)", "multi_agent_runtime": False}
    return {"kind": "unknown", "label": "Execution topology not recorded", "multi_agent_runtime": False}


def annotate_moments(moments: list[dict[str, Any]], agent_model: dict[str, Any]) -> list[dict[str, Any]]:
    """Attach logical identities and recorded edges to story moments in place."""
    annotations = agent_model.get("annotations", {})
    for moment in moments:
        raw = moment.get("raw_event") if isinstance(moment.get("raw_event"), dict) else moment
        key = global_event_id(raw)
        moment["global_event_id"] = key
        moment.update({name: value for name, value in (annotations.get(key) or {}).items()})
        moment.setdefault("logical_agent_id", "")
        moment.setdefault("edge", None)
    return moments
