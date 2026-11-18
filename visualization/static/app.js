(() => {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const AGENTS = {
    texture_agent: { name: "Texture agent", short: "TX", color: "#ae8dff" },
    lighting_agent: { name: "Lighting agent", short: "LX", color: "#f0bd68" },
    motion_agent: { name: "Motion agent", short: "MX", color: "#4ed8e8" },
    physics_agent: { name: "Physics agent", short: "PX", color: "#65d5a0" },
    investigator_1: { name: "Investigator 1", short: "I1", color: "#ae8dff" },
    investigator_2: { name: "Investigator 2", short: "I2", color: "#f0bd68" },
    investigator_3: { name: "Investigator 3", short: "I3", color: "#4ed8e8" },
    investigator_4: { name: "Investigator 4", short: "I4", color: "#65d5a0" },
    judge_coordinator: { name: "Judge coordinator", short: "JC", color: "#ef738c" },
    audio_investigator: { name: "Audio investigator", short: "AI", color: "#ae8dff" },
    audio_case_coordinator: { name: "Audio case coordinator", short: "AC", color: "#ef738c" },
    tooldf_planner: { name: "ToolDF planner", short: "TD", color: "#4ed8e8" },
    audiovisual_reviewer: { name: "Audiovisual reviewer", short: "AR", color: "#ef738c" },
    direct_demo: { name: "Direct tool demo", short: "DD", color: "#f0bd68" },
    system: { name: "ARGUS runtime", short: "SY", color: "#8d9aaa" },
    unknown: { name: "Native runtime", short: "RT", color: "#8d9aaa" },
  };
  const NODE_NAMES = {
    video: "Input video", audio: "Input audio", mcp: "MCP gateway", instrument: "Forensic instrument",
    evidence: "Evidence store", memory: "Investigation notebook", verdict: "Final output",
    audio_evidence: "Audio evidence store", source_separator: "Demucs separator", audio_verification_tool: "Supplementary verification tool",
    speech_deepfake_detector: "Speech detector", singing_deepfake_detector: "Singing detector",
    music_deepfake_detector: "Music detector", sound_deepfake_detector: "Sound detector",
    detect_speech_activity: "Speech activity", analyze_prosody: "Prosody analyzer",
    compare_speaker_identity: "Speaker verifier", compare_speaking_style: "Delivery comparison",
    detect_audio_edit_boundaries: "Edit boundary analyzer", inspect_breathing_patterns: "Breathing inspection",
    compare_audio_fingerprints: "Audio fingerprint", compare_transcripts: "Transcript comparison",
    diarize_audio_speakers: "Speaker diarization", transcribe_audio: "WhisperX transcription",
    test_audio_processing_alternative: "Benign processing control",
    ...Object.fromEntries(Object.entries(AGENTS).map(([key, value]) => [key, value.name])),
  };
  const IMPORTANT = new Set([
    "CASE_OPENED", "VIDEO_SAMPLED", "INITIAL_OBSERVATION", "TOOL_DECISION",
    "TOOL_EXECUTION", "EVIDENCE_RETURNED", "EVIDENCE_INTERPRETED",
    "HYPOTHESIS_REJECTED", "MEMORY_UPDATED", "MEMORY_SHARED", "MEMORY_READ",
    "SPECIALIST_REPORT_SENT", "JUDGE_REINSPECTION_REQUEST", "REINSPECTION_RESULT",
    "ORIGINAL_JUDGE_VERDICT", "AUGMENTED_JUDGE_VERDICT", "FALLBACK",
    "TOOL_FAILURE", "CASE_COMPLETED", "HYPOTHESIS_CREATED", "HYPOTHESIS_UPDATED",
    "QUESTION_OPENED", "QUESTION_CLAIMED", "QUESTION_RESOLVED", "PEER_REVIEW_REQUESTED",
    "EXPERT_CONSULTATION", "NEXT_ACTION_PLANNED", "NEXT_ACTION_EXECUTED",
    "AUDIO_RECEIVED", "AUDIO_PREPARED", "AUDIO_INVESTIGATION_STARTED", "AUDIO_SCENE_ANALYZED", "AUDIO_TOOL_PLANNED",
    "AUDIO_EVIDENCE_RECORDED", "AUDIO_EVIDENCE_INTERPRETED", "AUDIO_HYPOTHESIS_CREATED", "AUDIO_HYPOTHESIS_UPDATED", "AUDIO_FINDING_PUBLISHED",
    "AUDIO_VERDICT", "AUDIOVISUAL_REVIEW",
  ]);
  const ROUTINE_TOOLS = new Set([
    "get_video_metadata", "get_frame_manifest", "get_observation_status",
    "list_forensic_tools", "list_evidence", "get_final_result", "get_reinspection_status",
  ]);
  const TOOLDF_AUDIO_TOOLS = new Set(["source_separator", "speech_deepfake_detector", "singing_deepfake_detector", "music_deepfake_detector", "sound_deepfake_detector"]);
  const AUDIO_VERIFICATION_TOOLS = new Set(["detect_speech_activity", "analyze_prosody", "compare_speaker_identity", "compare_speaking_style", "detect_audio_edit_boundaries", "inspect_breathing_patterns", "compare_audio_fingerprints", "compare_transcripts", "diarize_audio_speakers", "transcribe_audio", "test_audio_processing_alternative"]);
  const STORY_SURFACES = new Set([
    "case_opened", "video_sampled", "observation_generated", "investigation_decision",
    "evidence_interpreted", "hypothesis_rejected", "memory_written", "memory_shared",
    "memory_read", "hypothesis_updated", "reinspection_requested", "reinspection_completed",
    "judge_completed", "augmented_verdict_created", "baseline_fallback_started",
    "agent_failed", "run_completed", "general_observation_generated",
    "hypothesis_created", "investigation_question_opened", "investigation_question_claimed",
    "investigation_question_resolved", "peer_review_requested", "peer_review_completed", "expert_consultation_completed",
    "next_action_planned", "next_action_started",
    "audio_received", "audio_prepared", "audio_track_extracted", "audio_scene_analyzed",
    "audio_tool_planned", "audio_evidence_interpreted", "audio_hypothesis_created",
    "audio_hypothesis_updated", "audio_finding_published", "audio_verdict_generated",
    "audio_verification_planned", "audio_tool_called", "audio_tool_result", "audio_investigation_stopped",
    "audio_peer_review_requested", "audio_peer_review_completed",
    "audiovisual_case_review",
  ]);
  const ICONS = {
    CASE_OPENED: "01", VIDEO_SAMPLED: "FR", INITIAL_OBSERVATION: "OB",
    TOOL_DECISION: "?", TOOL_EXECUTION: "→", EVIDENCE_RETURNED: "←",
    EVIDENCE_INTERPRETED: "✓", HYPOTHESIS_REJECTED: "×", MEMORY_UPDATED: "NB",
    MEMORY_SHARED: "SH", MEMORY_READ: "RD", SPECIALIST_REPORT_SENT: "RP",
    JUDGE_REINSPECTION_REQUEST: "RQ", REINSPECTION_RESULT: "RC",
    ORIGINAL_JUDGE_VERDICT: "JV", AUGMENTED_JUDGE_VERDICT: "AV",
    HYPOTHESIS_CREATED: "H+", HYPOTHESIS_UPDATED: "HΔ", QUESTION_OPENED: "Q+",
    QUESTION_CLAIMED: "QC", QUESTION_RESOLVED: "Q✓", PEER_REVIEW_REQUESTED: "PR",
    NEXT_ACTION_PLANNED: "NP", NEXT_ACTION_EXECUTED: "NX",
    EXPERT_CONSULTATION: "EX", FALLBACK: "FB", TOOL_FAILURE: "!", CASE_COMPLETED: "✓", native_event: "N",
    AUDIO_RECEIVED: "♫", AUDIO_PREPARED: "WV", AUDIO_INVESTIGATION_STARTED: "▶", AUDIO_SCENE_ANALYZED: "AU",
    AUDIO_TOOL_PLANNED: "?", AUDIO_EVIDENCE_RECORDED: "AE", AUDIO_EVIDENCE_INTERPRETED: "A✓", AUDIO_HYPOTHESIS_CREATED: "H+", AUDIO_HYPOTHESIS_UPDATED: "HΔ",
    AUDIO_FINDING_PUBLISHED: "AF", AUDIO_VERDICT: "AV", AUDIOVISUAL_REVIEW: "XR",
  };
  const PHASES = ["setup", "observe", "scan", "focus", "synthesize", "judge"];
  const state = {
    events: [], moments: [], context: {}, meta: {}, cursor: -1, selected: null, live: true,
    playing: false, timer: null, view: "story", imported: false, activeAgent: "", selectedOperation: "",
    waveform: null, audioInterval: null, playingAudioInterval: false, drawerAgent: "", stream: null,
  };
  const $ = (id) => document.getElementById(id);
  const els = {
    run: $("run-id"), video: $("video-id"), harness: $("harness"), live: $("live-badge"),
    trace: $("trace-path"), timeline: $("timeline"), raw: $("raw-timeline"), matrix: $("tool-matrix"),
    search: $("search"), agentFilter: $("agent-filter"), toolFilter: $("tool-family-filter"),
    displayMode: $("display-mode"), errorsOnly: $("errors-only"),
    scrubber: $("scrubber"), stepLabel: $("step-label"), elapsed: $("elapsed-label"),
    play: $("play-pause"), speed: $("speed"), empty: $("empty-state"),
  };
  const staticPreview = new URLSearchParams(window.location.search).has("static");

  function pretty(value) {
    return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
  }
  function truncate(value, max = 140) {
    const text = String(value ?? "").replace(/\s+/g, " ").trim();
    return text.length > max ? `${text.slice(0, max - 1)}…` : text;
  }
  function excerpt(value, max = 640) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    if (!text) return "No textual response was recorded for this older event.";
    if (text.length <= max) return text;
    const slice = text.slice(0, max);
    const boundary = Math.max(slice.lastIndexOf(". "), slice.lastIndexOf("; "));
    return `${slice.slice(0, boundary > max * 0.55 ? boundary + 1 : max).trim()} …`;
  }
  function escapeHtml(value) {
    const node = document.createElement("span"); node.textContent = String(value ?? ""); return node.innerHTML;
  }
  function agentInfo(role) {
    return AGENTS[role] || { name: pretty(role || "runtime"), short: "AI", color: "#8d9aaa" };
  }
  function evidenceId(event) {
    return event?.evidence_ids?.[0] || event?.evidence?.evidence_id
      || event?.result?.evidence_id
      || event?.result?.supporting_evidence_ids?.[0]
      || event?.result?.claim?.supporting_evidence_ids?.[0]
      || "";
  }
  function evidenceRecord(event) {
    if (event?.evidence) return event.evidence;
    const id = evidenceId(event);
    return (state.context.evidence || []).find((item) => item.evidence_id === id) || null;
  }
  function claimRecord(event) {
    if (event?.detail?.claim) return event.detail.claim;
    const id = event?.result?.claim_id;
    return (state.context.claims || []).find((item) => item.claim_id === id) || null;
  }
  function phaseFor(event) {
    const surface = event?.type || event?.surface || "";
    if (["AUDIO_RECEIVED", "AUDIO_PREPARED"].includes(surface)) return "setup";
    if (["AUDIO_SCENE_ANALYZED"].includes(surface)) return "observe";
    if (["AUDIO_TOOL_PLANNED", "AUDIO_HYPOTHESIS_CREATED", "AUDIO_HYPOTHESIS_UPDATED"].includes(surface)) return "scan";
    if (["AUDIO_EVIDENCE_INTERPRETED"].includes(surface)) return "focus";
    if (["AUDIO_FINDING_PUBLISHED"].includes(surface)) return "synthesize";
    if (["AUDIO_VERDICT", "AUDIOVISUAL_REVIEW"].includes(surface)) return "judge";
    if (["CASE_OPENED"].includes(surface)) return "setup";
    if (["VIDEO_SAMPLED", "INITIAL_OBSERVATION"].includes(surface)) return "observe";
    if (["TOOL_DECISION", "HYPOTHESIS_CREATED", "QUESTION_OPENED", "QUESTION_CLAIMED"].includes(surface)) return "scan";
    if (["TOOL_EXECUTION", "EVIDENCE_RETURNED", "EVIDENCE_INTERPRETED", "HYPOTHESIS_REJECTED", "TOOL_FAILURE"].includes(surface)) return "focus";
    if (["MEMORY_UPDATED", "MEMORY_SHARED", "MEMORY_READ", "SPECIALIST_REPORT_SENT", "HYPOTHESIS_UPDATED", "QUESTION_RESOLVED", "PEER_REVIEW_REQUESTED", "EXPERT_CONSULTATION", "JUDGE_REINSPECTION_REQUEST", "REINSPECTION_RESULT", "NEXT_ACTION_PLANNED", "NEXT_ACTION_EXECUTED"].includes(surface)) return "synthesize";
    if (["ORIGINAL_JUDGE_VERDICT", "AUGMENTED_JUDGE_VERDICT", "CASE_COMPLETED", "FALLBACK"].includes(surface) || event?.agent_role === "judge_coordinator") return "judge";
    return "setup";
  }
  function keyEvents() {
    return state.moments.length ? state.moments : state.events.filter((event) => IMPORTANT.has(event.type || event.surface) || event.status === "error");
  }
  function keyPosition(event = state.selected) {
    if (!event) return -1;
    return keyEvents().findIndex((item) => item.moment_id === event.moment_id || sequenceOf(item) === sequenceOf(event));
  }
  function findCall(event) {
    const index = state.events.findIndex((item) => sequenceOf(item) === sequenceOf(event));
    for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
      const candidate = state.events[cursor];
      if (candidate.surface === "tool_call" && candidate.agent_role === event.agent_role && candidate.tool_name === event.tool_name) return candidate;
    }
    return null;
  }
  function formatArguments(args = {}) {
    const clean = Object.fromEntries(Object.entries(args).filter(([key, value]) => key !== "video_id" && value !== null && value !== ""));
    if (!Object.keys(clean).length) return args.video_id ? `video_id: ${args.video_id}` : "No additional arguments.";
    return Object.entries(clean).map(([key, value]) => {
      const rendered = Array.isArray(value) ? `[${value.join(", ")}]` : typeof value === "object" ? JSON.stringify(value) : String(value);
      return `${pretty(key)}: ${rendered}`;
    }).join("\n");
  }
  function numeric(value, digits = 3) {
    return typeof value === "number" ? value.toFixed(digits) : String(value);
  }
  function sequenceOf(event) {
    return Number(event?.dashboard_sequence_num ?? event?.sequence_num ?? 0);
  }
  function identityOf(event) {
    return String(event?.global_event_id || `${event?.run_id || "run"}:${event?.event_id || sequenceOf(event)}`);
  }
  function modalityOf(event) {
    return String(event?.modality || event?.detail?.modality || event?.raw_event?.metadata?.modality || event?.metadata?.modality || (String(event?.type || event?.surface || "").startsWith("AUDIO") ? "audio" : "video"));
  }
  function audioToolSource() {
    return state.context.audio_topology === "clawteam" ? "tooldf_planner" : "audio_investigator";
  }
  function applyWorkspaceMode(mode) {
    const combinedAvailable = state.context.dashboard_mode === "combined" || state.context.dashboard_mode === "audiovisual";
    const selected = combinedAvailable ? mode : (state.context.audio_enabled && !state.context.video_available ? "audio" : "visual");
    document.documentElement.dataset.modality = selected === "combined" ? "audiovisual" : selected;
    $("audio-focus").hidden = selected === "visual" || !state.context.audio_enabled;
    $("media-focus").hidden = selected === "audio" || !state.context.video_available;
    if ($("timeline-filter")) $("timeline-filter").value = selected === "combined" ? "all" : selected;
  }
  function evidenceText(record) {
    if (!record) return "The diagnostic completed, but its full evidence record is not available yet.";
    if (String(record.evidence_id || "").startsWith("audio_ev_")) {
      if (record.component_type === "verification") {
        const measured = record.actual_tool_response || record.raw_measurements || {};
        if (["error", "unavailable"].includes(measured.execution_status)) return `${pretty(record.tool_name)} was ${measured.execution_status}; no substitute measurement or authenticity verdict was generated.`;
        const compact = Object.entries(measured).filter(([key]) => !["pitch_contour", "energy_contour", "segments", "words", "limitations", "suspect_transcript", "reference_transcript"].includes(key)).slice(0, 8).map(([key, value]) => `${pretty(key)}: ${typeof value === "object" ? JSON.stringify(value) : value}`).join(" · ");
        return `${pretty(record.tool_name)} returned supplementary measurements. ${compact}. This tool did not produce P(real) or an authenticity verdict.`;
      }
      if (record.tool_name === "source_separator") return `Demucs ${record.status || "completed"} for ${numeric(Number(record.start_time || 0), 2)}–${numeric(Number(record.end_time || 0), 2)}s. The stems are processing artifacts, not authenticity evidence.`;
      const score = record.raw_score === null || record.raw_score === undefined ? "unavailable" : numeric(Number(record.raw_score), 4);
      const threshold = record.threshold === null || record.threshold === undefined ? "unavailable" : numeric(Number(record.threshold), 4);
      return `${pretty(record.tool_name)} analyzed ${pretty(record.component_type)} at ${numeric(Number(record.start_time || 0), 2)}–${numeric(Number(record.end_time || 0), 2)}s using ${pretty(record.detector_variant)}. Result: ${String(record.prediction || "unknown").toUpperCase()}; P(real) ${score}; threshold ${threshold}.`;
    }
    const stats = record.summary_statistics || {};
    if (Array.isArray(stats.ranked_frames)) {
      const ranked = stats.ranked_frames.slice(0, 4).map((item) => `frame ${item.frame_index} at ${numeric(item.timestamp, 1)}s = ${numeric(item.measurement)}`).join("; ");
      return `Ranked ${stats.selected_frame_count || record.frame_indices?.length || 0} sampled frames using ${pretty(stats.method || record.parameters?.method)}. Strongest measurements: ${ranked}.`;
    }
    if (stats.mean_flow_magnitude !== undefined) {
      return `Dense flow across frames ${(record.frame_indices || []).join("–")}: mean magnitude ${numeric(stats.mean_flow_magnitude)}, temporal variation ${numeric(stats.flow_variation)}. Pair values: ${(stats.pair_mean_magnitudes || []).map((item) => numeric(item)).join(", ")}.`;
    }
    if (stats.mean_aligned_residual_change !== undefined) {
      return `Aligned residual change across frames ${(record.frame_indices || []).join(", ")}: mean ${numeric(stats.mean_aligned_residual_change)}. Pair measurements: ${(stats.pair_measurements || []).map((item) => numeric(item)).join(", ")}.`;
    }
    if (Array.isArray(stats.tracked_boxes)) {
      const confidence = Array.isArray(stats.tracking_confidence) && stats.tracking_confidence.length
        ? stats.tracking_confidence.reduce((sum, value) => sum + Number(value || 0), 0) / stats.tracking_confidence.length
        : null;
      const first = stats.tracked_boxes[0] || record.roi || [], last = stats.tracked_boxes.at(-1) || first;
      return `Tracked the selected ROI through ${(record.frame_indices || []).length} sampled frames, from [${first.join(", ")}] to [${last.join(", ")}].${confidence === null ? "" : ` Mean feature-survival confidence: ${numeric(confidence)}.`} Completed: ${Boolean(stats.completed)}.`;
    }
    if (stats.best_match) return `Best local reference match: suspect frame ${stats.best_match.suspect_frame_index} → reference frame ${stats.best_match.reference_frame_index}, similarity ${numeric(stats.best_match.score)}. This is retrieval evidence, not proof of manipulation.`;
    if (record.tool_name === "visual_grounding") return `SAM3 ${stats.status === "no_detection" ? "returned no detection" : `grounded ${(stats.boxes_original_pixels || []).length} region(s)`} for “${stats.query || "object"}”. Masks: ${(stats.mask_artifact_ids || []).join(", ") || "none"}. A miss does not prove absence.`;
    if (record.tool_name === "recognize_scene_text") {
      const transcription = String(stats.recognized_text || "[no readable text]").replace(/\s+/g, " ").trim();
      return `PaddleOCR-VL transcription: ${excerpt(transcription, 240)}. Model: ${stats.model_id || "unrecorded"}. Full text remains in the expandable normalized event; OCR disagreement is not proof of synthesis.`;
    }
    if (record.tool_name === "reverse_search_frame") return `Reverse image search returned ${stats.candidate_count || 0} candidate source reference(s). Candidates are not verified originals; external transmission authorization is recorded.`;
    if (record.tool_name === "search_source_evidence") return `Source search returned ${stats.candidate_count || 0} candidate reference(s). Provider text and generated summary are retained separately.`;
    if (record.tool_name === "inspect_source_webpage") return `Inspected ${(stats.pages || []).length} untrusted source page(s) for the recorded goal. Retrieved text remains evidence, never an instruction.`;
    if (stats.mean_absolute_difference !== undefined) return `Aligned-region similarity ${numeric(stats.similarity)}; mean absolute difference ${numeric(stats.mean_absolute_difference)}; p95 difference ${numeric(stats.difference_p95)}.`;
    if (Array.isArray(stats.per_frame_geometry)) return `Measured object-region geometry across ${stats.per_frame_geometry.length} frames; edge-fraction range ${numeric(stats.edge_fraction_range)}.`;
    if (Array.isArray(stats.pair_changes)) return `Visible region pair changes: ${stats.pair_changes.map((item) => numeric(item)).join(", ")}. Maximum ${numeric(stats.maximum_change)}.`;
    if (stats.successful_frames !== undefined || stats.tracked_rois) {
      return `ROI tracking covered ${(record.frame_indices || []).length} frames${stats.mean_confidence !== undefined ? ` with mean confidence ${numeric(stats.mean_confidence)}` : ""}. Recorded ROI: ${(record.roi || []).join(", ")}.`;
    }
    const important = Object.entries(stats).filter(([, value]) => typeof value === "number").slice(0, 6);
    const values = important.map(([key, value]) => `${pretty(key)} ${numeric(value)}`).join("; ");
    return `${pretty(record.tool_name)} measured frame${record.frame_indices?.length === 1 ? "" : "s"} ${(record.frame_indices || []).join(", ")}${record.roi ? ` inside ROI [${record.roi.join(", ")}]` : ""}. ${values}`.trim();
  }
  function observationText(event) {
    const role = String(event.result?.role || event.agent_role || "").replace("_agent", "");
    return event.content || state.context.observations?.[role] || "";
  }
  function judgeInput() {
    const entries = Object.entries(state.context.observations || {});
    if (!entries.length) return baseNoLora() ? "Four base-model role observations were passed to the judge." : "Four trained observer reports were passed to the judge.";
    return entries.map(([role, text]) => `${pretty(role)}: ${excerpt(text, 150)}`).join("\n");
  }
  function judgeText(event) {
    if (event.content) return event.content;
    if (event.surface === "augmented_verdict_created") return state.context.augmented_explanation || "";
    return state.context.original_explanation || "";
  }

  function transaction(event) {
    const role = event.agent_role || "system";
    const call = findCall(event);
    const record = evidenceRecord(event);
    const claim = claimRecord(event);
    let source = role, target = role, kind = "KEY MOMENT", color = "#4ed8e8";
    let input = "", output = "", purpose = "", inputLabel = "ORIGINAL INPUT / MESSAGE", outputLabel = "ORIGINAL OUTPUT / OBSERVATION";
    switch (event.surface) {
      case "tool_call":
        source = role; target = "mcp"; kind = "TOOL CALL";
        input = `${pretty(event.tool_name)}\n${formatArguments(event.tool_args)}`;
        output = "The trusted tool gateway accepted this call; its measured reply follows.";
        purpose = "A specialist requested a bounded diagnostic.";
        break;
      case "tool_result":
        source = "mcp"; target = role; kind = "TOOL REPLY"; color = "#6aa7ff";
        input = `${pretty(event.tool_name)}\n${formatArguments(call?.tool_args || {})}`;
        output = evidenceText(record) || JSON.stringify(event.result || {});
        purpose = "The tool returned measured data to the requesting agent.";
        break;
      case "observation_generated":
        source = role; target = "evidence"; kind = baseNoLora() ? "BASE-MODEL OBSERVATION" : "TRAINED OBSERVATION";
        input = baseNoLora() ? `Sampled video frames were analyzed by base Qwen2.5-VL using the ${pretty(event.result?.role)} role prompt.` : `Sampled video frames were analyzed by the trained ${pretty(event.result?.adapter || event.result?.role)} LoRA.`;
        output = excerpt(observationText(event));
        outputLabel = "ORIGINAL AGENT OBSERVATION";
        purpose = "This is the specialist model's substantive visual reading, not a status message.";
        break;
      case "forensic_tool_completed":
        source = role; target = "mcp"; kind = "DIAGNOSTIC ROUND TRIP"; color = "#6aa7ff";
        input = `${pretty(event.tool_name)}\n${formatArguments(call?.tool_args || {})}`;
        output = evidenceText(record);
        outputLabel = "TOOL'S MEASURED RESPONSE";
        purpose = `The ${agentInfo(role).name.toLowerCase()} tested its observation against actual frames.`;
        break;
      case "hypothesis_updated":
        source = role; target = "judge_coordinator"; kind = "AGENT CONCLUSION"; color = "#65d5a0";
        input = `Evidence reviewed: ${(event.result?.supporting_evidence_ids || []).join(", ")}\n${claim ? evidenceText((state.context.evidence || []).find((item) => item.evidence_id === claim.supporting_evidence_ids?.[0])) : ""}`;
        output = excerpt(event.content || (claim ? `${claim.claim}\n\nInterpretation: ${claim.interpretation}` : ""));
        outputLabel = "AGENT MESSAGE TO JUDGE";
        purpose = "The agent converted measurements into a bounded conclusion with limitations.";
        break;
      case "reinspection_requested":
        source = "judge_coordinator"; target = event.target_role || role; kind = "JUDGE CALLBACK"; color = "#ef738c";
        input = excerpt(event.content || state.context.reinspection_requests?.find((item) => item.request_id === event.result?.request_id)?.reason || "Judge requested more evidence.");
        output = `${pretty(event.tool_name)} requested on frames ${(event.result?.frame_indices || []).join(", ")}.`;
        purpose = "The judge sent a concrete uncertainty back to a specialist.";
        break;
      case "reinspection_completed":
        source = role; target = "judge_coordinator"; kind = "REINSPECTION RETURN"; color = "#65d5a0";
        input = `Requested reinspection ${event.result?.request_id || ""}`;
        output = `Returned evidence: ${(event.result?.evidence_ids || []).join(", ")}.`;
        purpose = "New measured evidence returned to the judge.";
        break;
      case "judge_completed":
        source = "judge_coordinator"; target = "verdict"; kind = "ORIGINAL VERDICT"; color = "#ef738c";
        input = judgeInput(); output = excerpt(judgeText(event));
        outputLabel = `JUDGE RESPONSE · ${String(event.result?.answer || "unknown").toUpperCase()}`;
        purpose = "The authoritative trained judge synthesized the four original reports.";
        break;
      case "augmented_verdict_created":
        source = "judge_coordinator"; target = "verdict"; kind = "AUGMENTED VERDICT"; color = "#ef738c";
        input = `${judgeInput()}\nPlus verified diagnostic evidence and agent conclusions.`;
        output = excerpt(judgeText(event));
        outputLabel = `EXPERIMENTAL RESPONSE · ${String(event.result?.answer || "unknown").toUpperCase()}`;
        purpose = "This evidence-aware result remains separately labeled from the original judge.";
        break;
      case "run_completed":
        source = "judge_coordinator"; target = "verdict"; kind = "FINAL COMMIT"; color = "#6aa7ff";
        input = "The original and optional augmented judgments were finalized.";
        output = `Committed answer: ${String(event.result?.answer || "unknown").toUpperCase()}.`;
        purpose = "The run closed with immutable outputs and a complete audit trace.";
        break;
      case "agent_failed":
        source = role; target = "judge_coordinator"; kind = "ERROR"; color = "#ff685f";
        input = "Agent execution"; output = excerpt(event.result?.error || event.content || "Failure recorded.");
        purpose = "The failure was contained and recorded.";
        break;
      default:
        source = role; target = role; kind = pretty(event.surface);
        input = formatArguments(event.tool_args || {}); output = excerpt(event.content || JSON.stringify(event.result || {}));
        purpose = "Exact audit event.";
    }
    return { source, target, kind, color, input, output, purpose, inputLabel, outputLabel };
  }

  function describe(event) {
    const tx = transaction(event);
    if (event.surface === "observation_generated") return { title: `${agentInfo(event.agent_role).name} produced a visual observation`, text: truncate(tx.output, 180) };
    if (event.surface === "forensic_tool_completed") return { title: `${agentInfo(event.agent_role).name} tested ${pretty(event.tool_name)}`, text: truncate(tx.output, 180) };
    if (event.surface === "hypothesis_updated") return { title: `${agentInfo(event.agent_role).name} sent its evidence-grounded conclusion`, text: truncate(tx.output, 180) };
    if (event.surface === "judge_completed") return { title: `Original judge: ${String(event.result?.answer || "unknown").toUpperCase()}`, text: truncate(tx.output, 180) };
    if (event.surface === "augmented_verdict_created") return { title: `Augmented judge: ${String(event.result?.answer || "unknown").toUpperCase()}`, text: truncate(tx.output, 180) };
    if (event.surface === "run_completed") return { title: `Final answer committed: ${String(event.result?.answer || "unknown").toUpperCase()}`, text: tx.purpose };
    if (event.surface === "reinspection_requested") return { title: `Judge asked ${pretty(event.target_role)} to inspect again`, text: truncate(tx.input, 180) };
    if (event.surface === "reinspection_completed") return { title: `${agentInfo(event.agent_role).name} returned reinspection evidence`, text: tx.output };
    if (event.surface === "agent_failed") return { title: `${agentInfo(event.agent_role).name} failed`, text: tx.output };
    return { title: `${nodeLabel(tx.source)} → ${nodeLabel(tx.target)}`, text: truncate(tx.output, 180) };
  }

  function nodeCenter(name) {
    const stage = $("flow-stage"); const node = document.querySelector(`[data-node="${CSS.escape(name)}"]`);
    if (!stage || !node) return null;
    const outer = stage.getBoundingClientRect(), inner = node.getBoundingClientRect();
    return { x: inner.left - outer.left + inner.width / 2, y: inner.top - outer.top + inner.height / 2 };
  }
  function routePath(source, target) {
    const start = nodeCenter(source), end = nodeCenter(target);
    if (!start || !end || source === target) return null;
    const dx = end.x - start.x, curve = Math.max(38, Math.abs(dx) * 0.42);
    if (source === "judge_coordinator" && target.endsWith("_agent")) return `M ${start.x} ${start.y} C ${start.x - curve} ${start.y - 100}, ${end.x + curve} ${end.y - 100}, ${end.x} ${end.y}`;
    return `M ${start.x} ${start.y} C ${start.x + Math.sign(dx || 1) * curve} ${start.y}, ${end.x - Math.sign(dx || 1) * curve} ${end.y}, ${end.x} ${end.y}`;
  }
  function drawBaseRoutes() {
    const group = $("base-routes"); group.replaceChildren(); const pairs = [];
    for (const role of ["texture_agent", "lighting_agent", "motion_agent", "physics_agent"]) pairs.push(["video", role], [role, "mcp"], [role, "evidence"], ["judge_coordinator", role]);
    pairs.push(["mcp", "evidence"], ["evidence", "judge_coordinator"], ["judge_coordinator", "mcp"], ["judge_coordinator", "verdict"]);
    for (const [source, target] of pairs) {
      const pathValue = routePath(source, target); if (!pathValue) continue;
      const path = document.createElementNS(NS, "path"); path.setAttribute("d", pathValue); path.setAttribute("class", "base-route"); group.append(path);
    }
  }
  function animateSignal(tx, delay = 0) {
    const pathValue = routePath(tx.source, tx.target); if (!pathValue) return;
    setTimeout(() => {
      const group = $("active-signals");
      const path = document.createElementNS(NS, "path"); path.setAttribute("d", pathValue); path.setAttribute("class", "active-route"); path.style.stroke = tx.color;
      const dot = document.createElementNS(NS, "circle"); dot.setAttribute("r", "4"); dot.setAttribute("class", "signal-dot"); dot.style.stroke = tx.color;
      const motion = document.createElementNS(NS, "animateMotion"); motion.setAttribute("dur", "820ms"); motion.setAttribute("path", pathValue); motion.setAttribute("fill", "freeze"); dot.append(motion); group.append(path, dot);
      for (const name of [tx.source, tx.target]) {
        const node = document.querySelector(`[data-node="${CSS.escape(name)}"]`); if (!node) continue;
        node.classList.remove("active-now"); void node.offsetWidth; node.classList.add("active-now");
      }
      setTimeout(() => { path.remove(); dot.remove(); }, 1050);
    }, delay);
  }
  function animateEvent(event, tx) {
    if (event.surface === "forensic_tool_completed") {
      animateSignal({ source: event.agent_role, target: "mcp", color: "#4ed8e8" });
      animateSignal({ source: "mcp", target: event.agent_role, color: "#6aa7ff" }, 900);
      return;
    }
    animateSignal(tx);
  }

  function renderExchange(event, animate = false) {
    if (!event) return;
    const tx = transaction(event), card = $("exchange-card");
    card.className = `exchange-card${event.status === "error" ? " error" : ""}`;
    $("exchange-kind").textContent = tx.kind; $("exchange-kind").style.color = tx.color;
    $("exchange-source").textContent = nodeLabel(tx.source);
    $("exchange-target").textContent = nodeLabel(tx.target);
    $("exchange-input-label").textContent = tx.inputLabel; $("exchange-output-label").textContent = tx.outputLabel;
    $("exchange-input").textContent = tx.input; $("exchange-output").textContent = tx.output; $("exchange-purpose").textContent = tx.purpose;
    if (animate) animateEvent(event, tx);
  }

  function setVideoTime(timestamp, record, selectedButton = null) {
    const video = $("evidence-video"), frame = $("evidence-frame");
    const seek = () => { try { video.currentTime = Math.max(0, Number(timestamp) || 0); video.pause(); } catch (_) { /* metadata not ready */ } };
    if (video.readyState >= 1) seek(); else video.addEventListener("loadedmetadata", seek, { once: true });
    if (record && state.context.video_available) {
      frame.hidden = false;
      frame.src = `/api/frame?t=${encodeURIComponent(Math.max(0, Number(timestamp) || 0))}`;
      frame.onerror = () => { frame.hidden = true; };
    } else {
      frame.hidden = true;
      frame.removeAttribute("src");
    }
    document.querySelectorAll("#frame-chips button").forEach((button) => button.classList.toggle("active", button === selectedButton));
    const selectedFrame = Number(selectedButton?.dataset.frame ?? record?.frame_indices?.[0] ?? 0);
    const selectedIndex = Math.max(0, (record?.frame_indices || []).indexOf(selectedFrame));
    const trackedRoi = record?.summary_statistics?.tracked_boxes?.[selectedIndex];
    $("media-time").textContent = `sample f${selectedFrame} · source ${numeric(Number(timestamp) || 0, 1)}s`;
    renderRoi(trackedRoi || record?.roi || null);
  }
  function renderRoi(roi) {
    const overlay = $("roi-overlay"), shell = overlay.parentElement, video = $("evidence-video"), frame = $("evidence-frame");
    if (!roi || roi.length !== 4) { overlay.hidden = true; return; }
    const sourceWidth = 256, sourceHeight = 256;
    const aspect = frame.naturalWidth && frame.naturalHeight ? frame.naturalWidth / frame.naturalHeight : (video.videoWidth && video.videoHeight ? video.videoWidth / video.videoHeight : 1);
    let width = shell.clientWidth, height = width / aspect;
    if (height > shell.clientHeight) { height = shell.clientHeight; width = height * aspect; }
    const left = (shell.clientWidth - width) / 2, top = (shell.clientHeight - height) / 2;
    overlay.style.left = `${left + (roi[0] / sourceWidth) * width}px`; overlay.style.top = `${top + (roi[1] / sourceHeight) * height}px`;
    overlay.style.width = `${((roi[2] - roi[0]) / sourceWidth) * width}px`; overlay.style.height = `${((roi[3] - roi[1]) / sourceHeight) * height}px`;
    overlay.hidden = false;
  }
  function renderMedia(event) {
    const record = evidenceRecord(event) || (() => {
      const ids = event?.result?.supporting_evidence_ids || claimRecord(event)?.supporting_evidence_ids || [];
      return (state.context.evidence || []).find((item) => item.evidence_id === ids[0]) || null;
    })();
    const video = $("evidence-video"), placeholder = $("video-placeholder");
    if (state.context.video_available && !video.getAttribute("src")) { video.src = "/api/video"; video.controls = true; }
    placeholder.hidden = Boolean(state.context.video_available);
    $("media-title").textContent = record ? `${pretty(record.tool_name)} · ${record.evidence_id}` : "Source video";
    const frames = record?.frame_indices || [];
    const timestamps = record?.frame_timestamps || frames.map((frame) => frame / 2);
    $("frame-chips").replaceChildren(...frames.slice(0, 16).map((frame, index) => {
      const button = document.createElement("button"); button.textContent = `f${frame} · ${numeric(timestamps[index] || 0, 1)}s`; button.dataset.frame = frame;
      button.addEventListener("click", () => setVideoTime(timestamps[index], record, button)); return button;
    }));
    const ranked = record?.summary_statistics?.ranked_frames?.[0];
    const preferredFrame = ranked?.frame_index ?? frames[0] ?? 0;
    const preferredIndex = Math.max(0, frames.indexOf(preferredFrame));
    const buttons = [...document.querySelectorAll("#frame-chips button")];
    setVideoTime(ranked?.timestamp ?? timestamps[preferredIndex] ?? 0, record, buttons[preferredIndex] || null);
    const compare = $("diagnostic-compare");
    if (record) {
      compare.hidden = false; $("diagnostic-image").src = `/api/artifact?id=${encodeURIComponent(record.evidence_id)}&t=${Date.now()}`;
      $("diagnostic-caption").textContent = excerpt(evidenceText(record), 210);
    } else { compare.hidden = true; renderRoi(null); }
  }

  function renderFlow() {
    drawBaseRoutes(); const through = state.events.slice(0, state.cursor + 1);
    for (const node of document.querySelectorAll("[data-agent]")) {
      const role = node.dataset.agent, events = through.filter((event) => event.agent_role === role);
      const started = events.some((event) => event.surface === "agent_started"), done = events.some((event) => event.surface === "task_completed") || (role === "judge_coordinator" && through.some((event) => event.surface === "run_completed"));
      const label = node.querySelector(":scope > i"); if (label) label.textContent = done ? "complete" : started ? "working" : role === "judge_coordinator" ? "blocked" : "queued";
      node.classList.toggle("dimmed", Boolean(state.activeAgent && state.activeAgent !== role));
    }
    const evidence = through.filter((event) => event.surface === "evidence_created").length;
    $("evidence-node-copy").textContent = `${evidence} verified record${evidence === 1 ? "" : "s"}`;
    const selectedTool = state.selected?.tool_name || "";
    const latestTool = selectedTool ? state.selected : [...through].reverse().find((event) => event.tool_name && !ROUTINE_TOOLS.has(event.tool_name));
    $("active-tool").textContent = latestTool ? pretty(latestTool.tool_name) : "MCP tools";
    $("active-tool-copy").textContent = latestTool ? `${agentInfo(latestTool.agent_role).name} · ${latestTool.status}` : "waiting for a call";
    document.querySelector('[data-node="mcp"]').classList.toggle("tool-active", Boolean(state.selected && transaction(state.selected).target === "mcp" || state.selected && transaction(state.selected).source === "mcp"));
    const manifest = through.find((event) => event.result?.sampling)?.result.sampling;
    if (manifest) $("video-node-copy").textContent = `${manifest.effective_frames || manifest.requested_frames} frames · ${manifest.frame_size}px`;
    const original = [...through].reverse().find((event) => ["run_completed", "judge_completed"].includes(event.surface));
    const augmented = [...through].reverse().find((event) => event.surface === "augmented_verdict_created");
    $("judge-node-copy").textContent = original ? "adjudication complete" : "waiting for reports";
    $("verdict-copy").textContent = original ? `Original: ${String(original.result?.answer || "unknown").toUpperCase()}` : "Pending verdict";
    document.querySelector('[data-node="verdict"] em').textContent = augmented ? `Augmented: ${String(augmented.result?.answer || "unknown").toUpperCase()} · kept separate` : "original + augmented kept separate";
    if (state.selected) { renderExchange(state.selected); renderMedia(state.selected); }
  }

  function eventMatches(event, raw = false) {
    if (!raw && !IMPORTANT.has(event.surface) && event.status !== "error") return false;
    const role = els.agentFilter.value || state.activeAgent;
    if (role && event.agent_role !== role && event.target_role !== role) return false;
    if (els.errorsOnly.checked && event.status !== "error") return false;
    const query = els.search.value.trim().toLowerCase();
    return !query || JSON.stringify(event).toLowerCase().includes(query) || Object.values(describe(event)).join(" ").toLowerCase().includes(query);
  }
  function visibleEvents(raw = false) {
    return state.events.slice(0, state.cursor + 1).filter((event) => eventMatches(event, raw));
  }
  function timelineItem(event, raw = false) {
    const info = agentInfo(event.agent_role), copy = describe(event), tx = transaction(event), item = document.createElement("li");
    item.className = `timeline-item${state.selected?.sequence_num === event.sequence_num ? " selected" : ""}`; item.dataset.sequence = event.sequence_num;
    const marker = document.createElement("span"); marker.className = `timeline-marker ${event.agent_role}${event.status === "error" ? " error" : ""}`; marker.textContent = raw ? `#${event.sequence_num}` : (ICONS[event.surface] || info.short);
    const card = document.createElement("div"); card.className = "timeline-card";
    card.innerHTML = `<div class="timeline-meta"><span>${escapeHtml(raw ? pretty(event.surface) : `${nodeLabel(tx.source)} → ${nodeLabel(tx.target)}`)}</span><time>${shortTime(event.timestamp)}</time></div><h3>${escapeHtml(copy.title)}</h3><p>${escapeHtml(copy.text)}</p><div class="timeline-exchange"><span><b>IN</b>${escapeHtml(truncate(tx.input, 180))}</span><span><b>OUT</b>${escapeHtml(truncate(tx.output, 220))}</span></div>`;
    item.append(marker, card); item.addEventListener("click", () => pinEvent(event)); return item;
  }
  function renderTimelines() {
    const story = visibleEvents(false); els.timeline.replaceChildren(...story.map((event) => timelineItem(event)));
    const raw = state.view === "raw" ? visibleEvents(true) : []; els.raw.replaceChildren(...raw.map((event) => timelineItem(event, true)));
    els.empty.hidden = (state.view === "story" ? story : raw).length > 0 || state.view === "matrix";
  }
  function renderMatrix() {
    if (state.view !== "matrix") { els.matrix.replaceChildren(); return; }
    const records = state.context.evidence || [];
    els.matrix.innerHTML = records.map((record) => `<button class="evidence-row" data-evidence="${escapeHtml(record.evidence_id)}"><img src="/api/artifact?id=${encodeURIComponent(record.evidence_id)}" alt=""><span><b>${escapeHtml(pretty(record.tool_name))}</b><small>${escapeHtml(agentInfo(record.agent_role).name)} · frames ${(record.frame_indices || []).join(", ")}</small><em>${escapeHtml(truncate(evidenceText(record), 130))}</em></span></button>`).join("") || `<div class="empty-state"><b>No evidence records yet</b></div>`;
    document.querySelectorAll(".evidence-row").forEach((row) => row.addEventListener("click", () => {
      const event = [...state.events].reverse().find((item) => evidenceId(item) === row.dataset.evidence && item.surface === "forensic_tool_completed"); if (event) selectEvent(event);
    }));
  }
  function renderPhases() {
    const current = state.selected || [...state.events.slice(0, state.cursor + 1)].reverse().find((event) => event.surface !== "native_event");
    const index = current ? PHASES.indexOf(phaseFor(current)) : -1;
    document.querySelectorAll("[data-phase]").forEach((button) => { const value = PHASES.indexOf(button.dataset.phase); button.classList.toggle("done", value < index); button.classList.toggle("active", value === index); });
  }
  function renderMetrics() {
    const through = state.events.slice(0, state.cursor + 1), moments = through.filter((event) => IMPORTANT.has(event.surface) || event.status === "error");
    $("metric-progress").textContent = state.events.length ? `${Math.round((state.cursor + 1) / state.events.length * 100)}%` : "0%";
    $("metric-events").textContent = moments.length; $("metric-tools").textContent = through.filter((event) => event.surface === "forensic_tool_completed").length;
    $("metric-evidence").textContent = through.filter((event) => event.surface === "evidence_created").length; $("metric-claims").textContent = through.filter((event) => event.surface === "hypothesis_updated").length;
    const errors = through.filter((event) => event.status === "error").length; $("metric-errors").textContent = errors; $("metric-errors").classList.toggle("has-errors", errors > 0);
  }
  function renderReplay() {
    const moments = keyEvents(), position = keyPosition();
    els.scrubber.max = Math.max(0, moments.length - 1); els.scrubber.value = Math.max(0, position);
    els.stepLabel.textContent = `Moment ${position >= 0 ? position + 1 : 0} / ${moments.length}`;
    const start = Date.parse(moments[0]?.timestamp || 0), now = Date.parse(state.selected?.timestamp || 0);
    els.elapsed.textContent = Number.isFinite(now - start) ? `+${duration(now - start)}` : "+00:00"; els.play.textContent = state.playing ? "Ⅱ" : "▶";
  }
  function render() { renderMetrics(); renderPhases(); renderFlow(); renderObservability(); renderTimelines(); renderMatrix(); renderReplay(); document.dispatchEvent(new CustomEvent("argus:av-selection", {detail:{context:state.context,selected:state.selected,maxSequence:cursorSequence(),events:state.events}})); }

  function selectEvent(event, options = {}) {
    state.selected = event; const info = agentInfo(event.agent_role), copy = describe(event), tx = transaction(event);
    $("inspector-empty").hidden = true; $("inspector-content").hidden = false; $("selected-sequence").textContent = `#${event.sequence_num}`;
    $("inspector-icon").textContent = ICONS[event.surface] || info.short; $("inspector-icon").style.color = event.status === "error" ? "#ff685f" : info.color;
    $("inspector-phase").textContent = `${pretty(phaseFor(event))} / ${pretty(event.surface)}`; $("inspector-title").textContent = copy.title; $("inspector-description").textContent = copy.text;
    $("inspector-input").textContent = tx.input; $("inspector-output").textContent = tx.output; $("fact-route").textContent = `${nodeLabel(tx.source)} → ${nodeLabel(tx.target)}`;
    $("fact-time").textContent = shortTime(event.timestamp, true); $("fact-status").textContent = event.status || "success"; $("fact-tool").textContent = event.tool_name || "—"; $("payload-json").textContent = JSON.stringify(event, null, 2);
    const id = evidenceId(event), artifact = $("artifact-card"), audioEvidence = String(id).startsWith("audio_ev_");
    if (id && !audioEvidence) {
      artifact.hidden = false; $("artifact-id").textContent = id; $("artifact-image").src = `/api/artifact?id=${encodeURIComponent(id)}&t=${Date.now()}`;
      const record = evidenceRecord(event), ids = record?.summary_statistics?.artifact_ids || event?.result?.artifact_ids || [];
      const all = state.context.artifacts || [], byId = Object.fromEntries(all.map((item) => [item.artifact_id, item]));
      $("reusable-artifacts").innerHTML = ids.map((artifactId) => {
        const item = byId[artifactId] || {}, parents = item.parent_artifact_ids || [], image = String(item.mime_type || "").startsWith("image/");
        return `<article><div>${image ? `<img src="/api/reusable-artifact?id=${encodeURIComponent(artifactId)}" alt="${escapeHtml(item.artifact_type || "artifact")}">` : `<span class="artifact-file">${escapeHtml(pretty(item.artifact_type || "data"))}</span>`}</div><b>${escapeHtml(artifactId)}</b><small>${escapeHtml(pretty(item.artifact_type || "artifact"))}</small><em>${escapeHtml(parents.length ? `${parents.join(" + ")} → ${artifactId}` : "source artifact")}</em></article>`;
      }).join("");
      const tabs = $("visual-artifact-tabs"), stats = recordForArtifacts?.summary_statistics || {};
      const roots = new Set([stats.source_image_artifact_id, ...(stats.mask_artifact_ids || [])].filter(Boolean));
      const dependent = all.filter((item) => (item.parent_artifact_ids || []).some((parent) => roots.has(parent)) && String(item.mime_type || "").startsWith("image/"));
      const choices = [
        ["Original", stats.original_frame_artifact_id || stats.source_image_artifact_id],
        ["Boxes", stats.bounding_box_overlay_artifact_id],
        ["Mask", (stats.mask_artifact_ids || [])[0]],
        ["Overlay", stats.segmentation_overlay_artifact_id],
        ["Crop", (stats.detected_crop_artifact_ids || [])[0]],
        ["Upstream preview", stats.upstream_preview_artifact_id],
        ["Downstream", dependent.find((item) => !ids.includes(item.artifact_id))?.artifact_id],
      ].filter((item, index, values) => item[1] && values.findIndex((other) => other[1] === item[1]) === index);
      if (recordForArtifacts?.tool_name === "visual_grounding" && choices.length) {
        tabs.hidden = false;
        const initial = choices.find((choice) => choice[0] === "Overlay") || choices[0];
        tabs.innerHTML = choices.map(([label, artifactId]) => `<button type="button" data-artifact-view="${escapeHtml(artifactId)}" class="${artifactId === initial[1] ? "active" : ""}">${escapeHtml(label)}</button>`).join("");
        $("artifact-image").src = `/api/reusable-artifact?id=${encodeURIComponent(initial[1])}&t=${Date.now()}`;
        tabs.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
          tabs.querySelectorAll("button").forEach((item) => item.classList.toggle("active", item === button));
          $("artifact-image").src = `/api/reusable-artifact?id=${encodeURIComponent(button.dataset.artifactView)}&t=${Date.now()}`;
        }));
      } else { tabs.hidden = true; tabs.innerHTML = ""; }
    } else { artifact.hidden = true; $("reusable-artifacts").innerHTML = ""; $("visual-artifact-tabs").hidden = true; $("visual-artifact-tabs").innerHTML = ""; }
    const provenance = $("provenance-card");
    if (["hypothesis_updated", "forensic_tool_completed"].includes(event.surface)) { provenance.hidden = false; $("provenance-list").innerHTML = ["Run/video scope recorded", "Exact frame indices retained", "Diagnostic artifact hash retained", "Measurement is not an authenticity probability"].map((item) => `<li>${item}</li>`).join(""); } else provenance.hidden = true;
    document.querySelectorAll(".timeline-item").forEach((item) => item.classList.toggle("selected", Number(item.dataset.sequence) === Number(event.sequence_num)));
    renderFlow(); renderPhases(); renderReplay(); if (!options.quiet) renderExchange(event, true);
  }
  function setMoment(value) {
    const moments = keyEvents(); if (!moments.length) return;
    const index = Math.max(0, Math.min(Number(value), moments.length - 1)), event = moments[index];
    state.cursor = state.events.findIndex((item) => sequenceOf(item) === sequenceOf(event)); state.live = index === moments.length - 1;
    render(); selectEvent(event);
  }
  function stopPlayback() { state.playing = false; clearInterval(state.timer); state.timer = null; renderReplay(); }
  function togglePlayback() {
    if (state.playing) { stopPlayback(); return; } const moments = keyEvents(); if (!moments.length) return;
    let position = keyPosition(); if (position >= moments.length - 1) position = -1;
    state.playing = true; state.timer = setInterval(() => { position += 1; if (position >= moments.length) { stopPlayback(); return; } setMoment(position); }, Number(els.speed.value)); renderReplay();
  }
  function shortTime(value, seconds = false) { const date = new Date(value); return Number.isNaN(date.valueOf()) ? "—" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: seconds ? "2-digit" : undefined }); }
  function duration(ms) { const total = Math.max(0, Math.floor(ms / 1000)); return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`; }

  function shouldShowLive(event) {
    if (event.surface === "native_event") return false;
    if (["tool_call", "tool_result"].includes(event.surface) && ROUTINE_TOOLS.has(event.tool_name)) return false;
    return IMPORTANT.has(event.surface) || ["tool_call", "tool_result"].includes(event.surface);
  }
  function addEvents(incoming, live = false) {
    const known = new Set(state.events.map((event) => Number(event.sequence_num))), added = [];
    incoming.forEach((event) => { if (!known.has(Number(event.sequence_num))) { state.events.push(event); added.push(event); } });
    state.events.sort((a, b) => Number(a.sequence_num) - Number(b.sequence_num)); if (state.live || state.cursor < 0) state.cursor = state.events.length - 1; render();
    const latest = [...added].reverse().find(shouldShowLive); if (live && latest) selectEvent(latest);
  }
  function applyMeta(meta) {
    state.meta = meta; els.run.textContent = truncate(meta.run_id || "pending", 12); els.run.title = meta.run_id || ""; els.video.textContent = meta.video_id || "pending"; els.harness.textContent = meta.harness || "—"; els.trace.textContent = meta.trace_path || "Imported browser trace";
    els.live.className = `live-badge ${meta.complete ? "complete" : "live"}`; els.live.querySelector("b").textContent = meta.complete ? "COMPLETE" : "LIVE TAIL";
  }
  async function loadContext() {
    if (state.imported) return;
    try { const response = await fetch("/api/context", { cache: "no-store" }); if (response.ok) state.context = await response.json(); } catch (_) { /* trace still works without enrichment */ }
  }
  async function bootstrap() {
    try {
      const response = await fetch("/api/events?after=0", { cache: "no-store" }); if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json(); applyMeta(data.summary); addEvents(data.events); await loadContext(); render();
      const moments = keyEvents(), requestedValue = new URLSearchParams(window.location.search).get("moment"), requested = requestedValue === null ? null : Number(requestedValue);
      const selected = Number.isInteger(requested) && requested >= 0 ? moments[Math.min(requested, moments.length - 1)] : moments.at(-1);
      if (selected) { state.cursor = state.events.findIndex((event) => sequenceOf(event) === sequenceOf(selected)); selectEvent(selected, { quiet: true }); }
      // Completed replays are immutable. Avoid leaving an SSE request open:
      // remote IDE browsers can otherwise show a permanent loading/blank state.
      if (!staticPreview && !data.summary.complete) connectStream();
    } catch (error) { els.live.className = "live-badge error"; els.live.querySelector("b").textContent = "OFFLINE"; console.error(error); }
  }
  function connectStream() {
    if (state.imported) return; const after = state.events.at(-1)?.sequence_num || 0, source = new EventSource(`/api/stream?after=${after}`);
    source.addEventListener("reset", async (message) => { state.events = []; state.context = {}; state.cursor = -1; state.selected = null; state.live = true; applyMeta(JSON.parse(message.data)); await loadContext(); render(); });
    source.addEventListener("trace", async (message) => {
      const event = JSON.parse(message.data); addEvents([event], true);
      if (["evidence_created", "hypothesis_updated", "run_completed"].includes(event.surface)) { await loadContext(); if (state.selected) selectEvent(state.selected, { quiet: true }); }
      if (event.surface === "run_completed") { applyMeta({ ...state.meta, complete: true }); source.close(); }
    });
    source.onerror = () => { if (!state.meta.complete) { els.live.className = "live-badge error"; els.live.querySelector("b").textContent = "RECONNECTING"; } };
  }

  // Story v2: all visible moments below are assembled from recorded trace events.
  function storyType(event) { return event?.type || event?.surface || ""; }
  function rawEvent(event) { return event?.raw_event || event || {}; }
  function transaction(event) {
    const role = event.agent_role || "system", type = storyType(event);
    const detail = event.detail || {}, raw = rawEvent(event), record = evidenceRecord(event);
    const claim = claimRecord(event);
    let source = role, target = role, kind = pretty(type), color = "#4ed8e8";
    let input = "", output = "", purpose = "Exact recorded investigation event.";
    let inputLabel = "ORIGINAL INPUT / MESSAGE", outputLabel = "ORIGINAL OUTPUT / OBSERVATION";
    if (type === "CASE_OPENED") {
      source = "video"; target = "system"; kind = "CASE OPENED";
      input = detail.source?.video_path || raw.content || "Source video supplied."; output = event.summary;
      purpose = "The immutable run and video scope were registered.";
    } else if (type === "VIDEO_SAMPLED") {
      source = "video"; target = role; kind = "SOURCE SAMPLING";
      input = formatArguments(detail.sampling || {}); output = event.summary;
      purpose = "Recorded frame indices, source timestamps, and resize geometry remain attached to later evidence.";
    } else if (type === "INITIAL_OBSERVATION") {
      source = role; target = "evidence"; kind = detail.generic ? "GENERAL VISUAL OBSERVATION" : "TRAINED OBSERVATION";
      input = detail.generic ? "Sampled video frames analyzed by adapter-free base Qwen-VL." : "Sampled video frames analyzed by this specialist's trained Qwen + LoRA observer.";
      output = excerpt(detail.observation || raw.content || ""); outputLabel = "ORIGINAL AGENT OBSERVATION";
      purpose = "This is the recorded specialist output, not a dashboard-generated interpretation.";
    } else if (type === "HYPOTHESIS_CREATED") {
      source = role; target = "memory"; kind = "HYPOTHESIS REGISTERED"; color = "#f0bd68";
      input = `Observation: ${detail.hypothesis?.observation || "Not recorded"}\nQuestion: ${detail.hypothesis?.question || "Not recorded"}`;
      output = `Candidate: ${detail.hypothesis?.candidate_explanation || event.summary}\nAlternatives: ${(detail.alternatives || []).join("; ")}`;
      purpose = "A falsifiable candidate and benign alternatives were recorded before testing.";
    } else if (type === "HYPOTHESIS_UPDATED") {
      source = "evidence"; target = role; kind = "HYPOTHESIS UPDATE"; color = detail.assessment === "supported" ? "#65d5a0" : "#f0bd68";
      input = `Evidence: ${(event.evidence_ids || []).join(", ")}`; output = detail.interpretation || event.summary;
      purpose = `The evidence-linked hypothesis state changed to ${pretty(detail.assessment)}.`;
    } else if (["QUESTION_OPENED", "QUESTION_CLAIMED", "QUESTION_RESOLVED"].includes(type)) {
      source = type === "QUESTION_CLAIMED" ? "memory" : role; target = type === "QUESTION_CLAIMED" ? role : "memory";
      kind = pretty(type); input = detail.question?.question || event.summary;
      output = `${detail.question?.question_id || "Question"} · ${pretty(detail.question?.status || "open")}${detail.question?.result_summary ? `\n${detail.question.result_summary}` : ""}`;
      purpose = "The shared case board coordinates complementary work and prevents duplicate claims.";
    } else if (type === "PEER_REVIEW_REQUESTED") {
      source = role; target = event.target_role; kind = "PEER REVIEW"; color = "#ef738c";
      input = `${detail.review?.hypothesis_id || "Hypothesis"}: ${detail.review?.question || event.summary}`;
      output = `Review requested from ${agentInfo(event.target_role).name}.`;
      purpose = "Another investigator was asked to challenge the current explanation.";
    } else if (type === "EXPERT_CONSULTATION") {
      source = role; target = event.target_role || "evidence"; kind = "TRAINED LORA CONSULT";
      input = `Optional specialty: ${detail.model?.specialty || "recorded specialist"}`;
      output = excerpt(detail.observation || event.summary); purpose = "A preserved specialty LoRA was used as a tool, not as the generic investigator identity.";
    } else if (type === "TOOL_DECISION") {
      source = role; target = `tool:${event.tool_name}`; kind = "PRE-TOOL DECISION"; color = "#f0bd68";
      input = `Observation: ${detail.observation || "Not recorded"}\nSuspicion: ${detail.suspicion || "Not recorded"}`;
      output = `Selected ${pretty(event.tool_name)}.\nWhy: ${detail.why || "Not recorded"}\nExpected: ${detail.expected_information || "Not recorded"}`;
      outputLabel = "RECORDED INVESTIGATOR DECISION"; purpose = "This rationale was committed before the tool request.";
    } else if (type === "TOOL_EXECUTION") {
      const audioTool = TOOLDF_AUDIO_TOOLS.has(event.tool_name), verificationTool = AUDIO_VERIFICATION_TOOLS.has(event.tool_name);
      source = role; target = `tool:${event.tool_name}`; kind = audioTool || verificationTool ? "AUDIO TOOL REQUEST" : "ACTUAL TOOL REQUEST";
      input = `${pretty(event.tool_name)}\n${formatArguments(detail.input || raw.tool_args || {})}`;
      output = detail.rationale_available ? `Authorized by decision ${event.decision_id}.` : (detail.missing_rationale || "Pre-call rationale unavailable.");
      purpose = "The request traveled from the investigator through MCP authorization to the named instrument.";
    } else if (type === "EVIDENCE_RETURNED") {
      const audioTool = TOOLDF_AUDIO_TOOLS.has(event.tool_name), verificationTool = AUDIO_VERIFICATION_TOOLS.has(event.tool_name);
      source = `tool:${event.tool_name}`; target = role; kind = audioTool || verificationTool ? "AUDIO TOOL RESPONSE" : "ACTUAL TOOL RESPONSE"; color = "#6aa7ff";
      input = `${pretty(event.tool_name)} · ${event.tool_call_id || "legacy call link unavailable"}`;
      output = typeof detail.output === "string" ? detail.output : (evidenceText(record) || JSON.stringify(detail.output || {}));
      outputLabel = "INSTRUMENT'S MEASURED RESPONSE";
      purpose = detail.missing_rationale || (audioTool ? "The real internal ToolDF tool returned evidence to the audio investigator." : "Measured evidence returned through MCP to the requesting investigator.");
    } else if (["EVIDENCE_INTERPRETED", "HYPOTHESIS_REJECTED"].includes(type)) {
      source = role; target = "evidence"; kind = type === "HYPOTHESIS_REJECTED" ? "HYPOTHESIS REJECTED" : "INVESTIGATOR INTERPRETATION";
      color = type === "HYPOTHESIS_REJECTED" ? "#ff685f" : "#65d5a0";
      input = `${pretty(detail.assessment)} · ${(event.evidence_ids || []).join(", ")}`;
      output = detail.interpretation || event.summary; outputLabel = "AGENT'S RECORDED INTERPRETATION";
      purpose = detail.reason_for_next_action || detail.next_action || "The measurement was interpreted before another diagnostic could be called.";
    } else if (type === "NEXT_ACTION_PLANNED") {
      source = role; target = detail.next_action_type === "stop_investigation" ? "memory" : "instrument"; kind = "NEXT ACTION PLANNED"; color = "#f0bd68";
      input = detail.reason_for_next_action || "No separate reason was recorded.";
      output = detail.next_action || "Not recorded"; outputLabel = "RECORDED PLAN — NOT YET EXECUTED";
      purpose = detail.next_tool ? `Planned instrument: ${pretty(detail.next_tool)}.` : `Action type: ${pretty(detail.next_action_type || "unrecorded")}.`;
    } else if (type === "NEXT_ACTION_EXECUTED") {
      source = role; target = detail.actual_tool ? `tool:${detail.actual_tool}` : "instrument"; kind = "NEXT ACTION ACTUALLY STARTED"; color = "#4ed8e8";
      input = detail.planned_action || "Earlier plan was not recorded.";
      output = `${pretty(detail.actual_tool)} via decision ${detail.actual_decision_id || "unavailable"}.`;
      outputLabel = "ACTUAL SUBSEQUENT ACTION";
      purpose = detail.matches_plan === true ? "The actual action matches the recorded plan." : detail.matches_plan === false ? "The investigator changed its plan; both values are preserved." : "Plan matching was not recorded.";
    } else if (["MEMORY_UPDATED", "MEMORY_SHARED"].includes(type)) {
      source = role; target = type === "MEMORY_SHARED" && event.target_role ? event.target_role : "memory"; kind = type === "MEMORY_SHARED" ? "FINDING SHARED" : "NOTEBOOK WRITE";
      input = detail.memory?.content || raw.content || event.summary;
      output = `Stored as ${event.memory_entry_id || detail.memory?.entry_id || "a scoped entry"}.`;
      purpose = type === "MEMORY_SHARED" ? "The owner explicitly authorized cross-agent reading." : "This note stays private until explicitly shared.";
    } else if (type === "MEMORY_READ") {
      source = "memory"; target = role; kind = "NOTEBOOK READ"; color = "#6aa7ff";
      input = `Authorized scope: ${detail.memory?.owner_agent || "shared"}`; output = event.summary;
      purpose = "The backend memory policy—not viewer filters—controls agent access.";
    } else if (type === "SPECIALIST_REPORT_SENT") {
      source = role; target = "evidence"; kind = "EVIDENCE CLAIM REGISTERED"; color = "#65d5a0";
      input = `Evidence: ${(claim?.supporting_evidence_ids || event.evidence_ids || []).join(", ")}`;
      output = excerpt(detail.interpretation || claim?.interpretation || claim?.claim || event.summary);
      outputLabel = "REGISTERED CLAIM"; purpose = "The claim entered the evidence store; only the experimental augmented judge reads that store.";
    } else if (type === "JUDGE_REINSPECTION_REQUEST") {
      source = "judge_coordinator"; target = event.target_role || role; kind = "JUDGE CALLBACK"; color = "#ef738c";
      input = excerpt(detail.request_reason || raw.content || "More evidence requested.");
      output = `${pretty(detail.requested_tool || event.tool_name)} on frames ${(detail.requested_frames || []).join(", ")}.`;
      purpose = "The judge sent one concrete unresolved question back to a specialist.";
    } else if (type === "REINSPECTION_RESULT") {
      source = role; target = "judge_coordinator"; kind = "REINSPECTION RETURN"; color = "#65d5a0";
      input = `Request ${event.reinspection_request_id || ""}`; output = `Returned evidence: ${(event.evidence_ids || detail.response?.evidence_ids || []).join(", ")}.`;
      purpose = "The requested measured result returned to adjudication.";
    } else if (["ORIGINAL_JUDGE_VERDICT", "AUGMENTED_JUDGE_VERDICT"].includes(type)) {
      source = "judge_coordinator"; target = "verdict"; color = "#ef738c";
      const original = type === "ORIGINAL_JUDGE_VERDICT"; kind = original ? "ORIGINAL VERDICT" : "AUGMENTED VERDICT";
      input = original ? judgeInput() : `${judgeInput()}\nPlus verified diagnostics and specialist reports.`;
      output = excerpt(detail.explanation || raw.content || "");
      outputLabel = `${original ? "JUDGE" : "EXPERIMENTAL"} RESPONSE · ${String(detail.answer ?? "unknown").toUpperCase()}`;
      purpose = original ? "The trained control judge used the original four observations." : "The evidence-aware experimental judgment is kept separate from the control.";
    } else if (type === "CASE_COMPLETED") {
      source = "judge_coordinator"; target = "verdict"; kind = "CASE COMPLETED"; color = "#6aa7ff";
      input = "Original and optional augmented judgments finalized."; output = event.summary; purpose = "The auditable run was closed.";
    } else if (type === "AUDIO_RECEIVED") {
      source = "audio"; target = "audio_investigator"; kind = "AUDIO RECEIVED";
      input = event.detail?.audio?.source_name || "Authorized source media"; output = event.summary;
      purpose = "A run-scoped audio reference entered the investigation without exposing agent-controlled paths.";
    } else if (type === "AUDIO_PREPARED") {
      source = "audio"; target = audioToolSource(); kind = "AUDIO PREPARED";
      input = `${event.detail?.audio?.duration_seconds || "?"}s source track`; output = event.summary;
      purpose = "The original timing and media hashes were recorded before model inference.";
    } else if (type === "AUDIO_SCENE_ANALYZED") {
      source = audioToolSource(); target = "audio_investigator"; kind = "SCENE UNDERSTANDING";
      input = "Prepared source waveform"; output = event.summary; purpose = "This is ToolDF's explicit audio-understanding summary, not hidden reasoning.";
    } else if (type === "AUDIO_TOOL_PLANNED") {
      source = audioToolSource(); target = "audio_investigator"; kind = "ADAPTIVE PLAN"; color = "#f0bd68";
      input = "Current audio scene and prior tool evidence"; output = event.summary; purpose = "The released ToolDF planner selected the next relevant component test.";
    } else if (type === "AUDIO_EVIDENCE_INTERPRETED") {
      source = "audio_investigator"; target = "audio_evidence"; kind = "AUDIO INTERPRETATION"; color = "#65d5a0";
      input = `Evidence: ${(event.evidence_ids || []).join(", ") || "linked tool result"}`; output = event.detail?.interpretation || event.summary;
      purpose = "Detector output and investigator interpretation remain separate.";
    } else if (type === "AUDIO_FINDING_PUBLISHED") {
      source = "audio_investigator"; target = "verdict"; kind = "AUDIO FINDING"; color = "#65d5a0";
      input = `Evidence: ${(event.evidence_ids || []).join(", ")}`; output = event.summary; purpose = "An evidence-linked audio finding was published to the case record.";
    } else if (type === "AUDIO_VERDICT") {
      source = "audio_investigator"; target = "verdict"; kind = "TOOLDF VERDICT"; color = "#ef738c";
      input = "ToolDF component evidence"; output = event.summary; purpose = "The released binary verdict is preserved separately from the broader assessment.";
    } else if (type === "AUDIOVISUAL_REVIEW") {
      const review = detail.review || raw.result || {};
      source = role; target = "verdict"; kind = "RULE-BASED CASE REVIEW"; color = "#f0bd68";
      input = `Original trained visual judge: ${String(review.visual_prediction ?? "unavailable").toUpperCase()}\nAudio Agent 5 assessment: ${String(review.audio_prediction ?? "unavailable").toUpperCase()}`;
      output = `${pretty(review.case_assessment)} — ${review.explanation || event.summary}`; outputLabel = `CASE ASSESSMENT · ${pretty(review.fusion_method || "rule")}`;
      purpose = "A transparent rule compares modality-level results; no scores are averaged and no fusion model exists.";
    } else if (["TOOL_FAILURE", "FALLBACK"].includes(type)) {
      source = role; target = type === "FALLBACK" ? "judge_coordinator" : role; kind = pretty(type); color = "#ff685f";
      input = detail.reason || `${pretty(event.tool_name)} · ${event.tool_call_id || ""}`;
      output = excerpt(detail.error || detail.output?.error || raw.result?.error || raw.content || event.summary);
      purpose = type === "FALLBACK" ? "The unchanged baseline took over and remains explicitly labeled." : "The failure was contained and recorded.";
    } else {
      input = formatArguments(raw.tool_args || {}); output = excerpt(event.summary || raw.content || JSON.stringify(raw.result || {}));
    }
    return { source, target, kind, color, input, output, purpose, inputLabel, outputLabel };
  }

  function describe(event) {
    const tx = transaction(event);
    return { title: event.summary || `${nodeLabel(tx.source)} → ${nodeLabel(tx.target)}`, text: truncate(tx.output || tx.purpose, 220) };
  }



  function drawWaveform() {
    const canvas = $("audio-waveform"); if (!canvas || !state.waveform) return;
    const ratio = window.devicePixelRatio || 1, width = Math.max(320, canvas.clientWidth), height = 150;
    canvas.width = width * ratio; canvas.height = height * ratio;
    const ctx = canvas.getContext("2d"); ctx.scale(ratio, ratio); ctx.clearRect(0, 0, width, height);
    const duration = Number(state.waveform.duration || 1), interval = state.audioInterval;
    if (interval) { ctx.fillStyle = "rgba(240,189,104,.17)"; ctx.fillRect(interval[0] / duration * width, 0, Math.max(2, (interval[1] - interval[0]) / duration * width), height); }
    ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--cyan").trim() || "#4ed8e8"; ctx.lineWidth = 1;
    ctx.beginPath(); const points = state.waveform.points || [];
    points.forEach((point, index) => { const x = index / Math.max(1, points.length - 1) * width; ctx.moveTo(x, height / 2 - Number(point.max || 0) * height * .44); ctx.lineTo(x, height / 2 - Number(point.min || 0) * height * .44); }); ctx.stroke();
    const continuity = (state.context.audio_evidence || []).find((item) => item.tool_name === "detect_audio_edit_boundaries");
    const boundaries = continuity?.actual_tool_response?.candidate_transition_times || [];
    ctx.strokeStyle = "#f0bd68"; ctx.lineWidth = 1;
    boundaries.forEach((item) => { const x = Number(item.time || 0) / duration * width; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke(); });
    const audio = $("evidence-audio"), position = Number(audio.currentTime || 0);
    ctx.strokeStyle = "#ef738c"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(position / duration * width, 0); ctx.lineTo(position / duration * width, height); ctx.stroke();
  }

  function drawProsody(measurement) {
    const canvas = $("prosody-plot"); if (!canvas || !measurement) return;
    const ratio = window.devicePixelRatio || 1, width = Math.max(320, canvas.clientWidth), height = 180;
    canvas.width = width * ratio; canvas.height = height * ratio;
    const ctx = canvas.getContext("2d"); ctx.scale(ratio, ratio); ctx.clearRect(0, 0, width, height);
    const contour = measurement.pitch_contour || [], energy = measurement.energy_contour || [];
    const validPitch = contour.filter((item) => Number.isFinite(Number(item.hz)));
    const times = [...contour, ...energy].map((item) => Number(item.time || 0));
    const maxTime = Math.max(1, ...times), minTime = Math.min(0, ...times);
    const maxPitch = Math.max(1, ...validPitch.map((item) => Number(item.hz)));
    ctx.strokeStyle = "#ae8dff"; ctx.lineWidth = 1.5; ctx.beginPath(); let started = false;
    validPitch.forEach((item) => { const x = (Number(item.time) - minTime) / Math.max(.001, maxTime - minTime) * width; const y = height - Number(item.hz) / maxPitch * (height - 18) - 8; if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y); }); ctx.stroke();
    const maxEnergy = Math.max(1e-8, ...energy.map((item) => Number(item.rms || 0)));
    ctx.strokeStyle = "#4ed8e8"; ctx.lineWidth = 1; ctx.beginPath(); started = false;
    energy.forEach((item) => { const x = (Number(item.time) - minTime) / Math.max(.001, maxTime - minTime) * width; const y = height - Number(item.rms || 0) / maxEnergy * (height - 18) - 8; if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y); }); ctx.stroke();
  }

  function renderVerificationWorkspace() {
    const panel = $("audio-verification-workspace"); if (!panel) return;
    const forensic = state.context.audio_mode === "forensic" || (state.context.audio_evidence || []).some((item) => item.component_type === "verification");
    panel.hidden = !forensic; if (!forensic) return;
    $("forensic-assessment").textContent = pretty(state.context.forensic_verification_assessment || "investigating");
    const records = state.context.audio_evidence || [], byTool = (name) => records.find((item) => item.tool_name === name)?.actual_tool_response;
    $("suspect-reference-audio").src = state.context.audio_available ? "/api/audio" : "";
    const references = state.context.audio_references || [];
    $("reference-audio-list").innerHTML = references.length ? references.map((item) => `<div class="reference-entry"><b>${escapeHtml(item.claimed_speaker || item.speaker_id || item.reference_id)}</b><audio controls preload="none" src="/api/reference-audio?id=${encodeURIComponent(item.reference_id)}"></audio><small>${escapeHtml(pretty(item.verification_status))} · ${escapeHtml(item.source_publisher || "publisher not recorded")} · ${escapeHtml(item.source_date || "date not recorded")}</small></div>`).join("") : "<p>No case-scoped reference was recorded.</p>";
    const speaker = byTool("compare_speaker_identity");
    $("speaker-comparison-output").textContent = speaker ? (speaker.execution_status === "success" ? `Measure: ${speaker.similarity_measure}. ${speaker.per_reference_scores.map((item) => `${item.reference}: ${item.cosine_similarity ?? item.execution_status}`).join(" · ")}. These are not identity probabilities.` : `Unavailable: ${(speaker.limitations || []).join(" ")}`) : "Speaker comparison was not executed.";
    const prosody = byTool("analyze_prosody");
    if (prosody) {
      drawProsody(prosody);
      $("prosody-output").textContent = `Pitch median ${prosody.pitch_median_hz ?? "unavailable"} Hz; pitch SD ${prosody.pitch_std_hz ?? "unavailable"} Hz; pauses ${prosody.pause_count ?? "unavailable"}; energy RMS median ${prosody.energy_rms_median ?? "unavailable"}. ${(prosody.limitations || []).join(" ")}`;
    } else $("prosody-output").textContent = "Prosody analysis was not executed.";
    const continuity = byTool("detect_audio_edit_boundaries"), boundaries = continuity?.candidate_transition_times || [];
    $("boundary-list").innerHTML = boundaries.length ? boundaries.map((item) => `<button type="button" data-boundary="${escapeHtml(item.time)}">${escapeHtml(Number(item.time).toFixed(3))}s · ΔE ${escapeHtml(item.energy_delta_db)} dB</button>`).join("") : "<p>No candidate boundary was recorded by the executed method.</p>";
    $("boundary-list").querySelectorAll("button").forEach((button) => button.addEventListener("click", () => { $("evidence-audio").currentTime = Number(button.dataset.boundary); drawWaveform(); }));
    $("continuity-output").textContent = continuity ? `${continuity.candidate_count} unresolved candidate(s). ${(continuity.limitations || []).join(" ")}` : "Boundary analysis was not executed; a candidate would not by itself prove a deepfake.";
    const transcript = byTool("compare_transcripts");
    $("suspect-transcript").textContent = transcript?.suspect_transcript || "Unavailable";
    $("reference-transcript").textContent = transcript?.reference_transcript || "Unavailable";
    $("transcript-diff").textContent = transcript ? `Token similarity ${transcript.similarity_ratio}. Differences: ${(transcript.differences || []).map((item) => `${item.operation}: “${item.suspect}” ↔ “${item.reference}”`).join(" · ") || "none"}. ${(transcript.limitations || []).join(" ")}` : "Transcript comparison was not executed.";
  }

  async function initializeAudio() {
    const enabled = Boolean(state.context.audio_enabled); document.documentElement.dataset.audio = enabled ? "enabled" : "disabled";
    const dashboardMode = state.context.dashboard_mode;
    document.documentElement.dataset.modality = dashboardMode === "combined" || dashboardMode === "audiovisual"
      ? "audiovisual" : enabled ? (state.context.video_available ? "audiovisual" : "audio") : "visual";
    $("audio-focus").hidden = !enabled; $("audio-verdict-card").hidden = !enabled;
    const workspace = $("workspace-mode");
    workspace.hidden = dashboardMode !== "combined" && dashboardMode !== "audiovisual";
    $("case-verdict-card").hidden = workspace.hidden;
    $("case-verdict").textContent = pretty(state.context.case_assessment || "unavailable");
    $("case-verdict-copy").textContent = state.context.case_assessment && state.context.case_assessment !== "unavailable"
      ? "Recorded by the case-review branch; modality predictions remain independent."
      : "No cross-modal case review was recorded; no unified decision was invented.";
    if (!enabled) return;
    if (!state.context.video_available) $("media-focus").hidden = true;
    // Audio phase names only when audio is the whole case; combined cases keep the investigation phases.
    if (!state.context.video_available) {
      const phaseLabels = ["Audio received", "Scene understanding", "Audio hypotheses", "Detector evidence", "Finding", "Audio assessment"];
      document.querySelectorAll("[data-phase]").forEach((button, index) => { const label = button.querySelector("span"); if (label) label.textContent = phaseLabels[index]; });
    }
    const metadata = state.context.audio_metadata || {};
    $("audio-node-copy").textContent = `${numeric(Number(metadata.duration_seconds || 0), 2)}s · ${metadata.sample_rate || "?"} Hz · ${metadata.channels || "?"} ch`;
    $("nyquist-label").textContent = `${Math.round(Number(metadata.sample_rate || 0) / 2).toLocaleString()} Hz`;
    $("audio-verdict").textContent = String(state.context.tooldf_original_prediction || "Pending").toUpperCase();
    $("audio-verdict-copy").textContent = `Broader assessment: ${pretty(state.context.audio_investigation_assessment || "pending")}. Scores are P(real).`;
    const audio = $("evidence-audio");
    if (!audio.getAttribute("src") && state.context.audio_available) audio.src = "/api/audio";
    $("audio-media-status").textContent = state.context.audio_available
      ? "Waveform is computed from the saved source signal. The highlight is the exact detector interval."
      : "Media unavailable. Recorded text, intervals, detector values, and provenance remain available.";
    if (state.context.audio_available) $("audio-spectrogram").src = "/api/audio-spectrogram";
    if (!state.waveform && !state.imported) {
      try { const response = await fetch("/api/audio-waveform", { cache: "no-store" }); if (response.ok) state.waveform = await response.json(); } catch (_) { /* panel remains explicit */ }
    }
    drawWaveform();
    renderVerificationWorkspace();
    applyWorkspaceMode(workspace.hidden ? document.documentElement.dataset.modality : workspace.value);
  }

  async function loadContext(importedContext = null) {
    if (state.imported && !importedContext) return;
    try {
      if (importedContext) state.context = importedContext;
      else {
        const response = await fetch("/api/context", { cache: "no-store" });
        if (!response.ok) return;
        const context = await response.json();
        if (state.imported) return;
        state.context = context;
      }
      state.moments = state.context.story || []; reselectAfterReload();
      $("fixture-banner").hidden = !state.context.simulation_fixture;
      $("fixture-banner").textContent = state.context.simulation_fixture ? "SIMULATION / TEST FIXTURE — NOT ACTUAL MODEL OR PROVIDER BEHAVIOR" : "";
      const execution = state.context.execution;
      const scriptedTools = state.context.agent_model?.execution_topology?.kind === "direct_demo";
      $("execution-banner").hidden = state.context.simulation_fixture || (!execution && !scriptedTools);
      const runtimeFailure = state.context.agent_model?.infrastructure?.runtime_failures?.slice(-1)[0]?.error;
      if (execution) $("execution-banner").textContent = `${execution.status === "failed" || runtimeFailure ? "MODEL INVESTIGATION FAILED" : execution.completed ? "RECORDED MODEL INVESTIGATION" : "LIVE MODEL INFERENCE"} · ${execution.backend} · ${execution.framework}${runtimeFailure ? ` · ${runtimeFailure}` : state.events.length ? " · decisions and findings below come from recorded investigator events" : " · initializing models; no investigator activity recorded yet"}`;
      else if (scriptedTools) $("execution-banner").textContent = "SCRIPTED TOOL VALIDATION · These recorded tool calls do not constitute a four-investigator/judge run. Use run_investigation.py to start an investigator case.";
      await initializeAudio();
      renderTopologyFrame();
      const policy = state.context.memory_policy || {};
      $("memory-policy-badge").textContent = `Memory: ${policy.memory_mode || (state.context.memories?.length ? "recorded" : "off")}`;
      let catalog = Object.values(state.context.tool_catalog || {});
      if (state.context.audio_enabled && !state.context.video_available && state.context.dashboard_mode !== "combined") catalog = catalog.filter((tool) => String(tool.category || "").startsWith("audio_"));
      const executedTools = new Set(state.events.map((event) => event.tool_name).filter(Boolean));
      catalog = catalog.filter((tool) => tool.category !== "openvlharness_visual" || executedTools.has(tool.name));
      const families = [...new Set(catalog.map((tool) => tool.category).filter(Boolean))];
      els.toolFilter.innerHTML = `<option value="">All instrument families</option>${families.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(pretty(name))}</option>`).join("")}`;
      $("instrument-rack").innerHTML = catalog.map((tool) => `<span class="instrument-chip" data-tool="${escapeHtml(tool.name)}" data-family="${escapeHtml(tool.category || "other")}" title="${escapeHtml(tool.purpose || "")}"><b>${escapeHtml(pretty(tool.name))}</b> · ${escapeHtml(pretty(tool.category || "other"))}</span>`).join("");
    } catch (_) { /* raw audit remains usable */ }
  }

  function referenceFor(record, sampledFrame) {
    const frames = record?.frame_indices || [], position = Math.max(0, frames.indexOf(Number(sampledFrame)));
    return { reference: record?.frame_references?.[position] || null, position };
  }
  function sourceRoi(record, position, reference) {
    const tracked = record?.summary_statistics?.tracked_boxes || [];
    const roi = tracked[position] || record?.roi; if (!roi || roi.length !== 4) return null;
    const transform = reference?.transform || record?.crop_transform || {};
    if (record.coordinate_space !== "processed_frame" || !(Number(transform.scale_x) > 0) || !(Number(transform.scale_y) > 0)) return null;
    const ox = Number(transform.offset_x || 0), oy = Number(transform.offset_y || 0);
    return [(roi[0] - ox) / transform.scale_x, (roi[1] - oy) / transform.scale_y, (roi[2] - ox) / transform.scale_x, (roi[3] - oy) / transform.scale_y];
  }
  function renderRoi(roi, dimensions = null) {
    const overlay = $("roi-overlay"), shell = overlay.parentElement, frame = $("evidence-frame");
    if (!roi || roi.length !== 4 || !dimensions?.[0] || !dimensions?.[1]) { overlay.hidden = true; return; }
    const sourceWidth = Number(dimensions[0]), sourceHeight = Number(dimensions[1]);
    const aspect = frame.naturalWidth && frame.naturalHeight ? frame.naturalWidth / frame.naturalHeight : sourceWidth / sourceHeight;
    let width = shell.clientWidth, height = width / aspect;
    if (height > shell.clientHeight) { height = shell.clientHeight; width = height * aspect; }
    const left = (shell.clientWidth - width) / 2, top = (shell.clientHeight - height) / 2;
    overlay.style.left = `${left + roi[0] / sourceWidth * width}px`; overlay.style.top = `${top + roi[1] / sourceHeight * height}px`;
    overlay.style.width = `${(roi[2] - roi[0]) / sourceWidth * width}px`; overlay.style.height = `${(roi[3] - roi[1]) / sourceHeight * height}px`;
    overlay.hidden = false;
  }
  function hideDiagnosticOverlay() {
    $("diagnostic-overlay").hidden = true;
    $("diagnostic-overlay-control").hidden = true;
  }
  function renderDiagnosticOverlay(record, position, roi) {
    hideDiagnosticOverlay();
    const dimensions = record?.input_crop_dimensions?.[position];
    const roiBox = $("roi-overlay"), overlay = $("diagnostic-overlay");
    if (!roi || !dimensions?.[0] || !dimensions?.[1] || roiBox.hidden) return;
    const key = `${record.evidence_id}:${position}`; overlay.dataset.key = key;
    overlay.onload = () => {
      if (overlay.dataset.key !== key
          || overlay.naturalWidth !== Number(dimensions[0])
          || overlay.naturalHeight !== Number(dimensions[1])
          || roiBox.hidden) return;
      for (const property of ["left", "top", "width", "height"]) {
        overlay.style[property] = roiBox.style[property];
      }
      overlay.style.opacity = $("diagnostic-overlay-opacity").value;
      overlay.hidden = false; $("diagnostic-overlay-control").hidden = false;
    };
    overlay.onerror = hideDiagnosticOverlay;
    overlay.src = `/api/artifact?id=${encodeURIComponent(record.evidence_id)}&overlay=1`;
  }
  function showEvidenceSample(record, sampledFrame, selectedButton = null) {
    const frame = $("evidence-frame"), crop = $("crop-image"), cropPlaceholder = $("crop-placeholder");
    const { reference, position } = referenceFor(record, sampledFrame);
    const exact = Boolean(reference && (reference.source_frame_index !== undefined || reference.timestamp_exact));
    const timestamp = reference?.timestamp;
    document.querySelectorAll("#frame-chips button").forEach((button) => button.classList.toggle("active", button === selectedButton));
    $("media-time").textContent = exact ? `sample f${sampledFrame} · source frame ${reference.source_frame_index ?? "—"} · ${numeric(Number(timestamp || 0), 3)}s` : `sample f${sampledFrame} · exact source mapping unavailable`;
    $("mapping-status").textContent = exact ? "exact recorded mapping" : "legacy mapping withheld";
    if (exact && state.context.video_available) {
      frame.hidden = false; frame.src = `/api/frame?id=${encodeURIComponent(record.evidence_id)}&sample=${encodeURIComponent(sampledFrame)}`;
      frame.onload = () => {
        renderRoi(sourceRoi(record, position, reference), reference.source_dimensions || record.source_dimensions);
        renderDiagnosticOverlay(record, position, sourceRoi(record, position, reference));
      };
      frame.onerror = () => { frame.hidden = true; renderRoi(null); hideDiagnosticOverlay(); };
    } else { frame.hidden = true; frame.removeAttribute("src"); renderRoi(null); hideDiagnosticOverlay(); }
    const roi = sourceRoi(record, position, reference);
    const storedInput = Boolean(record?.input_crop_refs?.[position]);
    const inputDimensions = record?.input_crop_dimensions?.[position];
    const roiLabel = roi ? `source ROI [${roi.map((value) => Math.round(value)).join(", ")}]` : "source ROI unavailable";
    $("crop-kind-label").textContent = storedInput
      ? (roi ? "EXACT CROP USED BY TOOL" : "EXACT PROCESSED FRAME USED BY TOOL")
      : "RECONSTRUCTED SOURCE CROP";
    $("crop-coordinate-label").textContent = storedInput
      ? `${inputDimensions?.[0] || "?"}×${inputDimensions?.[1] || "?"} processed pixels · ${roiLabel}`
      : `${roiLabel} · legacy record`;
    const sourceVideo = $("evidence-video");
    if (exact && Number.isFinite(Number(timestamp)) && sourceVideo.getAttribute("src")) {
      sourceVideo.pause(); sourceVideo.currentTime = Number(timestamp);
    }
    if (storedInput) {
      crop.hidden = false; cropPlaceholder.hidden = true;
      crop.src = `/api/input-crop?id=${encodeURIComponent(record.evidence_id)}&sample=${encodeURIComponent(sampledFrame)}`;
      crop.onerror = () => {
        if (exact && roi) {
          $("crop-kind-label").textContent = "RECONSTRUCTED SOURCE CROP";
          $("crop-coordinate-label").textContent = `${roiLabel} · persisted input missing`;
          crop.src = `/api/crop?id=${encodeURIComponent(record.evidence_id)}&sample=${encodeURIComponent(sampledFrame)}`;
          crop.onerror = () => { crop.hidden = true; cropPlaceholder.hidden = false; };
        } else { crop.hidden = true; cropPlaceholder.hidden = false; }
      };
    } else if (exact && roi) {
      crop.hidden = false; cropPlaceholder.hidden = true;
      crop.src = `/api/crop?id=${encodeURIComponent(record.evidence_id)}&sample=${encodeURIComponent(sampledFrame)}`;
      crop.onerror = () => { crop.hidden = true; cropPlaceholder.hidden = false; };
    } else { crop.hidden = true; crop.removeAttribute("src"); cropPlaceholder.hidden = false; }
  }
  function renderAudio(event) {
    if (!state.context.audio_enabled) return;
    const selectedOperation = (state.context.observability || []).find((item) => item.operation_id === state.selectedOperation);
    const record = evidenceRecord(event) || selectedOperation?.evidence || null;
    const audioRecord = record && String(record.evidence_id || "").startsWith("audio_ev_") ? record : null;
    const metadata = state.context.audio_metadata || {}, audio = $("evidence-audio");
    const start = Number(audioRecord?.start_time ?? event?.raw_event?.metadata?.start_time ?? 0);
    const end = Number(audioRecord?.end_time ?? event?.raw_event?.metadata?.end_time ?? start);
    state.audioInterval = end > start ? [start, end] : null;
    $("audio-focus-title").textContent = audioRecord ? `${pretty(audioRecord.tool_name)} · ${audioRecord.evidence_id}` : (event?.summary || "Audio investigation overview");
    $("audio-interval").textContent = state.audioInterval ? `${numeric(start, 3)}–${numeric(end, 3)}s · ${pretty(audioRecord?.component_type || "audio")}` : "No detector interval selected";
    $("audio-result-status").textContent = audioRecord ? pretty(audioRecord.status || "recorded") : "—";
    const verification = audioRecord?.component_type === "verification";
    $("audio-result-heading").textContent = verification ? "ACTUAL VERIFICATION MEASUREMENT" : "ACTUAL DETECTOR RESULT";
    const facts = audioRecord ? (verification ? [
      ["Tool", pretty(audioRecord.tool_name)], ["Evidence kind", "Supplementary verification"],
      ["Algorithm / model", audioRecord.model_or_algorithm || audioRecord.checkpoint_id || "Not recorded"],
      ["Execution", pretty(audioRecord.status || "recorded")],
      ["Interval", `${numeric(start, 3)}–${numeric(end, 3)}s`],
      ["Reference count", String((audioRecord.reference_audio_ids || []).length)],
      ["Units", Object.entries(audioRecord.measurement_units || {}).map(([key, value]) => `${pretty(key)}: ${value}`).join(" · ") || "Recorded in output"],
      ["Authenticity verdict", "Not produced by this tool"],
    ] : [
      ["Tool", pretty(audioRecord.tool_name)], ["Component", pretty(audioRecord.component_type)],
      ["Variant", pretty(audioRecord.detector_variant)], ["Input", pretty(audioRecord.input_kind)],
      ["Prediction", String(audioRecord.prediction || "not applicable").toUpperCase()],
      ["Detector P(real)", audioRecord.raw_score === null || audioRecord.raw_score === undefined ? "—" : numeric(Number(audioRecord.raw_score), 6)],
      ["Decision threshold", audioRecord.threshold === null || audioRecord.threshold === undefined ? "—" : numeric(Number(audioRecord.threshold), 6)],
      ["Interval", `${numeric(start, 3)}–${numeric(end, 3)}s`],
      ["Checkpoint", audioRecord.checkpoint_id || "Not recorded"],
    ]) : [];
    $("audio-result-facts").innerHTML = facts.map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
    $("audio-result-summary").textContent = audioRecord ? evidenceText(audioRecord) : (event?.detail?.interpretation || "Select a ToolDF detector result to inspect its exact score semantics.");
    if (state.audioInterval && audio.getAttribute("src")) { audio.pause(); audio.currentTime = start; }
    const video = $("evidence-video");
    const alignmentAvailable = state.context.alignment_available !== false
      && (state.context.alignment_available === true || metadata.resampling?.offset_measured === true);
    if (state.audioInterval && state.context.video_available && alignmentAvailable) {
      if (!video.getAttribute("src")) { video.src = "/api/video"; video.controls = true; }
      video.pause(); video.currentTime = start + Number(metadata.audio_offset_seconds || 0);
    }
    const separation = (state.context.audio_evidence || []).find((item) => item.tool_name === "source_separator" && (item.artifact_refs || []).length);
    $("stem-card").hidden = !separation;
    if (separation) {
      $("vocals-audio").src = `/api/audio-stem?id=${encodeURIComponent(separation.evidence_id)}&stem=vocals`;
      $("background-audio").src = `/api/audio-stem?id=${encodeURIComponent(separation.evidence_id)}&stem=background`;
    }
    drawWaveform();
  }
  function renderMedia(event) {
    const record = evidenceRecord(event), placeholder = $("video-placeholder"), video = $("evidence-video");
    const audioRecord = record && String(record.evidence_id || "").startsWith("audio_ev_");
    if (state.context.video_available && !video.getAttribute("src")) { video.src = "/api/video"; video.controls = true; }
    placeholder.hidden = Boolean((record || state.context.audio_enabled) && state.context.video_available);
    $("media-title").textContent = record ? `${pretty(record.tool_name)} · ${record.evidence_id}` : "No evidence linked to this moment";
    const frames = audioRecord ? [] : (record?.frame_indices || []);
    $("frame-chips").replaceChildren(...frames.slice(0, 16).map((sampled, position) => {
      const ref = record.frame_references?.[position], button = document.createElement("button");
      button.textContent = ref ? `f${sampled} · src ${ref.source_frame_index ?? "?"}` : `f${sampled} · unmapped`;
      button.dataset.frame = sampled; button.addEventListener("click", () => showEvidenceSample(record, sampled, button)); return button;
    }));
    if (record && frames.length) showEvidenceSample(record, frames[0], document.querySelector("#frame-chips button"));
    else { $("evidence-frame").hidden = true; $("crop-image").hidden = true; $("crop-placeholder").hidden = false; $("mapping-status").textContent = "—"; renderRoi(null); hideDiagnosticOverlay(); }
    const compare = $("diagnostic-compare");
    if (record && !audioRecord) {
      compare.hidden = false; $("diagnostic-tool-label").textContent = pretty(record.tool_name);
      $("diagnostic-image").src = `/api/artifact?id=${encodeURIComponent(record.evidence_id)}&t=${Date.now()}`;
      $("diagnostic-caption").textContent = excerpt(evidenceText(record), 240);
    } else compare.hidden = true;
    const reference = $("reference-media");
    if (record?.reference_source && (record.reference_frame_indices || []).length) {
      const refIndex = record.reference_frame_indices[0]; reference.hidden = false;
      $("reference-frame").src = `/api/reference-frame?id=${encodeURIComponent(record.evidence_id)}&sample=${encodeURIComponent(refIndex)}`;
      const confidence = record.matching_scores?.[0] ?? record.summary_statistics?.alignment_confidence;
      $("reference-confidence").textContent = confidence === undefined ? "recorded reference" : `alignment ${numeric(Number(confidence))}`;
      $("reference-caption").textContent = `${record.reference_source} · reference sample ${refIndex}. Similarity is retrieval evidence, not manipulation proof.`;
    } else reference.hidden = true;
    const detail = event?.detail || {};
    $("assessment-label").textContent = detail.assessment ? pretty(detail.assessment) : "not recorded for this step";
    $("media-finding").textContent = detail.interpretation || (record ? "Select the later interpretation moment to see the investigator's conclusion." : "Select an evidence-linked moment.");
    const stats = Object.entries(record?.summary_statistics || {}).filter(([, value]) => ["number", "boolean", "string"].includes(typeof value)).slice(0, 8);
    $("media-stats").innerHTML = stats.map(([key, value]) => {
      const display = typeof value === "string" ? excerpt(value.replace(/\s+/g, " ").trim(), 240) : numeric(value);
      return `<div><dt>${escapeHtml(pretty(key))}</dt><dd>${escapeHtml(display)}</dd></div>`;
    }).join("");
    renderAudio(event);
  }


  function eventMatches(event, raw = false) {
    const type = storyType(event);
    const timelineFilter = $("timeline-filter").value;
    const modality = modalityOf(event);
    if (timelineFilter === "visual" && !["video", "image"].includes(modality)) return false;
    if (timelineFilter === "audio" && modality !== "audio") return false;
    if (timelineFilter === "tools" && !["TOOL_DECISION", "TOOL_EXECUTION", "EVIDENCE_RETURNED", "TOOL_FAILURE", "AUDIO_TOOL_PLANNED"].includes(type)) return false;
    if (timelineFilter === "evidence" && !["EVIDENCE_RETURNED", "EVIDENCE_INTERPRETED", "AUDIO_EVIDENCE_RECORDED", "AUDIO_EVIDENCE_INTERPRETED", "AUDIO_FINDING_PUBLISHED"].includes(type)) return false;
    if (timelineFilter === "hypotheses" && !["HYPOTHESIS_CREATED", "HYPOTHESIS_UPDATED", "HYPOTHESIS_REJECTED", "AUDIO_HYPOTHESIS_CREATED", "AUDIO_HYPOTHESIS_UPDATED"].includes(type)) return false;
    if (timelineFilter === "errors" && !["TOOL_FAILURE", "FALLBACK"].includes(type) && event.status !== "error") return false;
    const role = els.agentFilter.value || state.activeAgent;
    if (role && !eventInvolvesAgent(event, role)) return false;
    if (els.errorsOnly.checked && !["TOOL_FAILURE", "FALLBACK"].includes(type) && event.status !== "error") return false;
    if (!raw && els.toolFilter.value) {
      const category = state.context.tool_catalog?.[event.tool_name]?.category || "";
      if (category !== els.toolFilter.value) return false;
    }
    if (!raw && type === "MEMORY_READ" && !$("show-memory-reads").checked) return false;
    if (!raw && ["MEMORY_UPDATED", "MEMORY_SHARED"].includes(type) && !$("show-memory-writes").checked) return false;
    const query = els.search.value.trim().toLowerCase();
    return !query || JSON.stringify(event).toLowerCase().includes(query) || Object.values(describe(event)).join(" ").toLowerCase().includes(query);
  }
  function visibleEvents(raw = false) {
    const maxSequence = cursorSequence();
    const source = raw ? state.events : keyEvents();
    return source.filter((event) => sequenceOf(event) <= maxSequence && eventMatches(event, raw));
  }
  function timelineItem(event, raw = false) {
    const type = storyType(event), info = agentInfo(event.agent_role), copy = raw ? { title: pretty(event.surface), text: truncate(event.content || JSON.stringify(event.result || {}), 220) } : describe(event);
    const tx = raw ? { source: event.agent_role, target: event.target_role || event.agent_role, input: formatArguments(event.tool_args || {}), output: excerpt(event.content || JSON.stringify(event.result || {}), 300) } : transaction(event);
    const item = document.createElement("li");
    const stateClass = type === "HYPOTHESIS_REJECTED" ? " rejected" : ["TOOL_FAILURE", "FALLBACK"].includes(type) ? " failure" : type.startsWith("MEMORY_") ? " memory" : "";
    item.className = `timeline-item ${type.toLowerCase()}${stateClass}${state.selected?.moment_id === event.moment_id || (!state.selected?.moment_id && state.selected?.sequence_num === event.sequence_num) ? " selected" : ""}`;
    item.dataset.sequence = sequenceOf(event); if (event.moment_id) item.dataset.moment = event.moment_id;
    const marker = document.createElement("span"); marker.className = `timeline-marker ${event.agent_role}${event.status === "error" ? " error" : ""}`;
    marker.textContent = raw ? `#${sequenceOf(event)}` : (ICONS[type] || info.short);
    const card = document.createElement("div"); card.className = "timeline-card";
    const detailed = !raw && els.displayMode.value === "detailed";
    card.innerHTML = `<div class="timeline-meta"><span>${escapeHtml(raw ? pretty(event.surface) : `${nodeLabel(tx.source)} → ${nodeLabel(tx.target)}`)}</span><time>${shortTime(event.timestamp)}</time></div><h3>${escapeHtml(copy.title)}</h3><p>${escapeHtml(copy.text)}</p>${detailed || raw ? `<div class="timeline-exchange"><span><b>IN</b>${escapeHtml(truncate(tx.input, 240))}</span><span><b>OUT</b>${escapeHtml(truncate(tx.output, 280))}</span></div>` : ""}`;
    item.append(marker, card); item.addEventListener("click", () => pinEvent(event)); return item;
  }
  function renderMemory() {
    if (state.view !== "memory") return;
    const maxTime = Date.parse(state.selected?.timestamp || new Date().toISOString()), maxSequence = sequenceOf(state.selected) || sequenceOf(state.events.at(-1)), owner = $("memory-agent").value;
    const memoryMoments = state.moments.filter((moment) => ["MEMORY_UPDATED", "MEMORY_SHARED"].includes(moment.type));
    const visibleIds = new Set(memoryMoments.filter((moment) => Number(moment.sequence_num) <= maxSequence).map((moment) => moment.memory_entry_id).filter(Boolean));
    const historical = new Map();
    memoryMoments.filter((moment) => Number(moment.sequence_num) <= maxSequence).forEach((moment) => {
      const payload = moment.detail?.memory || {}, id = moment.memory_entry_id || payload.memory_id;
      if (id) historical.set(id, { ...payload, memory_id: id });
    });
    const memorySource = historical.size ? [...historical.values()] : (state.context.memories || []);
    const entries = memorySource.filter((entry) => {
      const visibleAtCursor = memoryMoments.length ? visibleIds.has(entry.memory_id) : Date.parse(entry.created_at || 0) <= maxTime;
      if (!visibleAtCursor || (owner && logicalOf(entry.owner_agent, entry.run_id) !== owner)) return false;
      return entry.visibility === "shared" ? $("show-shared-memory").checked : $("show-own-memory").checked;
    });
    $("memory-list").innerHTML = entries.map((entry) => `<article class="memory-entry ${escapeHtml(entry.visibility)}" data-memory="${escapeHtml(entry.memory_id)}"><header><span>${escapeHtml(pretty(entry.status))}</span><em>${escapeHtml(entry.memory_id)}</em></header><h3>${escapeHtml(entry.summary)}</h3><p>${escapeHtml(entry.details)}</p><div class="chips"><span>${escapeHtml(agentInfo(entry.owner_agent).name)}</span> · <span>${escapeHtml(pretty(entry.entry_type))}</span> · <span>${escapeHtml(entry.visibility)}</span></div></article>`).join("") || `<div class="empty-state"><b>No entries visible at this replay moment</b><p>The notebook is historical: future entries are intentionally hidden.</p></div>`;
    document.querySelectorAll(".memory-entry[data-memory]").forEach((card) => card.addEventListener("click", () => {
      const moment = [...state.moments].reverse().find((item) => item.memory_entry_id === card.dataset.memory && Number(item.sequence_num) <= maxSequence);
      if (moment) { state.view = "story"; document.querySelectorAll(".view-tabs button").forEach((button) => button.classList.toggle("active", button.dataset.view === "story")); document.querySelectorAll(".view-pane").forEach((pane) => pane.classList.toggle("active", pane.id === "story-view")); selectEvent(moment); }
    }));
  }
  function openEvidence(evidenceId) {
    const moment = [...state.moments].reverse().find((item) => item.evidence_ids?.includes(evidenceId));
    if (moment) { state.view = "story"; document.querySelectorAll(".view-tabs button").forEach((button) => button.classList.toggle("active", button.dataset.view === "story")); document.querySelectorAll(".view-pane").forEach((pane) => pane.classList.toggle("active", pane.id === "story-view")); selectEvent(moment); }
  }
  function renderHypotheses() {
    if (state.view !== "hypotheses") return;
    const maxSequence = replaySequence();
    const created = state.moments.filter((item) => item.type === "HYPOTHESIS_CREATED" && Number(item.sequence_num) <= maxSequence);
    const updated = state.moments.filter((item) => item.type === "HYPOTHESIS_UPDATED" && Number(item.sequence_num) <= maxSequence);
    const hypotheses = created.length ? created.map((moment) => {
      const initial = moment.detail?.hypothesis || {}, id = initial.hypothesis_id;
      const latest = [...updated].reverse().find((item) => item.detail?.hypothesis?.hypothesis_id === id);
      return latest?.detail?.hypothesis || initial;
    }) : (state.context.hypotheses || []);
    const questions = state.context.questions || [], reviews = state.context.peer_reviews || [];
    const hypothesisCards = hypotheses.map((item) => {
      const support = item.supporting_evidence_ids || [], contradict = item.contradicting_evidence_ids || [];
      const updates = item.updates || [], latest = updates.at(-1);
      return `<article class="hypothesis-card"><header><b>${escapeHtml(item.hypothesis_id)} · ${escapeHtml(agentInfo(item.owner_agent).name)}</b><span class="${escapeHtml(item.status)}">${escapeHtml(pretty(item.status))}</span></header><h3>${escapeHtml(item.question)}</h3><p>${escapeHtml(item.observation)}</p><dl><div><dt>Candidate explanation</dt><dd>${escapeHtml(item.candidate_explanation)}</dd></div><div><dt>Competing explanations</dt><dd>${escapeHtml((item.alternative_explanations || []).join(" · "))}</dd></div><div><dt>Latest evidence interpretation</dt><dd>${escapeHtml(latest?.interpretation || "Not tested yet")}</dd></div><div><dt>Next action</dt><dd>${escapeHtml(item.next_test || "Stop / none recorded")}</dd></div></dl><div class="evidence-links">${[...support, ...contradict].map((id) => `<button data-evidence="${escapeHtml(id)}">${escapeHtml(id)}${contradict.includes(id) ? " · contradicts" : " · supports"}</button>`).join("") || "<span>No evidence linked yet</span>"}</div></article>`;
    }).join("");
    const questionCards = questions.map((item) => `<article class="question-card"><header><b>${escapeHtml(item.question_id)} · case question</b><span>${escapeHtml(pretty(item.status))}</span></header><h3>${escapeHtml(item.question)}</h3><p>${escapeHtml(item.owner_agent ? `Claimed by ${agentInfo(item.owner_agent).name}` : "Unclaimed")} ${escapeHtml(item.result_summary || "")}</p></article>`).join("");
    const reviewCards = reviews.map((item) => `<article class="question-card peer-review-card"><header><b>${escapeHtml(item.review_id)} · peer review</b><span>${escapeHtml(pretty(item.status))}</span></header><h3>${escapeHtml(item.question)}</h3><p>${escapeHtml(`${agentInfo(item.requested_by).name} → ${agentInfo(item.target_agent).name}`)}</p><p>${escapeHtml(item.response || "Awaiting independent review")}</p><div class="evidence-links">${(item.evidence_ids || []).map((id) => `<button data-evidence="${escapeHtml(id)}">${escapeHtml(id)}</button>`).join("")}</div></article>`).join("");
    $("hypothesis-board").innerHTML = hypothesisCards + questionCards + reviewCards || `<div class="empty-state"><b>No hypotheses recorded yet</b><p>The board populates from explicit backend registry events, never inferred UI labels.</p></div>`;
    document.querySelectorAll("#hypothesis-board [data-evidence]").forEach((button) => button.addEventListener("click", () => openEvidence(button.dataset.evidence)));
  }
  function renderSources() {
    if (state.view !== "sources") return;
    const records = (state.context.evidence || []).filter((item) => item.reference_source);
    $("source-board").innerHTML = records.map((record) => {
      const suspect = record.frame_indices?.[0] ?? 0, reference = record.reference_frame_indices?.[0] ?? 0;
      const score = record.matching_scores?.[0] ?? record.summary_statistics?.alignment_confidence;
      return `<article class="source-card" data-evidence="${escapeHtml(record.evidence_id)}"><header><b>${escapeHtml(pretty(record.tool_name))}</b><span>${score === undefined ? "alignment recorded" : `confidence ${escapeHtml(numeric(Number(score)))}`}</span></header><div class="source-pair"><div><p>Suspect sample f${escapeHtml(suspect)}</p><img src="/api/frame?id=${encodeURIComponent(record.evidence_id)}&sample=${encodeURIComponent(suspect)}" alt="Suspect frame"></div><div><p>Reference sample ${escapeHtml(reference)}</p><img src="/api/reference-frame?id=${encodeURIComponent(record.evidence_id)}&sample=${encodeURIComponent(reference)}" alt="Reference frame"></div></div><h3>${escapeHtml(record.reference_source)}</h3><p>${escapeHtml(evidenceText(record))}</p><div class="evidence-links"><button data-evidence="${escapeHtml(record.evidence_id)}">Open ${escapeHtml(record.evidence_id)} in story</button></div></article>`;
    }).join("") || `<div class="empty-state"><b>No authorized reference comparison</b><p>${escapeHtml(pretty(state.context.source_footage_status || "Reference source unavailable"))}. Internal visual analysis can continue without inventing a source.</p></div>`;
    document.querySelectorAll("#source-board [data-evidence]").forEach((button) => button.addEventListener("click", () => openEvidence(button.dataset.evidence)));
  }

  function replaySequence() {
    return sequenceOf(state.selected) || sequenceOf(state.events.at(-1));
  }
  function operationSnapshot(operation, maxSequence = replaySequence()) {
    const stage = operation.stage_sequences || {};
    const first = Math.min(...Object.values(stage).map(Number).filter(Number.isFinite));
    if (Number.isFinite(first) && first > maxSequence) return null;
    const value = structuredClone(operation);
    if (Number(stage.call || Infinity) > maxSequence) {
      value.tool_input = {}; value.tool_call_id = ""; value.execution_state = "planned";
    }
    if (Number(stage.result || Infinity) > maxSequence) {
      value.tool_output_original = null; value.tool_output_summary = ""; value.evidence_ids = []; value.evidence = null;
      value.execution_state = value.tool_call_id ? "running" : "planned";
    }
    if (Number(stage.interpretation || Infinity) > maxSequence) {
      value.interpretation_id = ""; value.agent_interpretation = ""; value.assessment = ""; value.interpretation_limitations = [];
      value.next_action_id = ""; value.next_planned_action = ""; value.next_action_type = ""; value.next_tool = ""; value.reason_for_next_action = ""; value.next_action_status = "not_recorded";
    }
    if (stage.plan !== undefined && Number(stage.plan) > maxSequence) {
      value.next_action_id = ""; value.next_planned_action = ""; value.next_action_type = ""; value.next_tool = ""; value.reason_for_next_action = ""; value.next_action_status = "not_recorded";
    }
    if (stage.next_actual !== undefined && Number(stage.next_actual) > maxSequence) value.next_actual_action = null;
    if (stage.hypothesis_update !== undefined && Number(stage.hypothesis_update) > maxSequence) value.hypothesis_update = null;
    if (stage.memory !== undefined && Number(stage.memory) > maxSequence) value.memory_updates = [];
    return value;
  }
  function operationForEvent(event) {
    const id = evidenceId(event), raw = rawEvent(event);
    return (state.context.observability || []).find((operation) =>
      (event.decision_id && operation.decision_id === event.decision_id)
      || (event.tool_call_id && operation.tool_call_id === event.tool_call_id)
      || (raw.next_action_id && operation.next_action_id === raw.next_action_id)
      || (id && (operation.evidence_ids || []).includes(id))
    ) || null;
  }
  function inputSummary(operation) {
    const args = operation.tool_input || {};
    if (args.start !== undefined || args.end !== undefined || String(operation.tool_family || "").startsWith("audio_")) {
      const start = Number(args.start ?? operation.evidence?.start_time ?? 0), end = Number(args.end ?? operation.evidence?.end_time ?? 0);
      return `audio ${numeric(start, 3)}–${numeric(end, 3)}s · ${pretty(operation.evidence?.input_kind || "original_audio")}`;
    }
    const frames = args.frame_indices || operation.selected_frames || [];
    const interval = args.start_frame !== undefined ? `samples ${args.start_frame}–${args.end_frame}` : frames.length ? `samples ${frames.join(", ")}` : args.frame_index !== undefined ? `sample ${args.frame_index}` : "video input";
    const roi = args.roi || operation.selected_roi;
    return `${interval}${roi ? ` · ROI [${roi.join(", ")}]` : " · full frame"}`;
  }
  function actualActionLabel(operation) {
    const actual = operation?.next_actual_action;
    if (!actual) return "Not executed / not recorded";
    if (actual.tool_name) return pretty(actual.tool_name);
    if (actual.action_type === "stop_investigation") return "Investigation stopped";
    return actual.action || pretty(actual.action_type || actual.status || "Recorded action");
  }
  function renderOperationDetail(operation) {
    const detail = $("operation-detail");
    if (!operation) { detail.hidden = true; detail.innerHTML = ""; return; }
    detail.hidden = false;
    const evidence = operation.evidence || {};
    const exactFrames = String(evidence.evidence_id || "").startsWith("audio_ev_")
      ? `Exact source interval ${evidence.start_time}–${evidence.end_time}s`
      : ((evidence.frame_references || []).map((item) => `sample ${item.sampled_frame_index} → source ${item.source_frame_index ?? "?"} @ ${item.timestamp ?? "?"}s`).join("; ") || "Exact source mapping not recorded");
    detail.innerHTML = `<div class="operation-detail-grid">
      <article><small>OBSERVATION / QUESTION</small><p>${escapeHtml(operation.observation || "Not recorded")}\n${escapeHtml(operation.investigative_question || "")}</p></article>
      <article><small>HYPOTHESIS</small><p>${escapeHtml(operation.hypothesis || "Not recorded")}\n${escapeHtml(operation.hypothesis_id || "")}</p></article>
      <article><small>WHY THIS TOOL</small><p>${escapeHtml(operation.reason_for_tool_choice || "Tool executed; pre-call rationale not recorded.")}\nExpected: ${escapeHtml(operation.expected_information || "Not recorded")}</p></article>
      <article><small>EXACT MEDIA SCOPE</small><p>${escapeHtml(inputSummary(operation))}\n${escapeHtml(exactFrames)}</p></article>
      <article><small>EXECUTION</small><p>${escapeHtml(pretty(operation.execution_state))}\nDecision: ${escapeHtml(operation.decision_id || "unavailable")}\nCall: ${escapeHtml(operation.tool_call_id || "unavailable")}</p></article>
      <article><small>MEASURED RESULT</small><p>${escapeHtml(operation.tool_output_summary || (operation.execution_state === "running" ? "Tool is running." : "Not available yet."))}</p></article>
      <article><small>AGENT INTERPRETATION</small><p>${escapeHtml(operation.agent_interpretation || "Not recorded")}</p></article>
      <article><small>PLAN → ACTUAL</small><p>Planned: ${escapeHtml(operation.next_planned_action || "Not recorded")}\nActual: ${escapeHtml(actualActionLabel(operation))}</p></article>
      <details><summary>Original trusted tool request and result</summary><pre>${escapeHtml(JSON.stringify({tool_input: operation.tool_input || {}, tool_output: operation.tool_output_original, evidence: operation.evidence}, null, 2))}</pre></details>
    </div>`;
  }
  function renderPostTool(operation) {
    const assessment = operation?.assessment || (operation?.execution_state === "failed" ? "tool_failed" : "");
    const status = $("post-tool-status"); status.textContent = assessment ? pretty(assessment) : "Not recorded"; status.className = `assessment-pill ${assessment}`;
    $("post-tool-found").textContent = operation?.tool_output_summary || (operation?.execution_state === "running" ? "Tool execution is still running." : "Not recorded");
    $("post-tool-interpretation").textContent = operation?.agent_interpretation || "Not recorded";
    const update = operation?.hypothesis_update;
    $("post-tool-hypothesis").textContent = update ? `${update.hypothesis_id || operation.hypothesis_id}: ${pretty(update.status)}\n${update.updates?.at(-1)?.interpretation || ""}` : operation?.assessment ? `${operation.hypothesis_id || "Hypothesis"}: ${pretty(operation.assessment)}` : "Not recorded";
    $("post-tool-uncertainty").textContent = (operation?.interpretation_limitations || []).join(" · ") || "Not recorded";
    $("post-tool-plan").textContent = operation?.next_planned_action ? `${operation.next_planned_action}\nWhy: ${operation.reason_for_next_action || "Not recorded"}\nStatus: ${pretty(operation.next_action_status)}` : "Not recorded";
    $("post-tool-actual").textContent = operation?.next_actual_action ? `${actualActionLabel(operation)}\n${operation.next_actual_action.decision_id ? `Decision: ${operation.next_actual_action.decision_id}\n` : ""}${operation.next_actual_action.matches_plan === true ? "Matches recorded plan" : operation.next_actual_action.matches_plan === false ? "Changed from recorded plan" : "Plan match not recorded"}` : "Not executed / not recorded";
    $("post-tool-memory").textContent = (operation?.memory_updates || []).map((item) => `${item.memory_id || "Memory"}: ${item.summary || item.details || "Recorded"}`).join("\n") || "Not recorded";
  }
  function renderObservability() {
    const all = (state.context.observability || []).map((item) => operationSnapshot(item)).filter(Boolean);
    const tools = [...new Set((state.context.observability || []).map((item) => item.tool_name).filter(Boolean))].sort();
    const families = [...new Set((state.context.observability || []).map((item) => item.tool_family).filter(Boolean))].sort();
    const toolSelect = $("operation-tool"), familySelect = $("operation-family");
    const selectedTool = toolSelect.value, selectedFamily = familySelect.value;
    toolSelect.innerHTML = `<option value="">All tools</option>${tools.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(pretty(value))}</option>`).join("")}`; toolSelect.value = selectedTool;
    familySelect.innerHTML = `<option value="">All families</option>${families.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(pretty(value))}</option>`).join("")}`; familySelect.value = selectedFamily;
    const query = $("operation-search").value.trim().toLowerCase(), agent = $("operation-agent").value, assessment = $("operation-assessment").value, hypothesis = $("operation-hypothesis").value.trim().toLowerCase();
    const onlyFailures = $("operation-failures").checked, from = Number($("operation-step-from").value || 0), to = Number($("operation-step-to").value || Infinity);
    const timeFrom = $("operation-time-from").value ? new Date($("operation-time-from").value).getTime() : -Infinity;
    const timeTo = $("operation-time-to").value ? new Date($("operation-time-to").value).getTime() : Infinity;
    const operations = all.filter((item) => {
      const haystack = JSON.stringify([item.agent_name,item.tool_name,item.observation,item.hypothesis,item.tool_output_summary,item.agent_interpretation,item.next_planned_action]).toLowerCase();
      const operationTime = Date.parse(item.timestamp || "");
      return (!query || haystack.includes(query)) && (!agent || logicalOf(item.agent_role, item.run_id) === agent) && (!toolSelect.value || item.tool_name === toolSelect.value) && (!familySelect.value || item.tool_family === familySelect.value) && (!assessment || item.assessment === assessment) && (!hypothesis || String(item.hypothesis_id).toLowerCase().includes(hypothesis)) && (!onlyFailures || item.execution_state === "failed") && item.step >= from && item.step <= to && (!Number.isFinite(operationTime) || (operationTime >= timeFrom && operationTime <= timeTo));
    });
    $("observability-count").textContent = `${operations.length} operation${operations.length === 1 ? "" : "s"}`;
    $("observability-rows").innerHTML = operations.map((item) => `<tr data-operation="${escapeHtml(item.operation_id)}" class="${item.execution_state === "failed" ? "failed" : ""} ${state.selectedOperation === item.operation_id ? "selected" : ""}"><td><b>${String(item.step).padStart(2,"0")}</b><span class="operation-state ${escapeHtml(item.execution_state)}">${escapeHtml(item.execution_state)}</span></td><td><b>${escapeHtml(pretty(item.modality || "video"))}</b></td><td><b>${escapeHtml(item.agent_name)}</b><small>${escapeHtml(item.hypothesis_id || "No hypothesis ID")}</small></td><td><b>${escapeHtml(pretty(item.tool_name))}</b><small>${escapeHtml(pretty(item.tool_family))}</small></td><td>${escapeHtml(truncate(inputSummary(item),120))}</td><td>${escapeHtml(truncate(item.tool_output_summary || (item.execution_state === "running" ? "Running…" : "Awaiting result"),150))}</td><td>${escapeHtml(pretty(item.assessment || "not recorded"))}</td><td><b>${escapeHtml(truncate(item.next_planned_action || "Not recorded",100))}</b><small>Actual: ${escapeHtml(actualActionLabel(item))}</small></td></tr>`).join("") || `<tr><td colspan="8">No forensic operations match the current filters or replay position.</td></tr>`;
    document.querySelectorAll("#observability-rows [data-operation]").forEach((row) => row.addEventListener("click", () => {
      state.selectedOperation = row.dataset.operation; const full = (state.context.observability || []).find((item) => item.operation_id === row.dataset.operation); const snapshot = full && operationSnapshot(full);
      const moment = [...state.moments].reverse().find((item) => Number(item.sequence_num) <= replaySequence() && (item.decision_id === full?.decision_id || item.tool_call_id === full?.tool_call_id || item.evidence_ids?.some((id) => full?.evidence_ids?.includes(id))));
      if (moment) selectEvent(moment); else { renderOperationDetail(snapshot); renderPostTool(snapshot); }
    }));
    let selected = operations.find((item) => item.operation_id === state.selectedOperation);
    if (!selected && operations.length) { selected = operations.at(-1); state.selectedOperation = selected.operation_id; }
    renderOperationDetail(selected || null); renderPostTool(selected || null);
  }
  function renderTimelines() {
    const story = visibleEvents(false); els.timeline.replaceChildren(...story.map((event) => timelineItem(event)));
    const raw = state.view === "raw" ? visibleEvents(true) : []; els.raw.replaceChildren(...raw.map((event) => timelineItem(event, true)));
    renderMemory(); renderHypotheses(); renderSources(); els.empty.hidden = (state.view === "story" ? story : raw).length > 0 || ["matrix", "memory", "hypotheses", "sources"].includes(state.view);
  }
  function renderMatrix() {
    if (state.view !== "matrix") { els.matrix.replaceChildren(); return; }
    const records = state.context.evidence || [];
    els.matrix.innerHTML = records.map((record) => {
      const audio = String(record.evidence_id || "").startsWith("audio_ev_");
      const media = audio ? `<span class="audio-evidence-glyph">♫</span>` : `<img src="/api/artifact?id=${encodeURIComponent(record.evidence_id)}" alt="">`;
      const scope = audio ? `${numeric(Number(record.start_time || 0), 2)}–${numeric(Number(record.end_time || 0), 2)}s · ${pretty(record.component_type)}` : `sampled frames ${(record.frame_indices || []).join(", ")}`;
      return `<button class="evidence-row" data-evidence="${escapeHtml(record.evidence_id)}">${media}<span><b>${escapeHtml(pretty(record.tool_name))}</b><small>${escapeHtml(agentInfo(record.agent_role).name)} · ${escapeHtml(scope)}</small><em>${escapeHtml(truncate(evidenceText(record), 150))}</em></span></button>`;
    }).join("") || `<div class="empty-state"><b>No evidence records yet</b></div>`;
    document.querySelectorAll(".evidence-row").forEach((row) => row.addEventListener("click", () => {
      const moment = [...state.moments].reverse().find((item) => item.evidence_ids?.includes(row.dataset.evidence)); if (moment) selectEvent(moment);
    }));
  }
  function renderMetrics() {
    const maxSequence = sequenceOf(state.selected) || sequenceOf(state.events.at(-1));
    const moments = keyEvents().filter((event) => Number(event.sequence_num || 0) <= maxSequence);
    $("metric-progress").textContent = keyEvents().length ? `${Math.round(moments.length / keyEvents().length * 100)}%` : "0%";
    $("metric-events").textContent = moments.length;
    $("metric-tools").textContent = moments.filter((event) => storyType(event) === "TOOL_EXECUTION").length;
    $("metric-evidence").textContent = moments.filter((event) => storyType(event) === "EVIDENCE_RETURNED").length;
    $("metric-claims").textContent = moments.filter((event) => storyType(event) === "SPECIALIST_REPORT_SENT").length;
    const errors = moments.filter((event) => ["TOOL_FAILURE", "FALLBACK"].includes(storyType(event)) || event.status === "error").length;
    $("metric-errors").textContent = errors; $("metric-errors").classList.toggle("has-errors", errors > 0);
  }
  function render() { renderMetrics(); renderPhases(); renderFlow(); renderObservability(); renderTimelines(); renderMatrix(); renderReplay(); document.dispatchEvent(new CustomEvent("argus:av-selection", {detail:{context:state.context,selected:state.selected,maxSequence:cursorSequence(),events:state.events}})); }

  function selectEvent(event, options = {}) {
    state.selected = event; const info = agentInfo(event.agent_role), copy = describe(event), tx = transaction(event), type = storyType(event);
    const linkedOperation = operationForEvent(event); if (linkedOperation) state.selectedOperation = linkedOperation.operation_id;
    $("inspector-empty").hidden = true; $("inspector-content").hidden = false; $("selected-sequence").textContent = `#${sequenceOf(event)}`;
    $("inspector-icon").textContent = ICONS[type] || info.short; $("inspector-icon").style.color = tx.color || info.color;
    $("inspector-phase").textContent = `${pretty(phaseFor(event))} / ${pretty(type)}`; $("inspector-title").textContent = copy.title; $("inspector-description").textContent = copy.text;
    $("inspector-input").textContent = tx.input; $("inspector-output").textContent = tx.output;
    $("fact-route").textContent = `${nodeLabel(tx.source)} → ${nodeLabel(tx.target)}`;
    $("fact-time").textContent = shortTime(event.timestamp, true); $("fact-status").textContent = event.status || "success";
    $("fact-tool").textContent = event.tool_name ? toolLabel(event.tool_name) : "—"; $("fact-decision").textContent = event.decision_id || "—"; $("fact-call").textContent = event.tool_call_id || "—";
    renderOwnership(event);
    $("payload-json").textContent = JSON.stringify(rawEvent(event), null, 2);
    const sections = [], detail = event.detail || {};
    for (const [label, value] of [["Investigation question", detail.question], ["Hypothesis", detail.hypothesis_id || detail.hypothesis?.candidate_explanation], ["Suspicion", detail.suspicion], ["Alternative explanation", detail.alternative_explanation || (detail.alternatives || []).join(" · ")], ["Original ToolDF plan", detail.plan?.original_plan], ["Source separation", detail.plan?.source_separation], ["Separation reason", detail.plan?.source_separation_reason], ["Why this action", detail.why], ["Expected information", detail.expected_information], ["Assessment", detail.assessment], ["Interpretation", detail.interpretation], ["Next action", detail.next_action], ["Causal link", detail.causal_link_basis], ["Recorded limitation", (detail.limitations || []).join(" · ")], ["Legacy trace notice", detail.missing_rationale]]) {
      if (value) sections.push(`<section class="investigation-section"><small>${escapeHtml(label)}</small><p>${escapeHtml(value)}</p></section>`);
    }
    $("investigation-sections").innerHTML = sections.join("");
    const id = evidenceId(event), artifact = $("artifact-card"), audioEvidence = String(id).startsWith("audio_ev_");
    if (id && !audioEvidence && !state.imported) {
      artifact.hidden = false; $("artifact-id").textContent = id; $("artifact-image").src = `/api/artifact?id=${encodeURIComponent(id)}&t=${Date.now()}`;
      const recordForArtifacts = evidenceRecord(event), ids = recordForArtifacts?.summary_statistics?.artifact_ids || event?.result?.artifact_ids || [];
      const all = state.context.artifacts || [], byId = Object.fromEntries(all.map((item) => [item.artifact_id, item]));
      $("reusable-artifacts").innerHTML = ids.map((artifactId) => {
        const item = byId[artifactId] || {}, parents = item.parent_artifact_ids || [], image = String(item.mime_type || "").startsWith("image/");
        return `<article><div>${image ? `<img src="/api/reusable-artifact?id=${encodeURIComponent(artifactId)}" alt="${escapeHtml(item.artifact_type || "artifact")}">` : `<span class="artifact-file">${escapeHtml(pretty(item.artifact_type || "data"))}</span>`}</div><b>${escapeHtml(artifactId)}</b><small>${escapeHtml(pretty(item.artifact_type || "artifact"))}</small><em>${escapeHtml(parents.length ? `${parents.join(" + ")} → ${artifactId}` : "source artifact")}</em></article>`;
      }).join("");
      const tabs = $("visual-artifact-tabs"), stats = recordForArtifacts?.summary_statistics || {};
      const roots = new Set([stats.source_image_artifact_id, ...(stats.mask_artifact_ids || [])].filter(Boolean));
      const dependent = all.filter((item) => (item.parent_artifact_ids || []).some((parent) => roots.has(parent)) && String(item.mime_type || "").startsWith("image/"));
      const choices = [
        ["Original", stats.original_frame_artifact_id || stats.source_image_artifact_id],
        ["Boxes", stats.bounding_box_overlay_artifact_id],
        ["Mask", (stats.mask_artifact_ids || [])[0]],
        ["Overlay", stats.segmentation_overlay_artifact_id],
        ["Crop", (stats.detected_crop_artifact_ids || [])[0]],
        ["Upstream preview", stats.upstream_preview_artifact_id],
        ["Downstream", dependent.find((item) => !ids.includes(item.artifact_id))?.artifact_id],
      ].filter((item, index, values) => item[1] && values.findIndex((other) => other[1] === item[1]) === index);
      if (recordForArtifacts?.tool_name === "visual_grounding" && choices.length) {
        tabs.hidden = false;
        const initial = choices.find((choice) => choice[0] === "Overlay") || choices[0];
        tabs.innerHTML = choices.map(([label, artifactId]) => `<button type="button" data-artifact-view="${escapeHtml(artifactId)}" class="${artifactId === initial[1] ? "active" : ""}">${escapeHtml(label)}</button>`).join("");
        $("artifact-image").src = `/api/reusable-artifact?id=${encodeURIComponent(initial[1])}&t=${Date.now()}`;
        tabs.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
          tabs.querySelectorAll("button").forEach((item) => item.classList.toggle("active", item === button));
          $("artifact-image").src = `/api/reusable-artifact?id=${encodeURIComponent(button.dataset.artifactView)}&t=${Date.now()}`;
        }));
      } else { tabs.hidden = true; tabs.innerHTML = ""; }
    } else { artifact.hidden = true; $("reusable-artifacts").innerHTML = ""; $("visual-artifact-tabs").hidden = true; $("visual-artifact-tabs").innerHTML = ""; }
    const provenance = $("provenance-card"), record = evidenceRecord(event);
    if (record) {
      provenance.hidden = false; $("provenance-list").innerHTML = [
        audioEvidence ? `Exact source interval: ${record.start_time}–${record.end_time}s` : (record.frame_references?.length ? "Exact source frame references retained" : "Legacy record: exact source frame mapping unavailable"),
        audioEvidence ? `Score semantics: ${record.score_type || "unrecorded"}` : `Coordinate space: ${record.coordinate_space || "unrecorded"}`,
        "Artifact integrity hash retained",
        audioEvidence ? "Audio detector output is model evidence, not proof of synthesis" : "Diagnostic measurements are not calibrated authenticity probabilities",
      ].map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    } else provenance.hidden = true;
    document.querySelectorAll(".timeline-item").forEach((item) => item.classList.toggle("selected", item.dataset.moment === event.moment_id || (!event.moment_id && Number(item.dataset.sequence) === sequenceOf(event))));
    renderMetrics(); renderFlow(); renderPhases(); renderObservability(); renderTimelines(); renderMatrix(); renderReplay(); if (!options.quiet) renderExchange(event, true);
    document.dispatchEvent(new CustomEvent("argus:av-selection", {detail:{context:state.context,selected:state.selected,maxSequence:cursorSequence(),events:state.events}}));
  }

  function addEvents(incoming, live = false) {
    const known = new Set(state.events.map(identityOf));
    incoming.forEach((event) => {
      const key = identityOf(event);
      if (!known.has(key)) { state.events.push(event); known.add(key); }
    });
    state.events.sort((a, b) => sequenceOf(a) - sequenceOf(b));
    if (state.live || state.cursor < 0) state.cursor = state.events.length - 1;
    if (!live) render();
  }

  // Six-agent topology: four peer visual investigators, Audio Agent 5, and
  // Judge Agent 6. Agents are the primary nodes and tools are chips owned by
  // the calling agent. Identities, states, and edges come from the server's
  // agent model (src/agentic/visualization/agents.py), which only reports
  // recorded events; live streaming and replay use this same code path.
  const LOGICAL_ORDER = ["visual_investigator_1", "visual_investigator_2", "visual_investigator_3", "visual_investigator_4", "audio_investigator", "judge"];
  const PRIMARY_COMPONENTS = new Set(["Generic visual investigator", "ToolDF audio investigator", "Judge coordinator"]);
  const STATE_TEXT = {
    not_invoked: ["○", "Not invoked"], queued: ["◔", "Queued"], active: ["●", "Active"],
    waiting_for_tool: ["◐", "Waiting for tool"], waiting_for_peer: ["◑", "Waiting for peer"],
    completed: ["✓", "Completed"], failed: ["✕", "Failed"], cancelled: ["⊘", "Cancelled"],
  };
  const TOOL_LABELS = {
    visual_grounding: "SAM3 grounding", recognize_scene_text: "PaddleOCR-VL OCR", reverse_search_frame: "Reverse image search",
    search_source_evidence: "Source search", inspect_source_webpage: "Webpage inspection", analyze_general: "Qwen2.5-VL observation",
    analyze_judge: "Original trained visual judge", analyze_augmented_judge: "Augmented judge (experimental)",
    run_tooldf_investigation: "ToolDF", get_audio_result: "Read ToolDF result", source_separator: "Demucs separation",
    speech_deepfake_detector: "Speech detector (AASIST)", singing_deepfake_detector: "Singing detector (AASIST)",
    music_deepfake_detector: "Music detector (AASIST)", sound_deepfake_detector: "Sound detector (AASIST)",
    trained_observers: "Trained LoRA observers (judge input)", case_review: "Rule-based case review", tooldf: "ToolDF planner",
    srm_residual: "SRM residual", fft_spectrum: "FFT spectrum",
  };
  const TRAINED_OBSERVER_TOOLS = new Set(["analyze_texture", "analyze_lighting", "analyze_motion", "analyze_physics"]);
  const TOOL_GROUP_ORDER = ["model", "forensic", "tooldf", "supplementary_verification"];
  const TOOL_GROUP_LABELS = { model: "Model evaluations", forensic: "Forensic tools", tooldf: "ToolDF internal tools", supplementary_verification: "Supplementary verification" };
  const EDGE_COLORS = {
    tool_request: "--cyan", tool_result: "--blue", model_evaluation: "--violet", finding_report: "--green",
    reinspection_request: "--rose", reinspection_return: "--green", agent_message: "--violet", case_review_input: "--amber", internal_check: "--faint",
  };
  const EDGE_VERBS = {
    tool_request: "request", tool_result: "result", model_evaluation: "model evaluation", finding_report: "finding → judge",
    reinspection_request: "reinspection request", reinspection_return: "reinspection return", agent_message: "agent message", case_review_input: "case-review input",
  };
  const TRAY_LIMIT = 5;
  const expandedTrays = new Set();

  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#4ed8e8"; }
  function agentModel() { return state.context.agent_model || { agents: [], communications: [], role_map: [] }; }
  function logicalAgent(id) { return agentModel().agents.find((agent) => agent.agent_id === id) || null; }
  function roleEntry(role, runId = "") {
    const map = agentModel().role_map || [];
    return map.find((item) => item.agent_role === role && (!runId || item.run_id === runId)) || map.find((item) => item.agent_role === role) || null;
  }
  function logicalOf(role, runId = "") {
    const entry = roleEntry(role, runId);
    return entry ? (entry.logical_agent_id || "infrastructure") : String(role || "");
  }
  function eventInvolvesAgent(event, agentId) {
    const annotated = Object.prototype.hasOwnProperty.call(event, "logical_agent_id");
    const ids = annotated
      ? [event.logical_agent_id || "infrastructure", event.logical_target_id]
      : [logicalOf(event.agent_role, event.run_id), event.target_role ? logicalOf(event.target_role, event.run_id) : ""];
    return ids.includes(agentId) || event.agent_role === agentId || event.target_role === agentId;
  }
  function agentInfo(role, runId = "") {
    const entry = roleEntry(role, runId), agent = entry && logicalAgent(entry.logical_agent_id);
    if (agent) {
      const name = PRIMARY_COMPONENTS.has(entry.component) ? agent.label : `${agent.label} · ${entry.component}`;
      const color = agent.team === "audio" ? "var(--violet)" : agent.team === "case_review" ? "var(--rose)" : "var(--cyan)";
      return { name, short: agent.short, color };
    }
    return AGENTS[role] || { name: pretty(role || "runtime"), short: "AI", color: "#8d9aaa" };
  }
  function baseNoLora() { return agentModel().model_provenance?.mode === "base_no_lora"; }
  function toolLabel(name) {
    if (baseNoLora() && name === "trained_observers") return "Base-model role observations (judge input)";
    if (baseNoLora() && name === "analyze_judge") return "Base-model visual judge";
    return TOOL_LABELS[name] || NODE_NAMES[name] || pretty(name);
  }
  function nodeLabel(name) {
    const value = String(name || "");
    if (value.startsWith("tool:")) return toolLabel(value.split(":").pop());
    if (logicalAgent(value)) return logicalAgent(value).label;
    if (roleEntry(value)) return agentInfo(value).name;
    return NODE_NAMES[value] || pretty(value);
  }
  function chipKey(tool) { return TRAINED_OBSERVER_TOOLS.has(tool) ? "trained_observers" : tool; }
  function cursorSequence() {
    // The final story moment also covers trailing non-story rows such as an agent's run_completed.
    const moments = keyEvents(), last = sequenceOf(state.events.at(-1)) || 0;
    if (!state.selected || (moments.length && keyPosition() === moments.length - 1)) return Math.max(last, sequenceOf(state.selected));
    return sequenceOf(state.selected);
  }
  function latestBefore(items, maxSequence) { return [...(items || [])].reverse().find((item) => Number(item.sequence) <= maxSequence) || null; }
  function topologyMode() {
    const present = (agent) => Boolean(agent && (agent.configured || agent.executed));
    const visual = LOGICAL_ORDER.slice(0, 4).some((id) => present(logicalAgent(id)));
    const audio = present(logicalAgent("audio_investigator"));
    return visual && audio ? "combined" : audio ? "audio_only" : "visual_only";
  }
  function agentView(agent, maxSequence) {
    const snapshot = latestBefore(agent.snapshots, maxSequence);
    let note = "";
    if (!snapshot || (snapshot.state === "not_invoked" && !agent.executed)) {
      note = agent.executed ? "Not started at this point in the replay"
        : !state.meta.complete && agent.configured ? "Configured · no recorded activity yet"
        : agent.team === "audio" ? "Not invoked in this run — audio was not analyzed"
        : agent.team === "case_review" ? "Not invoked in this run — no case review recorded"
        : "Not invoked in this run";
    }
    const tools = (agent.tools || [])
      .filter((tool) => Number(tool.call_sequence ?? tool.result_sequence) <= maxSequence)
      .map((tool) => ({ ...tool, status: tool.result_sequence !== null && tool.result_sequence <= maxSequence ? tool.status : "running" }));
    return { snapshot, state: snapshot?.state || "not_invoked", note, tools };
  }
  function identityLine(agent) {
    const roles = (agent.runtime_identities || []).map((item) => item.agent_role);
    if (!roles.length) return `ID ${agent.agent_id} · no runtime identity recorded`;
    const shown = roles.length > 2 ? `${roles.slice(0, 2).join(", ")} +${roles.length - 2}` : roles.join(", ");
    return `ID ${agent.agent_id} · runtime ${shown}`;
  }

  function renderTopologyFrame() {
    const model = agentModel(), stage = $("flow-stage");
    if (!stage) return;
    stage.dataset.fixture = state.context.simulation_fixture ? "true" : "false";
    if (!model.agents.length) {
      $("visual-team-row").innerHTML = `<p class="agent-component">The six-agent model needs the dashboard server's context; browser-imported traces show the story and raw audit only.</p>`;
      return;
    }
    const slots = { visual: $("visual-team-row"), audio: $("audio-agent-slot"), case_review: $("judge-slot") };
    if (slots.visual.querySelector("p.agent-component:only-child")) slots.visual.replaceChildren();
    for (const agent of model.agents) {
      if (document.querySelector(`[data-agent-card="${agent.agent_id}"]`)) continue;
      const card = document.createElement("article");
      card.className = `agent-card${agent.team === "case_review" ? " judge-card" : ""}`;
      card.dataset.agentCard = agent.agent_id; card.dataset.node = agent.agent_id; card.dataset.team = agent.team;
      card.tabIndex = 0; card.setAttribute("role", "button");
      card.innerHTML = `<div class="agent-card-head"><span class="agent-badge" aria-hidden="true">${escapeHtml(agent.short)}</span><div class="agent-title"><b>${escapeHtml(agent.label)}</b><small>${escapeHtml(agent.role)}</small></div><span class="state-pill" data-state="not_invoked"><i aria-hidden="true">○</i><span>Not invoked</span></span></div><p class="agent-component"></p><p class="agent-action"></p><dl class="agent-counters"></dl><p class="agent-finding"></p><div class="tool-tray" data-tool-tray="${escapeHtml(agent.agent_id)}" aria-label="${escapeHtml(agent.label)} tool calls"></div>`;
      slots[agent.team]?.append(card);
    }
    stage.dataset.topology = topologyMode();
    const topology = model.execution_topology || {};
    $("topology-badge").textContent = topology.label || "—"; $("topology-badge").title = topology.label || "";
  }

  function renderToolTray(agent, view, card) {
    const tray = card.querySelector(".tool-tray"), aggregated = new Map();
    for (const tool of view.tools) {
      const key = chipKey(tool.tool_name), item = aggregated.get(key) || { key, group: tool.tool_group, calls: [], status: "completed", last: 0 };
      item.calls.push(tool); item.last = Math.max(item.last, Number(tool.call_sequence ?? tool.result_sequence));
      if (tool.status === "running") item.status = "running"; else if (tool.status === "failed" && item.status !== "running") item.status = "failed";
      aggregated.set(key, item);
    }
    const maxSequence = cursorSequence();
    const review = (agent.model_evaluations || []).find((item) => item.kind === "rule_based_case_review" && item.sequence <= maxSequence);
    if (review) aggregated.set("case_review", { key: "case_review", group: "model", calls: [{ tool_call_id: "", sequence: review.sequence, global_event_id: review.global_event_id, native_role: "audiovisual_reviewer" }], status: "completed", last: review.sequence });
    const expanded = expandedTrays.has(agent.agent_id) || els.displayMode.value === "detailed";
    const items = [...aggregated.values()].sort((a, b) => TOOL_GROUP_ORDER.indexOf(a.group) - TOOL_GROUP_ORDER.indexOf(b.group) || a.last - b.last);
    const visible = expanded ? items : items.slice(-TRAY_LIMIT);
    const chip = (item) => {
      const ids = item.calls.map((call) => call.tool_call_id).filter(Boolean);
      const title = `${toolLabel(item.key)} · owned by ${agent.label}${ids.length ? ` · tool_call_id ${ids.join(", ")}` : ""} · ${item.calls.length} call(s)`;
      return `<button type="button" class="tool-chip" data-tool-node="tool:${escapeHtml(agent.agent_id)}:${escapeHtml(item.key)}" data-tool-key="${escapeHtml(item.key)}" data-group="${escapeHtml(item.group)}" data-status="${escapeHtml(item.status)}" title="${escapeHtml(title)}"><span>${escapeHtml(toolLabel(item.key))}</span>${item.calls.length > 1 ? `<i>×${item.calls.length}</i>` : ""}</button>`;
    };
    const groups = TOOL_GROUP_ORDER.map((group) => [group, visible.filter((item) => item.group === group)]).filter(([, members]) => members.length);
    tray.innerHTML = groups.map(([group, members]) => {
      if (group === "tooldf") {
        return `<div class="tool-group"><span class="tool-group-label">${escapeHtml(TOOL_GROUP_LABELS[group])}</span><button type="button" class="tool-chip" data-tool-node="tool:${escapeHtml(agent.agent_id)}:tooldf" data-tool-key="tooldf" data-group="model" title="ToolDF planner selects these internal tools for ${escapeHtml(agent.label)}"><span>ToolDF planner</span></button><div class="tool-group nested">${members.map(chip).join("")}</div></div>`;
      }
      return `<div class="tool-group">${groups.length > 1 || agent.team !== "visual" ? `<span class="tool-group-label">${escapeHtml(TOOL_GROUP_LABELS[group])}</span>` : ""}${members.map(chip).join("")}</div>`;
    }).join("") + (items.length > TRAY_LIMIT && els.displayMode.value !== "detailed"
      ? `<button type="button" class="tool-more" data-tray="${escapeHtml(agent.agent_id)}">${expanded ? "Show fewer" : `+${items.length - TRAY_LIMIT} earlier tools`}</button>` : "");
    const selectedCall = state.selected?.tool_call_id;
    if (selectedCall) tray.querySelectorAll(".tool-chip").forEach((node) => node.classList.toggle("selected-tool", (aggregated.get(node.dataset.toolKey)?.calls || []).some((call) => call.tool_call_id === selectedCall)));
  }

  function renderFlow() {
    renderTopologyFrame();
    const model = agentModel(), maxSequence = cursorSequence();
    for (const agent of model.agents) {
      const card = document.querySelector(`[data-agent-card="${agent.agent_id}"]`); if (!card) continue;
      const view = agentView(agent, maxSequence), snap = view.snapshot, [glyph, text] = STATE_TEXT[view.state] || ["?", pretty(view.state)];
      card.dataset.state = view.state;
      const pill = card.querySelector(".state-pill"); pill.dataset.state = view.state; pill.querySelector("i").textContent = glyph; pill.querySelector("span").textContent = text;
      card.querySelector(".agent-component").textContent = identityLine(agent);
      const action = card.querySelector(".agent-action");
      action.textContent = view.note || snap?.action || "No recorded action"; action.classList.toggle("muted", Boolean(view.note));
      const currentTool = snap?.current_tool ? toolLabel(snap.current_tool) : "—";
      const counters = agent.team === "case_review" ? [
        ["Current tool", currentTool],
        ["Model evaluations", (agent.model_evaluations || []).filter((item) => item.sequence <= maxSequence && item.kind !== "trained_observer_input").length],
        ["Findings in", (agent.received || []).filter((item) => item.sequence <= maxSequence).length],
        ["Reinspections", (agent.reinspections || []).filter((item) => item.sequence <= maxSequence).length],
      ] : [["Current tool", currentTool], ["Tool calls", snap?.tool_calls ?? 0], ["Evidence", snap?.evidence_count ?? 0]];
      card.querySelector(".agent-counters").innerHTML = counters.map(([key, value]) => `<div title="${escapeHtml(`${key}: ${value}`)}"><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
      const finding = view.note && !agent.executed ? "No finding — not invoked" : snap?.finding_status || "No finding recorded";
      card.querySelector(".agent-finding").innerHTML = `Finding: <b>${escapeHtml(finding)}</b>${agent.unresolved_at_run_end && state.meta.complete && maxSequence >= Number(agent.last_sequence || 0) ? " · no completion recorded" : ""}`;
      card.setAttribute("aria-label", `${agent.label}, ${text}. ${action.textContent}. Open investigator view.`);
      card.title = `${agent.label} (${agent.agent_id}) — ${agent.role}\n${(agent.runtime_identities || []).map((item) => `${item.agent_role} · ${item.component} · ${item.agent_session_ids.join(", ")}`).join("\n") || "No runtime identity recorded"}`;
      card.classList.toggle("dimmed", Boolean(state.activeAgent && state.activeAgent !== agent.agent_id));
      card.classList.toggle("selected-agent", state.drawerAgent === agent.agent_id);
      renderToolTray(agent, view, card);
    }
    const through = state.events.filter((event) => sequenceOf(event) <= maxSequence);
    const tasks = through.filter((event) => event.surface === "task_assigned").length;
    $("clawteam-copy").textContent = tasks ? `${tasks} task assignment${tasks === 1 ? "" : "s"}` : (model.infrastructure?.clawteam_tasks ? "not yet at this point" : "not used in this run");
    const mcpCalls = through.filter((event) => event.surface === "tool_call").length;
    const runtimeKind = model.execution_topology?.kind || "";
    $("gateway-copy").textContent = runtimeKind === "direct" || runtimeKind === "direct_demo" ? "not used (direct execution)"
      : runtimeKind === "simulated_fixture" ? `${mcpCalls} simulated call${mcpCalls === 1 ? "" : "s"}`
      : `${mcpCalls} recorded call${mcpCalls === 1 ? "" : "s"}`;
    const evidenceCount = state.moments.filter((moment) => moment.type === "EVIDENCE_RETURNED" && Number(moment.sequence_num) <= maxSequence).length;
    $("evidence-node-copy").textContent = `${evidenceCount} record${evidenceCount === 1 ? "" : "s"}`;
    const memoryIds = new Set(state.moments.filter((moment) => ["MEMORY_UPDATED", "MEMORY_SHARED"].includes(moment.type) && Number(moment.sequence_num) <= maxSequence).map((moment) => moment.memory_entry_id).filter(Boolean));
    $("memory-node-copy").textContent = `${memoryIds.size} entr${memoryIds.size === 1 ? "y" : "ies"}`;
    const sampling = state.moments.find((moment) => moment.type === "VIDEO_SAMPLED" && Number(moment.sequence_num) <= maxSequence)?.detail?.sampling;
    $("video-node-copy").textContent = sampling ? `${sampling.effective_frames || sampling.requested_frames} frames · ${sampling.frame_size || "source"} px` : state.context.video_available ? "source media available" : "not analyzed";
    renderCaseFindings(maxSequence);
    renderFollowState();
    drawBaseRoutes();
    if (state.selected) { renderExchange(state.selected); renderMedia(state.selected); renderOwnership(state.selected); }
    if (state.drawerAgent) renderAgentDrawer(state.drawerAgent);
  }

  // Geometry ---------------------------------------------------------------
  function boxOf(target) {
    const stage = $("flow-stage"), node = typeof target === "string" ? document.querySelector(target) : target;
    if (!stage || !node || !node.getClientRects().length) return null;
    const outer = stage.getBoundingClientRect(), inner = node.getBoundingClientRect();
    const left = inner.left - outer.left, top = inner.top - outer.top;
    return { left, top, width: inner.width, height: inner.height, cx: left + inner.width / 2, cy: top + inner.height / 2, bottom: top + inner.height, right: left + inner.width };
  }
  function cardBox(agentId) { return boxOf(`[data-agent-card="${agentId}"]`); }
  function judgePort(judge, agentId, offset) { return judge.left + judge.width * (LOGICAL_ORDER.indexOf(agentId) + 1) / 6 + offset; }
  function curve(x1, y1, x2, y2) { const mid = (y1 + y2) / 2; return `M ${x1} ${y1} C ${x1} ${mid}, ${x2} ${mid}, ${x2} ${y2}`; }
  function agentPath(source, target, offset = 0) {
    const from = cardBox(source), to = cardBox(target);
    if (!from || !to || source === target) return null;
    if (target === "judge") return curve(from.cx + offset, from.bottom, judgePort(to, source, offset), to.top);
    if (source === "judge") return curve(judgePort(from, target, offset), from.top, to.cx + offset, to.bottom);
    const lift = 24, y1 = from.top, y2 = to.top;
    return `M ${from.cx + offset} ${y1} C ${from.cx + offset} ${y1 - lift}, ${to.cx + offset} ${y2 - lift}, ${to.cx + offset} ${y2}`;
  }
  function commPath(edge) {
    const offset = edge.kind === "reinspection_request" ? 12 : edge.kind === "reinspection_return" ? -12 : edge.kind === "agent_message" ? (edge.source < edge.target ? -8 : 8) : 0;
    return agentPath(edge.source, edge.target, offset);
  }
  function toolPath(agentId, key, reverse) {
    const badge = boxOf(`[data-agent-card="${agentId}"] .agent-badge`);
    const chip = boxOf(`[data-tool-node="tool:${agentId}:${key}"]`) || boxOf(`[data-agent-card="${agentId}"] .tool-more`) || boxOf(`[data-agent-card="${agentId}"] .tool-tray`);
    if (!badge || !chip) return null;
    const a = { x: badge.left + 3, y: badge.bottom - 4 }, b = { x: chip.left + 4, y: chip.cy };
    const bend = Math.min(a.x, b.x) - 16;
    return reverse ? `M ${b.x} ${b.y} C ${bend} ${b.y}, ${bend} ${a.y}, ${a.x} ${a.y}` : `M ${a.x} ${a.y} C ${bend} ${a.y}, ${bend} ${b.y}, ${b.x} ${b.y}`;
  }
  function edgePath(edge) {
    if (!edge) return null;
    if (["tool_request", "tool_result", "model_evaluation"].includes(edge.kind)) {
      const agentId = edge.phase === "result" ? edge.target : edge.source;
      return toolPath(agentId, chipKey(edge.tool_name), edge.phase === "result");
    }
    return commPath(edge);
  }
  function svgElement(name, attributes = {}) {
    const node = document.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    return node;
  }
  function pathWithTitle(d, className, title, color = "") {
    const path = svgElement("path", { d, class: className });
    if (color) path.style.stroke = color;
    const label = svgElement("title"); label.textContent = title; path.append(label);
    return path;
  }

  function drawBaseRoutes() {
    const base = $("base-routes"), comms = $("comm-routes"); if (!base || !comms) return;
    base.replaceChildren(); comms.replaceChildren();
    const model = agentModel(); if (!model.agents.length) return;
    if (matchMedia("(max-width: 1000px)").matches) { drawSelectedRoute(); return; }
    const judge = logicalAgent("judge"), maxSequence = cursorSequence();
    if (judge && (judge.configured || judge.executed)) {
      for (const agent of LOGICAL_ORDER.slice(0, 5).map(logicalAgent)) {
        if (!agent || !(agent.configured || agent.executed)) continue;
        const d = agentPath(agent.agent_id, "judge");
        if (d) base.append(pathWithTitle(d, "topology-route", `${agent.label} → Judge Agent 6: topology relationship only, not an executed message`));
      }
    }
    const groups = new Map();
    for (const item of model.communications || []) {
      if (item.internal || Number(item.sequence) > maxSequence) continue;
      const key = `${item.kind}|${item.source}|${item.target}`;
      groups.set(key, [...(groups.get(key) || []), item]);
    }
    for (const items of groups.values()) {
      const last = items.at(-1), d = commPath(last); if (!d) continue;
      const title = `${pretty(last.kind)}: ${nodeLabel(last.source)} → ${nodeLabel(last.target)} · ${items.length} recorded event(s) · latest #${last.sequence}${last.content ? ` — ${truncate(last.content, 160)}` : ""}`;
      const path = pathWithTitle(d, `comm-route kind-${last.kind}`, title);
      comms.append(path);
      if (items.length > 1) {
        const point = path.getPointAtLength(path.getTotalLength() * 0.5);
        const count = svgElement("text", { x: point.x + 4, y: point.y - 4, class: "comm-count" }); count.textContent = `×${items.length}`; comms.append(count);
      }
    }
    drawSelectedRoute();
  }
  function drawSelectedRoute() {
    const group = $("selected-route"); if (!group) return;
    group.replaceChildren();
    const edge = state.selected?.edge, d = edgePath(edge); if (!d) return;
    const color = cssVar(EDGE_COLORS[edge.kind] || "--cyan");
    const path = pathWithTitle(d, "selected-route-path", `Selected: ${EDGE_VERBS[edge.kind] || pretty(edge.kind)}`, color);
    group.append(path);
    if (edge.phase) {
      // Tool edges stay inside the owning card, so the direction is labelled on the chip itself.
      const agentId = edge.phase === "result" ? edge.target : edge.source;
      const chip = document.querySelector(`[data-tool-node="tool:${agentId}:${chipKey(edge.tool_name)}"]`);
      if (chip) chip.dataset.edge = EDGE_VERBS[edge.kind] === "model evaluation" ? `model ${edge.phase}` : EDGE_VERBS[edge.kind];
      return;
    }
    const length = path.getTotalLength(), point = path.getPointAtLength(length * 0.35);
    const text = svgElement("text", { x: point.x + 6, y: point.y - 6, class: "route-label" });
    text.style.fill = color; text.textContent = EDGE_VERBS[edge.kind] || pretty(edge.kind);
    group.append(text);
  }
  function clearSignals() {
    $("active-signals")?.replaceChildren();
    document.querySelectorAll(".active-now,.tool-active").forEach((node) => node.classList.remove("active-now", "tool-active"));
  }
  function animateAlong(d, color, delay = 0) {
    if (!d) return;
    setTimeout(() => {
      const group = $("active-signals"); if (!group) return;
      const path = svgElement("path", { d, class: "active-route" }); path.style.stroke = color;
      const dot = svgElement("circle", { r: "4.5", class: "signal-dot" }); dot.style.stroke = color;
      const motion = svgElement("animateMotion", { dur: "820ms", path: d, fill: "freeze" });
      dot.append(motion); group.append(path, dot);
      if (typeof motion.beginElement === "function") motion.beginElement();
      setTimeout(() => { path.remove(); dot.remove(); }, 1150);
    }, delay);
  }
  function pulse(selector) {
    const node = document.querySelector(selector); if (!node) return;
    node.classList.remove("active-now"); void node.offsetWidth; node.classList.add("active-now");
  }
  function animateEvent(event) {
    clearSignals();
    const edge = event?.edge;
    if (!edge) { if (event?.logical_agent_id) pulse(`[data-agent-card="${event.logical_agent_id}"]`); return; }
    const color = cssVar(EDGE_COLORS[edge.kind] || "--cyan");
    if (["tool_request", "tool_result", "model_evaluation"].includes(edge.kind)) {
      const agentId = edge.phase === "result" ? edge.target : edge.source, key = chipKey(edge.tool_name);
      if (edge.tool_group === "tooldf" && edge.phase === "request") {
        animateAlong(toolPath(agentId, "tooldf", false), color);
        animateAlong(toolPath(agentId, key, false), color, 520);
      } else animateAlong(toolPath(agentId, key, edge.phase === "result"), color);
      pulse(`[data-agent-card="${agentId}"]`); pulse(`[data-tool-node="tool:${agentId}:${key}"]`);
      return;
    }
    animateAlong(commPath(edge), color);
    pulse(`[data-agent-card="${edge.source}"]`); pulse(`[data-agent-card="${edge.target}"]`);
  }

  // Area C ownership -------------------------------------------------------
  function renderOwnership(event) {
    const raw = rawEvent(event), ids = event.evidence_ids || raw.evidence_ids || [];
    const owner = event.logical_agent_id ? nodeLabel(event.logical_agent_id) : "Runtime / infrastructure (not a forensic agent)";
    const parts = [
      `<span>Owner <b>${escapeHtml(owner)}</b></span>`,
      `<span>native <code>${escapeHtml(event.agent_role || raw.agent_role || "unknown")}</code></span>`,
      event.logical_component && !PRIMARY_COMPONENTS.has(event.logical_component) ? `<span>component <b>${escapeHtml(event.logical_component)}</b></span>` : "",
      event.tool_name ? `<span>tool <b>${escapeHtml(toolLabel(event.tool_name))}</b></span>` : "",
      event.tool_call_id ? `<span>tool_call_id <code>${escapeHtml(event.tool_call_id)}</code></span>` : "",
      event.decision_id ? `<span>decision <code>${escapeHtml(event.decision_id)}</code></span>` : "",
      ids.length ? `<span>evidence <code>${escapeHtml(ids.join(", "))}</code></span>` : "",
      event.agent_session_id ? `<span>session <code>${escapeHtml(event.agent_session_id)}</code></span>` : "",
    ];
    document.querySelectorAll("[data-ownership]").forEach((node) => { node.innerHTML = parts.join(""); });
    $("fact-owner").textContent = owner;
    $("fact-native").textContent = `${event.agent_role || raw.agent_role || "unknown"}${event.agent_session_id ? ` · ${event.agent_session_id}` : ""}${event.mapping_basis ? ` · mapped by ${pretty(event.mapping_basis)}` : ""}`;
  }

  // Area D findings and judge ---------------------------------------------
  function assessmentTone(value) {
    const text = String(value || "").toLowerCase();
    if (["supports_suspicion", "supported", "fake", "manipulation_supported"].includes(text)) return "support";
    if (["contradicts_suspicion", "weakened", "rejected", "real", "no_manipulation_identified"].includes(text)) return "contradict";
    return "neutral";
  }
  function jumpButton(globalId, label) { return globalId ? `<button type="button" class="jump-link" data-jump="${escapeHtml(globalId)}">${escapeHtml(label)}</button>` : escapeHtml(label); }
  function agentAssessment(agent, maxSequence) {
    if (agent.team === "audio") {
      const verdict = latestBefore(agent.verdicts, maxSequence) || latestBefore((agent.findings || []).filter((item) => item.kind === "audio_finding"), maxSequence);
      return verdict?.audio_investigation_assessment || "";
    }
    return latestBefore(agent.interpretations, maxSequence)?.assessment || latestBefore(agent.hypotheses, maxSequence)?.status || "";
  }
  function reportCard(agent, maxSequence) {
    if (!agent.executed) {
      return `<article class="report-card" data-invoked="false" data-agent-report="${escapeHtml(agent.agent_id)}"><header><b>${escapeHtml(agent.label)}</b><span class="assessment-tag">Not invoked</span></header><p>${escapeHtml(agentView(agent, maxSequence).note || "Not invoked in this run")}.</p></article>`;
    }
    const findings = (agent.findings || []).filter((item) => item.sequence <= maxSequence);
    const finding = [...findings].reverse().find((item) => item.kind !== "evidence_claim") || findings.at(-1) || null;
    const interpretation = latestBefore(agent.interpretations, maxSequence);
    const assessment = agentAssessment(agent, maxSequence);
    const delivered = (agentModel().communications || []).filter((item) => item.source === agent.agent_id && item.target === "judge" && !item.internal && item.sequence <= maxSequence);
    const evidence = [...new Set([...(finding?.evidence_ids || []), ...(interpretation?.evidence_ids || [])])];
    const limitations = finding?.limitations?.length ? finding.limitations : (interpretation?.limitations || []);
    const text = finding?.text || interpretation?.text || (agentView(agent, maxSequence).snapshot ? "No finding recorded yet." : "Not started at this point in the replay.");
    const natives = (agent.runtime_identities || []).filter((item) => PRIMARY_COMPONENTS.has(item.component) || item.mapping_basis === "legacy_specialized_alias").map((item) => item.agent_role).join(", ");
    return `<article class="report-card" data-agent-report="${escapeHtml(agent.agent_id)}"><header><b>${escapeHtml(agent.label)}</b><span class="assessment-tag" data-tone="${assessmentTone(assessment)}">${escapeHtml(pretty(assessment || "not recorded"))}</span></header>
      <p>${escapeHtml(text)}</p>
      <dl><dt>Agent ID</dt><dd>${escapeHtml(agent.agent_id)}${natives ? ` (${escapeHtml(natives)})` : ""}</dd>
      <dt>Evidence</dt><dd>${evidence.map((id) => `<button type="button" class="jump-link" data-evidence="${escapeHtml(id)}">${escapeHtml(id)}</button>`).join(" ") || "none linked"}</dd>
      <dt>Confidence</dt><dd>${escapeHtml(finding?.confidence ?? "not recorded")}</dd>
      <dt>Limitations</dt><dd>${escapeHtml(limitations.join("; ") || "none recorded")}</dd>
      <dt>Reported</dt><dd>${finding ? jumpButton(finding.global_event_id, `#${finding.sequence} · ${shortTime(finding.timestamp, true)}`) : "—"}</dd>
      <dt>To judge</dt><dd>${delivered.length ? delivered.map((item) => jumpButton(item.global_event_id, `${EDGE_VERBS[item.kind] || pretty(item.kind)} #${item.sequence}`)).join(", ") : agent.team === "audio" ? "no recorded delivery (no case review yet)" : "no recorded delivery"}</dd></dl></article>`;
  }
  function differenceRows(maxSequence) {
    return LOGICAL_ORDER.slice(0, 5).map(logicalAgent).filter((agent) => agent?.executed).map((agent) => {
      const value = agentAssessment(agent, maxSequence);
      return { agent, value, tone: value ? assessmentTone(value) : "none" };
    });
  }
  function renderCaseFindings(maxSequence) {
    const model = agentModel(), judge = logicalAgent("judge");
    if (!model.agents.length || !$("investigator-reports")) return;
    $("investigator-reports").innerHTML = LOGICAL_ORDER.slice(0, 5).map(logicalAgent).filter(Boolean).map((agent) => reportCard(agent, maxSequence)).join("");
    const received = (judge?.received || []).filter((item) => item.sequence <= maxSequence);
    const observers = (judge?.model_evaluations || []).filter((item) => item.kind === "trained_observer_input" && item.sequence <= maxSequence).length;
    $("judge-received").innerHTML = `<h4>Received by Judge Agent 6</h4>${received.length ? `<ul>${received.map((item) => `<li>${jumpButton(item.global_event_id, `#${item.sequence}`)} <b>${escapeHtml(nodeLabel(item.source))}</b> · ${escapeHtml(EDGE_VERBS[item.kind] || pretty(item.kind))}${item.content ? ` — ${escapeHtml(truncate(item.content, 150))}` : ""}</li>`).join("")}</ul>` : `<p>${judge?.executed ? "No investigator finding reached the judge by this moment." : "Judge Agent 6 was not invoked in this run."}</p>`}
      <p class="note">${baseNoLora() ? "Base-model visual judge" : "Original trained visual judge"} inputs: ${observers ? `${observers} ${baseNoLora() ? "base-model role observation" : "trained LoRA observer report"}${observers === 1 ? "" : "s"} (precomputed by the runtime)` : "none recorded"}. Generic investigator findings are not inputs to this judge step.</p>`;
    const requests = (judge?.reinspections || []).filter((item) => item.sequence <= maxSequence);
    $("judge-reinspection").innerHTML = `<h4>Judge reinspection</h4>${requests.length ? `<ul>${requests.map((item) => {
      const done = item.completed_sequence !== null && item.completed_sequence <= maxSequence;
      return `<li>${jumpButton(item.global_event_id, `#${item.sequence}`)} → <b>${escapeHtml(nodeLabel(item.target || item.native_target))}</b> · ${escapeHtml(toolLabel(item.tool_name))}${item.frame_indices.length ? ` · frames ${escapeHtml(item.frame_indices.join(", "))}` : ""}<br>${escapeHtml(truncate(item.reason, 220))}<br><b>${done ? `Returned ${escapeHtml(item.returned_evidence_ids.join(", ") || "evidence")} at #${item.completed_sequence}` : state.meta.complete && item.completed_sequence === null ? "No completion recorded in this run" : "Awaiting recorded return"}</b></li>`;
    }).join("")}</ul>` : `<p>${judge?.executed ? "No reinspection was requested by this moment." : "Not applicable — the judge did not run."}</p>`}`;
    const rows = differenceRows(maxSequence), tones = new Set(rows.map((row) => row.tone));
    $("judge-differences").innerHTML = `<h4>Recorded assessment differences</h4><ul>${rows.map((row) => `<li><b>${escapeHtml(row.agent.label)}</b>: <span class="assessment-tag" data-tone="${row.tone}">${escapeHtml(pretty(row.value || "not recorded"))}</span></li>`).join("") || "<li>No investigator assessments recorded.</li>"}</ul>
      <p><b>${tones.has("support") && tones.has("contradict") ? "Investigators recorded conflicting assessments." : rows.length ? "No directly conflicting categorical assessments recorded." : ""}</b></p>
      <p class="note">Dashboard comparison of recorded values, not judge reasoning. The judge's own statements appear only where it recorded them (for example, a reinspection reason).</p>`;
    const evaluations = (judge?.model_evaluations || []).filter((item) => item.sequence <= maxSequence);
    const original = [...evaluations].reverse().find((item) => item.kind === "original_trained_visual_judge");
    const augmented = [...evaluations].reverse().find((item) => item.kind === "experimental_augmented_judge");
    const review = [...evaluations].reverse().find((item) => item.kind === "rule_based_case_review");
    $("original-verdict").textContent = original ? String(original.answer ?? "unknown").toUpperCase() : judge?.executed || !state.meta.complete ? "Pending" : "Not run";
    $("original-verdict-copy").textContent = original ? `${original.adapter ? `${original.adapter} · ` : ""}${truncate(original.explanation, 220)}` : `Inputs: four ${baseNoLora() ? "base-model role observations" : "trained LoRA observer reports"}. Not run by this moment.`;
    $("augmented-verdict").textContent = augmented ? String(augmented.answer ?? "unknown").toUpperCase() : "Not recorded";
    $("augmented-verdict-copy").textContent = augmented ? `Experimental, out-of-distribution evidence-augmented judge. ${truncate(augmented.explanation, 180)}` : "Experimental result kept separate from the trained control.";
    const audio = logicalAgent("audio_investigator"), verdict = latestBefore(audio?.verdicts, maxSequence);
    $("audio-verdict").textContent = verdict ? String(verdict.tooldf_original_prediction ?? "unavailable").toUpperCase() : audio?.executed ? "Pending" : "Not run";
    $("audio-verdict-copy").textContent = verdict ? `Supplementary audio forensic assessment: ${pretty(verdict.audio_investigation_assessment || "not recorded")}${state.context.forensic_verification_assessment && state.context.forensic_verification_assessment !== "not_run" ? ` · verification ${pretty(state.context.forensic_verification_assessment)}` : ""}. Scores are P(real).` : "ToolDF's original prediction is preserved separately from the supplementary assessment.";
    $("audio-verdict-card").hidden = !(audio?.configured || audio?.executed);
    $("case-verdict-card").hidden = !(review || topologyMode() === "combined");
    $("case-verdict").textContent = review ? pretty(review.case_assessment) : "Unavailable";
    $("case-verdict-copy").textContent = review ? `${review.explanation} Inputs recorded: visual ${String(review.visual_prediction ?? "none").toUpperCase()}, audio ${String(review.audio_prediction ?? "none").toUpperCase()}.` : "No cross-modal case review was recorded; no unified decision was invented.";
    $("case-rule-note").textContent = review ? `Case assessment: ${pretty(review.fusion_method || "rule")} — a transparent rule, not a fusion model.` : "No case-level rule was applied by this moment.";
    const assessment = state.context.visual_investigation_assessment || "inconclusive";
    $("visual-assessment").textContent = pretty(assessment);
    $("visual-assessment-copy").textContent = `Source status: ${pretty(state.context.source_footage_status || "not requested")}. Separate from the trained judge's binary label.`;
  }

  // Investigator-specific view --------------------------------------------
  function listOrEmpty(items, render, empty) { return items.length ? `<ol>${items.map(render).join("")}</ol>` : `<p class="empty">${escapeHtml(empty)}</p>`; }
  function openAgentDrawer(agentId) { state.drawerAgent = agentId; $("agent-drawer").hidden = false; renderFlow(); $("agent-drawer-close").focus({ preventScroll: true }); }
  function closeAgentDrawer() { state.drawerAgent = ""; $("agent-drawer").hidden = true; renderFlow(); }
  function renderAgentDrawer(agentId) {
    const agent = logicalAgent(agentId); if (!agent) return;
    const max = cursorSequence(), view = agentView(agent, max), [, stateText] = STATE_TEXT[view.state] || ["", pretty(view.state)];
    const bounded = (items) => (items || []).filter((item) => Number(item.sequence) <= max);
    $("agent-drawer-kicker").textContent = `${agent.team === "visual" ? "VISUAL TEAM" : agent.team === "audio" ? "AUDIO" : "CASE REVIEW"} · AS OF MOMENT #${max}`;
    $("agent-drawer-title").textContent = agent.label;
    $("agent-drawer-filter").textContent = state.activeAgent === agentId ? "Clear timeline filter" : "Filter timeline to this agent";
    const identity = `<section><h3>Identity</h3><dl class="kv"><dt>Agent</dt><dd>${escapeHtml(agent.label)} (${escapeHtml(agent.agent_id)})</dd><dt>Role</dt><dd>${escapeHtml(agent.role)}</dd><dt>Backend (configured)</dt><dd>${escapeHtml(agent.backend)}</dd><dt>Execution state</dt><dd>${escapeHtml(stateText)}${view.note ? ` — ${escapeHtml(view.note)}` : ""}</dd><dt>Configured</dt><dd>${agent.configured ? `yes · ${escapeHtml(pretty(agent.configured_basis))}` : "no"}</dd><dt>Runtime identities</dt><dd>${(agent.runtime_identities || []).map((item) => `${escapeHtml(item.agent_role)} — ${escapeHtml(item.component)} · ${escapeHtml(item.agent_session_ids.join(", "))} · ${escapeHtml(pretty(item.mapping_basis))}`).join("<br>") || "none recorded"}</dd></dl></section>`;
    const tools = listOrEmpty(view.tools, (tool) => `<li>${jumpButton(tool.global_event_id, toolLabel(tool.tool_name))} · <code>${escapeHtml(tool.tool_call_id || "no call id")}</code> · ${escapeHtml(pretty(tool.status))}${tool.evidence_ids?.length ? ` → ${escapeHtml(tool.evidence_ids.join(", "))}` : ""}${PRIMARY_COMPONENTS.has(tool.component) ? "" : ` <small>(${escapeHtml(tool.component)})</small>`}</li>`, "No tool calls recorded by this moment.");
    const messages = (agentModel().communications || []).filter((item) => (item.source === agentId || item.target === agentId) && item.sequence <= max);
    const messageList = listOrEmpty(messages, (item) => `<li>${jumpButton(item.global_event_id, `#${item.sequence}`)} ${escapeHtml(nodeLabel(item.source))} → ${escapeHtml(nodeLabel(item.target))} · ${escapeHtml(EDGE_VERBS[item.kind] || pretty(item.kind))}${item.content ? ` — ${escapeHtml(truncate(item.content, 160))}` : ""}</li>`, "No recorded communication by this moment.");
    let body = identity;
    const failures = bounded(agent.failures);
    if (failures.length) body += `<section><h3>Recorded failures</h3>${listOrEmpty(failures, (item) => `<li>${jumpButton(item.global_event_id, `#${item.sequence}`)} ${escapeHtml(item.error)}</li>`, "")}</section>`;
    if (agent.team === "visual") {
      const hypothesis = latestBefore(agent.hypotheses, max), interpretation = latestBefore(agent.interpretations, max), next = latestBefore(agent.next_actions, max);
      const finding = [...bounded(agent.findings)].reverse().find((item) => item.kind === "finding_report") || latestBefore(agent.findings, max);
      const observation = latestBefore(agent.observations, max);
      body += `<section><h3>Current hypothesis</h3>${hypothesis ? `<p>${jumpButton(hypothesis.global_event_id, hypothesis.hypothesis_id || "hypothesis")} · ${escapeHtml(pretty(hypothesis.status || "open"))}<br>${escapeHtml(hypothesis.text)}</p>` : `<p class="empty">No hypothesis recorded.</p>`}</section>
        <section><h3>Initial observation</h3>${observation ? `<p>${escapeHtml(truncate(observation.text, 420))}</p>` : `<p class="empty">No observation recorded.</p>`}</section>
        <section><h3>Observed evidence</h3>${listOrEmpty(bounded(agent.evidence), (item) => `<li><button type="button" class="jump-link" data-evidence="${escapeHtml(item.evidence_id)}">${escapeHtml(item.evidence_id)}</button> · ${escapeHtml(toolLabel(item.tool_name))} · <code>${escapeHtml(item.tool_call_id || "")}</code></li>`, "No evidence produced by this moment.")}</section>
        <section><h3>Tools called</h3>${tools}</section>
        <section><h3>Latest interpretation</h3>${interpretation ? `<p>${jumpButton(interpretation.global_event_id, pretty(interpretation.assessment || "interpretation"))}: ${escapeHtml(interpretation.text)}</p>` : `<p class="empty">Not recorded.</p>`}</section>
        <section><h3>Next planned action</h3>${next ? `<p>${escapeHtml(next.action)}${next.tool ? ` (${escapeHtml(toolLabel(next.tool))})` : ""} · ${escapeHtml(pretty(next.status))}</p>` : `<p class="empty">Not recorded.</p>`}</section>
        <section><h3>Final finding</h3>${finding ? `<p>${jumpButton(finding.global_event_id, `#${finding.sequence}`)} ${escapeHtml(finding.text)}</p>` : `<p class="empty">No finding recorded by this moment.</p>`}</section>
        <section><h3>Communication</h3>${messageList}</section>`;
    } else if (agent.team === "audio") {
      const scene = latestBefore(agent.scene, max), verdict = latestBefore(agent.verdicts, max), hypothesis = latestBefore(agent.hypotheses, max);
      const supplementary = view.tools.filter((tool) => tool.tool_group === "supplementary_verification");
      const internal = (agentModel().communications || []).filter((item) => item.internal && item.source === agentId && item.sequence <= max);
      body += `<section><h3>Detected components (ToolDF scene analysis)</h3>${scene ? `<p>${jumpButton(scene.global_event_id, `#${scene.sequence}`)} ${escapeHtml(scene.text)}</p>` : `<p class="empty">No scene analysis recorded.</p>`}</section>
        <section><h3>ToolDF original prediction</h3>${verdict ? `<p><b>${escapeHtml(String(verdict.tooldf_original_prediction ?? "unavailable").toUpperCase())}</b> — ${escapeHtml(verdict.text)}</p>` : `<p class="empty">Not produced by this moment.</p>`}</section>
        <section><h3>ToolDF tool calls</h3>${listOrEmpty(view.tools.filter((tool) => tool.tool_group !== "supplementary_verification"), (tool) => `<li>${jumpButton(tool.global_event_id, toolLabel(tool.tool_name))} · <code>${escapeHtml(tool.tool_call_id || "")}</code> · ${escapeHtml(pretty(tool.status))}${tool.evidence_ids?.length ? ` → ${escapeHtml(tool.evidence_ids.join(", "))}` : ""}</li>`, "No ToolDF tool calls by this moment.")}</section>
        <section><h3>Supplementary forensic checks</h3>${listOrEmpty(supplementary, (tool) => `<li>${jumpButton(tool.global_event_id, toolLabel(tool.tool_name))} · ${escapeHtml(pretty(tool.status))}${tool.evidence_ids?.length ? ` → ${escapeHtml(tool.evidence_ids.join(", "))}` : ""}</li>`, "No supplementary verification recorded.")}${internal.length ? `<p class="note">Internal checks inside Audio Agent 5: ${internal.map((item) => escapeHtml(truncate(item.content, 120))).join(" · ")}</p>` : ""}</section>
        <section><h3>Hypothesis</h3>${hypothesis ? `<p>${escapeHtml(hypothesis.hypothesis_id)} · ${escapeHtml(pretty(hypothesis.status || "open"))}<br>${escapeHtml(hypothesis.text)}</p>` : `<p class="empty">No hypothesis recorded.</p>`}</section>
        <section><h3>Final audio assessment</h3>${verdict ? `<p><b>${escapeHtml(pretty(verdict.audio_investigation_assessment || "not recorded"))}</b> (separate from ToolDF's original prediction)</p>` : `<p class="empty">Not produced by this moment.</p>`}</section>
        <section><h3>Communication</h3>${messageList}</section>`;
    } else {
      const evaluations = bounded(agent.model_evaluations), rows = differenceRows(max);
      const original = [...evaluations].reverse().find((item) => item.kind === "original_trained_visual_judge");
      const review = [...evaluations].reverse().find((item) => item.kind === "rule_based_case_review");
      const audio = logicalAgent("audio_investigator"), audioVerdict = latestBefore(audio?.verdicts, max);
      body += `<section><h3>Received investigator findings</h3>${listOrEmpty(bounded(agent.received), (item) => `<li>${jumpButton(item.global_event_id, `#${item.sequence}`)} <b>${escapeHtml(nodeLabel(item.source))}</b> · ${escapeHtml(EDGE_VERBS[item.kind] || pretty(item.kind))}${item.evidence_ids?.length ? ` · ${escapeHtml(item.evidence_ids.join(", "))}` : ""}${item.content ? ` — ${escapeHtml(truncate(item.content, 180))}` : ""}</li>`, "No investigator finding reached the judge by this moment.")}</section>
        <section><h3>Disagreements (recorded assessments)</h3>${rows.length ? `<ul>${rows.map((row) => `<li>${escapeHtml(row.agent.label)}: ${escapeHtml(pretty(row.value || "not recorded"))}</li>`).join("")}</ul>` : `<p class="empty">No investigator assessments recorded.</p>`}<p class="note">Comparison of recorded values; the judge did not record its own disagreement analysis unless shown under reinspection.</p></section>
        <section><h3>Requested reinspection</h3>${listOrEmpty(bounded(agent.reinspections), (item) => `<li>${jumpButton(item.global_event_id, `#${item.sequence}`)} → ${escapeHtml(nodeLabel(item.target || item.native_target))} · ${escapeHtml(toolLabel(item.tool_name))} — ${escapeHtml(truncate(item.reason, 200))}<br><b>${item.completed_sequence !== null && item.completed_sequence <= max ? `Returned at #${item.completed_sequence}: ${escapeHtml(item.returned_evidence_ids.join(", "))}` : "No recorded return by this moment"}</b></li>`, "No reinspection requested.")}</section>
        <section><h3>${baseNoLora() ? "Base-model visual judge" : "Original trained visual judge"} (internal model evaluation)</h3>${original ? `<p><b>${escapeHtml(String(original.answer ?? "unknown").toUpperCase())}</b> · ${escapeHtml(original.adapter || (baseNoLora() ? "base Qwen2.5-VL" : "adapter not recorded"))}<br>${escapeHtml(truncate(original.explanation, 600))}</p>` : `<p class="empty">Not invoked by this moment.</p>`}<p class="note">Inputs: ${evaluations.filter((item) => item.kind === "trained_observer_input").length} ${baseNoLora() ? "base-model role observations" : "trained LoRA observer reports"}. Audio evidence is never passed to the visual judge.</p></section>
        <section><h3>Audio findings</h3>${audioVerdict ? `<p>ToolDF original prediction <b>${escapeHtml(String(audioVerdict.tooldf_original_prediction ?? "unavailable").toUpperCase())}</b>; supplementary assessment <b>${escapeHtml(pretty(audioVerdict.audio_investigation_assessment || "not recorded"))}</b>. ${bounded(agent.received).some((item) => item.kind === "case_review_input") ? "Consumed by the recorded rule-based case review." : "Not consumed by any recorded judge step by this moment."}</p>` : `<p class="empty">${audio?.executed ? "No audio verdict by this moment." : "Audio was not analyzed in this run."}</p>`}</section>
        <section><h3>Final case assessment</h3>${review ? `<p><b>${escapeHtml(pretty(review.case_assessment))}</b> — ${escapeHtml(review.explanation)}<br><small>${escapeHtml(pretty(review.fusion_method))}: a transparent rule, not a learned fusion model.</small></p>` : `<p class="empty">No case-level review recorded by this moment.</p>`}</section>
        <section><h3>Internal model evaluations</h3>${tools}</section>`;
    }
    $("agent-drawer-body").innerHTML = body;
  }

  // Interaction ------------------------------------------------------------
  function jumpTo(globalId) {
    const moment = state.moments.find((item) => item.global_event_id === globalId)
      || [...state.moments].reverse().find((item) => Number(item.sequence_num) <= Number(String(globalId).split(":").pop().replace(/\D/g, "") || 0));
    if (moment) pinEvent(moment);
  }
  function pinEvent(event) {
    stopPlayback();
    state.live = keyPosition(event) >= keyEvents().length - 1;
    state.cursor = state.events.findIndex((item) => sequenceOf(item) === sequenceOf(event));
    selectEvent(event);
  }
  function selectToolChip(chip) {
    const agentId = chip.closest("[data-agent-card]")?.dataset.agentCard, key = chip.dataset.toolKey, max = cursorSequence();
    const moment = [...state.moments].reverse().find((item) => Number(item.sequence_num) <= max && item.logical_agent_id === agentId && item.edge && chipKey(item.edge.tool_name || "") === key)
      || [...state.moments].reverse().find((item) => Number(item.sequence_num) <= max && item.logical_agent_id === agentId && key === "case_review" && item.type === "AUDIOVISUAL_REVIEW");
    if (moment) pinEvent(moment);
  }
  function renderFollowState() {
    const node = $("follow-state"); if (!node) return;
    const moments = keyEvents(), position = keyPosition();
    const newer = position >= 0 ? moments.length - position - 1 : 0;
    node.classList.toggle("paused", !state.live);
    node.textContent = state.live ? (state.meta.complete ? "Replay · latest moment" : "Following live")
      : `Paused at moment ${position + 1}${newer ? ` · ${newer} newer` : ""}`;
  }
  function reselectAfterReload() {
    if (!state.selected) return;
    const key = state.selected.global_event_id || identityOf(rawEvent(state.selected));
    const match = state.moments.find((item) => item.global_event_id === key);
    if (match) state.selected = match;
  }
  function bindTopologyControls() {
    const stage = $("flow-stage");
    stage.addEventListener("click", (event) => {
      const more = event.target.closest(".tool-more");
      if (more) { const id = more.dataset.tray; if (expandedTrays.has(id)) expandedTrays.delete(id); else expandedTrays.add(id); renderFlow(); return; }
      const chip = event.target.closest(".tool-chip");
      if (chip) { selectToolChip(chip); return; }
      const card = event.target.closest("[data-agent-card]");
      if (card) openAgentDrawer(card.dataset.agentCard);
    });
    stage.addEventListener("keydown", (event) => {
      if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-agent-card]")) { event.preventDefault(); openAgentDrawer(event.target.dataset.agentCard); }
    });
    $("agent-drawer-close").addEventListener("click", closeAgentDrawer);
    $("agent-drawer-filter").addEventListener("click", () => {
      state.activeAgent = state.activeAgent === state.drawerAgent ? "" : state.drawerAgent; els.agentFilter.value = state.activeAgent; render();
    });
    for (const container of [$("agent-drawer-body"), $("case-findings")]) {
      container.addEventListener("click", (event) => {
        const jump = event.target.closest("[data-jump]"); if (jump) { jumpTo(jump.dataset.jump); return; }
        const evidence = event.target.closest("[data-evidence]"); if (evidence) openEvidence(evidence.dataset.evidence);
      });
    }
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && state.drawerAgent) closeAgentDrawer(); });
    document.querySelectorAll("[data-collapse]").forEach((button) => button.addEventListener("click", () => {
      const section = button.closest("section"), collapsed = section.classList.toggle("collapsed");
      button.textContent = collapsed ? "+" : "−"; button.setAttribute("aria-expanded", String(!collapsed));
    }));
    $("evidence-split").addEventListener("change", (event) => {
      $("evidence-panes").classList.toggle("split", event.target.checked);
      if (state.selected) renderMedia(state.selected); drawWaveform();
    });
  }

  // Live streaming: identical rendering to replay; the stream cursor is the
  // server's stable arrival index, and late or duplicate rows are reconciled.
  function streamOf(event) { return Number(event?.stream_sequence_num ?? sequenceOf(event)); }
  async function resyncEvents() {
    const response = await fetch("/api/events?after=0", { cache: "no-store" }); if (!response.ok) return;
    const data = await response.json(); if (state.imported) return;
    state.events = []; addEvents(data.events, true); applyMeta(data.summary);
  }
  function connectStream() {
    if (state.imported) return;
    const after = state.events.reduce((maximum, event) => Math.max(maximum, streamOf(event)), 0);
    const source = new EventSource(`/api/stream?after=${after}`);
    state.stream?.close(); state.stream = source;
    // Serialize deliveries: overlapping context fetches must not restore an
    // older snapshot or move a cursor the user paused while a fetch was pending.
    let queue = Promise.resolve();
    const enqueue = (handler) => (message) => {
      queue = queue.then(() => state.imported ? undefined : handler(message)).catch((error) => {
        console.error("Trace update failed", error);
      });
    };
    source.addEventListener("reset", enqueue(async (message) => { state.events = []; state.moments = []; state.context = {}; state.cursor = -1; state.selected = null; state.live = true; applyMeta(JSON.parse(message.data)); await loadContext(); render(); }));
    source.addEventListener("trace", enqueue(async (message) => {
      if (state.imported) return;
      const wasLive = state.live, event = JSON.parse(message.data);
      if (state.events.some((item) => identityOf(item) === identityOf(event))) return;
      const latestDisplay = state.events.reduce((maximum, item) => Math.max(maximum, sequenceOf(item)), 0);
      if (sequenceOf(event) <= latestDisplay) await resyncEvents(); else addEvents([event], true);
      const substantiveToolEvent = ["tool_call", "tool_result", "audio_tool_called", "audio_tool_result"].includes(event.surface) && !ROUTINE_TOOLS.has(event.tool_name);
      if (STORY_SURFACES.has(event.surface) || substantiveToolEvent || ["task_assigned", "agent_started", "task_completed"].includes(event.surface)) {
        await loadContext(); if (state.imported) return; render();
        if (wasLive && state.live) { const latest = keyEvents().at(-1); if (latest) { state.cursor = state.events.length - 1; selectEvent(latest); } }
        else renderFollowState();
      }
      if (event.surface === "run_completed") {
        try {
          const meta = await (await fetch("/api/meta", { cache: "no-store" })).json();
          if (state.imported) return;
          applyMeta(meta);
          if (meta.complete) {
            await resyncEvents(); await loadContext();
            if (state.imported) return;
            if (state.live && keyEvents().length) selectEvent(keyEvents().at(-1)); else render();
            source.close();
          }
        } catch (_) { /* keep streaming */ }
      }
    }));
    source.onerror = () => { if (!state.meta.complete) { els.live.className = "live-badge error"; els.live.querySelector("b").textContent = "RECONNECTING"; } };
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme; localStorage.setItem("argus-theme", theme); $("theme-toggle").textContent = theme === "light" ? "◐ Dark" : "☀ Light";
  }
  const requestedTheme = new URLSearchParams(window.location.search).get("theme");
  applyTheme(["dark", "light"].includes(requestedTheme) ? requestedTheme : (localStorage.getItem("argus-theme") || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark")));
  const requestedDisplay = new URLSearchParams(window.location.search).get("display");
  if (["summary", "detailed"].includes(requestedDisplay)) els.displayMode.value = requestedDisplay;
  const requestedView = new URLSearchParams(window.location.search).get("view");
  if (["story", "hypotheses", "sources", "memory", "matrix", "raw"].includes(requestedView)) {
    state.view = requestedView;
    document.querySelectorAll(".view-tabs button").forEach((button) => button.classList.toggle("active", button.dataset.view === requestedView));
    document.querySelectorAll(".view-pane").forEach((pane) => pane.classList.toggle("active", pane.id === `${requestedView}-view`));
  }
  if (new URLSearchParams(window.location.search).get("evidence") === "0") $("media-focus").hidden = true;
  $("theme-toggle").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light"));
  $("workspace-mode").addEventListener("change", (event) => { applyWorkspaceMode(event.target.value); render(); });
  document.querySelectorAll(".view-tabs button").forEach((button) => button.addEventListener("click", () => { state.view = button.dataset.view; document.querySelectorAll(".view-tabs button").forEach((item) => item.classList.toggle("active", item === button)); document.querySelectorAll(".view-pane").forEach((pane) => pane.classList.toggle("active", pane.id === `${state.view}-view`)); renderTimelines(); renderMatrix(); }));
  bindTopologyControls();
  [els.search, $("timeline-filter"), els.agentFilter, els.toolFilter, els.displayMode, els.errorsOnly].forEach((input) => input.addEventListener("input", () => { state.activeAgent = els.agentFilter.value; render(); }));
  ["operation-search", "operation-agent", "operation-tool", "operation-family", "operation-assessment", "operation-hypothesis", "operation-failures", "operation-step-from", "operation-step-to", "operation-time-from", "operation-time-to"].forEach((id) => $(id).addEventListener("input", renderObservability));
  [$("memory-agent"), $("show-own-memory"), $("show-shared-memory"), $("show-memory-writes"), $("show-memory-reads")].forEach((input) => input.addEventListener("input", render));
  $("diagnostic-overlay-opacity").addEventListener("input", (event) => { $("diagnostic-overlay").style.opacity = event.target.value; });
  $("evidence-audio").addEventListener("timeupdate", (event) => {
    const time = Number(event.target.currentTime || 0), minutes = Math.floor(time / 60), seconds = time - minutes * 60;
    if (state.playingAudioInterval && state.audioInterval && time >= state.audioInterval[1]) {
      event.target.pause(); event.target.currentTime = state.audioInterval[0]; state.playingAudioInterval = false;
    }
    $("audio-time-label").textContent = `${String(minutes).padStart(2, "0")}:${seconds.toFixed(3).padStart(6, "0")}`; drawWaveform();
  });
  $("evidence-audio").addEventListener("seeked", (event) => {
    const video = $("evidence-video"), metadata = state.context.audio_metadata || {};
    const aligned = state.context.alignment_available !== false
      && (state.context.alignment_available === true || metadata.resampling?.offset_measured === true);
    if (aligned && state.context.video_available && video.getAttribute("src")) video.currentTime = Number(event.target.currentTime || 0) + Number(metadata.audio_offset_seconds || 0);
  });
  $("audio-waveform").addEventListener("click", (event) => {
    if (!state.waveform) return; const bounds = event.currentTarget.getBoundingClientRect();
    $("evidence-audio").currentTime = (event.clientX - bounds.left) / Math.max(1, bounds.width) * Number(state.waveform.duration || 0);
  });
  $("play-audio-interval").addEventListener("click", async () => {
    const audio = $("evidence-audio"); if (!state.audioInterval || !audio.getAttribute("src")) return;
    audio.currentTime = state.audioInterval[0]; state.playingAudioInterval = true;
    try { await audio.play(); } catch (_) { state.playingAudioInterval = false; }
  });
  $("show-complete-audio").addEventListener("click", () => {
    state.playingAudioInterval = false; state.audioInterval = null; $("audio-interval").textContent = "Complete audio"; drawWaveform();
  });
  els.scrubber.addEventListener("input", () => { const value = els.scrubber.value; stopPlayback(); setMoment(value); }); els.play.addEventListener("click", togglePlayback);
  $("step-back").addEventListener("click", () => { stopPlayback(); setMoment(keyPosition() - 1); }); $("step-forward").addEventListener("click", () => { stopPlayback(); setMoment(keyPosition() + 1); });
  $("jump-start").addEventListener("click", () => { stopPlayback(); setMoment(0); }); $("jump-live").addEventListener("click", () => { stopPlayback(); setMoment(keyEvents().length - 1); });
  els.speed.addEventListener("change", () => { if (state.playing) { stopPlayback(); togglePlayback(); } });
  document.querySelectorAll("[data-phase]").forEach((button) => button.addEventListener("click", () => { const index = keyEvents().findIndex((event) => phaseFor(event) === button.dataset.phase); if (index >= 0) setMoment(index); }));
  $("file-input").addEventListener("change", async (event) => {
    const file = event.target.files[0]; if (!file) return;
    const status = $("import-status"); status.hidden = false; status.textContent = "Opening trace…";
    try {
      if (file.size > 16 * 1024 * 1024) throw new Error("Trace exceeds the 16 MiB preview limit; open it with the replay command.");
      const rows = (await file.text()).split(/\r?\n/).filter((line) => line.trim()).map((line) => JSON.parse(line));
      const response = await fetch("/api/trace-preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ events: rows }) });
      if (!response.ok) throw new Error(`Trace preview failed (HTTP ${response.status}). Check the normalized JSONL event format.`);
      const preview = await response.json();
      stopPlayback(); state.stream?.close(); state.stream = null;
      state.events = []; state.moments = []; state.context = {}; state.selected = null; state.cursor = -1;
      state.imported = true; state.live = true; state.activeAgent = ""; state.selectedOperation = "";
      state.waveform = null; state.audioInterval = null; state.playingAudioInterval = false;
      closeAgentDrawer(); expandedTrays.clear();
      for (const media of document.querySelectorAll("audio, video")) { media.pause(); media.removeAttribute("src"); media.load(); }
      for (const id of ["audio-spectrogram", "artifact-image", "evidence-frame", "crop-image"]) $(id).removeAttribute("src");
      for (const id of ["search", "agent-filter", "timeline-filter", "tool-family-filter", "operation-search", "operation-agent", "operation-tool", "operation-family", "operation-assessment", "operation-hypothesis", "operation-step-from", "operation-step-to", "operation-time-from", "operation-time-to"]) $(id).value = "";
      els.errorsOnly.checked = false; $("operation-failures").checked = false;
      applyMeta({ ...preview.summary, trace_path: file.name }); addEvents(preview.events, true);
      await loadContext(preview.context);
      state.view = "story";
      document.querySelectorAll(".view-tabs button").forEach((button) => button.classList.toggle("active", button.dataset.view === "story"));
      document.querySelectorAll(".view-pane").forEach((pane) => pane.classList.toggle("active", pane.id === "story-view"));
      const latest = keyEvents().at(-1); if (latest) selectEvent(latest, { quiet: true });
      status.textContent = preview.context.media_notice; render();
    } catch (error) { status.textContent = `Could not open trace: ${error.message}`; }
    finally { event.target.value = ""; }
  });
  document.addEventListener("keydown", (event) => { if (event.target.matches("input, select")) return; if (event.code === "Space") { event.preventDefault(); togglePlayback(); } if (event.key === "ArrowLeft") setMoment(keyPosition() - 1); if (event.key === "ArrowRight") setMoment(keyPosition() + 1); });
  let resizeTimer; window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { drawBaseRoutes(); drawWaveform(); if (state.selected) renderMedia(state.selected); }, 100); });
  bootstrap();
})();
