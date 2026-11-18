#!/usr/bin/env node
/*
 * Headless-Chrome validation and screenshots for the answer strip, coordinator
 * estimates, ground-truth release, compact team view, and configuration runs.
 *
 * Usage (start a Studio on a runs directory first, see docs/INVESTIGATION_STUDIO.md):
 *   STUDIO_VIEWER_TOKEN=... STUDIO_EVALUATOR_TOKEN=... node scripts/studio_browser_matrix.mjs \
 *     --base http://127.0.0.1:8799 --runs-dir outputs/studio_validation --out docs/images/studio_v3
 *
 * Expects fixture runs fixture_w1_memoff_peeroff, fixture_w2_memon_peeron,
 * fixture_w3_memon_peeroff, fixture_w4_memoff_peeron and (optional) legacy_demo
 * in the runs directory. It starts one slow deterministic fixture run itself to
 * observe the sealed reference and live estimates. Tokens are read from the
 * environment, exchanged through launch tickets, and never printed.
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
const OUT = args.out || "docs/images/studio_v3";
const RUNS = args["runs-dir"] || "outputs/studio_validation";
const CHROME = args.chrome || "google-chrome";
const TOKEN = process.env.STUDIO_VIEWER_TOKEN;
const EVALUATOR = process.env.STUDIO_EVALUATOR_TOKEN;
if (!TOKEN || !EVALUATOR) { console.error("Set STUDIO_VIEWER_TOKEN and STUDIO_EVALUATOR_TOKEN"); process.exit(2); }
mkdirSync(OUT, {recursive: true});

const profile = mkdtempSync(join(tmpdir(), "studio-chrome-"));
const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--window-size=1600,1000", "about:blank"],
{stdio: ["ignore", "ignore", "pipe"]});
const wsUrl = await new Promise((resolve, reject) => {
  let buffer = "";
  chrome.stderr.on("data", (chunk) => { buffer += chunk; const match = /DevTools listening on (ws:\/\/\S+)/.exec(buffer); if (match) resolve(match[1]); });
  chrome.on("exit", () => reject(new Error("Chrome exited")));
  setTimeout(() => reject(new Error("Chrome did not start")), 20000);
});
const port = new URL(wsUrl).port;
const page = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((target) => target.type === "page");
const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve) => socket.addEventListener("open", resolve, {once: true}));
let nextId = 0; const pending = new Map(); const problems = [];
socket.addEventListener("message", (message) => {
  const data = JSON.parse(message.data);
  if (data.id && pending.has(data.id)) { const {resolve, reject} = pending.get(data.id); pending.delete(data.id); if (data.error) reject(new Error(data.error.message)); else resolve(data.result); }
  else if (data.method === "Runtime.exceptionThrown") problems.push(`exception: ${data.params.exceptionDetails.exception?.description || data.params.exceptionDetails.text}`);
  else if (data.method === "Runtime.consoleAPICalled" && data.params.type === "error") problems.push(`console.error: ${data.params.args.map((a) => a.value ?? a.description).join(" ")}`);
  else if (data.method === "Log.entryAdded" && data.params.entry.level === "error") problems.push(`log: ${data.params.entry.text} ${data.params.entry.url || ""}`);
});
const send = (method, params = {}) => new Promise((resolve, reject) => { const id = ++nextId; pending.set(id, {resolve, reject}); socket.send(JSON.stringify({id, method, params})); });
const evaluate = async (expression) => {
  const result = await send("Runtime.evaluate", {expression, awaitPromise: true, returnByValue: true});
  if (result.exceptionDetails) throw new Error(`${expression.slice(0, 80)}: ${result.exceptionDetails.exception?.description}`);
  return result.result.value;
};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const frames = () => evaluate("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 150))))");
await send("Page.enable"); await send("Runtime.enable"); await send("Log.enable");

let width = 1600; let height = 1000;
async function viewport(w, h) { width = w; height = h; await send("Emulation.setDeviceMetricsOverride", {width: w, height: h, deviceScaleFactor: 1, mobile: false}); }
await viewport(1600, 1000);

async function ticket(evaluator) {
  const headers = {"X-Studio-Token": TOKEN, "Content-Type": "application/json"};
  if (evaluator) headers["X-Studio-Evaluator-Token"] = EVALUATOR;
  const response = await fetch(`${BASE}/api/launch-tickets`, {method: "POST", headers, body: JSON.stringify({ttl_seconds: 120, ...(evaluator ? {scopes: ["evaluator"]} : {})})});
  if (!response.ok) throw new Error(`ticket ${response.status}`);
  return (await response.json()).ticket;
}

let loads = 0;
async function open(run, {theme = "light", view = "team", evaluator = true, waitEvents = 1} = {}) {
  await send("Page.navigate", {url: `${BASE}/?blank=${loads}`});
  await sleep(300);
  await evaluate(`localStorage.setItem("studio.theme", ${JSON.stringify(theme)}); localStorage.setItem("studio.graph", JSON.stringify({mode: "full", viewMode: ${JSON.stringify(view)}, showMemory: true, showMemoryFlows: true, showInfra: false})); localStorage.setItem("studio.flowAnimation", "off"); true`);
  const fragment = new URLSearchParams({ticket: await ticket(evaluator), run}).toString();
  loads += 1;
  await send("Page.navigate", {url: `${BASE}/?view=${loads}#${fragment}`});
  for (let i = 0; i < 80; i += 1) {
    await sleep(150);
    const ready = await evaluate(`Boolean(typeof state !== 'undefined' && state.runId === ${JSON.stringify(run)} && state.events.length >= ${waitEvents} && document.querySelector('#team-view .harness'))`).catch(() => false);
    if (ready) break;
  }
  await frames();
}

async function shot(name, selector = null) {
  await frames();
  const clip = selector ? await evaluate(`(() => { const r = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect(); return {x: r.x + scrollX, y: r.y + scrollY, width: r.width, height: r.height, scale: 1}; })()`) : null;
  if (clip) await evaluate(`document.querySelector('.replay-bar').style.visibility = 'hidden'; true`);
  const result = await send("Page.captureScreenshot", {format: "png", captureBeyondViewport: Boolean(clip), ...(clip ? {clip} : {})});
  if (clip) await evaluate(`document.querySelector('.replay-bar').style.visibility = ''; true`);
  const bytes = Buffer.from(result.data, "base64");
  writeFileSync(join(OUT, `${name}.png`), bytes);
  // Verify the image content, not just the file: real PNG, expected size, non-uniform pixels.
  const ok = bytes.readUInt32BE(0) === 0x89504e47 && bytes.length > 8000;
  check(`screenshot ${name} is a nonblank PNG`, ok, `${bytes.length} bytes`);
  return bytes;
}

const checks = [];
function check(name, condition, detail = "") { checks.push({name, ok: Boolean(condition), detail}); console.log(`${condition ? "PASS" : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`); }

/** Layout facts about the compact team view at the current viewport. */
const layoutProbe = `(() => {
  const cards = [...document.querySelectorAll('#team-view .harness')].map((c) => { const r = c.getBoundingClientRect(); return {agent: c.dataset.agent, x: r.x, y: r.y, w: r.width, h: r.height}; });
  const workers = cards.filter((c) => c.agent !== 'coordinator');
  const overlaps = [];
  for (let i = 0; i < cards.length; i += 1) for (let j = i + 1; j < cards.length; j += 1) {
    const a = cards[i], b = cards[j];
    if (a.x < b.x + b.w - 1 && b.x < a.x + a.w - 1 && a.y < b.y + b.h - 1 && b.y < a.y + a.h - 1) overlaps.push(a.agent + '/' + b.agent);
  }
  const clipped = [...document.querySelectorAll('#team-view .harness-name, #team-view .as-label, #answer-strip .as-label')].filter((n) => n.scrollWidth > n.clientWidth + 1).length;
  const rows = new Set(workers.map((c) => Math.round(c.y / 10))).size;
  return {cards: cards.length, agents: [...new Set(cards.map((c) => c.agent))].length, workers: workers.length, rows,
    maxWorkerHeight: Math.max(0, ...workers.map((c) => c.h)), minWorkerWidth: Math.min(9999, ...workers.map((c) => c.w)), overlaps,
    pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, clipped,
    teamHeight: document.querySelector('#team-view').getBoundingClientRect().height,
    memory: workers.map((c) => document.querySelector('#team-view .harness[data-agent="' + c.agent + '"] .badge.memory .badge-text').textContent),
    peer: workers.map((c) => document.querySelector('#team-view .harness[data-agent="' + c.agent + '"] .badge.peer .badge-text').textContent),
    chips: workers.map((c) => document.querySelectorAll('#team-view .harness[data-agent="' + c.agent + '"] .chip.tool').length),
    model: document.querySelector('#team-view .harness[data-agent="coordinator"] .badge.model .badge-text')?.textContent };
})()`;
const strip = `({gt: document.querySelector('#gt-value').textContent, gtState: document.querySelector('#gt-cell').dataset.state, gtNote: document.querySelector('#gt-note').textContent,
  est: document.querySelector('#est-value').textContent, estStatus: document.querySelector('#est-cell').dataset.status, estNote: document.querySelector('#est-note').textContent,
  final: document.querySelector('#final-value').textContent, evaluation: document.querySelector('#eval-label').textContent, evalHidden: document.querySelector('#eval-label').classList.contains('hidden'),
  round: document.querySelector('#as-round').textContent, sticky: getComputedStyle(document.querySelector('#answer-strip')).position})`;
