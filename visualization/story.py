"""Deterministic, evidence-grounded assembly of readable investigation moments."""

from __future__ import annotations

import re
from typing import Any, Iterable

from ..forensic_tools import CONTEXT_TOOL_NAMES, LOW_LEVEL_TOOL_NAMES
from ..forensic_tools.registry import ForensicToolRegistry
from ..forensic_tools.video import TEMPORAL_TOOL_NAMES
from ..visual_capabilities import VISUAL_CAPABILITY_TOOL_NAMES


SUBSTANTIVE_TOOLS = frozenset((
    "extract_aligned_av_window", "locate_visible_speakers", "estimate_lip_speech_synchrony",
    "inspect_targeted_audio", "inspect_cross_modal_edit_boundary", "associate_speaker_with_face_track", "compare_audio_visual_events",
    *LOW_LEVEL_TOOL_NAMES,
    *TEMPORAL_TOOL_NAMES,
    *CONTEXT_TOOL_NAMES,
    *VISUAL_CAPABILITY_TOOL_NAMES,
    "consult_trained_argus_observer",
    "source_separator",
    "speech_deepfake_detector",
    "singing_deepfake_detector",
    "music_deepfake_detector",
    "sound_deepfake_detector",
    "run_tooldf_investigation",
    "detect_speech_activity", "analyze_prosody", "compare_speaker_identity",
    "compare_speaking_style", "detect_audio_edit_boundaries",
    "inspect_breathing_patterns", "compare_audio_fingerprints", "compare_transcripts",
    "diarize_audio_speakers", "transcribe_audio", "test_audio_processing_alternative",
))

AUDIO_SURFACES = frozenset({
    "audio_received", "audio_prepared", "audio_track_extracted",
    "audio_hypothesis_created", "audio_inference_started",
    "audio_scene_analyzed", "audio_tool_planned", "audio_evidence_created",
    "audio_evidence_interpreted", "audio_hypothesis_updated",
    "audio_finding_published", "audio_verdict_generated",
    "audio_analysis_failed",
    "audio_verification_planned", "audio_tool_called", "audio_tool_result",
    "audio_investigation_stopped",
    "audio_peer_review_requested", "audio_peer_review_completed",
})
AUDIO_TOOLS = frozenset({
    "source_separator", "speech_deepfake_detector",
    "singing_deepfake_detector", "music_deepfake_detector",
    "sound_deepfake_detector", "run_tooldf_investigation",
    "detect_speech_activity", "analyze_prosody", "compare_speaker_identity",
    "compare_speaking_style", "detect_audio_edit_boundaries",
    "inspect_breathing_patterns", "compare_audio_fingerprints", "compare_transcripts",
    "diarize_audio_speakers", "transcribe_audio", "test_audio_processing_alternative",
})


def event_modality(event: dict[str, Any]) -> str:
    """Return a stable modality without requiring legacy visual traces to change."""
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    explicit = str(metadata.get("modality") or event.get("modality") or "").lower()
    if explicit in {"image", "video", "audio", "audiovisual"}:
        return explicit
    surface = str(event.get("surface", ""))
    if surface in AUDIO_SURFACES or str(event.get("tool_name", "")) in AUDIO_TOOLS:
        return "audio"
    if surface == "audiovisual_case_review":
        return "audiovisual"
    return "video"


def event_sequence(event: dict[str, Any]) -> int:
    """Use a case-level replay sequence while preserving branch sequence numbers."""
    return int(event.get("dashboard_sequence_num", event.get("sequence_num", 0)) or 0)


_AUDIO_INTERVAL = re.compile(
    r"\[?\s*(\d+(?:\.\d+)?)\s*\(?s\)?\s*[-–]\s*(\d+(?:\.\d+)?)\s*\(?s\)?\s*\]?",
    re.IGNORECASE,
)


def audio_plan_details(text: str) -> dict[str, Any]:
    """Extract display facts from ToolDF's recorded plan without adding reasoning."""
    normalized = " ".join(str(text or "").split())
    lower = normalized.lower()
    interval = _AUDIO_INTERVAL.search(normalized)
    selected_tool = next((name for name in (
        "speech_deepfake_detector", "singing_deepfake_detector",
        "music_deepfake_detector", "sound_deepfake_detector",
        "source_separator", "run_tooldf_investigation",
    ) if name in lower and f"skip {name}" not in lower), "")
    component = next(
        (name for name in ("speech", "singing", "music", "sound") if name in lower),
        "",
    )
    separation = "unavailable"
    if "skip source_separator" in lower or "skip source separator" in lower:
        separation = "skipped"
    elif "source_separator" in lower or "source separator" in lower or "demucs" in lower:
        separation = "selected"
    return {
        "original_plan": normalized,
        "component": component,
        "selected_tool": selected_tool,
        "source_separation": separation,
        "source_separation_reason": (
            "The recorded plan states that no background component required separation."
            if separation == "skipped" and "no background" in lower else ""
        ),
        "start_time": float(interval.group(1)) if interval else None,
        "end_time": float(interval.group(2)) if interval else None,
    }


