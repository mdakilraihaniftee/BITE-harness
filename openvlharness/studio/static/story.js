"use strict";
/*
 * Semantic investigation story: one deterministic transformation from the
 * visible raw-event prefix to human-readable investigation steps.
 *
 * Each raw event is either attached to exactly one step (through a recorded
 * causal link: tool invocation/correlation, message ID, report event ID,
 * assignment ID, or the agent's phase) or left as a technical event that is
 * shown only in the Technical Trace. Steps are created in event order and
 * identified by their first source event ("step-<event_id>"), so IDs and
 * numbering are stable while the prefix grows (live streaming) and identical
 * at every replay position. Nothing here infers causality from timestamps or
 * adjacency, invents intent, or reads anything but recorded fields.
 *
 * The same module runs for live streaming and replay (and in Node tests).
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
    if (id === "orchestrator") return "Run";
    const match = /^worker_(\d+)$/.exec(id || "");
    return match ? `Worker ${Number(match[1])}` : (id || "Unknown");
  }
  /** "Visual_Grounding_Tool" -> "Visual Grounding" (display only; the raw name stays in details). */
  function toolLabel(name) {
    if (!name) return "a tool";
    return String(name).replace(/_Tool$/i, "").replace(/_/g, " ").trim() || String(name);
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
  function parseJson(text) { try { return typeof text === "string" ? JSON.parse(text) : null; } catch { return null; } }

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
    // Visual outputs (e.g. a crop) are stored as artifacts; name them factually.
    const raw = payload?.result && typeof payload.result === "object" ? payload.result : {};
    const imageKey = Object.keys(raw).find((key) => raw[key] && typeof raw[key] === "object" && raw[key].artifact_ref);
    const imageRef = typeof result === "object" && typeof result.image === "string" ? result.image : null;
    if (imageKey || imageRef) parts.push(`${/crop/i.test(imageKey || "") ? "a cropped image" : "an image"}${imageRef ? ` (${imageRef})` : ""}`);
    const text = find(result, ["text", "ocr_text", "recognized_text"]);
    if (typeof text === "string" && text) parts.push(`text “${short(text, 60)}”`);
    const observation = find(result, ["observation"]);
    let sentence = parts.length ? `returned ${parts.join(", ")}` : "returned a structured result";
    if (typeof observation === "string" && observation) sentence += `; tool note: “${short(observation, 120)}”`;
    return sentence;
  }
  function failureKind(payload) {
    const code = String(payload?.error?.code || payload?.error?.type || "").toLowerCase();
    const message = String(payload?.error?.message || payload?.error || "").toLowerCase();
    return code.includes("budget") || message.includes("budget") ? "budget" : "execution_failure";
  }

  const OUTCOME_TEXT = {
    running: "Running", completed: "Completed", execution_failure: "Execution failure", budget: "Budget stop",
    contradiction: "Contradiction", inconclusive: "Inconclusive", revised: "Hypothesis revised", retained: "Retained",
    withdrawn: "Withdrawn", provisional: "Provisional", estimate_revised: "Estimate revised", final: "Final",
    unresolved: "Unresolved", failure: "Failure", info: "",
  };

  function buildStory(events) {
    const steps = [];
    const stepOf = new Map();          // event_id -> step (every attached event)
    const toolStep = new Map();        // correlation -> tool step
    const legacyTool = new Map();      // agent + model call ID -> latest invocation
    const messageStep = new Map();     // message_id -> step
    const messageInfo = new Map();     // message_id -> {sender, recipient, type}
    const unclaimedSend = new Map();   // message_id -> MESSAGE_SENT not yet linked to a step
    const assignmentStep = new Map();  // assignment_id -> plan / follow-up step
    const lastTool = new Map();        // agent -> latest tool step awaiting its "next"
    const openPhase = new Map();       // agent -> {phase, step} for peer review / follow-up
    const reportByAgent = new Map();   // agent -> latest report step
    const reportStepByEvent = new Map(); // actual hypothesis event ID -> owning step
    const pendingNotebook = new Map(); // agent -> notebook-write events awaiting the report of that phase
    const roundStep = new Map();       // round -> divider
    const planStep = new Map();        // PARSEC-VL plan id -> plan step
    const verificationKey = {round: 0};
    let pendingConfig = null; let taskStep = null; let finalStep = null; let mainCount = 0;
    const technical = [];

    const attach = (step, event) => {
      if (stepOf.has(event.event_id)) return step;
      step.source_event_ids.push(event.event_id);
      for (const ref of event.artifact_refs || []) if (!step.artifact_refs.includes(ref)) step.artifact_refs.push(ref);
      stepOf.set(event.event_id, step);
      return step;
    };
    const create = (event, fields) => {
      const step = {
        id: `step-${event.event_id}`, run_id: event.run_id || null, number: null, agent: event.agent_id, level: "main", kind: "info", semantic_kind: "INFO",
        title: "", text: "", intent: null, intentRecorded: false, action: null, arguments: null, observation: null,
        interpretation: [], memory: [], next: null, nextEventId: null, outcome: "info", status: "completed",
        facts: [], list: null, primaryEventId: event.event_id, resultEventId: null, toolCallId: null,
        source_event_ids: [], artifact_refs: [], related_step_ids: [], evidence: null, ...fields,
      };
      if (step.level === "main") step.number = ++mainCount;
      steps.push(step);
      attach(step, event);
      return step;
    };
    const setNext = (agent, sentence, event) => {
      const previous = lastTool.get(agent);
      if (previous && !previous.next) { previous.next = sentence; previous.nextEventId = event.event_id; }
      lastTool.delete(agent);
    };
    const failure = (event, title, text, outcome = "execution_failure") =>
      create(event, {kind: "failure", semantic_kind: "FAILURE", title, text, outcome, status: "failed"});

    for (const event of events) {
      const p = event.payload || {};
      const agent = event.agent_id;
      const who = agentLabel(agent);
      const type = event.event_type;

      // ---- tool investigations: one step per invocation -------------------
      if (TOOL_EVENTS.has(type)) {
        // Qualify every correlation by owner, including runtime invocation IDs.
        // Parent/causal links are accepted only for this agent's tool step.
        const corr = p.invocation_id ? `${agent}|inv:${p.invocation_id}`
          : event.activity?.correlation_id ? `${agent}|${event.activity.correlation_id}` : null;
        const parents = [event.parent_event_id, ...(event.causal_refs || [])].map((id) => stepOf.get(id))
          .filter((s) => s?.kind === "tool" && s.agent === agent);
        const parent = new Set(parents).size === 1 ? parents[0] : null;
        const callKey = p.tool_call_id ? `${agent}|${p.tool_call_id}` : null;
        let step = corr ? toolStep.get(corr) : null;
        if (!step && parent && (!p.invocation_id || !parent.invocationId || parent.invocationId === p.invocation_id)) step = parent;
        if (!step && !corr && callKey) {
          const previous = legacyTool.get(callKey);
          // Model call IDs can be reused in subsequent turns. A new decision,
          // or a new request after a terminal result, opens another invocation.
          if (type !== "DECISION_SUMMARY_RECORDED" && !(type === "TOOL_CALL_REQUESTED" && previous?.status !== "running")) step = previous;
        }
        if (!step) {
          if ((type === "MEMORY_WRITTEN" || type === "EVIDENCE_OBSERVED") && event.status !== "failed") { technical.push(event.event_id); continue; }
          setNext(agent, `used ${toolLabel(event.tool_name)}`, event);
          step = create(event, {kind: "tool", semantic_kind: "TOOL_INVESTIGATION", action: event.tool_name, tool: event.tool_name,
            status: "running", outcome: "running", toolCallId: p.tool_call_id || null, invocationId: p.invocation_id || null});
        } else attach(step, event);
        if (corr) toolStep.set(corr, step);
        if (callKey) legacyTool.set(callKey, step);
        if (type === "DECISION_SUMMARY_RECORDED") {
          if (p.rationale_recorded !== false && (p.action_intent || p.current_goal)) {
            step.intent = p.current_goal && p.action_intent ? `${p.current_goal} — ${p.action_intent}` : (p.action_intent || p.current_goal);
            step.intentRecorded = true;
          }
          if (p.uncertainty) step.facts.push(["Recorded uncertainty", p.uncertainty]);
          if (p.expected_information) step.facts.push(["Expected information", p.expected_information]);
        } else if (type === "TOOL_CALL_REQUESTED") {
          step.arguments = p.arguments || null; step.toolCallId = p.tool_call_id || step.toolCallId;
          if (p.parse_error) step.facts.push(["Argument problem", short(p.parse_error?.message || p.parse_error, 160)]);
        } else if (type === "TOOL_CALL_STARTED") {
          step.status = "running";
        } else if (type === "TOOL_CALL_COMPLETED") {
          step.status = "completed"; step.outcome = "completed"; step.observation = summarizeResult(p);
          step.resultEventId = event.event_id; step.primaryEventId = event.event_id;
          lastTool.set(agent, step);
        } else if (type === "TOOL_CALL_FAILED") {
          step.status = "failed"; step.outcome = failureKind(p);
          step.observation = `failed: ${short(p.error?.message || p.error || "no usable evidence", 160)}`;
          step.resultEventId = event.event_id; step.primaryEventId = event.event_id;
          lastTool.set(agent, step);
        } else if (type === "TOOL_CALL_CANCELLED") {
          step.status = "failed"; step.outcome = "inconclusive"; step.observation = "was cancelled before returning evidence";
          lastTool.set(agent, step);
        } else if (type === "EVIDENCE_OBSERVED") {
          // Recorded post-observation assessment (only when the runtime recorded one).
          if (p.supported_findings) step.interpretation.push(["Found", p.supported_findings]);
          if (p.remaining_uncertainties) step.interpretation.push(["Still uncertain", p.remaining_uncertainties]);
          if (p.decision_to_continue_or_stop) step.interpretation.push(["Recorded decision", p.decision_to_continue_or_stop]);
          if (p.assessment === "contradicts") step.outcome = "contradiction";
          if (p.assessment === "inconclusive") step.outcome = "inconclusive";
        } else if (type === "MEMORY_WRITTEN") {
          step.memory.push("Result references saved to the working context");
        }
        if (event.status === "failed" && !["TOOL_CALL_FAILED", "TOOL_CALL_CANCELLED"].includes(type)) {
          step.status = "failed"; step.outcome = failureKind(p);
          step.observation = short(p.error?.message || p.error || event.summary || "The action failed.", 200);
          step.resultEventId = event.event_id; step.primaryEventId = event.event_id;
        }
        continue;
      }

      switch (type) {
        // ---- task and configuration ----------------------------------------
        case "RUN_CONFIGURATION_RECORDED":
          if (taskStep) { attach(taskStep, event); taskStep.config = p.effective_config; } else pendingConfig = event;
          break;
        case "TASK_RECEIVED":
          taskStep = create(event, {kind: "task", semantic_kind: "TASK", agent: "orchestrator", title: "Task received",
            text: short(p.original_task, 260), action: "task"});
          if (pendingConfig) { attach(taskStep, pendingConfig); taskStep.config = pendingConfig.payload?.effective_config; pendingConfig = null; }
          break;

        // ---- coordinator work allocation -------------------------------------
        case "COORDINATOR_PLAN_RECORDED": case "PLAN_CREATED": {
          const list = (p.assignments || []).map((a) => `${agentLabel(a.worker_id)}: ${short(a.scope, 110)}`);
          const step = create(event, {kind: "plan", semantic_kind: "ASSIGNMENT", agent: "coordinator",
            title: `Coordinator assigned the investigation to ${list.length} worker${list.length === 1 ? "" : "s"}`,
            text: p.planning_source === "same-task_fallback" ? "The plan did not name per-worker scopes; each worker received the original task." : "Each worker received its own scope.",
            list, started: []});
          for (const a of p.assignments || []) if (a?.assignment_id) assignmentStep.set(a.assignment_id, step);
          break;
        }
        case "FOLLOW_UP_ASSIGNED": {
          const step = create(event, {kind: "delegation", semantic_kind: "FOLLOW_UP", agent: "coordinator",
            title: `Coordinator requested further investigation from ${agentLabel(p.worker_id)}`,
            text: short(p.assignment?.scope || "", 240), outcome: p.delivery_status && p.delivery_status !== "delivered" ? "failure" : "info",
            status: p.delivery_status && p.delivery_status !== "delivered" ? "failed" : "completed",
            target: p.worker_id, started: []});
          if (p.assignment?.assignment_id) assignmentStep.set(p.assignment.assignment_id, step);
          if (p.message_id) {
            messageStep.set(p.message_id, step);
            if (unclaimedSend.has(p.message_id)) { attach(step, unclaimedSend.get(p.message_id)); unclaimedSend.delete(p.message_id); }
          }
          openPhase.set(p.worker_id, {phase: "follow_up", step});
          break;
        }
        case "WORKER_STARTED": {
          lastTool.delete(agent);
          const step = assignmentStep.get(p.assignment_id);
          if (step) { attach(step, event); step.started.push(who); } else technical.push(event.event_id);
          break;
        }

        // ---- communication ---------------------------------------------------
        case "MESSAGE_SENT": {
          const id = p.message_id; const mtype = String(p.message_type || "MESSAGE");
          const recipient = p.recipient_id; const content = parseJson(p.content);
          messageInfo.set(id, {sender: agent, recipient, type: mtype});
          // Only an explicit report reference can fold a message into a report.
          // Identical claims can describe independent communication acts.
          let linkedReport = p.metadata?.report_event_id ? reportStepByEvent.get(p.metadata.report_event_id) : null;
          if (linkedReport?.agent !== agent) linkedReport = null;
          let step = null;
          if (mtype === "TASK_ASSIGNMENT") {
            step = assignmentStep.get(content?.assignment_id) || null;
          } else if (mtype === "VERIFICATION_REQUEST") {
            const key = `verify:${verificationKey.round}`;
            step = messageStep.get(key);
            if (!step) {
              step = create(event, {kind: "verification", semantic_kind: "VERIFICATION_REQUEST", agent: "coordinator",
                title: "Coordinator asked workers to verify each other's findings", text: "", workers: []});
              messageStep.set(key, step);
            }
            step.workers.push(agentLabel(recipient));
            step.text = `Verification requested from ${step.workers.join(", ")}.`;
          } else if (linkedReport) {
            step = linkedReport;
            if (recipient !== "coordinator") { step.sharedWith = [...(step.sharedWith || []), agentLabel(recipient)]; }
            else step.reportedTo = "coordinator";
          } else if (mtype === "CANDIDATE_ANSWER" && recipient === "coordinator") {
            step = create(event, {kind: "report", semantic_kind: "REPORT_DELIVERY", level: "minor",
              title: `${who} sent its report to the coordinator`, text: short(content?.candidate_answer ?? p.content, 120)});
          } else {
            const original = p.correlation_id ? messageInfo.get(p.correlation_id) : null;
            const isReply = Boolean(original && original.sender === recipient && original.recipient === agent);
            if (isReply) {
              step = create(event, {kind: "communication", semantic_kind: "REPLY", title: `${who} replied to ${agentLabel(recipient)}`,
                text: short(content?.claim ?? content?.answer ?? p.content, 220), action: mtype});
              const question = messageStep.get(p.correlation_id);
              if (question) step.related_step_ids.push(question.id);
            } else {
              step = id ? messageStep.get(id) : null;
              if (!step) {
                const verb = mtype === "QUESTION" ? "asked" : mtype === "CONTRADICTION" ? "challenged" : "shared its finding with";
                step = create(event, {kind: "communication", semantic_kind: mtype === "QUESTION" ? "QUESTION" : "PEER_MESSAGE",
                  title: "", text: short(content?.claim !== undefined ? `Claim: ${content.claim}` : p.content, 220), action: mtype, recipients: [], verb});
              }
              step.recipients.push(agentLabel(recipient));
              step.title = `${who} ${step.verb} ${step.recipients.join(", ")}`;
            }
          }
          if (step) { attach(step, event); messageStep.set(id, step); } else { technical.push(event.event_id); unclaimedSend.set(id, event); }
          break;
        }
        case "MESSAGE_DELIVERED": case "MESSAGE_RECEIVED": {
          const step = messageStep.get(p.message_id);
          if (event.status === "failed") {
            if (step) {
              attach(step, event); step.status = "failed"; step.outcome = "execution_failure";
              step.facts.push(["Delivery failure", p.error?.message || p.error || event.summary || "The message could not be delivered."]);
            } else failure(event, `${who} could not receive a message`, short(p.error || event.summary, 200));
          } else if (step) attach(step, event); else technical.push(event.event_id);
          break;
        }
        case "MESSAGE_REJECTED": {
          const info = messageInfo.get(p.message_id) || {};
          failure(event, `${who}'s message could not be delivered`, `${info.recipient ? `To ${agentLabel(info.recipient)}: ` : ""}rejected (${String(p.reason || "unknown").replace(/_/g, " ")}).`,
            String(p.reason || "").includes("budget") ? "budget" : "execution_failure");
          break;
        }
        case "VERIFICATION_REQUESTED": {
          const step = messageStep.get(p.message_id) || messageStep.get(`verify:${verificationKey.round}`);
          if (step) attach(step, event); else create(event, {kind: "verification", semantic_kind: "VERIFICATION_REQUEST", agent: "coordinator",
            title: "Coordinator asked workers to verify each other's findings", text: `Verification requested from ${agentLabel(p.worker_id)}.`, workers: [agentLabel(p.worker_id)]});
          break;
        }
        case "VERIFICATION_REQUEST_REJECTED":
          failure(event, `Verification request to ${agentLabel(p.worker_id)} was not delivered`, `Delivery status: ${p.delivery_status || "rejected"}. That worker did not receive the request.`);
          break;

        // ---- worker conclusions ------------------------------------------------
        case "HYPOTHESIS_UPDATED": {
          const value = p.hypothesis;
          const phase = p.phase || null;
          const open = openPhase.get(agent);
          const previousValue = p.previous_hypothesis ?? reportByAgent.get(agent)?.value;
          const revised = p.revision_kind === "revised" || (!p.revision_kind && p.hypothesis_status === "reviewed"
            && previousValue !== undefined && String(previousValue) !== String(value));
          const retained = p.revision_kind === "retained" || (p.hypothesis_status === "reviewed" && !revised && reportByAgent.get(agent)?.value === value);
          setNext(agent, `reported candidate ${short(value, 40)}`, event);
          let step;
          if (retained && open && (!phase || open.phase === phase)) {
            step = attach(open.step, event);
            open.step.conclusion = `Kept candidate ${short(value, 40)}`;
            if (open.step.kind === "review") { open.step.outcome = "retained"; }
          } else {
            step = create(event, {kind: "hypothesis", semantic_kind: revised ? "HYPOTHESIS_REVISION" : "REPORT",
              title: revised ? `${who} revised its answer from ${short(previousValue, 30)} to ${short(value, 30)}`
                : retained ? `${who} kept its answer ${short(value, 30)}` : `${who} reported its answer: ${short(value, 40)}`,
              text: revised ? `After ${String(phase || "review").replace(/_/g, " ")}, the earlier answer ${short(previousValue, 40)} is no longer held.`
                : `Candidate answer ${short(value, 60)} (a worker claim, not the coordinator's estimate).`,
              outcome: revised ? "revised" : retained ? "retained" : "completed", value, phase,
              toolCallRefs: p.tool_call_refs || (p.evidence_references || []).filter((r) => String(r).startsWith("tool_call:")).map((r) => String(r).slice(10))});
            if (p.uncertainty) step.facts.push(["Reported limitation", p.uncertainty]);
            if (open) {
              step.related_step_ids.push(open.step.id);
              if (revised && (!phase || open.phase === phase)) {
                open.step.conclusion = `Revised its answer from ${short(previousValue, 30)} to ${short(value, 30)}`;
                open.step.outcome = "revised";
              }
            }
          }
          step.reportEventId = event.event_id;
          reportStepByEvent.set(event.event_id, step);
          step.value = value;
          reportByAgent.set(agent, step);
          for (const pending of pendingNotebook.get(agent) || []) { attach(step, pending); step.memory.push(`Findings saved to the optional notebook (${String(pending.payload?.phase || "").replace(/_/g, " ")})`); }
          pendingNotebook.delete(agent);
          break;
        }
        case "WORKER_FINISHED": case "PEER_REVIEW_FINISHED": case "FOLLOW_UP_FINISHED": {
          lastTool.delete(agent);
          const failed = event.status === "failed" || String(p.status || "").toUpperCase() === "FAILED";
          if (failed) {
            const step = failure(event, type === "WORKER_FINISHED" ? `${who} stopped without a usable answer`
              : `${who}'s ${type === "PEER_REVIEW_FINISHED" ? "peer review" : "further investigation"} failed`,
            short(p.failure_reason || p.error || p.uncertainty || "The worker failed.", 220));
            const open = openPhase.get(agent);
            if (open) { open.step.status = "failed"; open.step.outcome = "execution_failure"; step.related_step_ids.push(open.step.id); openPhase.delete(agent); }
            for (const pending of pendingNotebook.get(agent) || []) attach(step, pending);
            pendingNotebook.delete(agent);
            break;
          }
          const open = openPhase.get(agent);
          const target = type !== "WORKER_FINISHED" && open ? open.step : reportByAgent.get(agent);
          if (target) { attach(target, event); if (type !== "WORKER_FINISHED") { target.status = "completed"; openPhase.delete(agent); } }
          else technical.push(event.event_id);
          break;
        }
        case "PEER_REVIEW_STARTED": {
          const claims = (p.message_ids || []).map((id) => messageStep.get(id)).filter(Boolean);
          const step = create(event, {kind: "review", semantic_kind: "PEER_REVIEW", status: "running", outcome: "running",
            title: `${who} reviewed ${(p.message_ids || []).length} peer claim${(p.message_ids || []).length === 1 ? "" : "s"}`,
            text: "Checks other workers' reports as untrusted claims."});
          step.related_step_ids.push(...new Set(claims.map((s) => s.id)));
          openPhase.set(agent, {phase: "peer_review", step});
          break;
        }

        // ---- optional memory (folded into the step it served) --------------------
        case "OPTIONAL_MEMORY_WRITTEN": {
          const open = openPhase.get(agent);
          if (open && open.phase === p.phase) { attach(open.step, event); open.step.memory.push("Findings saved to the optional notebook"); }
          else pendingNotebook.set(agent, [...(pendingNotebook.get(agent) || []), event]);
          break;
        }
        case "OPTIONAL_MEMORY_READ": {
          const open = openPhase.get(agent);
          if (open && open.phase === p.phase) { attach(open.step, event); open.step.memory.push(`Retrieved ${p.entries} earlier notebook entr${p.entries === 1 ? "y" : "ies"}`); }
          else create(event, {kind: "memory", semantic_kind: "MEMORY_RETRIEVAL", title: `${who} retrieved earlier findings`,
            text: `Retrieved ${p.entries} notebook entr${p.entries === 1 ? "y" : "ies"} from its optional private memory.`});
          break;
        }

        // ---- coordinator answer state ------------------------------------------
        case "COORDINATOR_REASSESSMENT_RECORDED": {
          const outcome = p.outcome;
          if (outcome === "retained" && (p.estimate === null || p.estimate === undefined)) {
            const step = create(event, {kind: "assessment", semantic_kind: "ASSESSMENT", agent: "coordinator", outcome: "unresolved",
              title: "Coordinator could not yet form an estimate", text: `Reviewed ${(p.evidence || []).length} worker report(s); no value is supported yet.`,
              evidence: p.evidence || []});
            if (p.assessment_summary) step.facts.push(["Coordinator's assessment", p.assessment_summary]);
          } else if (outcome === "retained") {
            const step = create(event, {kind: "assessment", semantic_kind: "ASSESSMENT", agent: "coordinator", level: "minor", outcome: "retained",
              title: `Coordinator kept its estimate ${short(p.estimate, 30)}`, text: `Reviewed ${(p.evidence || []).length} new report(s); the estimate did not change.`, evidence: p.evidence || []});
            if (p.assessment_summary) step.facts.push(["Coordinator's assessment", p.assessment_summary]);
          } else if (outcome === "skipped_budget") {
            create(event, {kind: "assessment", semantic_kind: "BUDGET", agent: "coordinator", outcome: "budget",
              title: "Coordinator skipped a reassessment (budget)", text: "Not enough model budget remained for another reassessment and the final synthesis."});
          } else if (outcome === "unreadable") {
            failure(event, "Coordinator's reassessment could not be read", "The previous estimate stays current.");
          } else {
            create(event, {kind: "assessment", semantic_kind: "ASSESSMENT", agent: "coordinator", level: "minor", title: "Coordinator skipped a reassessment",
              text: "The configured reassessment limit was reached."});
          }
          break;
        }
        case "COORDINATOR_ESTIMATE_UPDATED": {
          const change = p.change_kind;
          if (change === "finalized") {
            finalStep = finalStep || create(event, {kind: "final", semantic_kind: "FINAL", agent: "coordinator", title: "Coordinator is finalizing the answer", status: "running", outcome: "running"});
            attach(finalStep, event);
            finalStep.estimateNote = p.estimate === null ? "abstained" : p.previous_estimate !== null && p.previous_estimate !== undefined && !p.value_changed
              ? `confirms its provisional estimate ${short(p.previous_estimate, 30)}` : p.previous_estimate !== null && p.previous_estimate !== undefined
                ? `changes its provisional estimate ${short(p.previous_estimate, 30)}` : "no provisional estimate preceded it";
            finalStep.evidence = p.evidence || [];
            break;
          }
          const step = create(event, {kind: "estimate", semantic_kind: "ESTIMATE", agent: "coordinator", evidence: p.evidence || [],
            title: {initial: `Coordinator formed a provisional estimate: ${short(p.estimate, 30)}`, restored: `Coordinator restored an estimate: ${short(p.estimate, 30)}`,
              revised: `Coordinator revised its estimate: ${short(p.previous_estimate, 30)} → ${short(p.estimate, 30)}`,
              withdrawn: `Coordinator withdrew its estimate ${short(p.previous_estimate, 30)}`}[change] || "Coordinator updated its answer state",
            text: change === "withdrawn" ? "No value is currently supported; the answer is unresolved."
              : p.summary ? `Coordinator's assessment: ${short(p.summary, 180)}` : "",
            outcome: {initial: "provisional", restored: "provisional", revised: "estimate_revised", withdrawn: "withdrawn"}[change] || "info"});
          if (p.summary) step.facts.push(["Coordinator's assessment", p.summary]);
          if (p.revision_reason) step.facts.push(["Recorded reason", p.revision_reason]);
          step.facts.push(["Reports considered", (p.evidence || []).map((item) => `${agentLabel(item.worker_id)}: ${short(item.candidate_answer, 30)}`).join("; ") || "none recorded"]);
          break;
        }
        case "COORDINATOR_SYNTHESIS": case "FINAL_SYNTHESIZED":
          finalStep = finalStep || create(event, {kind: "final", semantic_kind: "FINAL", agent: "coordinator", title: "Coordinator is finalizing the answer", status: "running", outcome: "running"});
          attach(finalStep, event);
          if (Array.isArray(p.candidate_answers)) finalStep.candidates = p.candidate_answers;
          break;
        case "FINAL_ANSWER_RECORDED": {
          finalStep = finalStep || create(event, {kind: "final", semantic_kind: "FINAL", agent: "coordinator"});
          attach(finalStep, event);
          const value = p.final_answer ?? p.answer;
          finalStep.value = value; finalStep.status = "completed"; finalStep.outcome = "final"; finalStep.primaryEventId = event.event_id;
          finalStep.title = `Coordinator finalized the answer: ${short(value, 60)}`;
          break;
        }
        case "RUN_COMPLETED":
          if (finalStep) attach(finalStep, event); else technical.push(event.event_id);
          break;

        // ---- rounds (dividers, not counted as steps) -------------------------------
        case "INVESTIGATION_ROUND_STARTED": {
          verificationKey.round = p.round || verificationKey.round;
          const step = create(event, {kind: "round", semantic_kind: "ROUND", agent: "orchestrator", level: "divider",
            title: `Round ${p.round} · ${String(p.kind || "").replace(/_/g, " ")}`, text: `${(p.workers || []).map(agentLabel).join(", ")}`});
          roundStep.set(p.round, step);
          break;
        }
        case "INVESTIGATION_ROUND_COMPLETED": {
          const step = roundStep.get(p.round);
          if (step) { attach(step, event); step.reports = p.reports; } else technical.push(event.event_id);
          break;
        }

        // ---- failures that affect the investigation --------------------------------
        case "BUDGET_UPDATED":
          if (p.granted === false) {
            const resource = String(p.resource || "execution").replace(/_/g, " ");
            failure(event, `${who} exhausted its ${resource} budget`, `Reservation denied (${String(p.reason || "limit").replace(/_/g, " ")}).`, "budget");
          } else technical.push(event.event_id);
          break;
        case "MODEL_REQUEST_FAILED":
          failure(event, `${who}'s model request failed`, short(p.error, 220));
          break;
        case "RUN_FAILED":
          failure(event, "The run stopped", short(p.error, 220), String(p.error || "").toLowerCase().includes("budget") ? "budget" : "execution_failure");
          break;
        case "RUN_CANCELLED":
          failure(event, "The run was cancelled", short(p.reason, 220), "inconclusive");
          break;
        case "SCHEDULER_CONFIGURED":
        case "SCHEDULER_TASK_STARTED":
        case "SCHEDULER_TASK_FINISHED":
          technical.push(event.event_id);
          break;
        case "PLAN_CANDIDATES_GENERATED": {
          // A worker's declared action plan is one major step; its tool actions appear as normal tool steps.
          const plan = p.plan || {};
          const branches = plan.branches || [];
          const primary = branches[0]?.actions || [];
          const independent = primary.filter((a) => !(a.depends_on || []).length).length;
          const proposer = plan.estimates?.proposer === "scripted fixture policy" ? "a scripted test policy" : plan.origin_type === "model" ? "the model" : String(plan.origin_type || "unknown").replace("_", " ");
          const step = create(event, {kind: "plan", semantic_kind: "ACTION_PLAN",
            title: `${who} proposed an action plan`,
            text: `${primary.length} action${primary.length === 1 ? "" : "s"}${independent > 1 ? `, ${independent} independent (run at the same time)` : ""}` +
              `${branches.length > 1 ? `; ${branches.length - 1} alternative${branches.length > 2 ? "s" : ""} if the goal is not reached` : ""}. Proposed by ${proposer}.`,
            list: branches.map((b) => `${b.name}${b.origin_type === "controller_heuristic" ? " (controller heuristic)" : ""}: ` +
              (b.actions || []).map((a) => String(a.tool).replace(/_Tool$/, "").replace(/_/g, " ")).join(" → "))});
          planStep.set(plan.plan_id, step);
          break;
        }
        case "PLAN_SELECTED": case "REPLAN_COMPLETED": case "PLAN_EXECUTION_COMPLETED": {
          const step = planStep.get(p.plan_id);
          if (!step) { technical.push(event.event_id); break; }
          attach(step, event);
          if (event.event_type === "PLAN_SELECTED" && p.decision?.speculation?.chosen?.length) step.facts.push(["Speculation", `started ${p.decision.speculation.chosen.join(", ")} early`]);
          if (event.event_type === "REPLAN_COMPLETED") step.facts.push(["Replanned", `switched to ${p.next_branch}${p.was_speculative ? " (already running)" : ""}`]);
          if (event.event_type === "PLAN_EXECUTION_COMPLETED") step.facts.push(["Outcome", p.satisfied ? `goal reached (${p.winning_branch})` : "goal not reached"]);
          break;
        }
        case "SPECULATIVE_RESULT_ADOPTED": {
          const branch = String(p.branch_id || "").split(".").at(-1);
          create(event, {kind: "plan", semantic_kind: "SPECULATION_ADOPTED", title: `${who} adopted the speculative ${branch} result`,
            text: `This branch started early while the first approach ran; its ${(p.adopted_actions || []).length} finished result(s) now enter the agent's evidence. No tool ran twice.`});
          break;
        }
        case "PLANNING_CONFIGURED":
        case "PLANNING_POOL_STARTED":
        case "PLAN_EVALUATION_STARTED":
        case "PLAN_EVALUATION_COMPLETED":
        case "PLAN_EVALUATION_SKIPPED":
        case "PLAN_TASK_PRUNED":
        case "SPECULATIVE_TASK_ADMITTED":
        case "SPECULATIVE_TASK_STARTED":
        case "SPECULATIVE_TASK_COMPLETED":
        case "SPECULATIVE_TASK_CANCEL_REQUESTED":
        case "SPECULATIVE_TASK_PRUNED":
        case "REPLAN_TRIGGERED":
          // PARSEC-VL queue bookkeeping: Technical Trace only. A failed tool call
          // is already told by its TOOL_CALL_FAILED step.
          technical.push(event.event_id);
          break;
        default:
          // Unknown or technical types stay in the trace unless they report a failure.
          if (event.status === "failed") failure(event, `${who}: ${short(event.summary || "An operation failed", 80)}`, short(event.summary, 200));
          else technical.push(event.event_id);
      }
    }
    for (const step of steps) finish(step);
    Object.defineProperty(steps, "technicalEventIds", {value: technical.filter((id) => !stepOf.has(id)), enumerable: false});
    return steps;
  }

  /** Final human-readable title/summary for steps whose text depends on accumulated state. */
  function finish(step) {
    const who = agentLabel(step.agent);
    if (step.kind === "tool") {
      const tool = toolLabel(step.tool);
      step.title = step.status === "running" ? `${who} is using ${tool}`
        : step.outcome === "budget" ? `${who} could not use ${tool} (budget exhausted)`
          : step.status === "failed" ? `${who}'s ${tool} call failed` : `${who} used ${tool}`;
      step.text = step.status === "running" ? `${tool} is running.` : `${tool} ${step.observation || "completed"}.`;
    }
    if (step.kind === "plan" && step.started?.length) step.facts = [["Started", step.started.join(", ")]];
    if (step.kind === "delegation" && step.started?.length) step.facts = [["Started", step.started.join(", ")]];
    if (step.kind === "hypothesis") {
      const extra = [];
      if (step.reportedTo) extra.push("reported to the coordinator");
      if (step.sharedWith?.length) extra.push(`shared with ${step.sharedWith.join(", ")}`);
      if (extra.length) step.delivery = `${extra.join("; ")}.`;
    }
    if (step.kind === "review" && step.conclusion) step.text = `${step.conclusion} after checking peer claims as untrusted reports.`;
    if (step.kind === "final") {
      step.text = [step.estimateNote ? `This ${step.estimateNote}.` : "", step.candidates?.length ? `Worker candidates considered: ${step.candidates.join(", ")}.` : ""].filter(Boolean).join(" ");
    }
    if (step.kind === "task" && step.config) {
      const c = step.config;
      step.facts = [["Configuration", `${c.num_workers} worker(s) · optional memory ${c.optional_worker_memory_enabled ? "on" : "off"} · peer communication ${c.peer_communication_enabled ? "on" : "off"} · ${c.execution_mode} · coordinator estimates ${c.coordinator_estimate_updates?.enabled ? "on" : "off"}`]];
    }
    step.outcomeText = OUTCOME_TEXT[step.outcome] ?? "";
    step.eventIds = step.source_event_ids;
    step.step_id = step.id;
    step.minor = step.level !== "main";
    step.resultSummary = step.observation;
    return step;
  }

  /**
   * Steps causally linked to an estimate/assessment/final step through recorded
   * references: report events, delivery events, and the tool calls each report
   * cited. Returns step ids (excluding the step itself).
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
      if (other.source_event_ids.some((id) => eventIds.has(id))) result.add(other.id);
      if (other.kind === "tool" && other.toolCallId && toolKeys.has(`${other.agent}|${other.toolCallId}`)) result.add(other.id);
    }
    return result;
  }

  /** Main (numbered) steps, as shown by default. */
  function mainSteps(steps) { return steps.filter((step) => step.level === "main"); }

  return {buildStory, linkedSteps, mainSteps, summarizeResult, agentLabel, toolLabel, OUTCOME_TEXT};
});