async function waitFor(expression, timeout = 15000) { const end = Date.now() + timeout; while (Date.now() < end) { if (await evaluate(expression).catch(() => false)) return true; await sleep(200); } return false; }

// ---- optional: real recorded runs (UI/replay verification only) -------------------------
if (args["real-runs"]) {
  for (const run of args["real-runs"].split(",")) {
    await open(run);
    await waitFor(`Boolean(state.reference) && document.querySelector('#gt-cell').dataset.state !== 'LOADING'`, 30000);
    const layout = await evaluate(layoutProbe);
    const s = await evaluate(strip);
    const total = await evaluate(`state.events.length`);
    const expected = await evaluate(`state.snapshot.effective_config.num_workers`);
    check(`${run}: ${expected} worker cards + coordinator, no overlap`, layout.workers === expected && layout.agents === layout.cards && !layout.overlaps.length, `${layout.workers} workers, ${total} events`);
    check(`${run}: reference released post-run with evaluation`, s.gtState === "AVAILABLE" && !s.evalHidden, `${s.gt} · ${s.evaluation} · final ${s.final}`);
    const history = await evaluate(`[...document.querySelectorAll('#estimate-history .eh-entry .eh-desc')].map((n) => n.textContent)`);
    check(`${run}: estimate history from recorded events`, history.length >= 1, history.join(" | "));
    await evaluate(`setReplayIndex(0); true`); await frames();
    const start = await evaluate(strip);
    check(`${run}: replay start shows no estimate and no final`, start.est === "No estimate yet" && start.final === "—", JSON.stringify({est: start.est, final: start.final}));
    await evaluate(`goLive(); true`); await frames();
    await shot(run);
  }
  const unexpected = problems.filter((item) => !/status of 40[13]/.test(item));
  check("no console errors or exceptions", unexpected.length === 0, unexpected.slice(0, 5).join(" | "));
  writeFileSync(join(OUT, "browser-real-runs-report.json"), `${JSON.stringify({checks, problems}, null, 2)}\n`);
  socket.close(); chrome.kill("SIGTERM"); await sleep(300); rmSync(profile, {recursive: true, force: true});
  const failed = checks.filter((item) => !item.ok);
  console.log(`${checks.length - failed.length}/${checks.length} browser checks passed`);
  process.exit(failed.length ? 1 : 0);
}