def _short(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _pretty(value: Any) -> str:
    return str(value or "").replace("_", " ").title()


def tool_catalog() -> dict[str, dict[str, Any]]:
    catalog = {item["name"]: item for item in ForensicToolRegistry().describe()}
    purposes = {
        "rank_suspicious_frames": "Rank sampled frames by one diagnostic measurement.",
        "track_video_roi": "Track a selected region across sampled frames.",
        "temporal_residual_consistency": "Compare aligned residual evidence across time.",
        "optical_flow_consistency": "Measure dense motion magnitude and temporal variation.",
    }
    for name in TEMPORAL_TOOL_NAMES:
        catalog[name] = {
            "name": name,
            "category": "video_temporal",
            "purpose": purposes[name],
            "limitations": [
                "The measurement is not a calibrated authenticity probability."
            ],
        }
    context_purposes = {
        "search_reference_sources": "Query an authorized source provider using selected keyframes.",
        "find_matching_reference_frames": "Search authorized local reference media for similar frames.",
        "align_reference_videos": "Estimate suspect/reference frame correspondences.",
        "compare_aligned_video_regions": "Compare a selected suspect/reference region.",
        "detect_scene_objects": "Ground requested object concepts or propose unlabeled regions.",
        "compare_scene_objects": "Measure selected object geometry across frames.",
        "compare_background_and_gestures": "Compare scene layout or gesture regions with a reference.",
        "detect_temporal_text_inconsistency": "Track visible-text structure and optional OCR.",
        "inspect_visual_overlay": "Measure visible logo, caption, or overlay changes.",
        "controlled_processing_test": "Test benign compression, blur, and resize alternatives.",
    }
    for name in CONTEXT_TOOL_NAMES:
        catalog[name] = {
            "name": name,
            "category": "context_reference",
            "purpose": context_purposes[name],
            "limitations": ["Descriptive evidence is not proof of manipulation."],
        }
    visual_purposes = {
        "visual_grounding": "Ground a named object and retain aligned masks, boxes, scores, and overlay artifacts.",
        "recognize_scene_text": "Transcribe visible text from an authorized image or crop.",
        "reverse_search_frame": "Find candidate source pages for an explicitly authorized evidence image.",
        "search_source_evidence": "Search provider-originated source evidence by text.",
        "inspect_source_webpage": "Retrieve untrusted source-page evidence for a stated goal.",
    }
    for name in VISUAL_CAPABILITY_TOOL_NAMES:
        catalog[name] = {
            "name": name,
            "category": "openvlharness_visual",
            "purpose": visual_purposes[name],
            "limitations": ["Capability output requires forensic interpretation and is not proof of manipulation."],
        }
    catalog["consult_trained_argus_observer"] = {
        "name": "consult_trained_argus_observer",
        "category": "trained_expert",
        "purpose": "Consult one original trained ARGUS specialist without replacing the generic investigator.",
        "limitations": ["The consultation is model output, not a signal-processing measurement."],
    }
    for name, category, purpose in (
        ("source_separator", "audio_separation", "Conditionally separate vocals and background using htdemucs."),
        ("speech_deepfake_detector", "audio_detector", "Evaluate a speech interval with its routed XLSR-AASIST checkpoint."),
        ("singing_deepfake_detector", "audio_detector", "Evaluate a singing interval with its routed XLSR-AASIST checkpoint."),
        ("music_deepfake_detector", "audio_detector", "Evaluate a music interval with its routed XLSR-AASIST checkpoint."),
        ("sound_deepfake_detector", "audio_detector", "Evaluate an environmental-sound interval with its routed XLSR-AASIST checkpoint."),
        ("run_tooldf_investigation", "audio_planner", "Run the released ToolDF adaptive audio investigation loop."),
    ):
        catalog[name] = {
            "name": name,
            "category": category,
            "purpose": purpose,
            "limitations": ["Audio model evidence is not proof of synthesis."],
        }
    verification_purposes = {
        "detect_speech_activity": "Localize speech and non-speech intervals before targeted analysis.",
        "analyze_prosody": "Measure pitch, energy, voiced activity, and pauses with physical units.",
        "compare_speaker_identity": "Compare pretrained speaker embeddings without converting similarity to identity probability.",
        "compare_speaking_style": "Compare descriptive delivery measurements against authorized references.",
        "detect_audio_edit_boundaries": "Localize candidate spectral or energy discontinuities.",
        "inspect_breathing_patterns": "Locate cautious breath-like acoustic candidates.",
        "compare_audio_fingerprints": "Check for near-identical aligned audio reuse.",
        "compare_transcripts": "Compare supplied or timestamped transcript content.",
        "diarize_audio_speakers": "Separate anonymous speaker turns without identifying a real person.",
        "transcribe_audio": "Create ASR segments and word timing when alignment is supported.",
        "test_audio_processing_alternative": "Test whether benign processing can reproduce a suspicious measurement.",
    }
    for name, purpose in verification_purposes.items():
        catalog[name] = {
            "name": name, "category": "audio_verification", "purpose": purpose,
            "limitations": ["Supplementary measurements address one forensic question and do not independently prove synthesis."],
        }
    return catalog


def evidence_summary(record: dict[str, Any] | None) -> str:
    if not record:
        return "The complete evidence record is unavailable."
    stats = record.get("summary_statistics") or {}
    tool = _pretty(record.get("tool_name"))
    if str(record.get("evidence_id", "")).startswith("audio_ev_"):
        if record.get("component_type") == "verification":
            response = record.get("actual_tool_response") or record.get("raw_measurements") or {}
            if response.get("execution_status") in {"error", "unavailable"}:
                return f"{tool} was {response.get('execution_status')}; no substitute measurement was generated."
            return _short(
                f"{tool} returned recorded supplementary measurements: {response}", 300
            )
        if record.get("tool_name") == "source_separator":
            return (
                f"{tool} {record.get('status', 'recorded')} for "
                f"{record.get('start_time', 0)}–{record.get('end_time', 0)}s. "
                "Separated stems are processing artifacts, not authenticity evidence."
            )
        score = record.get("raw_score")
        threshold = record.get("threshold")
        score_text = (
            f"P(real)={score} against threshold {threshold}"
            if score is not None and threshold is not None else "score unavailable"
        )
        return (
            f"{tool} analyzed {record.get('component_type', 'audio')} from "
            f"{record.get('start_time', 0)}–{record.get('end_time', 0)}s using the "
            f"{_pretty(record.get('detector_variant'))} checkpoint and returned "
            f"{str(record.get('prediction', 'unknown')).upper()} ({score_text})."
        )
    if isinstance(stats.get("ranked_frames"), list):
        ranked = "; ".join(
            f"sample f{item.get('frame_index')} at {item.get('timestamp')}s = {item.get('measurement')}"
            for item in stats["ranked_frames"][:4]
        )
        return f"{tool} ranked the selected sampled frames. Highest recorded measurements: {ranked}."
    if stats.get("mean_flow_magnitude") is not None:
        return (
            f"{tool} measured mean flow magnitude {stats.get('mean_flow_magnitude')} "
            f"and temporal variation {stats.get('flow_variation')} across samples "
            f"{record.get('frame_indices', [])}."
        )
    if stats.get("grounding_backend") is not None:
        return (
            f"{tool} used {str(stats.get('grounding_backend')).replace('_', ' ')} and returned "
            f"{stats.get('detection_count', 0)} bounded region proposal(s)."
        )
    if record.get("tool_name") == "search_reference_sources":
        return (
            f"{tool} returned {stats.get('candidate_count', 0)} authorized local candidate(s); "
            "candidates still require visual alignment and comparison."
        )
    if record.get("tool_name") == "visual_grounding":
        return (
            f"{tool} {stats.get('status', 'completed')} for {stats.get('query', 'the query')} "
            f"with {len(stats.get('boxes_original_pixels') or [])} aligned region(s), "
            f"{len(stats.get('mask_artifact_ids') or [])} reusable mask(s), and model "
            f"{stats.get('model_id', 'unrecorded')}. A miss does not prove absence."
        )
    if record.get("tool_name") == "recognize_scene_text":
        transcription = " ".join(str(stats.get("recognized_text") or "[no readable text]").split())
        return (
            f"{tool} returned transcription {_short(transcription, 240)!r} "
            f"using {stats.get('model_id', 'an unrecorded model')}; no token boxes were claimed."
        )
    if record.get("tool_name") in {"reverse_search_frame", "search_source_evidence"}:
        return (
            f"{tool} retained {stats.get('candidate_count', 0)} candidate source reference(s). "
            "Candidates are not verified originals."
        )
    if record.get("tool_name") == "inspect_source_webpage":
        return (
            f"{tool} retained {len(stats.get('pages') or [])} untrusted page result(s); "
            "retrieved content remains evidence, never operational instruction."
        )
    if stats.get("mean_aligned_residual_change") is not None:
        return (
            f"{tool} measured mean aligned residual change "
            f"{stats.get('mean_aligned_residual_change')} across samples "
            f"{record.get('frame_indices', [])}."
        )
    if isinstance(stats.get("tracked_boxes"), list):
        boxes = stats["tracked_boxes"]
        return (
            f"{tool} tracked the ROI through {len(boxes)} sampled frames, from "
            f"{boxes[0] if boxes else record.get('roi')} to {boxes[-1] if boxes else record.get('roi')}; "
            f"completed={bool(stats.get('completed'))}."
        )
    if isinstance(stats.get("best_match"), dict):
        match = stats["best_match"]
        return (
            f"{tool} matched suspect sample f{match.get('suspect_frame_index')} to "
            f"reference sample {match.get('reference_frame_index')} with recorded similarity "
            f"{match.get('score')}; this is retrieval evidence, not manipulation proof."
        )
    if stats.get("mean_absolute_difference") is not None:
        return (
            f"{tool} recorded similarity {stats.get('similarity')} and mean absolute "
            f"difference {stats.get('mean_absolute_difference')} for the selected pair."
        )
    if isinstance(stats.get("per_frame_geometry"), list):
        return (
            f"{tool} measured object-region geometry in {len(stats['per_frame_geometry'])} "
            f"frames; edge-fraction range {stats.get('edge_fraction_range')}."
        )
    if isinstance(stats.get("pair_changes"), list):
        return f"{tool} measured pairwise region changes {stats.get('pair_changes')}."
    measurements = [
        f"{_pretty(key)} {value}"
        for key, value in stats.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ][:6]
    suffix = "; ".join(measurements) or "No compact numeric summary was recorded."
    return f"{tool} returned evidence {record.get('evidence_id', '')}. {suffix}"


def _agent_name(role: str) -> str:
    """Display name on the six-agent console; native roles stay in the raw audit."""
    return {
        "texture_agent": "Trained texture observer",
        "lighting_agent": "Trained lighting observer",
        "motion_agent": "Trained motion observer",
        "physics_agent": "Trained physics observer",
        "judge_coordinator": "Judge Agent 6",
        "system": "ARGUS runtime",
        "investigator_1": "Visual Agent 1",
        "investigator_2": "Visual Agent 2",
        "investigator_3": "Visual Agent 3",
        "investigator_4": "Visual Agent 4",
        "audio_investigator": "Audio Agent 5",
        "tooldf_planner": "Audio Agent 5 (ToolDF planner)",
        "independent_audio_reviewer": "Audio Agent 5 (independent-corroboration check)",
        "audiovisual_reviewer": "Judge Agent 6 (rule-based case review)",
        "audio_case_coordinator": "Judge Agent 6 (ClawTeam audio case coordinator)",
        "clawteam_coordinator": "ClawTeam coordination",
        "direct_demo": "Scripted tool demo",
    }.get(role, _pretty(role))


def assemble_tool_observability(
    rows: Iterable[dict[str, Any]], context: dict[str, Any]
) -> list[dict[str, Any]]:
    """Group trusted lifecycle events without revealing information before its sequence."""
    events = sorted(rows, key=event_sequence)
    evidence = {
        str(item.get("evidence_id")): item
        for item in context.get("evidence", [])
        if isinstance(item, dict) and item.get("evidence_id")
    }
    catalog = tool_catalog()
    operations: list[dict[str, Any]] = []
    by_decision: dict[str, dict[str, Any]] = {}
    by_call: dict[str, dict[str, Any]] = {}
    by_next_action: dict[str, dict[str, Any]] = {}

    def create(event: dict[str, Any], *, legacy: bool = False) -> dict[str, Any]:
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        decision_id = str(event.get("decision_id") or result.get("decision_id") or "")
        operation = {
            "operation_id": decision_id or str(event.get("tool_call_id")) or f"legacy_{len(operations) + 1}",
            "step": len(operations) + 1,
            "timestamp": str(event.get("timestamp", "")),
            "agent_role": str(event.get("agent_role", "unknown")),
            "agent_name": _agent_name(str(event.get("agent_role", "unknown"))),
            "modality": event_modality(event),
            "tool_name": str(result.get("next_tool") or event.get("tool_name") or ""),
            "tool_family": "",
            "decision_id": decision_id,
            "tool_call_id": str(event.get("tool_call_id", "")),
            "hypothesis_id": str(event.get("hypothesis_id") or result.get("hypothesis_id") or ""),
            "observation": str(result.get("current_observation", "")),
            "hypothesis": str(result.get("suspicion", "")),
            "investigative_question": str(result.get("question", "")),
            "reason_for_tool_choice": str(result.get("reason_for_action", "")),
            "expected_information": str(result.get("expected_information", "")),
            "selected_frames": list(result.get("selected_frames") or []),
            "selected_roi": result.get("selected_roi"),
            "tool_input": {},
            "execution_state": "planned" if not legacy else "running",
            "tool_output_original": None,
            "tool_output_summary": "",
            "evidence_ids": [],
            "evidence": None,
            "interpretation_id": "",
            "agent_interpretation": "",
            "assessment": "",
            "interpretation_limitations": [],
            "next_action_id": "",
            "next_planned_action": "",
            "next_action_type": "",
            "next_tool": "",
            "reason_for_next_action": "",
            "next_action_status": "not_recorded",
            "next_actual_action": None,
            "hypothesis_update": None,
            "memory_updates": [],
            "legacy_missing_rationale": legacy or not decision_id,
            "causal_link_basis": "recorded" if event.get("tool_call_id") else "unavailable",
            "stage_sequences": {},
            "event_ids": {},
        }
        tool = catalog.get(operation["tool_name"], {})
        operation["tool_family"] = str(tool.get("category", "other"))
        operations.append(operation)
        if decision_id:
            by_decision[decision_id] = operation
        return operation

    for event in events:
        surface = str(event.get("surface", ""))
        sequence = event_sequence(event)
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        decision_id = str(event.get("decision_id") or result.get("decision_id") or "")
        call_id = str(event.get("tool_call_id") or result.get("tool_call_id") or "")
        operation = by_call.get(call_id) or by_decision.get(decision_id)

        if surface == "investigation_decision":
            operation = operation or create(event)
            operation.update(
                tool_name=str(result.get("next_tool") or event.get("tool_name") or ""),
                hypothesis_id=str(event.get("hypothesis_id") or result.get("hypothesis_id") or ""),
                observation=str(result.get("current_observation", "")),
                hypothesis=str(result.get("suspicion", "")),
                investigative_question=str(result.get("question", "")),
                reason_for_tool_choice=str(result.get("reason_for_action", "")),
                expected_information=str(result.get("expected_information", "")),
                selected_frames=list(result.get("selected_frames") or []),
                selected_roi=result.get("selected_roi"),
                execution_state="planned",
            )
            operation["tool_family"] = str(
                catalog.get(operation["tool_name"], {}).get("category", "other")
            )
            operation["stage_sequences"]["decision"] = sequence
            operation["event_ids"]["decision"] = str(event.get("event_id", ""))
        elif surface in {"tool_call", "audio_tool_called"} and event.get("tool_name") in SUBSTANTIVE_TOOLS:
            operation = operation or create(event, legacy=True)
            audio_call = str((event.get("metadata") or {}).get("modality", "")) == "audio"
            operation.update(
                tool_name=str(event.get("tool_name", "")),
                tool_call_id=call_id,
                tool_input=dict(event.get("tool_args") or {}),
                execution_state="running",
                investigative_question=(
                    f"What does {_pretty(event.get('tool_name'))} report for the selected audio interval?"
                    if audio_call else operation.get("investigative_question", "")
                ),
                reason_for_tool_choice=(
                    str(event.get("content", "")) if audio_call
                    else operation.get("reason_for_tool_choice", "")
                ),
                expected_information=(
                    "A real service response with component, interval, P(real), threshold, and prediction."
                    if audio_call and event.get("tool_name") != "source_separator"
                    else "Run-scoped separated stems and completion status."
                    if audio_call else operation.get("expected_information", "")
                ),
                legacy_missing_rationale=(not audio_call and operation.get("legacy_missing_rationale", True)),
            )
            operation["tool_family"] = str(
                catalog.get(operation["tool_name"], {}).get("category", "other")
            )
            operation["stage_sequences"]["call"] = sequence
            operation["event_ids"]["call"] = str(event.get("event_id", ""))
            if call_id:
                by_call[call_id] = operation
        elif surface in {"tool_result", "audio_tool_result"} and event.get("tool_name") in SUBSTANTIVE_TOOLS:
            operation = operation or create(event, legacy=True)
            ids = [str(item) for item in event.get("evidence_ids", []) if item]
            record = evidence.get(ids[0]) if ids else None
            operation.update(
                tool_name=str(event.get("tool_name", operation.get("tool_name", ""))),
                tool_call_id=call_id,
                execution_state="failed" if event.get("status") == "error" else "completed",
                tool_output_original=result,
                tool_output_summary=(
                    str(result.get("error", "Tool failed."))
                    if event.get("status") == "error"
                    else evidence_summary(record) if record else _short(result, 500)
                ),
                evidence_ids=ids,
                evidence=record,
            )
            operation["stage_sequences"]["result"] = sequence
            operation["event_ids"]["result"] = str(event.get("event_id", ""))
            if call_id:
                by_call[call_id] = operation
        elif surface == "audio_evidence_interpreted" and operation is None:
            # Legacy ToolDF traces omitted this ID. Associate only one unambiguous
            # completed audio call; otherwise leave the relationship unavailable.
            candidates = [
                item for item in operations
                if item.get("modality") == "audio"
                and item.get("execution_state") in {"completed", "failed"}
                and not item.get("agent_interpretation")
            ]
            if len(candidates) == 1:
                operation = candidates[0]
                operation["causal_link_basis"] = "deterministic_single_pending_audio_call"

        if surface in {"evidence_interpreted", "audio_evidence_interpreted"} and operation:
            operation.update(
                interpretation_id=str(event.get("interpretation_id") or result.get("interpretation_id") or ""),
                agent_interpretation=str(result.get("finding") or event.get("content") or ""),
                assessment=str(result.get("assessment") or ("inconclusive" if surface.startswith("audio_") else "")),
                interpretation_limitations=list(result.get("limitations") or []),
                next_action_id=str(event.get("next_action_id") or result.get("next_action_id") or ""),
                next_planned_action=str(result.get("next_action", "")),
                next_action_type=str(result.get("next_action_type", "")),
                next_tool=str(result.get("next_tool", "")),
                reason_for_next_action=str(result.get("reason_for_next_action", "")),
                next_action_status="planned" if result.get("next_action") else "not_recorded",
            )
            operation["stage_sequences"]["interpretation"] = sequence
            operation["event_ids"]["interpretation"] = str(event.get("event_id", ""))
            if operation["next_action_id"]:
                by_next_action[operation["next_action_id"]] = operation
        elif surface == "next_action_planned" and operation:
            operation.update(
                next_action_id=str(event.get("next_action_id") or result.get("next_action_id") or ""),
                next_planned_action=str(result.get("next_action") or event.get("content") or ""),
                next_action_type=str(result.get("next_action_type", "")),
                next_tool=str(result.get("next_tool", "")),
                reason_for_next_action=str(result.get("reason_for_next_action", "")),
                next_action_status=str(result.get("status", "planned")),
            )
            operation["stage_sequences"]["plan"] = sequence
            operation["event_ids"]["plan"] = str(event.get("event_id", ""))
            if operation["next_action_id"]:
                by_next_action[operation["next_action_id"]] = operation
            if (
                operation["next_action_type"] == "stop_investigation"
                and operation["next_action_status"] == "completed"
            ):
                operation["next_actual_action"] = {
                    "action": operation["next_planned_action"],
                    "action_type": "stop_investigation",
                    "matches_plan": True,
                    "status": "completed",
                    "sequence_num": sequence,
                    "event_id": event.get("event_id", ""),
                }
                operation["stage_sequences"]["next_actual"] = sequence
        elif surface == "next_action_started":
            plan_id = str(event.get("next_action_id") or result.get("next_action_id") or "")
            source_operation = by_next_action.get(plan_id)
            if source_operation:
                source_operation["next_actual_action"] = {
                    "action": result.get("planned_action", ""),
                    "action_type": "tool_call",
                    "tool_name": result.get("actual_tool") or event.get("tool_name"),
                    "decision_id": result.get("actual_decision_id") or decision_id,
                    "matches_plan": result.get("matches_plan"),
                    "status": result.get("status", "started"),
                    "sequence_num": sequence,
                    "event_id": event.get("event_id", ""),
                }
                source_operation["next_action_status"] = str(result.get("status", "started"))
                source_operation["stage_sequences"]["next_actual"] = sequence
        elif surface in {"hypothesis_updated", "audio_hypothesis_updated"}:
            ids = {str(item) for item in event.get("evidence_ids", []) if item}
            candidates = [
                item for item in operations
                if item["agent_role"] == event.get("agent_role")
                and ids.intersection(item.get("evidence_ids", []))
            ]
            if candidates:
                target = candidates[-1]
                target["hypothesis_update"] = result
                target["hypothesis_id"] = str(result.get("hypothesis_id") or target.get("hypothesis_id", ""))
                status = str(result.get("status", ""))
                target["assessment"] = {
                    "supported": "supports_suspicion",
                    "weakened": "contradicts_suspicion",
                    "rejected": "contradicts_suspicion",
                    "inconclusive": "inconclusive",
                }.get(status, target.get("assessment") or status)
                target["stage_sequences"]["hypothesis_update"] = sequence
        elif surface == "memory_written":
            ids = {str(item) for item in event.get("evidence_ids", []) if item}
            decision_ids = {str(item) for item in result.get("decision_ids", []) if item}
            candidates = [
                item for item in operations
                if item["decision_id"] in decision_ids
                or ids.intersection(item.get("evidence_ids", []))
            ]
            if candidates:
                target = candidates[-1]
                target["memory_updates"].append(result)
                target["stage_sequences"]["memory"] = sequence

    return operations


def assemble_story(
    rows: Iterable[dict[str, Any]], context: dict[str, Any]
) -> list[dict[str, Any]]:
    """Convert real ordered trace events into compact, non-invented moments."""
    events = list(rows)
    evidence = {
        str(item.get("evidence_id")): item
        for item in context.get("evidence", [])
        if isinstance(item, dict)
    }
    claims = {
        str(item.get("claim_id")): item
        for item in context.get("claims", [])
        if isinstance(item, dict)
    }
    catalog = tool_catalog()
    moments: list[dict[str, Any]] = []
    pending_audio_results: list[dict[str, Any]] = []
    pending_audio_received_id = ""

    def add(
        event: dict[str, Any], moment_type: str, summary: str, **detail: Any
    ) -> None:
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        evidence_ids = list(event.get("evidence_ids") or result.get("evidence_ids") or [])
        if result.get("evidence_id") and result["evidence_id"] not in evidence_ids:
            evidence_ids.append(result["evidence_id"])
        record = evidence.get(str(evidence_ids[0])) if evidence_ids else None
        modality = str(detail.pop("modality", "") or event_modality(event))
        sequence = event_sequence(event)
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        tool_args = event.get("tool_args") if isinstance(event.get("tool_args"), dict) else {}
        start_time = detail.pop("start_time", metadata.get("start_time", tool_args.get("start")))
        end_time = detail.pop("end_time", metadata.get("end_time", tool_args.get("end")))
        event_id = event.get("event_id") or f"legacy_seq_{event.get('sequence_num', 0)}"
        moments.append(
            {
                "moment_id": f"moment_{len(moments) + 1:04d}",
                "run_id": event.get("run_id", ""),
                "modality": modality,
                "event_ids": [event_id],
                "actor": event.get("agent_role", "system"),
                "moment_type": moment_type,
                "type": moment_type,
                "sequence_num": sequence,
                "source_sequence_num": event.get("sequence_num", 0),
                "event_id": event_id,
                "parent_event_id": event.get("parent_event_id", ""),
                "timestamp": event.get("timestamp", ""),
                "status": event.get("status", "success"),
                "agent_role": event.get("agent_role", "system"),
                "target_role": event.get("target_role", ""),
                "tool_name": event.get("tool_name", ""),
                "tool_call_id": event.get("tool_call_id", ""),
                "decision_id": event.get("decision_id", ""),
                "memory_entry_id": event.get("memory_entry_id", ""),
                "reinspection_request_id": event.get("reinspection_request_id", ""),
                "evidence_ids": evidence_ids,
                "summary": _short(summary, 180),
                "details": detail,
                "detail": detail,
                "start_time": start_time,
                "end_time": end_time,
                "evidence": record,
                "raw_event": event,
            }
        )

    for event in events:
        surface = str(event.get("surface", ""))
        role = str(event.get("agent_role", "system"))
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        content = str(event.get("content", ""))
        if surface.startswith(("crossmodal_", "av_")) or surface == "case_review_completed":
            interval = (event.get("metadata") or {}).get("source_interval") or {}
            add(event, "AV_" + surface.upper(), content or surface.replace("_", " "),
                request_id=(event.get("metadata") or {}).get("request_id", ""),
                source_interval=interval, recorded_result=result, modality="audiovisual",
                start_time=interval.get("start"), end_time=interval.get("end"))
        elif surface == "case_opened":
            add(event, "CASE_OPENED", content or "A new forensic case was opened.", source=result)
        elif surface == "video_sampled":
            sampling = result.get("sampling") or {}
            add(
                event,
                "VIDEO_SAMPLED",
                f"Source evidence was sampled into {sampling.get('effective_frames', 'recorded')} investigation frames.",
                sampling=sampling,
            )
        elif surface in {"observation_generated", "general_observation_generated"}:
            observation = content or context.get("observations", {}).get(role.removesuffix("_agent"), "")
            add(
                event,
                "INITIAL_OBSERVATION",
                f"{_agent_name(role)} recorded its {'generic' if surface.startswith('general') else 'trained'} visual observation.",
                observation=observation,
                recorded_text_available=bool(observation),
                generic=surface.startswith("general"),
            )
        elif surface == "expert_consultation_completed":
            add(event, "EXPERT_CONSULTATION",
                f"{_agent_name(role)} consulted the preserved {_pretty(result.get('specialty'))} LoRA.",
                observation=content, model=result, direction="agent_to_agent")
        elif surface == "hypothesis_created":
            add(event, "HYPOTHESIS_CREATED",
                f"{_agent_name(role)} registered {result.get('hypothesis_id')}: {_short(content, 105)}",
                hypothesis=result, alternatives=result.get("alternative_explanations", []))
        elif surface == "investigation_question_opened":
            add(event, "QUESTION_OPENED",
                f"{_agent_name(role)} opened a case question: {_short(content, 110)}",
                question=result, direction="agent_to_memory")
        elif surface == "investigation_question_claimed":
            add(event, "QUESTION_CLAIMED",
                f"{_agent_name(role)} claimed {result.get('question_id')} to prevent duplicate work.",
                question=result, direction="memory_to_agent")
        elif surface == "investigation_question_resolved":
            add(event, "QUESTION_RESOLVED",
                f"{_agent_name(role)} resolved {result.get('question_id')}: {_short(content, 105)}",
                question=result, direction="agent_to_memory")
        elif surface == "peer_review_requested":
            add(event, "PEER_REVIEW_REQUESTED",
                f"{_agent_name(role)} asked {_agent_name(str(event.get('target_role')))} to challenge {result.get('hypothesis_id')}.",
                review=result, direction="agent_to_agent")
        elif surface == "peer_review_completed":
            add(event, "PEER_REVIEW_COMPLETED",
                f"{_agent_name(role)} returned an evidence-linked review of {result.get('hypothesis_id')}: {_pretty(result.get('assessment'))}.",
                review=result, evidence_ids=result.get("evidence_ids", []),
                observation=content, direction="agent_to_agent")
        elif surface == "investigation_decision":
            add(
                event,
                "TOOL_DECISION",
                f"{_agent_name(role)} selected {_pretty(result.get('next_tool') or event.get('tool_name'))} to test: {_short(result.get('suspicion'), 95)}",
                observation=result.get("current_observation", ""),
                suspicion=result.get("suspicion", ""),
                why=result.get("reason_for_action", ""),
                expected_information=result.get("expected_information", ""),
                evidence_basis=result.get("evidence_basis", []),
                selected_frames=result.get("selected_frames", []),
                selected_roi=result.get("selected_roi"),
                question=result.get("question", ""),
                hypothesis_id=result.get("hypothesis_id", ""),
                alternative_explanation=result.get("alternative_explanation", ""),
                rationale_available=True,
            )
        elif surface in {"tool_call", "audio_tool_called"} and event.get("tool_name") in SUBSTANTIVE_TOOLS:
            decision_id = str(event.get("decision_id", ""))
            add(
                event,
                "TOOL_EXECUTION",
                f"{_agent_name(role)} submitted an actual request to {_pretty(event.get('tool_name'))}.",
                input=event.get("tool_args", {}),
                rationale_available=bool(decision_id),
                missing_rationale=(
                    "Tool invoked; pre-call decision rationale unavailable."
                    if not decision_id else ""
                ),
                tool=catalog.get(str(event.get("tool_name")), {}),
                direction="agent_to_tool",
            )
        elif surface in {"tool_result", "audio_tool_result"} and event.get("tool_name") in SUBSTANTIVE_TOOLS:
            ids = list(event.get("evidence_ids") or [])
            record = evidence.get(str(ids[0])) if ids else None
            add(
                event,
                "TOOL_FAILURE" if event.get("status") == "error" else "EVIDENCE_RETURNED",
                (
                    f"{_pretty(event.get('tool_name'))} failed: {_short(result.get('error'), 100)}"
                    if event.get("status") == "error"
                    else f"{_pretty(event.get('tool_name'))} returned measured evidence to {_agent_name(role)}."
                ),
                output=evidence_summary(record) if record else result,
                limitations=(record or {}).get("limitations", []),
                tool=catalog.get(str(event.get("tool_name")), {}),
                direction="tool_to_agent",
            )
            if event_modality(event) == "audio":
                pending_audio_results.append(event)
        elif surface == "forensic_tool_completed" and not event.get("tool_call_id"):
            evidence_id = str(result.get("evidence_id", ""))
            add(
                event,
                "EVIDENCE_RETURNED",
                f"{_pretty(event.get('tool_name'))} returned evidence; its older trace has no stable call link.",
                output=evidence_summary(evidence.get(evidence_id)),
                rationale_available=False,
                missing_rationale="Tool invoked; pre-call decision rationale unavailable.",
                direction="tool_to_agent",
            )
        elif surface == "evidence_interpreted":
            assessment = str(result.get("assessment", event.get("metadata", {}).get("assessment", "")))
            add(
                event,
                "HYPOTHESIS_REJECTED" if assessment == "contradicts_suspicion" else "EVIDENCE_INTERPRETED",
                f"{_agent_name(role)} assessed the result as {_pretty(assessment)}: {_short(result.get('finding') or content, 105)}",
                interpretation=result.get("finding") or content,
                assessment=assessment,
                limitations=result.get("limitations", []),
                next_action=result.get("next_action", ""),
                reason_for_next_action=result.get("reason_for_next_action", ""),
            )
        elif surface == "next_action_planned":
            add(
                event,
                "NEXT_ACTION_PLANNED",
                f"{_agent_name(role)} planned: {_short(result.get('next_action') or content, 120)}",
                next_action=result.get("next_action") or content,
                next_action_type=result.get("next_action_type", "unrecorded"),
                next_tool=result.get("next_tool", ""),
                reason_for_next_action=result.get("reason_for_next_action", ""),
                next_action_status=result.get("status", "planned"),
            )
        elif surface == "next_action_started":
            add(
                event,
                "NEXT_ACTION_EXECUTED",
                f"{_agent_name(role)} actually started {_pretty(result.get('actual_tool') or event.get('tool_name'))}.",
                planned_action=result.get("planned_action", ""),
                planned_tool=result.get("planned_tool", ""),
                actual_tool=result.get("actual_tool") or event.get("tool_name", ""),
                actual_decision_id=result.get("actual_decision_id", ""),
                matches_plan=result.get("matches_plan"),
                next_action_status=result.get("status", "started"),
            )
        elif surface == "hypothesis_rejected":
            # The interpretation moment already carries the rejection; retain one story line.
            continue
        elif surface == "memory_written":
            add(
                event,
                "MEMORY_UPDATED",
                f"{_agent_name(role)} wrote to its investigation notebook: {_short(content, 105)}",
                memory=result,
                direction="agent_to_memory",
            )
        elif surface == "memory_shared":
            add(
                event,
                "MEMORY_SHARED",
                f"{_agent_name(role)} shared a finding with {_agent_name(str(event.get('target_role')))}."
                if event.get("target_role") else f"{_agent_name(role)} published an authorized case finding.",
                memory=result,
                direction="agent_to_memory",
            )
        elif surface == "memory_read":
            add(
                event,
                "MEMORY_READ",
                f"{_agent_name(role)} read {result.get('owner_agent', 'authorized')} notebook entries.",
                memory=result,
                direction="memory_to_agent",
            )
        elif surface == "hypothesis_updated":
            if result.get("hypothesis_id"):
                add(event, "HYPOTHESIS_UPDATED",
                    f"{result.get('hypothesis_id')} is now {_pretty(result.get('status'))}: {_short(content, 105)}",
                    hypothesis=result, interpretation=content,
                    assessment=result.get("status"), next_action=result.get("next_test", ""))
            else:
                claim = claims.get(str(result.get("claim_id", "")))
                add(event, "SPECIALIST_REPORT_SENT",
                    f"{_agent_name(role)} registered an evidence-grounded claim in the evidence store.",
                    claim=claim or {}, interpretation=(claim or {}).get("interpretation", content),
                    direction="agent_to_judge")
        elif surface == "reinspection_requested":
            add(
                event,
                "JUDGE_REINSPECTION_REQUEST",
                f"{_agent_name(role)} requested {_agent_name(str(event.get('target_role')))} to verify: {_short(content, 100)}",
                request_reason=content,
                requested_frames=result.get("frame_indices", []),
                requested_tool=event.get("tool_name", ""),
                direction="judge_to_agent",
            )
        elif surface == "reinspection_completed":
            add(
                event,
                "REINSPECTION_RESULT",
                f"{_agent_name(role)} returned reinspection evidence to the judge.",
                response=result,
                direction="agent_to_judge",
            )
        elif surface == "judge_completed":
            add(
                event,
                "ORIGINAL_JUDGE_VERDICT",
                f"Original trained ARGUS judge returned {str(result.get('answer', 'unknown')).upper()}.",
                explanation=content or context.get("original_explanation", ""),
                answer=result.get("answer"),
                original=True,
                direction="judge_to_verdict",
            )
        elif surface == "augmented_verdict_created":
            add(
                event,
                "AUGMENTED_JUDGE_VERDICT",
                f"Experimental evidence-augmented judge returned {str(result.get('answer', 'unknown')).upper()}.",
                explanation=content or context.get("augmented_explanation", ""),
                answer=result.get("answer"),
                original=False,
                direction="judge_to_verdict",
            )
        elif surface == "baseline_fallback_started":
            add(event, "FALLBACK", "Enhanced coordination failed; the unchanged trained baseline path started.", reason=event.get("metadata", {}).get("reason", ""))
        elif surface == "agent_failed":
            add(event, "TOOL_FAILURE", f"{_agent_name(role)} failed: {_short(result.get('error'), 120)}", error=result.get("error", ""))
        elif surface == "audio_received":
            # Coalesce receipt and deterministic preprocessing into one readable
            # setup moment. The original receipt remains in the raw audit.
            pending_audio_received_id = str(event.get("event_id", ""))
        elif surface in {"audio_prepared", "audio_track_extracted"}:
            add(event, "AUDIO_PREPARED", content or "Audio was received and prepared with source timing retained.", audio=result, modality="audio")
            if pending_audio_received_id:
                moments[-1]["event_ids"].insert(0, pending_audio_received_id)
        elif surface == "audio_inference_started":
            # Lifecycle status is retained in raw audit; the next scene moment is
            # the first meaningful recorded output.
            continue
        elif surface == "audio_scene_analyzed":
            add(event, "AUDIO_SCENE_ANALYZED", content or "ToolDF described the audible scene.", scene=result, modality="audio")
        elif surface == "audio_verification_planned":
            add(event, "AUDIO_INVESTIGATION_STARTED", content or "The outer controller selected bounded supplementary checks.",
                verification_plan=result, modality="audio")
        elif surface == "audio_tool_planned":
            plan_text = content or str(result.get("summary", ""))
            plan = audio_plan_details(plan_text)
            add(event, "AUDIO_TOOL_PLANNED", plan_text or "ToolDF selected its next audio test.",
                plan=plan, source_separation=plan.get("source_separation"),
                start_time=plan.get("start_time"), end_time=plan.get("end_time"), modality="audio")
        elif surface == "audio_evidence_created":
            # The paired tool result already exposes this exact evidence record.
            continue
        elif surface == "audio_evidence_interpreted":
            linked = event
            causal_link_basis = "recorded"
            if not event.get("tool_call_id") and not event.get("evidence_ids"):
                if len(pending_audio_results) == 1:
                    source = pending_audio_results.pop()
                    linked = dict(event)
                    linked["tool_call_id"] = source.get("tool_call_id", "")
                    linked["evidence_ids"] = list(source.get("evidence_ids") or [])
                    causal_link_basis = "deterministic_single_pending_audio_call"
                else:
                    causal_link_basis = "unavailable"
            add(linked, "AUDIO_EVIDENCE_INTERPRETED", content or "ToolDF interpreted returned audio evidence.",
                interpretation=content, remaining_uncertainty=result.get("remaining_uncertainty", ""),
                next_action=result.get("next_action", ""), causal_link_basis=causal_link_basis,
                modality="audio")
        elif surface in {"audio_hypothesis_created", "audio_hypothesis_updated"}:
            kind = "AUDIO_HYPOTHESIS_CREATED" if surface.endswith("created") else "AUDIO_HYPOTHESIS_UPDATED"
            add(event, kind, content or "The audio hypothesis was recorded.", hypothesis=result, modality="audio")
        elif surface == "audio_finding_published":
            # The hypothesis update carries the evidence-linked finding and the
            # following event carries ToolDF's preserved verdict.
            continue
        elif surface == "audio_verdict_generated":
            add(event, "AUDIO_VERDICT", content or "ToolDF produced its original audio verdict.", verdict=result, modality="audio")
        elif surface == "audio_analysis_failed":
            add(event, "TOOL_FAILURE", content or "Audio investigation failed.", error=result.get("error", ""), modality="audio")
        elif surface == "audio_investigation_stopped":
            add(event, "AUDIO_FINDING_PUBLISHED", content or "Supplementary verification stopped.",
                stop_reason=result.get("reason", ""), tool_calls_used=result.get("tool_calls_used"), modality="audio")
        elif surface == "audio_peer_review_requested":
            add(event, "PEER_REVIEW_REQUESTED", content or "Independent audio verification was requested.",
                review=result, modality="audio", direction="agent_to_agent")
        elif surface == "audio_peer_review_completed":
            add(event, "EXPERT_CONSULTATION", content or "Independent audio verification completed.",
                review=result, assessment=result.get("independent_verification", "inconclusive"), modality="audio",
                direction="agent_to_agent")
        elif surface == "audiovisual_case_review":
            add(event, "AUDIOVISUAL_REVIEW", content or "The case reviewer compared modality-level findings without score fusion.", review=result)
        elif surface == "run_completed":
            if context.get("case_id") and str(event.get("run_id", "")) != str(context.get("case_id")):
                # A branch completed; this is not automatically a case-level verdict.
                continue
            if event_modality(event) == "audio" and any(
                item.get("type") == "AUDIO_VERDICT" for item in moments
            ):
                continue
            answer = result.get("answer", result.get("assessment", "unknown"))
            add(event, "CASE_COMPLETED", f"Case completed with assessment {str(answer).upper()}.", answer=answer)
    return moments
