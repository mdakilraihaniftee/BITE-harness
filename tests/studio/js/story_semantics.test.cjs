// Semantic investigation-story grouping and causality tests (node --test).
// Event sequences are written out explicitly so every grouping rule is checked
// against a known causal structure (invocations, message IDs, report IDs).
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

global.self = global;
const Story = require(path.resolve(__dirname, "../../../openvlharness/studio/static/story.js"));

function recorder() {
  const events = [];
  const add = (event_type, agent_id, payload = {}, extra = {}) => {
    const event = {event_id: extra.id || `e${events.length}`, sequence: events.length, event_type, agent_id, payload,
      status: extra.status || "completed", summary: extra.summary || event_type, tool_name: extra.tool || null,
      artifact_refs: extra.artifacts || [], causal_refs: [], parent_event_id: null};
    events.push(event);
    return event;
  };
  return {events, add};
}

/** One full tool invocation: decision, request, start, result, evidence, working-memory write. */
function toolCall(r, agent, tool, inv, {fail = null, result = {boxes: [[1, 2, 3, 4]]}, callId = "call_0", stopBefore = null} = {}) {
  const p = {invocation_id: inv, tool_call_id: callId};
  const steps = [
    ["DECISION_SUMMARY_RECORDED", {...p, rationale_recorded: false, action_intent: `Invoke ${tool}`}],
    ["TOOL_CALL_REQUESTED", {...p, arguments: {query: "grapes"}}],
    ["TOOL_CALL_STARTED", p],
    fail ? ["TOOL_CALL_FAILED", {...p, error: fail}] : ["TOOL_CALL_COMPLETED", {...p, canonical_result: result}],
    ["EVIDENCE_OBSERVED", p],
    ["MEMORY_WRITTEN", {...p, memory_kind: "working_context"}],
  ];
  for (const [type, payload] of steps) {
    if (stopBefore === type) return;
    if (fail && (type === "EVIDENCE_OBSERVED" || type === "MEMORY_WRITTEN")) continue;
    r.add(type, agent, payload, {tool, status: type === "TOOL_CALL_FAILED" ? "failed" : "completed"});
  }
}

function plan(r, workers) {
  const assignments = workers.map((w, i) => ({assignment_id: `a${i}`, worker_id: w, scope: `scope for ${w}`}));
  r.add("RUN_STARTED", "orchestrator", {});
  r.add("TASK_RECEIVED", "orchestrator", {original_task: "How many grapes?"});
  r.add("MODEL_REQUEST_STARTED", "coordinator", {request_id: "m0"});
  r.add("MODEL_RESPONSE_RECEIVED", "coordinator", {request_id: "m0"});
  r.add("BUDGET_UPDATED", "coordinator", {resource: "model_requests", granted: true});
  r.add("COORDINATOR_PLAN_RECORDED", "coordinator", {assignments});
  for (const a of assignments) {
    r.add("MESSAGE_SENT", "coordinator", {message_id: `m_${a.assignment_id}`, recipient_id: a.worker_id, message_type: "TASK_ASSIGNMENT", content: JSON.stringify(a)});
    r.add("MESSAGE_DELIVERED", a.worker_id, {message_id: `m_${a.assignment_id}`, sender_id: "coordinator", message_type: "TASK_ASSIGNMENT"});
    r.add("WORKER_STARTED", a.worker_id, {assignment_id: a.assignment_id, phase: "initial"});
  }
}

const main = (steps) => Story.mainSteps(steps);
const byKind = (steps, kind) => steps.filter((s) => s.kind === kind);

test("scheduler bookkeeping never becomes a fabricated empty action plan", () => {
  const r = recorder();
  for (const type of ["SCHEDULER_CONFIGURED", "SCHEDULER_TASK_STARTED", "SCHEDULER_TASK_FINISHED"]) {
    r.add(type, "worker_01", {task_id: "tool1", operation: "OCR_Tool"});
  }
  assert.equal(main(Story.buildStory(r.events)).length, 0);
  r.add("PLAN_CANDIDATES_GENERATED", "worker_01", {plan: {plan_id: "p1", origin_type: "model",
    branches: [{name: "primary", actions: [{id: "ocr", tool: "OCR_Tool", depends_on: []}]}]}});
  const steps = main(Story.buildStory(r.events));
  assert.equal(steps.length, 1);
  assert.equal(steps[0].semantic_kind, "ACTION_PLAN");
  assert.match(steps[0].text, /1 action.*the model/);
});