// ---- 1-4: configuration runs, compact team view --------------------------------------
const CONFIGS = [
  {run: "fixture_w1_memoff_peeroff", n: 1, memory: "Memory off", peer: "Peer off", shot: "01-w1-memory-off-peer-off"},
  {run: "fixture_w2_memon_peeron", n: 2, memory: "Memory on", peer: "Peer on", shot: "02-w2-memory-on-peer-on"},
  {run: "fixture_w3_memon_peeroff", n: 3, memory: "Memory on", peer: "Peer off", shot: "03-w3-memory-on-peer-off"},
  {run: "fixture_w4_memoff_peeron", n: 4, memory: "Memory off", peer: "Peer on", shot: "04-w4-memory-off-peer-on"},
];
for (const config of CONFIGS) {
  await open(config.run);
  await waitFor(`document.querySelector('#gt-cell').dataset.state === 'AVAILABLE'`);
  const layout = await evaluate(layoutProbe);
  check(`${config.run}: ${config.n} worker cards + 1 coordinator`, layout.workers === config.n && layout.cards === config.n + 1, JSON.stringify({cards: layout.cards}));
  check(`${config.run}: one card per agent (no duplicate harness/agent blocks)`, layout.agents === layout.cards);
  check(`${config.run}: memory indicators`, layout.memory.every((t) => t === config.memory), layout.memory.join(","));
  check(`${config.run}: peer indicators`, layout.peer.every((t) => t === config.peer), layout.peer.join(","));
  check(`${config.run}: tool chips inside every worker card`, layout.chips.every((n) => n >= 1), layout.chips.join(","));
  check(`${config.run}: compact cards (worker height ≤ 300 px)`, layout.maxWorkerHeight <= 300, `${Math.round(layout.maxWorkerHeight)} px`);
  check(`${config.run}: no overlapping cards, no horizontal page scroll`, !layout.overlaps.length && layout.pageOverflow <= 0, JSON.stringify({overlaps: layout.overlaps, overflow: layout.pageOverflow}));
  check(`${config.run}: all workers in one row at 1600 px`, layout.rows === 1, `rows ${layout.rows}`);
  check(`${config.run}: team view fits a desktop screen`, layout.teamHeight < 720, `${Math.round(layout.teamHeight)} px`);
  const s = await evaluate(strip);
  check(`${config.run}: ground truth released to evaluator after completion`, s.gtState === "AVAILABLE" && s.gt === "5", JSON.stringify(s));
  check(`${config.run}: separate final answer and evaluation label`, s.final === "5" && s.evaluation.includes("Correct"), s.evaluation);
  const config2 = await evaluate(`[...document.querySelectorAll('#config-chips .cfg-chip')].map((c) => c.textContent).join(' | ')`);
  check(`${config.run}: effective configuration chips`, config2.includes(`Workers${config.n}`), config2);
  await shot(config.shot);
}

