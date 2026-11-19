// PARSEC-VL view model: built only from the visible event prefix (node --test).
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

global.self = global;
const Parsec = require(path.resolve(__dirname, "../../../openvlharness/studio/static/parsec-view.js"));
const runs = JSON.parse(fs.readFileSync(process.env.PARSEC_RUNS, "utf8"));
const overlap = (a, b) => a.start < b.end && b.start < a.end;

test("legacy run without PARSEC data says so and invents nothing", () => {
  const model = Parsec.buildModel(runs.legacy);
  assert.equal(model.available, false);
  assert.equal(model.message, "No PARSEC-VL planning or scheduler data was recorded for this run.");
  assert.equal(model.tasks.length, 0);
  assert.equal(model.plans.length, 0);
});

test("parallel plan: independent actions overlap, dependents wait (recorded intervals)", () => {
  const model = Parsec.buildModel(runs.parallel);
  const byAction = Object.fromEntries(model.tasks.map((t) => [t.action, t]));
  assert.ok(overlap(byAction.ocr_full, byAction.g), "OCR(original) and grounding overlap");
  assert.ok(byAction.z.start >= byAction.g.end, "Zoom waits for grounding");
  assert.ok(byAction.ocr_crop.start >= byAction.z.end, "crop OCR waits for Zoom");
  for (const t of model.tasks) assert.ok(t.enqueue <= t.start && t.start <= t.end);
  const plan = model.plans[0];
  assert.equal(Parsec.originLabel(plan, plan.plan.branches[0]), "Scripted policy (fixture)");
  const graph = Parsec.planGraph(plan, model.tasks);
  assert.deepEqual(graph.edges.filter((e) => e.from !== "input").map((e) => [e.from.split(":")[1], e.to.split(":")[1]]),
    [["g", "z"], ["z", "ocr_crop"]]);
  const critical = Parsec.criticalPath(plan, model.tasks);
  assert.ok([...critical].some((id) => id.endsWith(":g")) && [...critical].some((id) => id.endsWith(":ocr_crop")));
});

test("lanes never overlap inside a row and respect pool capacity", () => {
  const model = Parsec.buildModel(runs.parallel);
  for (const mode of ["slot", "pool", "agent"]) {
    for (const group of Parsec.lanes(model, mode)) {
      if (group.planning) continue;
      for (const row of group.rows) for (let i = 0; i < row.length; i++) for (let j = i + 1; j < row.length; j++)
        assert.ok(!overlap(row[i], row[j]), `${mode}/${group.label}`);
      if (mode === "pool" && model.capacities[group.key.slice(5)]) assert.ok(group.rows.length <= model.capacities[group.key.slice(5)]);
    }
  }
});

test("speculation run: speculative branch flagged and adopted, budget consistent", () => {
  const model = Parsec.buildModel(runs.speculative);
  const spec = model.tasks.filter((t) => t.speculative);
  assert.ok(spec.length >= 1 && spec.every((t) => t.adopted));
  assert.equal(model.budget.spent, model.tasks.filter((t) => t.start !== null).length);
  assert.equal(model.budget.physical, model.tasks.filter((t) => t.start !== null).length);
  assert.ok(model.budget.limit >= model.budget.used);
  const lines = Parsec.decisionText(model.plans[0]);
  assert.ok(lines.some((l) => l.includes("S1") || l.includes("S2")), lines.join(" | "));
  assert.ok(lines.some((l) => l.startsWith("Replanned")), lines.join(" | "));
  const pvo = Parsec.predictedVsObserved(model.plans[0], model.tasks);
  assert.equal(pvo.observed.satisfied, true);
  for (const t of model.tasks.filter((x) => x.evidenceEvent)) assert.ok(runs.speculative.some((e) => e.event_id === t.evidenceEvent));
});

test("replay prefixes never show the future", () => {
  const events = runs.speculative;
  const adoptAt = events.findIndex((e) => e.event_type === "SPECULATIVE_RESULT_ADOPTED");
  assert.ok(adoptAt > 0);
  const before = Parsec.buildModel(events.slice(0, adoptAt));
  assert.ok(before.tasks.every((t) => !t.adopted), "no adoption before the adoption event");
  for (let k = 1; k <= events.length; k++) {
    const model = Parsec.buildModel(events.slice(0, k));
    const seen = new Set(events.slice(0, k).map((e) => e.event_id));
    for (const t of model.tasks) {
      assert.ok(seen.has(t.eventId), "task from a visible event");
      if (t.open) {
        const finished = events.find((e) => e.event_type === "SCHEDULER_TASK_FINISHED" && e.payload.task_id === t.id);
        assert.ok(t.end === Math.max(t.start, model.now), "running task ends at 'now'");
        if (finished) assert.ok(t.end <= finished.payload.finish_time + 1e-6 || t.end === t.start, "never at its future finish");
      }
      if (t.evidenceEvent) assert.ok(seen.has(t.evidenceEvent), "evidence link only to visible events");
    }
    for (const p of model.plans) assert.ok(seen.has(p.eventId));
  }
});
