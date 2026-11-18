// Simple team picture: traffic counts and the highlighted flow come only from recorded events.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

global.self = global;
const Simple = require(path.resolve(__dirname, "../../../openvlharness/studio/static/simple-team.js"));

const ev = (event_type, agent_id, payload = {}, extra = {}) => ({event_type, agent_id, payload, ...extra});

test("traffic counts assignments, reports and peer messages from MESSAGE_SENT", () => {
  const t = Simple.traffic([
    ev("MESSAGE_SENT", "coordinator", {recipient_id: "worker_01"}),
    ev("MESSAGE_SENT", "coordinator", {recipient_id: "worker_02"}),
    ev("MESSAGE_SENT", "coordinator", {recipient_id: "worker_01"}),
    ev("MESSAGE_SENT", "worker_01", {recipient_id: "coordinator"}),
    ev("MESSAGE_SENT", "worker_02", {recipient_id: "worker_01"}),
    ev("MESSAGE_SENT", "worker_01", {recipient_id: "worker_02"}),
    ev("HYPOTHESIS_UPDATED", "worker_01", {hypothesis: 5}),
  ]);
  assert.equal(t.assign.get("worker_01"), 2);
  assert.equal(t.assign.get("worker_02"), 1);
  assert.equal(t.report.get("worker_01"), 1, "a recorded report message wins over the answer count");
  assert.equal(t.peer.get("worker_01|worker_02"), 2, "both directions share one undirected pair");
});

test("without a message bus, reports fall back to recorded answers; nothing is invented", () => {
  const t = Simple.traffic([ev("HYPOTHESIS_UPDATED", "worker_02", {hypothesis: 3}), ev("HYPOTHESIS_UPDATED", "worker_02", {hypothesis: 4})]);
  assert.equal(t.report.get("worker_02"), 2);
  assert.equal(t.assign.size, 0);
  assert.equal(t.peer.size, 0);
  assert.equal(Simple.traffic([]).report.size, 0);
});

test("activeFlow reads the event's activity annotation only", () => {
  assert.deepEqual(Simple.activeFlow(ev("TOOL_CALL_REQUESTED", "worker_01", {}, {tool_name: "Zoom_In_Tool", activity: {kind: "tool_request"}})),
    {type: "tool", agent: "worker_01", tool: "Zoom_In_Tool"});
  assert.deepEqual(Simple.activeFlow(ev("MESSAGE_SENT", "coordinator", {}, {activity: {kind: "message", sender: "coordinator", recipient: "worker_02"}})), {type: "assign", worker: "worker_02"});
  assert.deepEqual(Simple.activeFlow(ev("MESSAGE_SENT", "worker_02", {}, {activity: {kind: "message", recipient: "coordinator"}})), {type: "report", worker: "worker_02"});
  assert.deepEqual(Simple.activeFlow(ev("MESSAGE_SENT", "worker_02", {}, {activity: {kind: "message", recipient: "worker_01"}})), {type: "peer", key: "worker_01|worker_02"});
  assert.equal(Simple.activeFlow(ev("RUN_STARTED", "orchestrator")), null, "no annotation, no highlight");
  assert.equal(Simple.activeFlow(null), null);
});

test("labels and badges", () => {
  assert.equal(Simple.label("worker_03"), "Worker 3");
  assert.equal(Simple.badge("coordinator"), "C");
  assert.equal(Simple.badge("worker_12"), "W12");
  assert.equal(Simple.toolLabel("Visual_Grounding_Tool"), "Visual Grounding");
});