// ---- 11-13: light/dark compact architecture and expanded detail ------------------------
await open("fixture_w4_memoff_peeron", {theme: "light"});
await evaluate(`document.querySelector('.architecture-panel').scrollIntoView({block: 'start'}); window.scrollBy(0, -150); true`);
await shot("11-compact-architecture-light", ".architecture-panel");
await open("fixture_w4_memoff_peeron", {theme: "dark"});
const darkBg = await evaluate(`getComputedStyle(document.body).backgroundColor`);
check("dark theme applied", darkBg === "rgb(14, 19, 26)", darkBg);
const contrast = await evaluate(`(() => { const c = getComputedStyle(document.querySelector('#team-view .harness .harness-name')).color; const b = getComputedStyle(document.querySelector('#team-view .harness')).backgroundColor; return c + ' on ' + b; })()`);
check("dark theme card text uses theme tokens", contrast.includes("rgb(") && !contrast.startsWith("rgb(0, 0, 0)"), contrast);
await shot("12-compact-architecture-dark", ".architecture-panel");
await open("fixture_w2_memon_peeron", {theme: "light"});
await evaluate(`document.querySelector('#team-view .harness[data-agent="worker_02"] .expand').click(); true`);
await frames();
const expanded = await evaluate(`(() => { const d = document.querySelector('#team-view .harness[data-agent="worker_02"] .harness-details'); return {hidden: d.hidden, rows: d.querySelectorAll('dt').length, text: d.textContent}; })()`);
check("expanded harness shows model, memory, peer, tools, and budget", !expanded.hidden && expanded.rows >= 7 && expanded.text.includes("Working context") && expanded.text.includes("left"), `${expanded.rows} rows`);
await shot("13-expanded-harness-detail", ".architecture-panel");
await evaluate(`document.querySelector('#team-view .harness[data-agent="worker_02"] .expand').click(); document.querySelectorAll('[data-graph-mode]')[1].click(); true`);
await frames();
const fullNodes = await evaluate(`document.querySelectorAll('#agent-graph .arch-svg .node').length`);
check("full architecture view still renders the technical graph", fullNodes >= 15, `${fullNodes} SVG nodes`);
await evaluate(`document.querySelectorAll('[data-graph-mode]')[0].click(); true`);

