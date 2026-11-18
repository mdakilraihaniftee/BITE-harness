"use strict";
/*
 * Human-readable investigation story from the visible event prefix.
 *
 * Every sentence is built from recorded fields only. Intentions are quoted only
 * when the runtime recorded them; otherwise the step says no rationale was
 * recorded. "Next" links appear only once the next action is itself visible,
 * so replay never reveals the future. Causal links come from explicit event,
 * report, and tool-call references, never from temporal proximity alone.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.StudioStory = api;
})(typeof self !== "undefined" ? self : this, function () {
  const TOOL_EVENTS = new Set(["DECISION_SUMMARY_RECORDED", "TOOL_CALL_REQUESTED", "TOOL_CALL_STARTED",
    "TOOL_CALL_COMPLETED", "TOOL_CALL_FAILED", "TOOL_CALL_CANCELLED", "EVIDENCE_OBSERVED", "MEMORY_WRITTEN"]);

  function agentLabel(id) {
    if (id === "coordinator") return "Coordinator";
    if (id === "orchestrator") return "Orchestrator";
    const match = /^worker_(\d+)$/.exec(id || "");
    return match ? `Worker ${Number(match[1])}` : (id || "Unknown");
  }

  function short(value, limit = 140) {
    if (value === null || value === undefined) return "";
    const text = typeof value === "string" ? value : JSON.stringify(value);
    return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
  }

  function find(value, keys, depth = 0) {
    if (!value || typeof value !== "object" || depth > 5) return undefined;
    if (Array.isArray(value)) { for (const item of value) { const hit = find(item, keys, depth + 1); if (hit !== undefined) return hit; } return undefined; }
    for (const key of keys) if (Object.prototype.hasOwnProperty.call(value, key)) return value[key];
    for (const item of Object.values(value)) { const hit = find(item, keys, depth + 1); if (hit !== undefined) return hit; }
    return undefined;
  }

  /** Factual summary of what a tool returned (no interpretation). */
  function summarizeResult(payload) {
    const result = payload?.canonical_result ?? payload?.result;
    if (result === null || result === undefined) return "returned no structured result";
    const boxes = find(result, ["boxes", "pred_boxes", "bounding_boxes", "bboxes"]);
    const parts = [];
    if (Array.isArray(boxes)) parts.push(`${boxes.length} region${boxes.length === 1 ? "" : "s"}`);
    const crop = find(result, ["crop_bounds", "crop_box"]);
    if (Array.isArray(crop) && crop.length >= 4) parts.push(`a crop of ${Math.round(crop[2] - crop[0])}×${Math.round(crop[3] - crop[1])} px`);
    const found = find(result, ["candidates_found"]);
    if (typeof found === "number") parts.push(`${found} additional candidate${found === 1 ? "" : "s"}`);
    const lowConfidence = find(result, ["low_confidence_regions"]);
    if (Array.isArray(lowConfidence) && lowConfidence.length) parts.push(`${lowConfidence.length} low-confidence region${lowConfidence.length === 1 ? "" : "s"}`);
    const text = find(result, ["text", "ocr_text", "recognized_text"]);
    if (typeof text === "string" && text) parts.push(`text “${short(text, 60)}”`);
    const observation = find(result, ["observation"]);
    let sentence = parts.length ? `returned ${parts.join(", ")}` : "returned a structured result";
    if (typeof observation === "string" && observation) sentence += `. Tool note: “${short(observation, 120)}”`;
    return sentence;
  }

  function failureKind(payload) {
    const code = String(payload?.error?.code || payload?.error?.type || "").toLowerCase();
    const message = String(payload?.error?.message || payload?.error || "").toLowerCase();
    if (code.includes("budget") || message.includes("budget")) return "budget";
    return "execution_failure";
  }

  const OUTCOME_TEXT = {
    success: "Completed", execution_failure: "Execution failure", budget: "Budget stop", contradiction: "Contradiction",
    inconclusive: "Inconclusive", revised: "Hypothesis revised", retained: "Retained", running: "In progress",
    withdrawn: "Estimate withdrawn", info: "",
  };

  function buildStory(events) {
    const steps = [];
    const byCorrelation = new Map();
    const lastToolStep = new Map();
    const peerBurst = new Map();
    const push = (step) => { step.id = `s${steps.length}`; step.eventIds = step.eventIds || [step.primaryEventId]; steps.push(step); return step; };
    const attachNext = (agent, sentence, eventId) => {
      const previous = lastToolStep.get(agent);
      if (previous && !previous.next) { previous.next = sentence; previous.nextEventId = eventId; }
      lastToolStep.delete(agent);
    };

    for (const event of events) {
      const p = event.payload || {};
      const agent = event.agent_id;
      const who = agentLabel(agent);
      const type = event.event_type;
      if (TOOL_EVENTS.has(type) && (agent === "coordinator" || /^worker_\d+$/.test(agent))) {
        const corr = event.activity?.correlation_id || p.invocation_id || p.tool_call_id || event.event_id;
        let step = byCorrelation.get(corr);
        if (!step) {
          if (type === "MEMORY_WRITTEN" && !event.tool_name) continue;
          attachNext(agent, `requested ${event.tool_name || "another tool"}`, event.event_id);
          step = push({kind: "tool", agent, title: `${who} — ${event.tool_name || "Tool action"}`, primaryEventId: event.event_id,
            eventIds: [], outcome: "running", tool: event.tool_name, toolCallId: p.tool_call_id || null, facts: []});
          byCorrelation.set(corr, step);
        }
        step.eventIds.push(event.event_id);
        if (type === "DECISION_SUMMARY_RECORDED") {
          step.intent = p.rationale_recorded === false
            ? "No explicit public rationale was recorded for this action."
            : (p.action_intent || p.current_goal || null);
          if (p.current_goal && p.rationale_recorded !== false) step.goal = p.current_goal;
          if (p.uncertainty) step.facts.push(["Recorded uncertainty", p.uncertainty]);
        } else if (type === "TOOL_CALL_REQUESTED") {
          step.arguments = p.arguments || null;
          step.primaryEventId = event.event_id;
          step.toolCallId = p.tool_call_id || step.toolCallId;
        } else if (type === "TOOL_CALL_COMPLETED") {
          step.outcome = "success"; step.resultSummary = summarizeResult(p); step.resultEventId = event.event_id;
          step.primaryEventId = event.event_id;
        } else if (type === "TOOL_CALL_FAILED") {
          step.outcome = failureKind(p);
          step.resultSummary = `failed: ${short(p.error?.message || p.error || "no usable evidence", 120)}`;
          step.resultEventId = event.event_id; step.primaryEventId = event.event_id;
        } else if (type === "TOOL_CALL_CANCELLED") {
          step.outcome = "inconclusive"; step.resultSummary = "was cancelled before returning evidence";
        } else if (type === "EVIDENCE_OBSERVED") {
          if (p.supported_findings) step.facts.push(["Found", p.supported_findings]);
          if (p.remaining_uncertainties) step.facts.push(["Still uncertain", p.remaining_uncertainties]);
          if (p.decision_to_continue_or_stop) step.facts.push(["Recorded decision", p.decision_to_continue_or_stop]);
          if (p.assessment === "contradicts") step.outcome = "contradiction";
          if (p.assessment === "inconclusive") step.outcome = "inconclusive";
        } else if (type === "MEMORY_WRITTEN") {
          step.memory = "Result references entered the worker's working context.";
        }
        if (type === "TOOL_CALL_COMPLETED" || type === "TOOL_CALL_FAILED" || type === "TOOL_CALL_CANCELLED") lastToolStep.set(agent, step);
        continue;
      }

      switch (type) {
        case "TASK_RECEIVED":
          push({kind: "task", agent: "orchestrator", title: "Task received", text: short(p.original_task, 220), primaryEventId: event.event_id, outcome: "info"});
          break;
        case "RUN_CONFIGURATION_RECORDED": {
          const c = p.effective_config || {};
          push({kind: "config", agent: "orchestrator", title: "Run configuration recorded", primaryEventId: event.event_id, outcome: "info",
            text: `${c.num_workers} worker(s) · optional memory ${c.optional_worker_memory_enabled ? "ON" : "OFF"} · peer communication ${c.peer_communication_enabled ? "ON" : "OFF"} · ${c.execution_mode || "?"} execution · coordinator estimates ${c.coordinator_estimate_updates?.enabled ? `ON (≤${c.coordinator_estimate_updates.max_reassessments} extra calls)` : "OFF"}.`});
          break;
        }
        case "COORDINATOR_PLAN_RECORDED": case "PLAN_CREATED": {
          const list = (p.assignments || []).map((a) => `${agentLabel(a.worker_id)}: ${short(a.scope, 90)}`);
          push({kind: "plan", agent: "coordinator", title: "Coordinator — Work assigned", primaryEventId: event.event_id, outcome: "info",
            text: `Assigned ${list.length} subtask${list.length === 1 ? "" : "s"}${p.planning_source === "same-task_fallback" ? " (fallback: the plan did not name per-worker scopes)" : ""}.`, list});
          break;
        }
        case "INVESTIGATION_ROUND_STARTED":
          push({kind: "round", agent: "orchestrator", title: `Round ${p.round} · ${String(p.kind || "").replaceAll("_", " ")}`, primaryEventId: event.event_id, outcome: "info",
            text: `${(p.workers || []).map(agentLabel).join(", ")} started.`, minor: true});
          break;
        case "WORKER_STARTED":
          lastToolStep.delete(agent);
          break;
        case "HYPOTHESIS_UPDATED": {
          const value = p.hypothesis;
          attachNext(agent, `reported candidate ${short(value, 40)}`, event.event_id);
          const revised = p.revision_kind === "revised";
          const retained = p.revision_kind === "retained";
          const step = push({kind: "hypothesis", agent, primaryEventId: event.event_id, outcome: revised ? "revised" : retained ? "retained" : "success",
            title: revised ? `${who} — Candidate revised` : retained ? `${who} — Candidate retained` : `${who} — Candidate reported`,
            text: revised ? `Revised its candidate from ${short(p.previous_hypothesis, 40)} to ${short(value, 40)} after ${String(p.phase || "review").replaceAll("_", " ")}.`
              : retained ? `Kept its candidate ${short(value, 40)} after ${String(p.phase || "review").replaceAll("_", " ")}.`
                : `Reported candidate answer ${short(value, 60)} to the coordinator.`,
            reportEventId: event.event_id, toolCallRefs: p.tool_call_refs || [], facts: []});
          if (p.uncertainty) step.facts.push(["Reported uncertainty", p.uncertainty]);
          if (revised) step.facts.push(["Earlier hypothesis", `${short(p.previous_hypothesis, 60)} — no longer held`]);
          break;
        }
        case "WORKER_FINISHED":
          if (event.status === "failed" || String(p.status || "").toUpperCase() === "FAILED") {
            push({kind: "failure", agent, title: `${who} — Investigation failed`, primaryEventId: event.event_id, outcome: "execution_failure",
              text: short(p.failure_reason || "The worker stopped without a usable answer.", 200)});
          }
          lastToolStep.delete(agent);
          break;
        case "MESSAGE_SENT": {
          const recipient = p.recipient_id;
          const peer = p.channel === "peer" || (/^worker_/.test(agent) && /^worker_/.test(recipient || ""));
          if (!peer) break;
          const key = `${agent}|${p.message_type}`;
          const open = peerBurst.get(key);
          if (open && open === steps.at(-1)) {
            open.recipients.push(agentLabel(recipient)); open.eventIds.push(event.event_id);
            open.text = `Shared its ${String(p.message_type).toLowerCase().replaceAll("_", " ")} with ${open.recipients.join(", ")}.`;
          } else {
            const step = push({kind: "peer", agent, title: `${who} → peers`, primaryEventId: event.event_id, outcome: "info", recipients: [agentLabel(recipient)],
              text: `Shared its ${String(p.message_type).toLowerCase().replaceAll("_", " ")} with ${agentLabel(recipient)}.`});
            peerBurst.set(key, step);
          }
          break;
        }
        case "VERIFICATION_REQUESTED": {
          const last = steps.at(-1);
          if (last?.kind === "verification") { last.workers.push(agentLabel(p.worker_id)); last.eventIds.push(event.event_id); last.text = `Asked ${last.workers.join(", ")} to independently verify peer claims.`; }
          else push({kind: "verification", agent: "coordinator", title: "Coordinator — Verification requested", primaryEventId: event.event_id, outcome: "info", workers: [agentLabel(p.worker_id)],
            text: `Asked ${agentLabel(p.worker_id)} to independently verify peer claims.`});
          break;
        }
        case "PEER_REVIEW_STARTED":
          push({kind: "review", agent, title: `${who} — Reviewing peer claims`, primaryEventId: event.event_id, outcome: "running",
            text: `Began reviewing ${(p.message_ids || []).length} peer claim(s) as untrusted reports.`});
          break;
        case "FOLLOW_UP_ASSIGNED":
          push({kind: "delegation", agent: "coordinator", title: `Coordinator — Follow-up delegated to ${agentLabel(p.worker_id)}`, primaryEventId: event.event_id, outcome: "info",
            text: short(p.assignment?.scope || "", 220)});
          break;
        case "OPTIONAL_MEMORY_WRITTEN":
          push({kind: "memory", agent, title: `${who} — Notebook updated`, primaryEventId: event.event_id, outcome: "info", minor: true,
            text: `Wrote its ${String(p.phase || "").replaceAll("_", " ")} findings (${p.tool_observations ?? 0} tool observation(s)) to its optional private notebook.`});
          break;
        case "OPTIONAL_MEMORY_READ":
          push({kind: "memory", agent, title: `${who} — Notebook retrieved`, primaryEventId: event.event_id, outcome: "info", minor: true,
            text: `Retrieved ${p.entries} notebook entr${p.entries === 1 ? "y" : "ies"} before ${String(p.phase || "").replaceAll("_", " ")}.`});
          break;
        case "COORDINATOR_REASSESSMENT_RECORDED": {
          const outcome = p.outcome;
          const text = outcome === "retained"
            ? (p.estimate !== null && p.estimate !== undefined ? `Reviewed ${(p.evidence || []).length} new report(s); kept its estimate ${short(p.estimate, 40)}.` : `Reviewed ${(p.evidence || []).length} new report(s); still no estimate.`)
            : outcome === "skipped_budget" ? "Skipped a reassessment to keep model budget for the final synthesis."
              : outcome === "skipped_limit" ? "Skipped a reassessment: the configured reassessment limit was reached."
                : "The reassessment response could not be read; the previous estimate stays current.";
          const step = push({kind: "assessment", agent: "coordinator", title: outcome === "retained" ? "Coordinator — Estimate unchanged" : "Coordinator — Reassessment skipped",
            primaryEventId: event.event_id, outcome: outcome === "retained" ? "retained" : outcome === "unreadable" ? "execution_failure" : outcome.startsWith("skipped_budget") ? "budget" : "info",
            text, evidence: p.evidence || [], facts: []});
          if (p.assessment_summary) step.facts.push(["Public assessment", p.assessment_summary]);
          break;
        }
        case "COORDINATOR_ESTIMATE_UPDATED": {
          const change = p.change_kind;
          const title = {initial: "Coordinator — Provisional estimate", restored: "Coordinator — Estimate restored", revised: "Coordinator — Answer revised",
            withdrawn: "Coordinator — Estimate withdrawn", finalized: "Coordinator — Final answer"}[change] || "Coordinator — Answer state";
          const text = change === "revised" ? `Changed its provisional answer from ${short(p.previous_estimate, 40)} to ${short(p.estimate, 40)}.`
            : change === "withdrawn" ? `No longer considers ${short(p.previous_estimate, 40)} supported; the answer is unresolved.`
              : change === "finalized" ? (p.estimate === null ? "Finalized without an answer." : p.previous_estimate !== null && p.previous_estimate !== undefined && !p.value_changed
                ? `Finalized ${short(p.estimate, 40)}, confirming its provisional estimate.` : `Recorded final answer ${short(p.estimate, 40)}.`)
                : `Formed a provisional estimate: ${short(p.estimate, 40)}.`;
          const step = push({kind: "estimate", agent: "coordinator", title, primaryEventId: event.event_id, text,
            outcome: change === "withdrawn" ? "withdrawn" : change === "revised" ? "revised" : "success", evidence: p.evidence || [], facts: [],
            outcomeText: {initial: "Provisional", restored: "Provisional", revised: "Estimate revised", withdrawn: "Withdrawn", finalized: "Final"}[change] || ""});
          if (p.summary) step.facts.push(["Public assessment", p.summary]);
          if (p.revision_reason) step.facts.push(["Recorded reason", p.revision_reason]);
          step.facts.push(["Evidence considered", (p.evidence || []).map((item) => `${agentLabel(item.worker_id)}: ${short(item.candidate_answer, 30)}`).join("; ") || "none recorded"]);
          break;
        }
        case "FINAL_ANSWER_RECORDED": {
          const already = steps.some((s) => s.kind === "estimate" && s.title === "Coordinator — Final answer");
          if (!already) push({kind: "final", agent: "coordinator", title: "Coordinator — Final answer", primaryEventId: event.event_id, outcome: "success",
            text: `Recorded final answer ${short(p.final_answer ?? p.answer, 80)}.`});
          break;
        }
        case "BUDGET_UPDATED":
          if (p.granted === false && p.resource !== "tool_calls") {
            push({kind: "budget", agent, title: `${who} — Budget limit`, primaryEventId: event.event_id, outcome: "budget",
              text: `A ${String(p.resource).replaceAll("_", " ")} reservation was denied (${p.reason || "limit"}).`});
          }
          break;
        case "RUN_FAILED":
          push({kind: "failure", agent: "orchestrator", title: "Run stopped", primaryEventId: event.event_id, outcome: String(p.error || "").toLowerCase().includes("budget") ? "budget" : "execution_failure",
            text: short(p.error, 200)});
          break;
        case "RUN_COMPLETED":
          push({kind: "complete", agent: "orchestrator", title: "Investigation completed", primaryEventId: event.event_id, outcome: "success", minor: true,
            text: "The run reached its terminal state; the final answer was persisted."});
          break;
        default:
          break;
      }
    }
    for (const step of steps) {
      if (step.kind !== "tool") continue;
      const verb = step.outcome === "running" ? "is running" : step.resultSummary || "completed";
      step.text = `${step.tool || "The tool"} ${verb}.`;
      step.outcomeText = OUTCOME_TEXT[step.outcome] || "";
    }
    for (const step of steps) step.outcomeText = step.outcomeText ?? (OUTCOME_TEXT[step.outcome] || "");
    return steps;
  }

  /**
   * Steps causally linked to an estimate/assessment step through recorded
   * references: report events, delivery events, and the tool calls each
   * report cited. Returns step ids (excluding the step itself).
   */
  function linkedSteps(step, steps) {
    if (!step || !Array.isArray(step.evidence) || !step.evidence.length) return new Set();
    const eventIds = new Set(); const toolKeys = new Set();
    for (const item of step.evidence) {
      for (const id of [item.report_event_id, item.delivered_event_id]) if (id) eventIds.add(id);
      for (const call of item.tool_call_refs || []) toolKeys.add(`${item.worker_id}|${call}`);
    }
    const result = new Set();
    for (const other of steps) {
      if (other.id === step.id) continue;
      if (other.eventIds.some((id) => eventIds.has(id))) result.add(other.id);
      if (other.kind === "tool" && other.toolCallId && toolKeys.has(`${other.agent}|${other.toolCallId}`)) result.add(other.id);
    }
    return result;
  }

  return {buildStory, linkedSteps, summarizeResult, agentLabel, OUTCOME_TEXT};
});