test("an actually recorded empty action plan remains visible", () => {
  const r = recorder();
  r.add("PLAN_CANDIDATES_GENERATED", "worker_01", {plan: {plan_id: "empty", origin_type: "model", branches: []}});
  const steps = main(Story.buildStory(r.events));
  assert.equal(steps.length, 1);
  assert.match(steps[0].text, /0 actions/);
});

test("1-3: requested/started/completed/evidence become one card updated in place", () => {
  const r = recorder(); plan(r, ["worker_01"]);
  toolCall(r, "worker_01", "Zoom_In_Tool", "inv1", {result: {crop_bounds: [0, 0, 50, 40]}});
  const steps = Story.buildStory(r.events);
  const tools = byKind(steps, "tool");
  assert.equal(tools.length, 1);
  assert.equal(tools[0].source_event_ids.length, 6);
  assert.equal(tools[0].status, "completed");
  assert.match(tools[0].observation, /crop of 50×40 px/);
  assert.equal(tools[0].intent, null, "no rationale recorded -> no invented intent");
  assert.ok(tools[0].memory.length, "memory write folded into the step");
  // Running state at an earlier replay position, same stable ID.
  const before = byKind(Story.buildStory(r.events.slice(0, r.events.length - 3)), "tool")[0];
  assert.equal(before.id, tools[0].id);
  assert.equal(before.status, "running");
  assert.equal(before.observation, null);
});

test("4: ordinary memory writes, model calls, budget grants and deliveries create no cards", () => {
  const r = recorder(); plan(r, ["worker_01"]);
  toolCall(r, "worker_01", "Visual_Grounding_Tool", "inv1");
  r.add("MEMORY_READ", "worker_01", {memory_kind: "working_context"});
  const steps = Story.buildStory(r.events);
  assert.deepEqual(main(steps).map((s) => s.kind), ["task", "plan", "tool"]);
  const technical = new Set(steps.technicalEventIds);
  for (const e of r.events.filter((x) => ["MODEL_REQUEST_STARTED", "MODEL_RESPONSE_RECEIVED", "BUDGET_UPDATED", "MEMORY_READ", "RUN_STARTED"].includes(x.event_type))) assert.ok(technical.has(e.event_id), e.event_type);
});

test("5,7: assignment delivery is part of the plan; revisions and notebook writes fold correctly", () => {
  const r = recorder(); plan(r, ["worker_01"]);
  const planStep = byKind(Story.buildStory(r.events), "plan")[0];
  assert.equal(planStep.source_event_ids.length, 4, "plan + send + delivery + worker start");
  toolCall(r, "worker_01", "Visual_Grounding_Tool", "inv1");
  r.add("OPTIONAL_MEMORY_WRITTEN", "worker_01", {phase: "initial"});
  const report = r.add("HYPOTHESIS_UPDATED", "worker_01", {hypothesis: "50", revision_kind: "initial", phase: "initial"});
  r.add("MESSAGE_SENT", "worker_01", {message_id: "rep1", recipient_id: "coordinator", message_type: "CANDIDATE_ANSWER", content: "{}", metadata: {report_event_id: report.event_id}});
  r.add("MESSAGE_DELIVERED", "coordinator", {message_id: "rep1", sender_id: "worker_01", message_type: "CANDIDATE_ANSWER"});
  r.add("WORKER_FINISHED", "worker_01", {status: "COMPLETED", phase: "initial"});
  r.add("PEER_REVIEW_STARTED", "worker_01", {message_ids: [], phase: "peer_review"});
  r.add("HYPOTHESIS_UPDATED", "worker_01", {hypothesis: "46", previous_hypothesis: "50", revision_kind: "revised", phase: "peer_review"});
  const steps = Story.buildStory(r.events);
  const reports = byKind(steps, "hypothesis");
  assert.equal(reports.length, 2);
  assert.equal(reports[0].source_event_ids.length, 5, "report + notebook + send + delivery + finish");
  assert.equal(reports[0].delivery, "reported to the coordinator.");
  assert.equal(reports[1].outcome, "revised");
  assert.match(reports[1].title, /50 to 46/);
});

