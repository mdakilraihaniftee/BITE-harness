"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const app = fs.readFileSync(path.resolve(__dirname, "../../../openvlharness/studio/static/app.js"), "utf8");
const statusFunction = app.slice(app.indexOf("function updateRunConnection()"), app.indexOf("async function startStream()"));

for (const [status, event, expected] of [
  ["FAILED", null, "Run failed · recorded"],
  ["COMPLETED", null, "Run completed · recorded"],
  ["RUNNING", "RUN_FAILED", "Run failed · recorded"],
  ["RUNNING", "RUN_COMPLETED", "Run completed · recorded"],
  ["CANCELLED", null, "Run cancelled · recorded"],
  ["RUNNING", null, "Run loaded · live stream"],
]) {
  test(`stream status: ${status} / ${event}`, () => {
    let label, notice;
    const context = {
      state: {snapshot: {state: {status}}, events: event ? [{event_type: event}] : []},
      terminalStates: new Set(["FAILED", "COMPLETED", "CANCELLED", "BUDGET_EXHAUSTED"]),
      setConnection(value) { label = value; },
      setNotice(value) { notice = value; },
    };
    vm.runInNewContext(statusFunction + "\nupdateRunConnection();", context);
    assert.equal(label, expected);
    if (expected.includes("failed")) assert.match(notice, /does not restart/);
  });
}
