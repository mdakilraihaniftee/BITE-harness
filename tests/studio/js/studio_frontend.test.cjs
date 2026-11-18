// Frontend unit tests (node --test). Data: STUDIO_TEST_DATA = JSON {runs: {name: {topology, events}}, topologies: {N: topology}}.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const STATIC = path.resolve(__dirname, "../../../openvlharness/studio/static");
const Activity = require(path.join(STATIC, "activity-state.js"));
const Graph = require(path.join(STATIC, "architecture-graph.js"));
const data = JSON.parse(fs.readFileSync(process.env.STUDIO_TEST_DATA, "utf8"));
const fixture = data.runs.fixture;
const demo = data.runs.demo;

function summary(state) {
  return {
    count: state.count,
    open: [...state.open.keys()].sort(),
    runStatus: state.runStatus,
    agents: [...state.agents].map(([id, a]) => [id, a.status, a.subtask, a.candidate, [...a.tools]]).sort(),
    nodes: [...state.nodes].map(([id, n]) => [id, n.touches || 0, n.failures, n.requests, n.lastEventId]).sort(),
    edges: [...state.edges].map(([id, e]) => [id, e.events.length, e.last && e.last.eventId, e.last && e.last.direction]).sort(),
  };
}

test("state at K depends only on the first K events (no future leakage)", () => {
  for (const run of [fixture, demo]) {
    for (let k = 0; k <= run.events.length; k += 5) {
      const truncated = Activity.computeState(run.topology, run.events.slice(0, k));
      const prefix = Activity.computeState(run.topology, run.events, k);
      assert.deepEqual(summary(prefix), summary(truncated));
    }
  }
});

test("incremental application equals recomputation (forward and backward stepping)", () => {
  const incremental = Activity.createState(fixture.topology);
  for (let k = 0; k < fixture.events.length; k += 1) {
    Activity.applyEvent(incremental, fixture.events[k]);
    if (k % 9 === 0) assert.deepEqual(summary(incremental), summary(Activity.computeState(fixture.topology, fixture.events, k + 1)));
  }
  const back = Activity.computeState(fixture.topology, fixture.events, 10);
  assert.equal(back.count, 10);
  assert.equal(summary(back).count, 10);
});

test("concurrent same-tool calls stay open separately and close independently", () => {
  const events = fixture.events;
  const secondStart = events.findIndex((e) => e.event_type === "TOOL_CALL_STARTED" && e.agent_id === "worker_02");
  const state = Activity.computeState(fixture.topology, events, secondStart + 1);
  const tools = [...state.open.values()].filter((o) => o.toolNode === "tool:Visual_Grounding_Tool");
  assert.equal(tools.length, 2);
  assert.deepEqual(new Set(tools.map((o) => o.agentId)), new Set(["worker_01", "worker_02"]));
  assert.match(Activity.agentStatusLine(state, "worker_01"), /Running: Visual_Grounding_Tool/);
  const firstClose = events.findIndex((e) => e.event_type === "TOOL_CALL_COMPLETED" && e.agent_id === "worker_02");
  const after = Activity.computeState(fixture.topology, events, firstClose + 1);
  const remaining = [...after.open.values()].filter((o) => o.toolNode === "tool:Visual_Grounding_Tool");
  assert.deepEqual(remaining.map((o) => o.agentId), ["worker_01"]);
});

test("request and response highlights traverse the same edges in opposite directions", () => {
  const state = Activity.computeState(fixture.topology, fixture.events);
  const request = fixture.events.find((e) => e.event_type === "TOOL_CALL_REQUESTED" && e.agent_id === "worker_01");
  const result = fixture.events.find((e) => e.event_type === "TOOL_CALL_COMPLETED" && e.agent_id === "worker_01");
  const req = Activity.highlightFor(state, request);
  const res = Activity.highlightFor(state, result);
  assert.equal(req.style, "request");
  assert.equal(res.style, "response");
  const harnessEdge = "worker_01.harness->worker_01.tool_router";
  assert.equal(req.hops.find((h) => h.edgeId === harnessEdge).direction, "forward");
  assert.equal(res.hops.find((h) => h.edgeId === harnessEdge).direction, "reverse");
  assert.equal(state.unresolvedHops, 0);
});

test("future events are not reflected at an early replay position", () => {
  const early = Activity.computeState(fixture.topology, fixture.events, 12);
  assert.notEqual(early.agents.get("coordinator").status, "completed");
  assert.equal(early.nodes.get("result").touches || 0, 0);
  assert.equal(early.nodes.get("tool:Visual_Grounding_Tool").requests, 0);
  const done = Activity.computeState(fixture.topology, fixture.events);
  assert.equal(done.runStatus, "COMPLETED");
  assert.equal(String(done.agents.get("coordinator").candidate), "3");
});

test("flow styles distinguish requests, responses, failures, messages and memory", () => {
  const styles = ["tool_request", "tool_result", "tool_failure", "tool_denied", "reply", "question", "memory_write", "memory_read", "budget_deny", "assignment"]
    .map((kind) => Activity.flowStyle(kind));
  assert.deepEqual(styles, ["request", "response", "failure", "failure", "message-return", "message", "memory", "memory", "failure", "control"]);
});