test("6: estimate changes are main steps; unchanged reassessments are routine", () => {
  const r = recorder(); plan(r, ["worker_01"]);
  r.add("COORDINATOR_REASSESSMENT_RECORDED", "coordinator", {outcome: "retained", estimate: null, assessment_summary: "Counts conflict."});
  r.add("COORDINATOR_ESTIMATE_UPDATED", "coordinator", {change_kind: "initial", estimate: "12", status: "provisional", evidence: []});
  r.add("COORDINATOR_REASSESSMENT_RECORDED", "coordinator", {outcome: "retained", estimate: "12"});
  r.add("COORDINATOR_ESTIMATE_UPDATED", "coordinator", {change_kind: "revised", previous_estimate: "12", estimate: "13", status: "revised", evidence: []});
  r.add("COORDINATOR_SYNTHESIS", "coordinator", {candidate_answers: ["13"]});
  r.add("COORDINATOR_ESTIMATE_UPDATED", "coordinator", {change_kind: "finalized", previous_estimate: "13", estimate: "13", value_changed: false, status: "final", evidence: []});
  r.add("FINAL_ANSWER_RECORDED", "coordinator", {final_answer: "13"});
  r.add("RUN_COMPLETED", "orchestrator", {final_answer: "13"});
  const steps = Story.buildStory(r.events);
  assert.deepEqual(main(steps).slice(2).map((s) => s.title), [
    "Coordinator could not yet form an estimate",
    "Coordinator formed a provisional estimate: 12",
    "Coordinator revised its estimate: 12 → 13",
    "Coordinator finalized the answer: 13",
  ]);
  assert.ok(steps.some((s) => s.level === "minor" && s.outcome === "retained"));
  const final = byKind(steps, "final")[0];
  assert.equal(final.source_event_ids.length, 4, "synthesis + finalization + final answer + run completed");
  assert.match(final.text, /confirms its provisional estimate 13/);
});

test("8: questions and replies need a valid correlation", () => {
  const r = recorder(); plan(r, ["worker_01", "worker_02"]);
  r.add("MESSAGE_SENT", "worker_01", {message_id: "q1", recipient_id: "worker_02", message_type: "QUESTION", content: "Is region 3 a grape?", channel: "peer"});
  r.add("MESSAGE_DELIVERED", "worker_02", {message_id: "q1", sender_id: "worker_01"});
  r.add("MESSAGE_SENT", "worker_02", {message_id: "r1", recipient_id: "worker_01", message_type: "EVIDENCE", correlation_id: "q1", content: "{\"claim\": \"no\"}", channel: "peer"});
  // Same correlation but from an unrelated sender: not a reply.
  r.add("MESSAGE_SENT", "worker_03", {message_id: "x1", recipient_id: "worker_01", message_type: "EVIDENCE", correlation_id: "q1", content: "{\"claim\": \"yes\"}", channel: "peer"});
  const steps = byKind(Story.buildStory(r.events), "communication");
  assert.equal(steps.length, 3);
  assert.equal(steps[0].title, "Worker 1 asked Worker 2");
  assert.equal(steps[0].source_event_ids.length, 2, "delivery folded into the question");
  assert.equal(steps[1].semantic_kind, "REPLY");
  assert.deepEqual(steps[1].related_step_ids, [steps[0].id]);
  assert.notEqual(steps[2].semantic_kind, "REPLY");
});

