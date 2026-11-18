"use strict";
/*
 * Answer state for the visible event prefix: the coordinator's provisional
 * estimate, its revision history, the final answer, and investigation progress.
 *
 * Pure and replay-safe: the result for the first K events never depends on
 * event K+1 or later. Estimates come only from recorded
 * COORDINATOR_ESTIMATE_UPDATED events; worker answers are never promoted to
 * coordinator estimates, and nothing here ever sees ground truth.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.StudioAnswer = api;
})(typeof self !== "undefined" ? self : this, function () {
  const STATUS_TEXT = {
    none: "No estimate yet",
    provisional: "Provisional",
    revised: "Revised",
    unresolved: "Unresolved",
    final: "Final",
    abstained: "Abstained",
  };

  /**
   * How estimates were recorded for this run:
   *  - "recorded": estimate events are enabled (they may not have occurred yet)
   *  - "final_only": the run records only the final answer state
   *  - "legacy": the run predates coordinator answer-state recording
   */
  function recordingMode(effectiveConfig, events) {
    if (events.some((e) => e.event_type === "COORDINATOR_ESTIMATE_UPDATED")) {
      return effectiveConfig?.coordinator_estimate_updates?.enabled === false ? "final_only" : "recorded";
    }
    if (!effectiveConfig) return "legacy";
    return effectiveConfig.coordinator_estimate_updates?.enabled ? "recorded" : "final_only";
  }

  function foldAnswerState(events, count, options = {}) {
    const limit = Math.max(0, Math.min(events.length, count ?? events.length));
    const visible = events.slice(0, limit);
    const effective = options.effectiveConfig || null;
    const state = {
      mode: recordingMode(effective, events.slice(0, limit)),
      estimate: {status: "none", value: null, revision: 0, eventId: null, sequence: null, summary: null, reason: null},
      history: [],
      lastAssessment: null,
      final: null,
      round: null,
      roundKind: null,
      roundOpen: false,
      evidenceReceived: 0,
      reportsByRound: false,
      runStatus: null,
    };
    let busReports = 0;
    for (const event of visible) {
      const p = event.payload || {};
      switch (event.event_type) {
        case "COORDINATOR_ESTIMATE_UPDATED": {
          const entry = {
            revision: p.revision, value: p.estimate ?? null, status: p.status || "provisional",
            changeKind: p.change_kind || null, valueChanged: p.value_changed !== false,
            previousValue: p.previous_estimate ?? null, previousStatus: p.previous_status || null,
            summary: p.summary || null, reason: p.revision_reason || null,
            evidence: Array.isArray(p.evidence) ? p.evidence : [], evidenceRefs: p.evidence_refs || event.causal_refs || [],
            eventId: event.event_id, sequence: event.sequence, round: p.round ?? null,
          };
          state.history.push(entry);
          state.estimate = {status: entry.status, value: entry.value, revision: entry.revision, eventId: entry.eventId,
            sequence: entry.sequence, summary: entry.summary, reason: entry.reason};
          // The final-answer field comes only from FINAL_ANSWER_RECORDED (one source per field).
          break;
        }
        case "COORDINATOR_REASSESSMENT_RECORDED":
          state.lastAssessment = {outcome: p.outcome, eventId: event.event_id, sequence: event.sequence, summary: event.summary};
          break;
        case "FINAL_ANSWER_RECORDED": {
          const value = p.final_answer ?? p.answer ?? null;
          state.final = {value, eventId: event.event_id, sequence: event.sequence, source: "final_event"};
          break;
        }
        case "INVESTIGATION_ROUND_STARTED":
          state.round = p.round ?? state.round; state.roundKind = p.kind || null; state.roundOpen = true;
          break;
        case "INVESTIGATION_ROUND_COMPLETED":
          state.roundOpen = false; state.reportsByRound = true;
          state.evidenceReceived += Number(p.reports || 0);
          break;
        case "MESSAGE_DELIVERED":
          if (event.agent_id === "coordinator" && p.message_type === "CANDIDATE_ANSWER") busReports += 1;
          break;
        case "RUN_STATE_CHANGED":
          state.runStatus = p.to || state.runStatus;
          break;
        case "RUN_COMPLETED": state.runStatus = "COMPLETED"; break;
        case "RUN_FAILED": state.runStatus = state.runStatus && state.runStatus !== "RUNNING" ? state.runStatus : "FAILED"; break;
        case "RUN_CANCELLED": state.runStatus = "CANCELLED"; break;
        default: break;
      }
    }
    // Older runs have no round records; count reports that reached the coordinator.
    if (!state.reportsByRound) state.evidenceReceived = busReports;
    return state;
  }

  function statusText(status) { return STATUS_TEXT[status] || status || ""; }

  /** One-line description of an estimate entry (never implies a numeric change on finalization). */
  function describeEntry(entry) {
    if (!entry) return "";
    switch (entry.changeKind) {
      case "initial": return `First provisional estimate: ${entry.value}`;
      case "restored": return `Provisional estimate restored: ${entry.value}`;
      case "revised": return `Revised ${entry.previousValue} → ${entry.value}`;
      case "withdrawn": return `Estimate ${entry.previousValue} withdrawn; unresolved`;
      case "finalized":
        if (entry.value === null) return "Finalized without an answer (abstained)";
        if (entry.previousValue === null) return `Final answer ${entry.value} (no provisional estimate preceded it)`;
        return entry.valueChanged ? `Final answer ${entry.value} (changed from provisional ${entry.previousValue})` : `Final answer ${entry.value} (confirms the provisional estimate)`;
      default: return entry.value === null ? "Unresolved" : String(entry.value);
    }
  }

  return {foldAnswerState, statusText, describeEntry, recordingMode, STATUS_TEXT};
});
