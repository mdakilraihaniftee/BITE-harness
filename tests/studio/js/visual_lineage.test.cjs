// Visual lineage and geometry tests (node --test).
// STUDIO_VISUAL_DATA: {run: {events, artifacts, aliases}} from the visual-chain fixture.
// STUDIO_GEOMETRY_VECTORS: tests/studio/geometry_vectors.json (shared with Python).
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

global.self = global;
const STATIC = path.resolve(__dirname, "../../../openvlharness/studio/static");
const G = require(path.join(STATIC, "geometry.js"));
global.StudioGeometry = G;
const L = require(path.join(STATIC, "visual-lineage.js"));
const vectors = JSON.parse(fs.readFileSync(process.env.STUDIO_GEOMETRY_VECTORS, "utf8"));
const {run} = JSON.parse(fs.readFileSync(process.env.STUDIO_VISUAL_DATA, "utf8"));
const build = (events = run.events) => L.buildLineage(events, {artifacts: run.artifacts, aliases: run.aliases});
const near = (a, b, tol = 1e-6) => a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) <= tol);
const invs = (lin, agent) => [...lin.invocations.values()].filter((i) => i.agent === agent);
const toRoot = (lin, inv, box) => { const input = lin.images.get(inv.inputKeys[0]); const c = lin.chainToRoot(input.key); return c.complete ? G.applyBox(G.then(inv.detections.toInput, c.transform), box) : null; };

test("geometry.js matches the shared Python vectors", () => {
  const make = (spec) => { const [kind, a] = Object.entries(spec)[0];
    return kind === "crop" ? G.cropTransform(a.box, a.output) : kind === "resize" ? G.resizeTransform(a.child, a.parent)
      : kind === "letterbox" ? G.letterboxTransform(a.content, a.padding, a.parent) : G.normalizedTransform(a.scale, a.frame); };
  for (const c of vectors.chains) {
    const t = G.compose(c.chain.map(make));
    assert.ok(near(G.applyBox(t, c.box), c.expected), c.name);
    assert.ok(near(G.applyBox(G.inverse(t), c.expected), c.box), `${c.name} inverse`);
  }
  for (const c of vectors.clip) assert.deepEqual(G.clipBox(c.box, ...c.size), c.expected);
  for (const c of vectors.zoom) {
    const r = G.reconstructZoom({coords: c.coords, padding: c.padding}, c.input, [c.expected[2] - c.expected[0], c.expected[3] - c.expected[1]]);
    assert.deepEqual(r.cropBox, c.expected, c.name); assert.equal(r.verified, true);
  }
  for (const [x, y] of vectors.round_half_even) assert.equal(G.roundHalfEven(x), y);
  assert.equal(G.cropTransform([10, 10, 5, 20], [5, 10]), null);
});

test("zoom on the original: ROI, verified crop, and the actual crop as output", () => {
  const lin = build(); const zoom = invs(lin, "worker_01").find((i) => /Zoom/.test(i.tool));
  assert.deepEqual(zoom.roi.cropBox, [438, 230, 640, 400]); assert.equal(zoom.roi.verified, true); assert.equal(zoom.roi.method, "recorded");
  assert.ok(near(zoom.roi.requested, [469.76, 250, 620.16, 380], 1e-9));
  const out = lin.images.get(zoom.outputKeys[0]);
  assert.equal(out.kind, "crop"); assert.equal(out.registryId, "tool_generated_image_2"); assert.deepEqual([out.width, out.height], [202, 170]);
  assert.ok(run.artifacts[out.artifactId], "crop pixels are a stored artifact");
  assert.equal(lin.images.get(out.parentKey).registryId, "input_image_1");
});

test("detection on the zoomed crop: drawn on the crop, mapped to the original", () => {
  const lin = build(); const [ground0, , detect] = invs(lin, "worker_01");
  assert.equal(lin.images.get(ground0.inputKeys[0]).kind, "input");
  assert.deepEqual(ground0.detections.boxes[0], [190, 40, 301, 151], "boxes on the original stay in source pixels");
  assert.equal(lin.images.get(detect.inputKeys[0]).registryId, "tool_generated_image_2");
  assert.equal(detect.detections.system, "input_pixels");
  assert.deepEqual(detect.detections.boxes, [[67, 55, 96, 84], [114, 92, 141, 119]]);
  assert.ok(near(toRoot(lin, detect, detect.detections.boxes[0]), [505, 285, 534, 314]));
  assert.ok(near(toRoot(lin, detect, detect.detections.boxes[1]), [552, 322, 579, 349]));
});