test("layout is deterministic, overlap-free, and scales to many workers", () => {
  for (const [n, topology] of Object.entries(data.topologies)) {
    const a = Graph.layoutTopology(topology, {});
    const b = Graph.layoutTopology(JSON.parse(JSON.stringify(topology)), {});
    assert.deepEqual([...a.nodes], [...b.nodes], `N=${n} stable`);
    const visible = [...a.nodes.values()].filter((item) => !item.hidden);
    for (let i = 0; i < visible.length; i += 1) for (let j = i + 1; j < visible.length; j += 1) {
      const p = visible[i]; const q = visible[j];
      assert.ok(!(p.x < q.x + q.w && q.x < p.x + p.w && p.y < q.y + q.h && q.y < p.y + p.h), `N=${n}: ${p.id} overlaps ${q.id}`);
    }
    for (const edge of topology.edges) {
      const s = Graph.visibleNode(a, edge.source); const t = Graph.visibleNode(a, edge.target);
      assert.ok(s && t && Graph.edgeGeometry(edge, s, t, a), `N=${n}: edge ${edge.id} drawable`);
    }
    const collapsed = Graph.layoutTopology(topology, {collapsed: new Set(topology.agents)});
    assert.ok(collapsed.height < a.height, `N=${n}: collapse reduces height`);
    assert.ok(Graph.visibleNode(collapsed, "worker_01.tool_router").id === "worker_01", "collapsed internals proxy to the agent");
    const noMemory = Graph.layoutTopology(topology, {showMemory: false});
    assert.ok(Graph.visibleNode(noMemory, "worker_01.memory").id === "worker_01.harness");
  }
});

test("reversed edge geometry starts where the forward geometry ends", () => {
  const topology = data.topologies["2"];
  const layout = Graph.layoutTopology(topology, {});
  const edge = topology.edges.find((e) => e.id === "coordinator->result");
  const points = Graph.edgeGeometry(edge, Graph.visibleNode(layout, edge.source), Graph.visibleNode(layout, edge.target), layout);
  const forward = Graph.pathData(points).match(/-?\d+\.\d/g);
  const reverse = Graph.pathData(points, true).match(/-?\d+\.\d/g);
  assert.deepEqual(reverse.slice(0, 2), forward.slice(-2));
  assert.deepEqual(reverse.slice(-2), forward.slice(0, 2));
});

function loadTheme({stored = {}, dark = false, reduced = false} = {}) {
  const storage = new Map(Object.entries(stored));
  const documentElement = {dataset: {}, style: {}};
  const sandbox = {
    localStorage: {getItem: (k) => (storage.has(k) ? storage.get(k) : null), setItem: (k, v) => storage.set(k, String(v))},
    matchMedia: (query) => ({matches: query.includes("dark") ? dark : query.includes("reduce") ? reduced : false, addEventListener() {}}),
    document: {documentElement},
  };
  sandbox.self = sandbox;
  vm.runInNewContext(fs.readFileSync(path.join(STATIC, "theme.js"), "utf8"), sandbox);
  return {Theme: sandbox.StudioTheme, storage, documentElement};
}

test("theme: light, dark, system, persistence, and reduced motion", () => {
  let env = loadTheme({dark: true});
  assert.equal(env.documentElement.dataset.theme, "dark", "system follows dark preference by default");
  env.Theme.setPreference("light");
  assert.equal(env.documentElement.dataset.theme, "light");
  assert.equal(env.storage.get("studio.theme"), "light");
  env = loadTheme({stored: {"studio.theme": "dark"}, dark: false});
  assert.equal(env.documentElement.dataset.theme, "dark", "persisted choice restored on reload");
  env = loadTheme({stored: {"studio.theme": "bogus"}, dark: false});
  assert.equal(env.Theme.preference(), "system");
  assert.equal(env.documentElement.dataset.theme, "light");
  assert.equal(loadTheme({reduced: true}).Theme.animationEnabled(), false);
  const plain = loadTheme();
  plain.Theme.setAnimation(false);
  assert.equal(plain.Theme.animationEnabled(), false);
  assert.deepEqual([...plain.storage.keys()].sort(), ["studio.flowAnimation"]);
});

test("disconnected preview is generic, self-consistent, drawable, and activity-free", () => {
  const preview = Graph.previewTopology();
  const ids = new Set(preview.nodes.map((node) => node.id));
  assert.equal(preview.scope, "preview");
  assert.ok(preview.nodes.every((node) => node.provenance === "preview"));
  assert.ok(preview.edges.every((edge) => edge.provenance === "preview" && ids.has(edge.source) && ids.has(edge.target)));
  assert.deepEqual(preview.agents, ["coordinator", "worker_template"]);
  assert.ok(!preview.nodes.some((node) => /worker_0\d/.test(node.id)), "no invented worker instances");
  const layout = Graph.layoutTopology(preview, {});
  for (const edge of preview.edges) {
    const s = Graph.visibleNode(layout, edge.source); const t = Graph.visibleNode(layout, edge.target);
    assert.ok(s && t && Graph.edgeGeometry(edge, s, t, layout), edge.id);
  }
  for (const item of layout.nodes.values()) assert.ok([item.x, item.y, item.w, item.h].every(Number.isFinite));
  const state = Activity.computeState(preview, []);
  assert.equal(state.open.size, 0);
  assert.equal(state.edges.size, 0);
});
