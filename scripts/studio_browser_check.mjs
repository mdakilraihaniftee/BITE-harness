#!/usr/bin/env node
/*
 * Headless-Chrome interaction checks and screenshots for the Investigation Studio.
 *
 * Usage:
 *   STUDIO_VIEWER_TOKEN=... node scripts/studio_browser_check.mjs \
 *     --base http://127.0.0.1:8799 --out docs/images/studio [--chrome google-chrome]
 *
 * Requires the runs `studio_protocol_fixture` (scripts/studio_protocol_fixture.py),
 * `real_fsc147_row0_studio` (a recorded real run) and `studio_demo_architecture`
 * (scripts/multi_agent_smoke.py). The viewer token is read from the environment,
 * typed into the password field via the URL fragment (which the page removes),
 * and never appears in screenshots or output.
 */
import {spawn} from "node:child_process";
import {mkdirSync, mkdtempSync, rmSync, writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";

const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, index, all) => {
  if (value.startsWith("--")) pairs.push([value.slice(2), all[index + 1]]);
  return pairs;
}, []));
const BASE = args.base || "http://127.0.0.1:8799";
const OUT = args.out || "docs/images/studio";
const CHROME = args.chrome || "google-chrome";
const TOKEN = process.env.STUDIO_VIEWER_TOKEN;
if (!TOKEN) { console.error("Set STUDIO_VIEWER_TOKEN"); process.exit(2); }
mkdirSync(OUT, {recursive: true});

const profile = mkdtempSync(join(tmpdir(), "studio-chrome-"));
const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--window-size=1600,1300", "about:blank"],
{stdio: ["ignore", "ignore", "pipe"]});
const wsUrl = await new Promise((resolve, reject) => {
  let buffer = "";
  chrome.stderr.on("data", (chunk) => {
    buffer += chunk;
    const match = /DevTools listening on (ws:\/\/\S+)/.exec(buffer);
    if (match) resolve(match[1]);
  });
  chrome.on("exit", () => reject(new Error(`Chrome exited: ${buffer}`)));
  setTimeout(() => reject(new Error("Chrome did not start")), 20000);
});
const port = new URL(wsUrl).port;
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = targets.find((target) => target.type === "page");
const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve) => socket.addEventListener("open", resolve, {once: true}));
let nextId = 0;
const pending = new Map();
const problems = [];
socket.addEventListener("message", (message) => {
  const data = JSON.parse(message.data);
  if (data.id && pending.has(data.id)) {
    const {resolve, reject} = pending.get(data.id); pending.delete(data.id);
    if (data.error) reject(new Error(data.error.message)); else resolve(data.result);
  } else if (data.method === "Runtime.exceptionThrown") {
    problems.push(`exception: ${data.params.exceptionDetails.exception?.description || data.params.exceptionDetails.text}`);
  } else if (data.method === "Runtime.consoleAPICalled" && data.params.type === "error") {
    problems.push(`console.error: ${data.params.args.map((a) => a.value ?? a.description).join(" ")}`);
  } else if (data.method === "Log.entryAdded" && data.params.entry.level === "error") {
    problems.push(`log: ${data.params.entry.text} ${data.params.entry.url || ""}`);
  }
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++nextId; pending.set(id, {resolve, reject});
  socket.send(JSON.stringify({id, method, params}));
});
const evaluate = async (expression) => {
  const result = await send("Runtime.evaluate", {expression, awaitPromise: true, returnByValue: true});
  if (result.exceptionDetails) throw new Error(`${expression.slice(0, 80)}: ${result.exceptionDetails.exception?.description}`);
  return result.result.value;
};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const frames = () => evaluate("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 120))))");
async function waitFor(expression, timeout = 10000) { const end = Date.now() + timeout; while (Date.now() < end) { if (await evaluate(expression).catch(() => false)) return true; await sleep(150); } return false; }

await send("Page.enable"); await send("Runtime.enable"); await send("Log.enable");
await send("Emulation.setDeviceMetricsOverride", {width: 1600, height: 1250, deviceScaleFactor: 1, mobile: false});