test("nested crops compose: original -> crop A -> crop B -> detection", () => {
  const lin = build(); const steps = invs(lin, "worker_01");
  const nested = steps[4]; const input = lin.images.get(nested.inputKeys[0]);
  assert.equal(input.registryId, "tool_generated_image_4");
  const chain = lin.chainToRoot(input.key);
  assert.equal(chain.complete, true); assert.equal(chain.chain.length, 2);
  assert.ok(near(toRoot(lin, nested, [10, 9, 37, 36]), [552, 322, 579, 349]));
});

test("concurrent workers keep separate images, scopes, and invocations", () => {
  const lin = build();
  const w2 = invs(lin, "worker_02"); const w1 = invs(lin, "worker_01");
  const w2crop = lin.images.get(w2[0].outputKeys[0]); const w1first = lin.images.get(w1[0].outputKeys[0]);
  assert.equal(w2crop.registryId, "tool_generated_image_1"); assert.equal(w1first.registryId, "tool_generated_image_1");
  assert.notEqual(w2crop.key, w1first.key); assert.notEqual(w2crop.artifactId, w1first.artifactId);
  assert.deepEqual(w2[0].roi.cropBox, [158, 20, 332, 170]);
  assert.deepEqual(w2[1].detections.boxes, [[32, 20, 143, 131]]);
  assert.ok(w2.every((i) => i.agent === "worker_02") && new Set([...w1, ...w2].map((i) => i.key)).size === w1.length + w2.length);
});

test("replay: inputs at request time, outputs only after the result", () => {
  const detectReq = run.events.findIndex((e) => e.agent_id === "worker_01" && e.event_type === "TOOL_CALL_REQUESTED" && e.payload.arguments?.image_id === "tool_generated_image_2" && /Grounding/.test(e.tool_name));
  const prefix = build(run.events.slice(0, detectReq + 1));
  const inv = prefix.invocations.get(prefix.byEvent.get(run.events[detectReq].event_id));
  assert.equal(inv.status, "requested"); assert.equal(prefix.images.get(inv.inputKeys[0]).registryId, "tool_generated_image_2");
  assert.equal(inv.detections, null); assert.equal(inv.outputKeys.length, 0);
  for (let k = 0; k <= run.events.length; k += 7) {
    const lin = build(run.events.slice(0, k)); const seen = new Set(run.events.slice(0, k).map((e) => e.event_id));
    for (const i of lin.invocations.values()) { if (i.resultEventId) assert.ok(seen.has(i.resultEventId)); if (i.outputKeys.length) assert.equal(i.status, "completed"); }
  }
});

test("older runs: crops are reconstructed with the tool rule and verified; unverifiable ones are not drawn", () => {
  const legacy = run.events.map((e) => { const c = JSON.parse(JSON.stringify(e)); delete c.payload.visual; delete c.payload.visual_inputs; delete c.payload.image_scope; return c; });
  const lin = build(legacy); const zoom = invs(lin, "worker_01").find((i) => /Zoom/.test(i.tool));
  assert.equal(zoom.roi.method, "reconstructed"); assert.equal(zoom.roi.verified, true); assert.deepEqual(zoom.roi.cropBox, [438, 230, 640, 400]);
  // A crop whose size cannot be reproduced is never aligned.
  const tampered = JSON.parse(JSON.stringify(legacy));
  const done = tampered.find((e) => e.event_id === zoom.resultEventId); done.payload.arguments = {};
  const req = tampered.find((e) => e.event_id === zoom.requestEventId); req.payload.arguments.coords = [700, 600, 960, 950];
  const bad = invs(build(tampered), "worker_01").find((i) => /Zoom/.test(i.tool));
  assert.equal(bad.roi.verified, false); const out = build(tampered).images.get(bad.outputKeys[0]);
  assert.equal(out.toParent, null);
});