// ---- 9-10, 14: replay of the N=1 run (initial → revised → final), causal evidence ---------
await open("fixture_w1_memoff_peeroff");
const positions = await evaluate(`(() => { const idx = (t, n = 0) => state.events.map((e, i) => [e, i]).filter(([e]) => e.event_type === t)[n]?.[1];
  return {first: idx('COORDINATOR_ESTIMATE_UPDATED', 0), revised: idx('COORDINATOR_ESTIMATE_UPDATED', 1), final: idx('FINAL_ANSWER_RECORDED', 0), total: state.events.length}; })()`);
const at = async (count) => { await evaluate(`setReplayIndex(${count}); true`); await frames(); return evaluate(strip); };
let s = await at(positions.first);
check("replay before first estimate shows no estimate and no final answer", s.est === "No estimate yet" && s.estStatus === "none" && s.final === "—", JSON.stringify(s));
await shot("07-before-first-estimate");
s = await at(positions.first + 1);
check("replay at first estimate shows provisional 4 and no final", s.est === "4" && s.estStatus === "provisional" && s.final === "—", JSON.stringify(s));
await shot("08-first-provisional-estimate");
s = await at(positions.revised + 1);
check("replay at revision shows revised 5 (never the later final early)", s.est === "5" && s.estStatus === "revised" && s.final === "—", JSON.stringify(s));
await shot("09-revised-estimate");
s = await at(positions.final);
check("replay one step before final answer keeps the final field empty", s.final === "—", JSON.stringify(s));
s = await at(positions.final + 1);
check("final answer appears with its own event", s.final === "5" && s.estStatus === "final" && !s.evalHidden, JSON.stringify(s));
await at(positions.total);
const history = await evaluate(`[...document.querySelectorAll('#estimate-history .eh-entry')].map((n) => n.querySelector('.eh-desc').textContent)`);
check("estimate history lists provisional, revision, and confirming final", history.length === 3 && history[1].includes("Revised 4 → 5") && history[2].includes("confirms"), history.join(" | "));
await evaluate(`document.querySelector('#estimate-history-panel').scrollIntoView({block: 'center'}); true`);
await shot("10-final-answer");
// Select the revision in the story and verify linked evidence and ROI.
await evaluate(`window.scrollTo(0, 0); [...document.querySelectorAll('.story-step')].find((n) => n.textContent.includes('Answer revised')).click(); true`);
await frames(); await sleep(400); await frames();
const sync = await evaluate(`({linked: document.querySelectorAll('.story-step.linked').length, roi: document.querySelectorAll('#image-stage .overlay rect').length,
  crop: Boolean(document.querySelector('#derived-stage img')), shown: [...document.querySelectorAll('#evidence-facts .fact')].map((f) => f.textContent).join(' | ')})`);
check("estimate revision links recorded evidence steps", sync.linked >= 1, `${sync.linked} linked steps`);
check("estimate revision shows the cited tool's ROI and crop", sync.roi >= 1 && sync.crop && sync.shown.includes("Shown for"), JSON.stringify(sync));
await evaluate(`document.querySelector('.workspace').scrollIntoView({block: 'start'}); window.scrollBy(0, -170); true`);
await shot("14-roi-synchronized-with-estimate-revision");

// ---- viewer-only access never receives the reference ----------------------------------
await open("fixture_w2_memon_peeron", {evaluator: false});
await waitFor(`document.querySelector('#gt-cell').dataset.state === 'ACCESS_DENIED'`);
s = await evaluate(strip);
check("viewer without evaluator scope sees 'Reference access not permitted'", s.gtState === "ACCESS_DENIED" && s.gt === "Withheld" && s.evalHidden, JSON.stringify(s));
const leaked = await evaluate(`JSON.stringify(state.reference).includes('"value"')`);
check("viewer-only reference payload carries no value", !leaked);

