// Answer-state, story, and compact-team unit tests (node --test).
// Data: STUDIO_ANSWER_DATA = JSON {runs: {name: snapshot}} from recorded fixture runs.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const STATIC = path.resolve(__dirname, "../../../openvlharness/studio/static");
global.self = global;
global.StudioActivity = require(path.join(STATIC, "activity-state.js"));
const Answer = require(path.join(STATIC, "answer-state.js"));
const Story = require(path.join(STATIC, "story.js"));
const Team = require(path.join(STATIC, "team-view.js"));
const {runs} = JSON.parse(fs.readFileSync(process.env.STUDIO_ANSWER_DATA, "utf8"));
const revision = runs.revision; // N=1: provisional 4 -> revised 5 -> final 5
const fold = (run, k) => Answer.foldAnswerState(run.events, k, {effectiveConfig: run.effective_config});
const indexOf = (run, type, n = 0) => run.events.map((e, i) => [e, i]).filter(([e]) => e.event_type === type)[n][1];

test("A: no estimate before the coordinator assesses (never zero, never a worker answer)", () => {
  const firstHypothesis = indexOf(revision, "HYPOTHESIS_UPDATED");
  const state = fold(revision, firstHypothesis + 1);
  assert.equal(state.estimate.status, "none");
  assert.equal(state.estimate.value, null);
  assert.equal(state.final, null);
  assert.equal(state.mode, "recorded");
});

test("B: first provisional estimate appears only with its recorded event", () => {
  const at = indexOf(revision, "COORDINATOR_ESTIMATE_UPDATED");
  assert.equal(fold(revision, at).estimate.status, "none");
  const state = fold(revision, at + 1);
  assert.deepEqual([state.estimate.value, state.estimate.status, state.estimate.revision], ["4", "provisional", 1]);
});

test("C: evidence without change creates no revision", () => {
  const run = runs.retained;
  const retained = run.events.filter((e) => e.event_type === "COORDINATOR_REASSESSMENT_RECORDED" && e.payload.outcome === "retained");
  assert.ok(retained.length >= 1);
  const full = fold(run, run.events.length);
  assert.deepEqual(full.history.map((h) => h.changeKind), ["initial", "finalized"]);
  const steps = Story.buildStory(run.events);
  assert.ok(steps.some((s) => s.kind === "assessment" && s.title === "Coordinator — Estimate unchanged"));
});

test("D: revision records old and new values with supporting evidence", () => {
  const state = fold(revision, indexOf(revision, "COORDINATOR_ESTIMATE_UPDATED", 1) + 1);
  assert.deepEqual([state.estimate.value, state.estimate.status], ["5", "revised"]);
  const entry = state.history.at(-1);
  assert.equal(entry.previousValue, "4");
  assert.ok(entry.evidence.length >= 1 && entry.evidence[0].report_event_id);
  assert.match(Answer.describeEntry(entry), /Revised 4 → 5/);
});

test("E: withdrawal leaves no stale estimate as current", () => {
  const run = runs.withdrawal;
  const at = indexOf(run, "COORDINATOR_ESTIMATE_UPDATED", 1);
  const state = fold(run, at + 1);
  assert.equal(state.estimate.status, "unresolved");
  assert.equal(state.estimate.value, null);
  assert.match(Answer.describeEntry(state.history.at(-1)), /withdrawn/);
});

test("F: finalization fills the final field from its own event and keeps history", () => {
  const finalAt = indexOf(revision, "FINAL_ANSWER_RECORDED");
  assert.equal(fold(revision, finalAt).final, null);
  const state = fold(revision, finalAt + 1);
  assert.equal(state.final.value, "5");
  assert.equal(state.history.length, 3);
  assert.match(Answer.describeEntry(state.history.at(-1)), /confirms the provisional estimate/);
});

test("G: replay at every prefix shows exactly the last recorded estimate", () => {
  for (const run of Object.values(runs)) {
    let last = null; let final = null;
    for (let k = 0; k <= run.events.length; k += 1) {
      const state = fold(run, k);
      assert.equal(state.estimate.value, last ? last.payload.estimate : null, `prefix ${k}`);
      assert.equal(state.final?.value ?? null, final, `final at prefix ${k}`);
      const event = run.events[k];
      if (event?.event_type === "COORDINATOR_ESTIMATE_UPDATED") last = event;
      if (event?.event_type === "FINAL_ANSWER_RECORDED") final = event.payload.final_answer;
    }
  }
});

test("legacy runs: estimates reported as not recorded, never invented from worker answers", () => {
  const run = runs.legacy;
  const state = fold(run, run.events.length);
  assert.equal(state.mode, "legacy");
  assert.equal(state.history.length, 0);
  assert.equal(state.estimate.status, "none");
  assert.notEqual(state.final, null);
  const model = Team.teamModel(run.topology, null);
  assert.ok(model.workers.every((w) => w.memory === "unknown"));
});

test("story never reveals later steps and links estimates through recorded references", () => {
  const steps = Story.buildStory(revision.events);
  const estimate = steps.find((s) => s.title === "Coordinator — Answer revised");
  const linked = Story.linkedSteps(estimate, steps);
  assert.ok([...linked].some((id) => steps.find((s) => s.id === id).kind === "tool"));
  assert.ok([...linked].every((id) => steps.find((s) => s.id === id).kind !== "estimate"));
  const prefix = Story.buildStory(revision.events.slice(0, indexOf(revision, "TOOL_CALL_COMPLETED") + 1));
  const tool = prefix.find((s) => s.kind === "tool");
  assert.equal(tool.next, undefined, "next action must not appear before it happens");
  assert.equal(prefix.filter((s) => s.kind === "estimate").length, 0);
  const failures = Story.buildStory(runs.w4.events).filter((s) => s.kind === "tool" && s.outcome !== "success");
  assert.ok(failures.some((s) => s.outcome === "execution_failure"), "tool failure is an execution failure");
  assert.ok(failures.some((s) => s.outcome === "budget"), "budget denial is a budget stop, not a failed hypothesis");
  assert.ok(Story.buildStory(revision.events).some((s) => s.kind === "hypothesis" && s.outcome === "revised"));
});

test("compact team model: one card per agent with policy indicators for 1-4 workers", () => {
  for (const [name, n, memory, peer] of [["revision", 1, "off", "off"], ["w2", 2, "on", "on"], ["w3", 3, "on", "off"], ["w4", 4, "off", "on"]]) {
    const run = runs[name];
    const model = Team.teamModel(run.topology, run.effective_config);
    assert.equal(model.workers.length, n, name);
    assert.ok(model.coordinator);
    assert.ok(model.workers.every((w) => w.memory === memory && w.peer === peer && w.tools.length >= 3), name);
    assert.equal(model.coordinator.memory, "record");
    assert.equal(model.services.length, 1);
    assert.ok(model.services[0].fixture);
  }
  assert.equal(Team.teamModel(runs.single_peer.topology, runs.single_peer.effective_config).workers[0].peer, "on_single");
});
