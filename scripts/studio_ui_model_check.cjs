#!/usr/bin/env node
/*
 * UI-model checks for recorded runs, using the real Studio frontend modules.
 *
 * stdin: JSON array of {snapshot, expected: {workers, memory, peer}} where
 * snapshot is the public /api/runs/<id>/snapshot payload. stdout: JSON array of
 * {passed, detail} in the same order. Used by scripts/studio_config_matrix.py.
 */
"use strict";
const path = require("node:path");
const fs = require("node:fs");
const STATIC = path.join(__dirname, "..", "openvlharness", "studio", "static");
global.self = global;
const Activity = require(path.join(STATIC, "activity-state.js"));
global.StudioActivity = Activity;
const Answer = require(path.join(STATIC, "answer-state.js"));
const Story = require(path.join(STATIC, "story.js"));
const Team = require(path.join(STATIC, "team-view.js"));

function check({snapshot, expected}) {
  const problems = [];
  const events = snapshot.events;
  const model = Team.teamModel(snapshot.topology, snapshot.effective_config);
  if (!model.coordinator) problems.push("no coordinator card");
  if (model.workers.length !== expected.workers) problems.push(`worker cards ${model.workers.length} != ${expected.workers}`);
  const memory = expected.memory ? "on" : "off";
  const peer = expected.peer ? (expected.workers > 1 ? "on" : "on_single") : "off";
  for (const worker of model.workers) {
    if (worker.memory !== memory) problems.push(`${worker.id} memory ${worker.memory} != ${memory}`);
    if (worker.peer !== peer) problems.push(`${worker.id} peer ${worker.peer} != ${peer}`);
    if (!worker.tools.length) problems.push(`${worker.id} has no tool chips`);
  }
  const ids = new Set([model.coordinator?.id, ...model.workers.map((w) => w.id)]);
  if (ids.size !== expected.workers + 1) problems.push("duplicate harness cards");
  // Replay correctness: at every prefix the estimate equals the last recorded estimate event.
  let last = null; let finalSeen = null;
  for (let k = 0; k <= events.length; k += 1) {
    const state = Answer.foldAnswerState(events, k, {effectiveConfig: snapshot.effective_config});
    const expectedValue = last ? last.payload.estimate : null;
    const expectedStatus = last ? last.payload.status : "none";
    if (state.estimate.value !== expectedValue || state.estimate.status !== expectedStatus) { problems.push(`prefix ${k}: estimate ${state.estimate.value}/${state.estimate.status}`); break; }
    if ((state.final?.value ?? null) !== (finalSeen ?? null)) { problems.push(`prefix ${k}: final shown early`); break; }
    const event = events[k];
    if (event?.event_type === "COORDINATOR_ESTIMATE_UPDATED") last = event;
    if (event?.event_type === "FINAL_ANSWER_RECORDED") finalSeen = event.payload.final_answer;
  }
  const full = Answer.foldAnswerState(events, events.length, {effectiveConfig: snapshot.effective_config});
  if (String(full.final?.value) !== String(snapshot.final.final_answer)) problems.push(`final ${full.final?.value} != ${snapshot.final.final_answer}`);
  if (full.mode !== "recorded") problems.push(`estimate mode ${full.mode}`);
  const steps = Story.buildStory(events);
  // Finalization is folded into the final-answer step; every other change is its own step.
  const estimateSteps = steps.filter((s) => s.kind === "estimate").length + steps.filter((s) => s.kind === "final"
    && s.source_event_ids.some((id) => events.find((e) => e.event_id === id)?.event_type === "COORDINATOR_ESTIMATE_UPDATED")).length;
  const estimateEvents = events.filter((e) => e.event_type === "COORDINATOR_ESTIMATE_UPDATED").length;
  if (estimateSteps !== estimateEvents) problems.push(`story estimate steps ${estimateSteps} != ${estimateEvents}`);
  const toolSteps = steps.filter((s) => s.kind === "tool").length;
  const toolEvents = events.filter((e) => e.event_type === "TOOL_CALL_REQUESTED").length;
  if (toolSteps !== toolEvents) problems.push(`story tool steps ${toolSteps} != ${toolEvents}`);
  const linked = steps.filter((s) => s.kind === "estimate").map((s) => Story.linkedSteps(s, steps).size);
  if (!linked.some((n) => n > 0)) problems.push("no estimate step links to recorded evidence");
  const activity = Activity.computeState(snapshot.topology, events, events.length);
  for (const worker of model.workers) if (!activity.agents.get(worker.id)) problems.push(`${worker.id} missing from activity state`);
  return {passed: problems.length === 0, detail: problems.join("; ") || `${model.workers.length} worker cards, ${steps.length} story steps, ${estimateEvents} estimate states, replay-safe at ${events.length + 1} prefixes`};
}

const input = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(input.map(check)));