// ---- legacy run compatibility ----------------------------------------------------------
const legacy = await fetch(`${BASE}/api/runs`, {headers: {"X-Studio-Token": TOKEN}}).then((r) => r.json()).then((p) => p.runs.find((r) => r.run_id === "legacy_demo"));
if (legacy) {
  await open("legacy_demo");
  await frames();
  s = await evaluate(strip);
  const legacyMemory = await evaluate(`[...document.querySelectorAll('#team-view .badge.memory .badge-text')].map((n) => n.textContent)`);
  check("legacy run: estimate history reported as not recorded", s.estNote.includes("not recorded"), s.estNote);
  check("legacy run: final answer still shown", s.final !== "—", s.final);
  check("legacy run: worker memory shown as unknown, not invented", legacyMemory.slice(1).every((t) => t === "Memory unknown"), legacyMemory.join(","));
  check("legacy run: no reference label available", s.gtState === "NOT_AVAILABLE", s.gtState);
}

// ---- 5-6: sealed reference while a run is executing, released afterwards ---------------
const liveRun = `live_sealed_${Date.now()}`;
const producer = spawn("python", ["scripts/studio_config_matrix.py", "run", "--workers", "2", "--memory", "on", "--peer", "on", "--output-dir", RUNS, "--run-id", liveRun, "--step-delay", "0.9"], {stdio: "ignore"});
for (let i = 0; i < 100; i += 1) { const listed = await fetch(`${BASE}/api/runs`, {headers: {"X-Studio-Token": TOKEN}}).then((r) => r.json()); if (listed.runs.some((r) => r.run_id === liveRun)) break; await sleep(300); }
await open(liveRun, {waitEvents: 3});
await waitFor(`state.events.some((e) => e.event_type === 'WORKER_STARTED')`, 30000);
s = await evaluate(strip);
check("ground truth sealed during active inference", s.gtState === "SEALED" && s.gt === "Sealed", JSON.stringify(s));
check("coordinator shows no estimate before its first assessment", s.est === "No estimate yet", s.est);
check("answer strip is sticky", s.sticky === "sticky", s.sticky);
await shot("05-ground-truth-sealed-during-inference");
await waitFor(`state.events.some((e) => e.event_type === 'RUN_COMPLETED')`, 180000);
await waitFor(`document.querySelector('#gt-cell').dataset.state === 'AVAILABLE'`, 15000);
s = await evaluate(strip);
check("ground truth released after completion (evaluator)", s.gtState === "AVAILABLE" && s.gt === "5", JSON.stringify(s));
await evaluate(`document.querySelector('#gt-detail').open = true; true`);
const provenance = await evaluate(`document.querySelector('#gt-provenance').textContent`);
check("released reference shows provenance", provenance.includes("deterministic_fixture") && provenance.includes("normalization rule"), provenance.slice(0, 160));
await shot("06-ground-truth-released-after-completion");
producer.kill();

// ---- laptop viewport ------------------------------------------------------------------
await viewport(1280, 800);
await open("fixture_w4_memoff_peeron");
const laptop = await evaluate(layoutProbe);
check("laptop 1280×800: four workers in ≤ 2 rows, no overlap, no page scroll", laptop.rows <= 2 && !laptop.overlaps.length && laptop.pageOverflow <= 0, JSON.stringify({rows: laptop.rows, overflow: laptop.pageOverflow, minWidth: Math.round(laptop.minWorkerWidth)}));
check("laptop 1280×800: compact card height", laptop.maxWorkerHeight <= 320, `${Math.round(laptop.maxWorkerHeight)} px`);
await shot("15-laptop-w4");
await viewport(390, 844);
await open("fixture_w3_memon_peeroff");
const phone = await evaluate(layoutProbe);
check("phone 390 px: no horizontal page scroll", phone.pageOverflow <= 0, `overflow ${phone.pageOverflow}`);

const unexpected = problems.filter((item) => !/status of 40[13]/.test(item));
check("no console errors or exceptions", unexpected.length === 0, unexpected.slice(0, 5).join(" | "));
writeFileSync(join(OUT, "browser-matrix-report.json"), `${JSON.stringify({checks, problems}, null, 2)}\n`);
socket.close(); chrome.kill("SIGTERM"); await sleep(300); rmSync(profile, {recursive: true, force: true});
const failed = checks.filter((item) => !item.ok);
console.log(`${checks.length - failed.length}/${checks.length} browser checks passed`);
process.exit(failed.length ? 1 : 0);