test("9-10: tool failures and budget stops stay visible and are distinguished", () => {
  const r = recorder(); plan(r, ["worker_01"]);
  toolCall(r, "worker_01", "Depth_Estimation_Tool", "inv1", {fail: {code: "service_unavailable", message: "offline"}});
  toolCall(r, "worker_01", "Zoom_In_Tool", "inv2", {fail: {code: "budget_denied", message: "tool budget exhausted"}, callId: "call_1"});
  r.add("BUDGET_UPDATED", "worker_01", {resource: "model_requests", granted: false, reason: "actor_limit"}, {status: "failed"});
  r.add("MESSAGE_REJECTED", "worker_01", {message_id: "z", reason: "budget_denied"}, {status: "failed"});
  r.add("RUN_FAILED", "orchestrator", {error: "RuntimeError: boom"}, {status: "failed"});
  const steps = main(Story.buildStory(r.events));
  const outcomes = steps.filter((s) => s.kind === "tool" || s.kind === "failure").map((s) => s.outcome);
  assert.deepEqual(outcomes, ["execution_failure", "budget", "budget", "budget", "execution_failure"]);
  assert.match(steps.find((s) => s.outcome === "budget" && s.kind === "tool").title, /budget exhausted/);
});

test("concurrent same-tool calls by different workers never exchange results", () => {
  const r = recorder(); plan(r, ["worker_01", "worker_02"]);
  const req = (agent, inv) => {
    r.add("TOOL_CALL_REQUESTED", agent, {invocation_id: inv, tool_call_id: "call_0", arguments: {query: agent}}, {tool: "Visual_Grounding_Tool"});
    r.add("TOOL_CALL_STARTED", agent, {invocation_id: inv, tool_call_id: "call_0"}, {tool: "Visual_Grounding_Tool"});
  };
  req("worker_01", "invA"); req("worker_02", "invB");
  r.add("TOOL_CALL_COMPLETED", "worker_02", {invocation_id: "invB", tool_call_id: "call_0", canonical_result: {boxes: [[1, 1, 2, 2]]}}, {tool: "Visual_Grounding_Tool"});
  r.add("TOOL_CALL_COMPLETED", "worker_01", {invocation_id: "invA", tool_call_id: "call_0", canonical_result: {boxes: [[1, 1, 2, 2], [3, 3, 4, 4], [5, 5, 6, 6]]}}, {tool: "Visual_Grounding_Tool"});
  r.add("HYPOTHESIS_UPDATED", "worker_02", {hypothesis: "1", revision_kind: "initial", phase: "initial"});
  const steps = Story.buildStory(r.events);
  const tools = byKind(steps, "tool");
  assert.equal(tools.length, 2);
  const w1 = tools.find((s) => s.agent === "worker_01"); const w2 = tools.find((s) => s.agent === "worker_02");
  assert.match(w1.observation, /3 regions/); assert.match(w2.observation, /1 region\b/);
  assert.ok(w1.source_event_ids.every((id) => r.events.find((e) => e.event_id === id).agent_id === "worker_01"));
  assert.equal(w2.next, "reported candidate 1");
  assert.ok(!w1.next, "another worker's hypothesis is never attached as this worker's next step");
  assert.ok(!w1.source_event_ids.some((id) => r.events.find((e) => e.event_id === id).event_type === "HYPOTHESIS_UPDATED"));
});

test("replay: prefixes never show future results and step IDs are stable and deterministic", () => {
  const r = recorder(); plan(r, ["worker_01", "worker_02"]);
  toolCall(r, "worker_01", "Visual_Grounding_Tool", "inv1");
  r.add("HYPOTHESIS_UPDATED", "worker_01", {hypothesis: "12", revision_kind: "initial", phase: "initial"});
  r.add("COORDINATOR_ESTIMATE_UPDATED", "coordinator", {change_kind: "initial", estimate: "12", status: "provisional", evidence: []});
  toolCall(r, "worker_02", "Zoom_In_Tool", "inv2", {result: {candidates_found: 1}});
  r.add("FINAL_ANSWER_RECORDED", "coordinator", {final_answer: "13"});
  let previous = [];
  for (let k = 0; k <= r.events.length; k += 1) {
    const steps = Story.buildStory(r.events.slice(0, k));
    const ids = steps.map((s) => s.id);
    assert.deepEqual(ids.slice(0, previous.length), previous, `ids stable at ${k}`);
    const visible = new Set(r.events.slice(0, k).map((e) => e.event_id));
    for (const step of steps) for (const id of step.source_event_ids) assert.ok(visible.has(id), `future event in step at ${k}`);
    if (k < r.events.length) assert.ok(!steps.some((s) => s.kind === "final"), "final answer not shown early");
    assert.equal(JSON.stringify(steps), JSON.stringify(Story.buildStory(r.events.slice(0, k))), "deterministic");
    previous = ids;
  }
});