let loads = 0;
const debug = (...items) => { if (process.env.STUDIO_DEBUG) console.log(new Date().toISOString().slice(17, 23), ...items); };
async function open(run, {theme = "light", mode = "full", event = null} = {}) {
  debug("navigate blank");
  await send("Page.navigate", {url: `${BASE}/?blank=${loads}`});
  debug("navigated blank");
  await sleep(400);
  await evaluate(`localStorage.setItem("studio.theme", ${JSON.stringify(theme)}); localStorage.setItem("studio.graph", JSON.stringify({mode: ${JSON.stringify(mode)}, viewMode: ${JSON.stringify(mode)}, showMemory: true, showMemoryFlows: true, showInfra: false})); localStorage.setItem("studio.flowAnimation", "off"); true`);
  const fragment = new URLSearchParams({token: TOKEN, run, ...(event ? {event} : {})}).toString();
  loads += 1;
  debug("navigate run");
  await send("Page.navigate", {url: `${BASE}/?view=${loads}#${fragment}`});
  debug("navigated run");
  for (let i = 0; i < 60; i += 1) {
    await sleep(150);
    const t0 = Date.now();
    const ready = await evaluate(`Boolean(document.querySelector('.arch-svg .node') && typeof state !== 'undefined' && state.runId === ${JSON.stringify(run)} && state.events.length > 0)`).catch((error) => String(error.message).slice(0, 60));
    if (process.env.STUDIO_DEBUG) console.log("probe", i, ready, Date.now() - t0, "ms");
    if (ready === true) break;
  }
  debug("ready; waiting frames");
  await frames();
  debug("frames done");
}

async function shot(name, selector = null) {
  await frames();
  const clip = selector ? await evaluate(`(() => { const r = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect(); return {x: r.x + scrollX, y: r.y + scrollY, width: r.width, height: r.height, scale: 1}; })()`) : null;
  const result = await send("Page.captureScreenshot", {format: "png", captureBeyondViewport: Boolean(clip), ...(clip ? {clip} : {})});
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(result.data, "base64"));
  console.log(`screenshot ${join(OUT, `${name}.png`)}`);
}

const checks = [];
function check(name, condition, detail = "") { checks.push({name, ok: Boolean(condition), detail}); console.log(`${condition ? "PASS" : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`); }

// Responses the negative scenarios provoke on purpose (rejected token, reused
// launch link, old backend without /api/info). Anything else is a failure.
const EXPECTED = [/status of 401 .*\/api\/runs$/, /status of 401 .*\/api\/launch-tickets\/redeem$/, /status of 404 .*:\d+\/api\/info$/];
async function finish(reportName) {
  const unexpected = problems.filter((item) => !EXPECTED.some((pattern) => pattern.test(item.trim())));
  check("no unexpected console errors or exceptions", unexpected.length === 0, unexpected.slice(0, 5).join(" | "));
  writeFileSync(join(OUT, reportName), `${JSON.stringify({checks, problems}, null, 2)}\n`);
  socket.close(); chrome.kill("SIGTERM");
  await sleep(300);
  rmSync(profile, {recursive: true, force: true});
  const failed = checks.filter((item) => !item.ok);
  console.log(`${checks.length - failed.length}/${checks.length} browser checks passed`);
  process.exit(failed.length ? 1 : 0);
}