test("unknown frames, failures, empty results, and missing inputs are explicit", () => {
  const events = JSON.parse(JSON.stringify(run.events));
  const detect = events.find((e) => e.event_type === "TOOL_CALL_COMPLETED" && e.agent_id === "worker_02" && /Grounding/.test(e.tool_name));
  delete detect.payload.canonical_result.size;
  let inv = invs(build(events), "worker_02").find((i) => i.detections);
  assert.equal(inv.detections.toInput, null); assert.match(inv.detections.reason, /missing transform metadata/);
  detect.payload.canonical_result.boxes = []; detect.payload.canonical_result.size = [150, 174];
  inv = invs(build(events), "worker_02").find((i) => i.detections);
  assert.equal(inv.detections.boxes.length, 0);
  const failed = {...events.find((e) => e.event_type === "TOOL_CALL_COMPLETED" && e.agent_id === "worker_02" && /Zoom/.test(e.tool_name))};
  failed.event_type = "TOOL_CALL_FAILED"; failed.payload = {...failed.payload, error: {message: "boom"}};
  const withFailure = events.map((e) => (e.event_id === failed.event_id ? failed : e));
  inv = invs(build(withFailure), "worker_02").find((i) => /Zoom/.test(i.tool));
  assert.equal(inv.status, "failed"); assert.equal(inv.outputKeys.length, 0); assert.equal(inv.inputKeys.length, 1);
  const noInput = events.map((e) => { if (!/TOOL_CALL/.test(e.event_type) || e.agent_id !== "worker_02") return e; const c = JSON.parse(JSON.stringify(e)); delete c.payload.visual; delete c.payload.visual_inputs; if (c.payload.meta) delete c.payload.meta.image_resolution; if (c.payload.arguments) delete c.payload.arguments.image_id; return c; });
  inv = invs(build(noInput), "worker_02").find((i) => i.detections);
  assert.equal(inv.inputKeys.length, 0); assert.match(inv.detections.reason, /processed image was not recorded/);
});

test("a registry ID reused in a later phase never inherits the earlier image", () => {
  const strip = (e) => { const c = JSON.parse(JSON.stringify(e)); delete c.payload.visual; delete c.payload.visual_inputs; delete c.payload.image_scope; return c; };
  const legacy = run.events.filter((e) => !(e.event_type === "MEMORY_READ")).map(strip);
  const zoomReq = legacy.find((e) => e.agent_id === "worker_02" && e.event_type === "TOOL_CALL_REQUESTED" && /Zoom/.test(e.tool_name));
  const zoomDone = legacy.find((e) => e.agent_id === "worker_02" && e.event_type === "TOOL_CALL_COMPLETED" && /Zoom/.test(e.tool_name));
  const other = run.events.find((e) => e.agent_id === "worker_01" && e.event_type === "TOOL_CALL_COMPLETED" && /Zoom/.test(e.tool_name));
  // A second call in a later phase returns a different crop under the same registry ID.
  const req2 = {...JSON.parse(JSON.stringify(zoomReq)), event_id: "again_req", sequence: 9998, activity: null, payload: {...zoomReq.payload, invocation_id: "again", arguments: {image_id: "input_image_1", coords: [734, 625, 969, 950], padding: 50}}};
  const done2 = {...JSON.parse(JSON.stringify(zoomDone)), event_id: "again_done", sequence: 9999, activity: null, artifact_refs: other.artifact_refs, payload: {...zoomDone.payload, invocation_id: "again"}};
  for (const withBoundary of [false, true]) {
    const events = [...legacy, ...(withBoundary ? [{...legacy.find((e) => e.event_type === "WORKER_STARTED" && e.agent_id === "worker_02"), event_id: "phase2", sequence: 9997}] : []), req2, done2];
    const lin = build(events);
    const zooms = invs(lin, "worker_02").filter((i) => /Zoom/.test(i.tool));
    const [a, b] = zooms.map((i) => lin.images.get(i.outputKeys[0]));
    assert.notEqual(a.key, b.key, `boundary=${withBoundary}`);
    assert.equal(b.artifactId, other.artifact_refs[0]); assert.deepEqual([b.width, b.height], [202, 170]);
    assert.equal(zooms[1].roi.verified, true, "the later crop verifies against its own pixels");
  }
});