test("legacy events without invocation IDs, phases, or message metadata still group", () => {
  const r = recorder(); plan(r, ["worker_01", "worker_02"]);
  r.add("TOOL_CALL_REQUESTED", "worker_01", {tool_call_id: "c1", arguments: {}}, {tool: "Zoom_In_Tool"});
  r.add("TOOL_CALL_COMPLETED", "worker_01", {tool_call_id: "c1", result: {}}, {tool: "Zoom_In_Tool"});
  r.add("HYPOTHESIS_UPDATED", "worker_01", {hypothesis: "3", hypothesis_status: "supported_by_current_evidence"});
  r.add("MESSAGE_SENT", "worker_01", {message_id: "h1", recipient_id: "worker_02", message_type: "HYPOTHESIS", content: "{\"claim\": \"3\"}"});
  r.add("FINAL_SYNTHESIZED", "coordinator", {});
  r.add("FINAL_ANSWER_RECORDED", "coordinator", {final_answer: "3"});
  const steps = Story.buildStory(r.events);
  assert.equal(byKind(steps, "tool")[0].source_event_ids.length, 2);
  assert.equal(byKind(steps, "communication").length, 1, "a legacy peer claim stays separate without an explicit report link");
  assert.equal(byKind(steps, "final")[0].title, "Coordinator finalized the answer: 3");
});

test("owner checks apply to reused invocation IDs and activity correlations", () => {
  const r = recorder();
  for (const agent of ["worker_01", "worker_02"]) {
    r.add("TOOL_CALL_REQUESTED", agent, {invocation_id: "reused", arguments: {image_id: agent}}, {tool: "Zoom_In_Tool"});
    r.events.at(-1).activity = {correlation_id: "inv:reused"};
  }
  r.add("TOOL_CALL_COMPLETED", "worker_02", {invocation_id: "reused", canonical_result: {boxes: [[0, 0, 1, 1]]}}, {tool: "Zoom_In_Tool"});
  const tools = byKind(Story.buildStory(r.events), "tool");
  assert.equal(tools.length, 2);
  assert.equal(tools[0].status, "running");
  assert.equal(tools[1].status, "completed");
  for (const step of tools) assert.ok(step.source_event_ids.every((id) => r.events.find((e) => e.event_id === id).agent_id === step.agent));
});

test("parent and causal references group ID-less events, but reject cross-agent parents", () => {
  const r = recorder();
  const request = r.add("TOOL_CALL_REQUESTED", "worker_01", {arguments: {image_id: "input_image_1"}}, {tool: "Zoom_In_Tool"});
  const result = r.add("TOOL_CALL_COMPLETED", "worker_01", {canonical_result: {crop_bounds: [0, 0, 10, 20]}}, {tool: "Zoom_In_Tool"});
  result.parent_event_id = request.event_id;
  const evidence = r.add("EVIDENCE_OBSERVED", "worker_01", {supported_findings: ["The crop contains a candidate."]});
  evidence.causal_refs = [result.event_id];
  const other = r.add("TOOL_CALL_COMPLETED", "worker_02", {canonical_result: {boxes: []}}, {tool: "Zoom_In_Tool"});
  other.parent_event_id = request.event_id;
  const tools = byKind(Story.buildStory(r.events), "tool");
  assert.equal(tools.length, 2);
  assert.deepEqual(tools[0].source_event_ids, [request.event_id, result.event_id, evidence.event_id]);
  assert.equal(tools[0].interpretation.length, 1);
  assert.deepEqual(tools[1].source_event_ids, [other.event_id]);
});