if (args["live-run"]) {
  // Watch a run that is being written right now (start the producer first).
  const run = args["live-run"];
  // Fresh headless profiles can take a long time on their first navigation;
  // warm up first, then wait for the producer to create the run.
  await send("Page.navigate", {url: `${BASE}/health`});
  console.log("LIVE_READY", new Date().toISOString());
  for (let i = 0; i < 600; i += 1) {
    const listed = await fetch(`${BASE}/api/runs`, {headers: {"X-Studio-Token": TOKEN}}).then((r) => r.json()).catch(() => ({runs: []}));
    if (listed.runs.some((item) => item.run_id === run)) break;
    await sleep(100);
  }
  console.log(`live: opening at ${new Date().toISOString()}`);
  if (args["link-file"]) {
    // Follow the exact link printed by the task launcher (real reuse/start path).
    const {readFileSync} = await import("node:fs");
    const linkText = readFileSync(args["link-file"], "utf8").match(/http:\/\/\S+#ticket=\S+/)?.[0];
    check("live: launcher printed a single-use link", Boolean(linkText) && !linkText.includes(TOKEN));
    await send("Page.navigate", {url: linkText});
    for (let i = 0; i < 80 && !(await evaluate(`state.runId === ${JSON.stringify(run)}`).catch(() => false)); i += 1) await sleep(150);
    await evaluate(`state.graph.setOptions({mode: "live"}); renderAll(); true`);
  } else await open(run, {theme: "dark", mode: "live"});
  console.log(`live: opened at ${new Date().toISOString()}`);
  const samples = [];
  for (let i = 0; i < 300; i += 1) {
    const sample = await evaluate(`({events: state.events.length, nodes: document.querySelectorAll('.arch-svg .node').length,
      running: document.querySelectorAll('.node.is-running').length, live: state.live,
      svg: document.querySelector('.arch-svg') ? (window.__svgId ??= new WeakMap(), (window.__svgCount ??= 0), window.__svgId.has(document.querySelector('.arch-svg')) ? window.__svgId.get(document.querySelector('.arch-svg')) : (window.__svgId.set(document.querySelector('.arch-svg'), ++window.__svgCount), window.__svgCount)) : 0,
      done: state.events.some((e) => e.event_type === 'RUN_COMPLETED'), tools: document.querySelectorAll('.node-tool').length})`);
    samples.push(sample);
    if (sample.running && !samples.some((s) => s.shot)) { sample.shot = true; await shot("12-live-run-in-progress", ".architecture-panel"); }
    if (sample.done) break;
    await sleep(100);
  }
  const last = samples.at(-1);
  check("live: events streamed incrementally", new Set(samples.map((s) => s.events)).size > 5, `${samples[0].events} → ${last.events}`);
  check("live: run completed while watching", last.done);
  check("live: running activity observed during the run", samples.some((s) => s.running > 0));
  check("live: full topology (workers, harnesses, tools) available mid-run and stable", samples[0].tools >= 2 && samples.every((x) => x.nodes === samples[0].nodes) && !samples[0].done, `${samples[0].nodes} nodes at event ${samples[0].events}`);
  check("live: graph rebuilt only on topology changes", Math.max(...samples.map((s) => s.svg)) <= 4, `svg instances ${Math.max(...samples.map((s) => s.svg))}`);
  check("live: stayed in live mode", samples.every((s) => s.live));
  await finish("browser-live-checks.json");
}

/** Select event by type/agent/predicate and position replay just after it. */
async function selectAt(predicate, {replay = true} = {}) {
  return evaluate(`(() => {
    const index = state.events.findIndex(${predicate});
    if (index < 0) return null;
    if (${replay}) { state.live = false; state.replayIndex = index + 1; }
    state.selectedEventId = state.events[index].event_id;
    renderAll();
    return {index, id: state.events[index].event_id, type: state.events[index].event_type, total: state.events.length};
  })()`);
}
const selectedFlows = () => evaluate(`[...document.querySelectorAll('.flow.on.level-selected')].map((p) => p.getAttribute('class'))`);

// 1-2. Full architecture in both themes.
for (const theme of ["light", "dark"]) {
  await open("studio_protocol_fixture", {theme});
  const info = await evaluate(`({theme: document.documentElement.dataset.theme, nodes: document.querySelectorAll('.arch-svg .node').length, topo: state.topology.nodes.length, href: location.href, tokenType: document.querySelector('#token').type, bg: getComputedStyle(document.body).backgroundColor})`);
  check(`${theme}: theme applied`, info.theme === theme, info.bg);
  check(`${theme}: every topology node drawn`, info.nodes === info.topo, `${info.nodes}/${info.topo}`);
  check(`${theme}: token removed from URL`, !info.href.includes("token") && !info.href.includes(TOKEN));
  check(`${theme}: token field masked`, info.tokenType === "password");
  const contrast = await evaluate(`(() => {
    const parse = (c) => c.match(/[\\d.]+/g).slice(0, 3).map(Number);
    const lum = (rgb) => { const [r, g, b] = rgb.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
    const ratio = (a, b) => { const [x, y] = [lum(parse(a)), lum(parse(b))].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
    const probe = (name) => { const d = document.createElement('div'); d.style.color = 'var(' + name + ')'; document.body.append(d); const v = getComputedStyle(d).color; d.remove(); return v; };
    const panel = probe('--panel-background'); const graph = probe('--graph-node-background');
    return {primary: ratio(probe('--text-primary'), panel), secondary: ratio(probe('--text-secondary'), panel),
      nodeText: ratio(probe('--text-primary'), graph), nodeSub: ratio(probe('--text-secondary'), graph),
      request: ratio(probe('--flow-request'), probe('--graph-background')), response: ratio(probe('--flow-response'), probe('--graph-background')),
      failure: ratio(probe('--flow-failure'), probe('--graph-background'))};
  })()`);
  check(`${theme}: body text contrast ≥ 4.5`, contrast.primary >= 4.5 && contrast.secondary >= 4.5, JSON.stringify({p: contrast.primary.toFixed(1), s: contrast.secondary.toFixed(1)}));
  check(`${theme}: node label contrast ≥ 4.5`, contrast.nodeText >= 4.5 && contrast.nodeSub >= 4.5, `${contrast.nodeText.toFixed(1)} / ${contrast.nodeSub.toFixed(1)}`);
  check(`${theme}: arrow contrast ≥ 3`, contrast.request >= 3 && contrast.response >= 3 && contrast.failure >= 3, `${contrast.request.toFixed(1)} / ${contrast.response.toFixed(1)} / ${contrast.failure.toFixed(1)}`);
  await shot(`01-full-architecture-${theme}`, ".architecture-panel");
}

// Theme persistence through the visible control, and system mode.
await evaluate(`document.querySelector('[data-theme-choice="dark"]').click(); true`);
await send("Page.reload"); await sleep(1200);
check("theme persists across reload", (await evaluate("document.documentElement.dataset.theme")) === "dark" && (await evaluate("localStorage.getItem('studio.theme')")) === "dark");
check("theme storage holds no token", !(await evaluate("JSON.stringify(Object.assign({}, localStorage))")).includes(TOKEN));
await send("Emulation.setEmulatedMedia", {features: [{name: "prefers-color-scheme", value: "dark"}]});
await evaluate(`document.querySelector('[data-theme-choice="system"]').click(); true`);
check("system mode follows dark preference", (await evaluate("document.documentElement.dataset.theme")) === "dark");
await send("Emulation.setEmulatedMedia", {features: [{name: "prefers-color-scheme", value: "light"}]});
await sleep(150);
check("system mode follows light preference", (await evaluate("document.documentElement.dataset.theme")) === "light");
await send("Emulation.setEmulatedMedia", {features: []});

// 3. Tool request path (real recorded run), Live Activity mode.
await open("real_fsc147_row0_studio", {theme: "light", mode: "live"});
let sel = await selectAt(`(e) => e.event_type === "TOOL_CALL_REQUESTED" && e.agent_id === "worker_02"`);
await frames();
let flows = await selectedFlows();
check("tool request highlights request-direction path", flows.length === 2 && flows.every((c) => c.includes("flow-request")), JSON.stringify(flows));
check("replay hides future final answer", (await evaluate("document.querySelector('#final-answer').classList.contains('empty-state')")));
check("replay result node pending", (await evaluate(`document.querySelector('[data-node="result"] .node-sub').textContent`)) === "pending");
await shot("03-tool-request-path", ".architecture-panel");

// Advance to STARTED to show running tool, then the result.
sel = await selectAt(`(e) => e.event_type === "TOOL_CALL_STARTED" && e.agent_id === "worker_02"`);
await frames();
check("running tool shows running state", await evaluate(`document.querySelector('[data-node="tool:Visual_Grounding_Tool"]').classList.contains('is-running')`));
sel = await selectAt(`(e) => e.event_type === "TOOL_CALL_COMPLETED" && e.agent_id === "worker_01"`);
await frames();
flows = await selectedFlows();
check("tool result highlights response-direction path", flows.length === 3 && flows.every((c) => c.includes("flow-response")), JSON.stringify(flows));
const reverse = await evaluate(`(() => { const p = [...document.querySelectorAll('.flow.on.level-selected')][0]; return p.getAttribute('d'); })()`);
check("response overlay geometry is distinct from request direction", Boolean(reverse));
await send("Emulation.setEmulatedMedia", {features: []});
await evaluate(`localStorage.setItem("studio.theme", "dark"); StudioTheme.apply("dark"); true`);
await shot("04-tool-result-return-path", ".architecture-panel");
// 9. ROI evidence for the same selection.
await evaluate(`localStorage.setItem("studio.theme", "light"); StudioTheme.apply("light"); true`);
await frames(); await sleep(500);
// Runs that record the processed image use the tool-action workspace; others the original viewer.
await waitFor(`!document.querySelector('#tool-action').classList.contains('hidden') ? [...document.querySelectorAll('#tool-action img')].every((i) => i.complete && i.naturalWidth > 0) : true`, 10000);
const roi = await evaluate(`({rects: document.querySelectorAll('#image-stage .overlay rect').length + document.querySelectorAll('#tool-action .ta-shape.det rect').length,
  label: document.querySelector('#tool-action').classList.contains('hidden') ? document.querySelector('#coordinate-label').textContent : document.querySelector('#tool-action .ta-panel figcaption')?.textContent || ''})`);
check("ROI boxes drawn with authoritative dimensions", roi.rects > 0 && (roi.label.includes("source pixels") || /\d+×\d+/.test(roi.label)), JSON.stringify(roi));
await evaluate("document.querySelector('.workspace').scrollIntoView(); true");
await shot("09-selected-event-roi-evidence");
await evaluate("scrollTo(0, 0); true");

// Stable DOM identities while replay advances.
const stable = await evaluate(`(async () => {
  const before = document.querySelector('[data-node="worker_01"]');
  setReplayIndex(state.replayIndex + 3);
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  return before === document.querySelector('[data-node="worker_01"]');
})()`);
check("graph nodes keep DOM identity across updates", stable);

// 7. Coordinator assignment; 8. memory write.
sel = await selectAt(`(e) => e.event_type === "MESSAGE_SENT" && e.agent_id === "coordinator" && e.payload.message_type === "TASK_ASSIGNMENT"`);
await frames();
flows = await selectedFlows();
check("coordinator assignment travels coordinator → bus", flows.length === 1 && flows[0].includes("flow-control"), JSON.stringify(flows));
await shot("07-coordinator-assignment", ".architecture-panel");
sel = await selectAt(`(e) => e.event_type === "MEMORY_WRITTEN" && e.agent_id === "worker_01"`);
await frames();
flows = await selectedFlows();
check("memory write highlights harness → memory", flows.length === 1 && flows[0].includes("flow-memory"), JSON.stringify(flows));
await shot("08-worker-memory-write", ".architecture-panel");

// Backward stepping removes later activity; go-live restores current status.
// The raw timeline lives in the "Event log" tab (the story is the default tab).
await evaluate(`setTab("log"); state.selectedEventId = null; setReplayIndex(5); true`); await frames();
check("backward replay clears later running tools", (await evaluate("document.querySelectorAll('.node.is-running').length")) === 0);
check("backward replay hides later timeline cards", (await evaluate("document.querySelectorAll('.event-card').length")) === 5);
await evaluate("goLive(); true"); await frames();
check("go live restores final answer", !(await evaluate("document.querySelector('#final-answer').classList.contains('empty-state')")));

// 5-6. Worker question and correlated reply; concurrent same-tool calls (fixture).
await open("studio_protocol_fixture", {theme: "light", mode: "live"});
sel = await selectAt(`(e) => e.event_type === "MESSAGE_SENT" && e.payload.message_type === "QUESTION"`);
await frames();
flows = await selectedFlows();
check("worker question travels sender → bus", flows.length === 1 && flows[0].includes("flow-message"), JSON.stringify(flows));
check("question queued for recipient", await evaluate(`document.querySelector('[data-node="comm_bus"]').classList.contains('is-queued')`));
await shot("05-worker-to-worker-question", ".architecture-panel");
sel = await selectAt(`(e) => e.event_type === "MESSAGE_SENT" && e.activity && e.activity.kind === "reply"`);
await frames();
// The caption shows the story step; the raw flow label is in the caption detail.
const caption = await evaluate("document.querySelector('#activity-label').textContent + ' | ' + document.querySelector('#activity-detail').textContent");
flows = await selectedFlows();
check("reply recognised from correlation id", caption.includes("Worker 3 replied to Worker 1") && caption.includes("Worker 3 → Worker 1") && flows[0]?.includes("flow-message-return"), caption);
await evaluate(`localStorage.setItem("studio.theme", "dark"); StudioTheme.apply("dark"); true`);
await shot("06-worker-to-worker-reply", ".architecture-panel");
await evaluate(`localStorage.setItem("studio.theme", "light"); StudioTheme.apply("light"); true`);
sel = await selectAt(`(e) => e.event_type === "TOOL_CALL_STARTED" && e.agent_id === "worker_02"`);
await evaluate("state.selectedEventId = null; renderAll(); true"); await frames();
const concurrent = await evaluate(`({running: document.querySelector('[data-node="tool:Visual_Grounding_Tool"] .node-sub').textContent, w1: document.querySelector('[data-node="worker_01"] .node-sub').textContent, w2: document.querySelector('[data-node="worker_02"] .node-sub').textContent, flows: document.querySelectorAll('.flow.on.level-running').length})`);
check("concurrent same-tool calls both shown running", concurrent.running.includes("×2") && concurrent.w1.includes("Running") && concurrent.w2.includes("Running"), JSON.stringify(concurrent));
await shot("11-concurrent-same-tool-calls", ".architecture-panel");

// Edge and node inspectors.
await evaluate(`selectEdge("worker_01->comm_bus"); true`); await frames();
check("edge inspector lists related events", (await evaluate("document.querySelectorAll('#inspector .event-link').length")) > 0);
await evaluate(`selectNode("worker_03"); true`); await frames();
const inspector = await evaluate("document.querySelector('#inspector').textContent");
check("node inspector shows agent details without fetching memory", inspector.includes("Agent ID") && (await evaluate("document.querySelector('#memory-content').textContent")).includes("Select an agent"));

// 10. Completed deterministic demo in replay mode, dark theme.
await open("studio_demo_architecture", {theme: "dark", mode: "full"});
await evaluate("setReplayIndex(state.events.length - 1); true"); await frames();
check("demo replay labelled deterministic", (await evaluate("document.querySelector('#replay-mode').textContent")) === "Deterministic replay");
await shot("10-completed-run-replay-dark");
await shot("02-full-page-dark");

// Reduced motion disables animation classes.
await send("Emulation.setEmulatedMedia", {features: [{name: "prefers-reduced-motion", value: "reduce"}]});
await evaluate("localStorage.setItem('studio.flowAnimation', 'on'); state.graph.setOptions({animate: true}); true");
check("reduced motion disables flow animation", !(await evaluate("document.querySelector('.arch-svg').classList.contains('animate')")));

// Legacy (pre-Studio) run remains viewable.
await open("real_two_worker_smoke_v3", {theme: "light"});
check("legacy run renders graph", (await evaluate("document.querySelectorAll('.arch-svg .node').length")) > 10);

// ---------------------------------------------------------------------------
// Lifecycle and empty states.
const graphStats = () => evaluate(`(() => {
  const svg = document.querySelector('.arch-svg'); const r = svg ? svg.getBoundingClientRect() : {width: 0, height: 0};
  const visibleEdges = [...document.querySelectorAll('.arch-svg .edge')].filter((e) => getComputedStyle(e).display !== 'none').length;
  const boxes = [...document.querySelectorAll('.arch-svg .node-box')].map((b) => b.getBBox());
  return {nodes: document.querySelectorAll('.arch-svg .node').length, edges: document.querySelectorAll('.arch-svg .edge').length, visibleEdges,
    finite: boxes.every((b) => [b.x, b.y, b.width, b.height].every(Number.isFinite) && b.width > 0 && b.height > 0),
    width: r.width, height: r.height, scope: ((svg && svg.getAttribute('class')) || '').match(/scope-([a-z]+)/)?.[1] || null,
    viewBox: (svg && svg.getAttribute('viewBox')) || '', activeFlows: document.querySelectorAll('.flow.on').length,
    chip: document.querySelector('#connection-state').textContent, notice: document.querySelector('#graph-notice').textContent,
    title: document.querySelector('#architecture-title').textContent, task: document.querySelector('#task-title').textContent};
})()`);
async function visit(url, {theme = "light", until = "true", tries = 80} = {}) {
  await send("Page.navigate", {url: `${BASE}/?blank=${loads}`}); await sleep(300);
  await evaluate(`localStorage.setItem("studio.theme", ${JSON.stringify(theme)}); localStorage.setItem("studio.flowAnimation", "off"); localStorage.setItem("studio.graph", JSON.stringify({mode: "full", viewMode: "full"})); true`);
  loads += 1;
  await send("Page.navigate", {url: url.replace("/#", `/?visit=${loads}#`).replace(/\/$/, `/?visit=${loads}`)});
  for (let i = 0; i < tries; i += 1) { await sleep(150); if (await evaluate(`Boolean(${until})`).catch(() => false)) break; }
  await frames();
}
async function mintLink(run) {
  const response = await fetch(`${BASE}/api/launch-tickets`, {method: "POST", headers: {"X-Studio-Token": TOKEN, "Content-Type": "application/json"}, body: "{}"});
  const {ticket} = await response.json();
  return `${BASE}/#${new URLSearchParams(run ? {ticket, run} : {ticket})}`;
}
const viewValid = (stats) => /^-?[\d.]+ -?[\d.]+ [\d.]+ [\d.]+$/.test(stats.viewBox) && stats.width > 300 && stats.height > 200;

// A. Disconnected: generic preview, no data, no activity.
await visit(`${BASE}/`, {until: "document.querySelector('.arch-svg .node') && document.querySelector('#connection-state').textContent === 'Authentication required'"});
let stats = await graphStats();
const previewCounts = await evaluate("({nodes: StudioGraph.previewTopology().nodes.length, edges: StudioGraph.previewTopology().edges.length})");
check("A disconnected: preview architecture drawn", stats.scope === "preview" && stats.nodes === previewCounts.nodes && stats.edges === previewCounts.edges && stats.finite && viewValid(stats), JSON.stringify({...stats, notice: undefined}));
check("A disconnected: labelled as preview, not live", stats.title.includes("Architecture preview — not live execution"));
check("A disconnected: no activity and no run data", stats.activeFlows === 0 && !(await evaluate("document.body.innerText")).match(/fsc147|worker_0\d|real_/i));
check("A disconnected: connection instructions visible", stats.chip === "Authentication required" && stats.notice.includes("viewer token"));
await shot("13-disconnected-architecture-preview", ".architecture-panel");

// Invalid token is visible, not silent.
await visit(`${BASE}/#token=definitely-wrong`, {until: "document.querySelector('#connection-state').textContent === 'Invalid token'"});
stats = await graphStats();
check("L invalid token reported", stats.chip === "Invalid token" && stats.notice.includes("rejected") && stats.scope === "preview");

// B. Connected without a run: configured architecture with a worker template.
await visit(await mintLink(null), {until: "document.querySelector('.arch-svg.scope-configured .node')"});
stats = await graphStats();
const configured = await evaluate("state.configured && {nodes: state.configured.nodes.length, edges: state.configured.edges.length, tools: state.configured.nodes.filter((n) => n.type === 'tool').length, agents: state.configured.agents}");
check("B connected: configured architecture drawn", stats.scope === "configured" && configured && stats.nodes === configured.nodes && stats.edges === configured.edges && stats.finite && viewValid(stats), JSON.stringify({nodes: stats.nodes, edges: stats.edges, configured}));
check("B connected: worker template, not invented workers", JSON.stringify(configured.agents) === JSON.stringify(["coordinator", "worker_template"]) && (await evaluate("document.querySelectorAll('.group-worker_template').length")) === 1);
check("B connected: labelled configured, no activity", stats.title.includes("Configured architecture — no task running") && stats.activeFlows === 0 && stats.chip === "Connected");
check("B connected: run menu populated", (await evaluate("document.querySelector('#run-select').options.length")) > 2 && !(await evaluate("document.querySelector('#run-select').disabled")));
check("B connected: token removed from URL and field", !(await evaluate("location.href")).includes("ticket") && (await evaluate("document.querySelector('#token').value")) === "");
await shot("14-connected-configured-architecture", ".architecture-panel");
await evaluate(`localStorage.setItem("studio.theme", "dark"); StudioTheme.apply("dark"); true`);
await shot("15-connected-configured-architecture-dark", ".architecture-panel");

// Used launch link cannot be replayed.
const link = await mintLink("real_fsc147_row0_studio");
await visit(link, {until: "state.runId === 'real_fsc147_row0_studio'"});
await visit(link, {until: "document.querySelector('#connection-state').textContent === 'Authentication required'"});
stats = await graphStats();
check("L launch link is single-use", stats.notice.includes("expired or was already used") && stats.scope === "preview");

// C. Completed real run, full architecture, via a launch link.
await visit(await mintLink("real_fsc147_row0_studio"), {until: "state.runId === 'real_fsc147_row0_studio' && document.querySelector('.arch-svg.scope-run')"});
stats = await graphStats();
await evaluate(`setTab("log"); true`); await frames();
const runTopo = await evaluate("({nodes: state.topology.nodes.length, edges: state.topology.edges.length, workers: state.topology.agents.filter((a) => a.startsWith('worker_')).length})");
check("C real run: run topology drawn", stats.scope === "run" && stats.nodes === runTopo.nodes && stats.edges === runTopo.edges && runTopo.workers === 2 && stats.finite && viewValid(stats), JSON.stringify(runTopo));
check("C real run: task, timeline, final answer, evidence", stats.task.includes("seagull") && (await evaluate("document.querySelectorAll('.event-card').length")) > 50
  && !(await evaluate("document.querySelector('#final-answer').classList.contains('empty-state')")) && (await evaluate("Boolean(document.querySelector('#image-stage img') || document.querySelector('#tool-action img'))")));
check("C real run: run kept in URL without credentials", (await evaluate("location.hash")) === "#run=real_fsc147_row0_studio");
await shot("16-completed-real-run-full-architecture", ".architecture-panel");

// J. Replay then switch runs resets state.
await evaluate("setReplayIndex(20); state.selectedEventId = state.events[10].event_id; renderAll(); true"); await frames();
check("J replay keeps topology visible", (await graphStats()).nodes === runTopo.nodes);
await evaluate(`(() => { const s = document.querySelector('#run-select'); s.value = 'studio_protocol_fixture'; s.dispatchEvent(new Event('change')); return true; })()`);
for (let i = 0; i < 40 && !(await evaluate("state.runId === 'studio_protocol_fixture' && state.events.length > 0")); i += 1) await sleep(150);
await frames();
check("J switching runs resets replay and selection", await evaluate("state.live && state.selectedEventId === null && state.topology.agents.length === 4"));
// Going live again after replay leaves the graph intact.
await evaluate("setReplayIndex(5); goLive(); true"); await frames();
check("J returning to live keeps graph", (await graphStats()).nodes > 20);

// I. Legacy run without topology manifest.
await visit(await mintLink("real_two_worker_smoke_v3"), {until: "state.runId === 'real_two_worker_smoke_v3' && document.querySelector('.arch-svg.scope-run')"});
stats = await graphStats();
const legacy = await evaluate("({nodes: state.topology.nodes.length, inferred: state.topology.nodes.filter((n) => n.provenance !== 'configured').length, source: state.topology.source})");
check("I legacy run renders observed/inferred structure", stats.nodes === legacy.nodes && legacy.inferred > 0 && stats.finite, JSON.stringify(legacy));
await shot("17-legacy-run", ".architecture-panel");

// K. Laptop size.
await send("Emulation.setDeviceMetricsOverride", {width: 1366, height: 768, deviceScaleFactor: 1, mobile: false});
await frames();
stats = await graphStats();
check("K laptop size: graph visible", stats.width > 900 && stats.height > 300 && stats.nodes > 10, `${Math.round(stats.width)}x${Math.round(stats.height)}`);
await shot("18-laptop-size");
await send("Emulation.setDeviceMetricsOverride", {width: 1600, height: 1250, deviceScaleFactor: 1, mobile: false});

// H. Requested run appears only after the browser opened.
const pendingRun = `studio_pending_${Date.now()}`;
await visit(await mintLink(pendingRun), {until: "document.querySelector('#connection-state').textContent === 'Waiting for run'"});
check("H waiting state shown for not-yet-existing run", (await graphStats()).notice.includes(pendingRun));
const produced = spawn("python", ["scripts/studio_protocol_fixture.py", "--output-dir", "outputs/multi_agent", "--run-id", pendingRun], {stdio: "ignore"});
await new Promise((resolve) => produced.on("exit", resolve));
for (let i = 0; i < 60 && !(await evaluate(`state.runId === ${JSON.stringify(pendingRun)} && state.events.length > 50`)); i += 1) await sleep(200);
await frames();
stats = await graphStats();
check("H run discovered and loaded without refresh", stats.scope === "run" && (await evaluate(`state.runId`)) === pendingRun && stats.nodes > 20);
rmSync(join("outputs/multi_agent", pendingRun), {recursive: true, force: true});
rmSync(join("outputs/multi_agent", `${pendingRun}_source.png`), {force: true});

// F. Outdated backend serving these static files.
if (args["old-port"]) {
  const old = spawn("python", ["tests/studio/fake_old_studio.py", args["old-port"], "old-backend-token"], {stdio: "ignore"});
  await sleep(800);
  const oldBase = `http://127.0.0.1:${args["old-port"]}`;
  await send("Page.navigate", {url: `${oldBase}/?visit=${loads++}#token=old-backend-token`});
  for (let i = 0; i < 40 && (await evaluate("document.querySelector('#connection-state')?.textContent").catch(() => "")) !== "Backend incompatible"; i += 1) await sleep(150);
  await frames();
  const incompatible = await evaluate("({chip: document.querySelector('#connection-state').textContent, notice: document.querySelector('#graph-notice').textContent, connect: document.querySelector('#connect').disabled, nodes: document.querySelectorAll('.arch-svg .node').length})");
  check("F outdated backend detected, not treated as connected", incompatible.chip === "Backend incompatible" && incompatible.notice.includes("outdated") && incompatible.connect && incompatible.nodes > 0, JSON.stringify(incompatible).slice(0, 200));
  await shot("19-incompatible-backend", ".architecture-panel");
  old.kill("SIGTERM");
}

await finish("browser-checks.json");