test("reused legacy model call IDs open fresh steps on later turns", () => {
  const r = recorder();
  for (const count of [1, 2]) {
    r.add("DECISION_SUMMARY_RECORDED", "worker_01", {tool_call_id: "call_0"}, {tool: "Visual_Grounding_Tool"});
    r.add("TOOL_CALL_REQUESTED", "worker_01", {tool_call_id: "call_0", arguments: {query: "fruit"}}, {tool: "Visual_Grounding_Tool"});
    r.add("TOOL_CALL_COMPLETED", "worker_01", {tool_call_id: "call_0", canonical_result: {boxes: Array(count).fill([0, 0, 1, 1])}}, {tool: "Visual_Grounding_Tool"});
  }
  const tools = byKind(Story.buildStory(r.events), "tool");
  assert.equal(tools.length, 2);
  assert.equal(tools[0].source_event_ids.length, 3);
  assert.match(tools[0].observation, /1 region\b/);
  assert.match(tools[1].observation, /2 regions/);
});

test("identical uncorrelated messages remain distinct; another agent's report cannot own them", () => {
  const r = recorder();
  const report = r.add("HYPOTHESIS_UPDATED", "worker_01", {hypothesis: "3", revision_kind: "initial"});
  for (const message_id of ["q1", "q2"]) r.add("MESSAGE_SENT", "worker_02", {
    message_id, recipient_id: "worker_01", message_type: "QUESTION", content: "Verify region 3", metadata: {report_event_id: report.event_id},
  });
  const steps = Story.buildStory(r.events);
  assert.equal(byKind(steps, "communication").length, 2);
  assert.equal(byKind(steps, "hypothesis")[0].source_event_ids.length, 1);
  const action = r.add("TOOL_CALL_REQUESTED", "worker_02", {invocation_id: "inv1", arguments: {}}, {tool: "Zoom_In_Tool"});
  r.add("MESSAGE_SENT", "worker_02", {message_id: "q3", recipient_id: "worker_01", message_type: "QUESTION", content: "Inspect again",
    metadata: {report_event_id: action.event_id}});
  const withBadLink = Story.buildStory(r.events);
  assert.equal(byKind(withBadLink, "tool")[0].source_event_ids.length, 1, "report links must name real hypothesis events, not arbitrary actions");
  assert.equal(byKind(withBadLink, "communication").length, 3);
});

test("important technical failures, budget denials, and failed review remain visible", () => {
  const r = recorder();
  r.add("MEMORY_READ", "worker_01", {error: "Earlier evidence unavailable"}, {status: "failed", summary: "Earlier evidence unavailable"});
  r.add("BUDGET_UPDATED", "worker_01", {resource: "tool_calls", granted: false, reason: "actor_limit"}, {status: "failed"});
  r.add("TOOL_CALL_FAILED", "worker_02", {error: "offline"}, {status: "failed", tool: "Zoom_In_Tool"});
  r.add("PEER_REVIEW_STARTED", "worker_01", {message_ids: ["q1"]});
  r.add("PEER_REVIEW_FINISHED", "worker_01", {status: "FAILED", failure_reason: "Verification could not finish"}, {status: "failed"});
  const steps = main(Story.buildStory(r.events));
  assert.equal(steps.filter((s) => s.status === "failed").length, 5);
  assert.ok(steps.some((s) => s.outcome === "budget"));
  assert.ok(steps.some((s) => /peer review failed/.test(s.title)));
  assert.ok(steps.some((s) => /Earlier evidence unavailable/.test(s.text)));
});

test("single-agent identities retain tool actions and failed message delivery updates its card", () => {
  const r = recorder();
  toolCall(r, "main_agent", "Zoom_In_Tool", "single-inv");
  r.add("MESSAGE_SENT", "worker_01", {message_id: "q1", recipient_id: "worker_02", message_type: "QUESTION", content: "Please verify"});
  r.add("MESSAGE_DELIVERED", "worker_02", {message_id: "q1", error: "recipient unavailable"}, {status: "failed"});
  const steps = Story.buildStory(r.events);
  assert.equal(byKind(steps, "tool")[0].source_event_ids.length, 6);
  assert.equal(byKind(steps, "tool")[0].agent, "main_agent");
  const message = byKind(steps, "communication")[0];
  assert.equal(message.status, "failed");
  assert.equal(message.source_event_ids.length, 2);
  assert.ok(message.facts.some(([key]) => key === "Delivery failure"));
});
