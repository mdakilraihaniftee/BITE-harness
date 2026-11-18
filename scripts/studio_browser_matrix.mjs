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
async function open(run, {theme = "light", view = "team", evaluator = true, waitEvents = 1, technical = true} = {}) {
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
  // Older blocks measure the architecture graph, which now lives in the collapsed "Technical details".
  if (technical) await evaluate(`document.querySelector('#technical-details').open = true; true`);
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

// ---- optional: Simple view (team picture, selected-step card, answers) -------------------
if (args.simple) {
  const runs = args.simple.split(",");
  const simpleProbe = `(() => {
    const cards = [...document.querySelectorAll('#simple-team .st-card')].map((c) => { const r = c.getBoundingClientRect(); return {agent: c.dataset.agent, x: r.x, y: r.y, w: r.width, h: r.height,
      tools: [...c.querySelectorAll('.st-tool')].map((t) => t.textContent), state: c.querySelector('.st-state').textContent, answer: c.querySelector('.st-answer').textContent}; });
    const overlaps = [];
    for (let i = 0; i < cards.length; i += 1) for (let j = i + 1; j < cards.length; j += 1) { const a = cards[i], b = cards[j];
      if (a.x < b.x + b.w - 1 && b.x < a.x + a.w - 1 && a.y < b.y + b.h - 1 && b.y < a.y + a.h - 1) overlaps.push(a.agent + '/' + b.agent); }
    const recordedTools = {}; for (const [id, a] of state.activityCache?.state?.agents || []) recordedTools[id] = [...(a.tools || new Map())].reduce((n, [, c]) => n + c, 0);
    return {cards, overlaps, recordedTools, routes: document.querySelectorAll('#simple-team .st-route.st-link').length,
      technicalOpen: document.querySelector('#technical-details').open, teamVisible: document.querySelector('#team-view').checkVisibility(),
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      focus: [...document.querySelectorAll('#focus-flow > li .fl-label')].map((n) => n.textContent), focusTitle: document.querySelector('#focus-title').textContent,
      focusMode: document.querySelector('#focus-mode').textContent,
      reports: document.querySelectorAll('#candidate-row .report-card').length,
      hiddenDetails: [...document.querySelectorAll('#story-list .story-step:not(.selected) .story-details')].every((d) => getComputedStyle(d).display === 'none')};
  })()`;
  for (const [index, run] of runs.entries()) {
    const tag = run.replace(/[^a-z0-9]+/gi, "-").slice(0, 40);
    await open(run, {theme: "light", technical: false});
    await waitFor(`document.querySelector('#simple-team .st-card') && document.querySelector('#story-list .story-step')`, 30000);
    await frames(); await sleep(300); await frames();
    const p = await evaluate(simpleProbe);
    const workers = p.cards.filter((c) => c.agent !== "coordinator");
    check(`${tag}: technical details collapsed by default`, !p.technicalOpen && !p.teamVisible);
    check(`${tag}: one card per agent, none overlapping`, p.cards.length === Object.keys(p.recordedTools).length || p.cards.length >= 2, `${p.cards.length} cards, overlaps ${p.overlaps.join(",") || "none"}`);
    check(`${tag}: no overlaps and no horizontal page scroll`, !p.overlaps.length && p.overflow <= 0, `overflow ${p.overflow}`);
    check(`${tag}: one coordinator→worker route per worker`, p.routes === workers.length, `${p.routes} routes, ${workers.length} workers`);
    const toolSums = Object.fromEntries(workers.map((w) => [w.agent, w.tools.reduce((n, t) => n + Number(/×(\d+)/.exec(t)?.[1] || 0), 0)]));
    check(`${tag}: tool chips match recorded tool calls`, workers.every((w) => toolSums[w.agent] === (p.recordedTools[w.agent] || 0)), JSON.stringify({chips: toolSums, recorded: p.recordedTools}));
    check(`${tag}: worker answer cards match workers that answered`, p.reports === workers.filter((w) => w.answer.startsWith("Answer:")).length, `${p.reports} cards`);
    check(`${tag}: selected-step card follows the latest step`, p.focus.length > 0 && /latest/i.test(p.focusMode), `${p.focusTitle} · ${p.focusMode}`);
    check(`${tag}: unselected story steps are compact`, p.hiddenDetails);
    await evaluate(`window.scrollTo(0, 0); true`);
    await shot(`simple-${index + 1}-${tag}-overview`);
    if (index === 0) await shot(`simple-${index + 1}-${tag}-answers`, ".results-panel");
    // Tool chip → that worker's latest step with that tool, explained in the focus card.
    const chip = await evaluate(`(() => { const c = document.querySelector('#simple-team .st-tool'); if (!c) return null; const agent = c.closest('.st-card').dataset.agent; c.click(); return {agent, tool: c.dataset.tool}; })()`);
    if (chip) {
      await frames(); await sleep(400); await frames();
      const f = await evaluate(`({labels: [...document.querySelectorAll('#focus-flow > li .fl-label')].map((n) => n.textContent), title: document.querySelector('#focus-title').textContent,
        request: document.querySelector('#focus-flow .fl-request p')?.textContent || '', selectedAgent: document.querySelector('.story-step.selected')?.dataset.agent,
        active: Boolean(document.querySelector('#simple-team .st-tool.active')), follow: !document.querySelector('#clear-event').hidden})`);
      check(`${tag}: tool chip opens that worker's tool step`, f.selectedAgent === chip.agent, `${chip.agent} ${chip.tool} → ${f.title}`);
      check(`${tag}: tool step reads Why → Request → Result → Interpretation → Next`, ["Why", "Request", "Result", "Interpretation", "Next"].every((k, i) => f.labels[i] === k), f.labels.join(","));
      check(`${tag}: request is described in plain words`, f.request.length > 0 && !/[{}]/.test(f.request), f.request);
      check(`${tag}: selected tool chip highlighted, "Follow latest" offered`, f.active && f.follow);
      await evaluate(`document.querySelector('.story-step.selected')?.scrollIntoView({block: 'center'}); document.querySelector('.workspace').scrollIntoView({block: 'start'}); window.scrollBy(0, -170); true`);
      await shot(`simple-${index + 1}-${tag}-tool-step`);
      await evaluate(`document.querySelector('#clear-event').click(); true`); await frames();
      check(`${tag}: "Follow latest" returns to the latest step`, await evaluate(`/latest/i.test(document.querySelector('#focus-mode').textContent) && document.querySelector('#clear-event').hidden`));
    }
    // Agent card → filter the story to that agent; click again to clear.
    const worker = workers[0]?.agent;
    if (worker) {
      await evaluate(`document.querySelector('#simple-team .st-card[data-agent="${worker}"]').click(); true`); await frames();
      const filt = await evaluate(`({value: document.querySelector('#story-agent').value, dimmed: document.querySelectorAll('#simple-team .st-card.dimmed').length,
        others: [...document.querySelectorAll('#story-list .story-step')].filter((n) => n.dataset.agent && n.dataset.agent !== ${JSON.stringify(worker)}).length})`);
      check(`${tag}: clicking an agent card shows only its steps`, filt.value === worker && filt.dimmed === p.cards.length - 1, JSON.stringify(filt));
      await evaluate(`document.querySelector('#simple-team .st-card[data-agent="${worker}"]').click(); true`); await frames();
      check(`${tag}: clicking it again clears the filter`, await evaluate(`document.querySelector('#story-agent').value === '' && !document.querySelector('#simple-team .st-card.dimmed')`));
    }
    // Technical details still hold the full architecture graph.
    await evaluate(`document.querySelector('#technical-details').open = true; true`); await frames(); await sleep(300);
    check(`${tag}: technical details expand to the full architecture`, await evaluate(`Boolean(document.querySelector('#team-view .harness')?.checkVisibility()) && document.querySelector('#team-view .harness').getBoundingClientRect().height > 0`));
    await evaluate(`document.querySelector('#technical-details').open = false; true`);
  }
  // Dark theme and phone width on the first run.
  await open(runs[0], {theme: "dark", technical: false});
  await waitFor(`document.querySelector('#simple-team .st-card') && document.querySelector('#story-list .story-step')`, 30000); await frames(); await sleep(300);
  await evaluate(`window.scrollTo(0, 0); true`); await shot("simple-dark");
  await viewport(390, 844);
  await open(runs[0], {theme: "light", technical: false});
  await waitFor(`document.querySelector('#simple-team .st-card')`, 30000); await frames(); await sleep(300);
  check("phone width: no horizontal page scroll", await evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth <= 0`));
  await evaluate(`document.querySelector('.simple-team-panel').scrollIntoView({block: 'start'}); true`); await shot("simple-phone");
  await viewport(1600, 1000);
  const unexpected = problems.filter((item) => !/status of 40[13]/.test(item));
  check("no console errors or exceptions", unexpected.length === 0, unexpected.slice(0, 5).join(" | "));
  writeFileSync(join(OUT, "browser-simple-report.json"), `${JSON.stringify({checks, problems}, null, 2)}\n`);
  socket.close(); chrome.kill("SIGTERM"); await sleep(300); rmSync(profile, {recursive: true, force: true});
  const failed = checks.filter((item) => !item.ok);
  console.log(`${checks.length - failed.length}/${checks.length} browser checks passed`);
  process.exit(failed.length ? 1 : 0);
}

// ---- optional: visual tool actions (original -> ROI -> zoom -> detection on crop) ---------
if (args.visual) {
  const [RUN, REAL] = args.visual.split(",");
  const near = (a, b, tol = 2) => a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) <= tol);
  const selectTool = async (agent, index) => {
    await evaluate(`(() => { const s = storySteps().filter((x) => x.kind === "tool" && x.agent === ${JSON.stringify(agent)})[${index}]; selectStep(s); return true; })()`);
    await waitFor(`(() => { const imgs = [...document.querySelectorAll('#tool-action img')]; return !document.querySelector('#tool-action').classList.contains('hidden') && imgs.every((i) => i.complete && i.naturalWidth > 0); })()`, 15000);
    await frames();
  };
  /** Overlay rectangles measured on screen and converted to the displayed image's natural pixels. */
  const measure = (title) => evaluate(`(() => {
    const panel = [...document.querySelectorAll('#tool-action .ta-panel')].find((p) => p.querySelector('figcaption strong').textContent.startsWith(${JSON.stringify(title)}));
    if (!panel) return null; const img = panel.querySelector('img'); if (!img) return {img: null, rects: []};
    const r = img.getBoundingClientRect(); const nw = img.naturalWidth, nh = img.naturalHeight; const k = Math.min(r.width / nw, r.height / nh);
    const ox = r.left + (r.width - nw * k) / 2, oy = r.top + (r.height - nh * k) / 2;
    return {img: [nw, nh], caption: panel.querySelector('figcaption').textContent, note: panel.querySelector('.ta-note')?.textContent || '',
      rects: [...panel.querySelectorAll('.ta-shape rect')].map((rect) => { const b = rect.getBoundingClientRect();
        return {cls: rect.parentNode.getAttribute('class').replace('ta-shape ', ''), box: [(b.left - ox) / k, (b.top - oy) / k, (b.right - ox) / k, (b.bottom - oy) / k]}; })};
  })()`);
  const workspace = async (name) => { await evaluate(`document.querySelector('.evidence-column').scrollIntoView({block: 'start'}); window.scrollBy(0, -170); true`); await shot(name); };

  await open(RUN, {theme: "light"});
  await waitFor(`storySteps().filter((s) => s.kind === "tool").length >= 7`, 30000);
  // 1-2: Zoom on the original: selected ROI + crop boundary on the input, actual crop as output.
  await selectTool("worker_01", 1);
  let input = await measure("Actual input"); let output = await measure("Actual zoomed image");
  const roi = input.rects.find((r) => r.cls === "roi"); const crop = input.rects.find((r) => r.cls === "crop");
  check("zoom input is the original 640×400 image", near(input.img, [640, 400], 0), JSON.stringify(input.img));
  check("selected ROI drawn at its recorded place on the original", roi && near(roi.box, [469.76, 250, 620.16, 380]), JSON.stringify(roi?.box?.map(Math.round)));
  check("crop boundary drawn at the executed crop [438,230,640,400]", crop && near(crop.box, [438, 230, 640, 400]), JSON.stringify(crop?.box?.map(Math.round)));
  check("zoom output is the actual 202×170 crop", output && near(output.img, [202, 170], 0) && /verified against the returned 202×170 crop/.test(output.note), output?.note);
  await workspace("visual-01-original-with-roi");
  await evaluate(`[...document.querySelectorAll('#tool-action .ta-panel')].find((p) => /zoomed image/i.test(p.textContent)).scrollIntoView({block: 'center'}); true`);
  await shot("visual-02-zoomed-result");
  // 3-4: Detection on the zoomed crop: boxes on the crop, mapped boxes on the original.
  await selectTool("worker_01", 2);
  output = await measure("Detections on the processed image"); const context = await measure("Original context");
  const dets = output.rects.filter((r) => r.cls.startsWith("det")).map((r) => r.box);
  check("detector input/output panel shows the crop (202×170), not the original", near(output.img, [202, 170], 0), JSON.stringify(output.img));
  check("crop-local boxes drawn on the crop at [67,55,96,84] and [114,92,141,119]", dets.length === 2 && near(dets[0], [67, 55, 96, 84]) && near(dets[1], [114, 92, 141, 119]), JSON.stringify(dets.map((b) => b.map(Math.round))));
  const mapped = context.rects.filter((r) => r.cls.startsWith("det")).map((r) => r.box); const foot = context.rects.find((r) => r.cls === "footprint");
  check("original context shows the crop footprint [438,230,640,400]", foot && near(foot.box, [438, 230, 640, 400]), JSON.stringify(foot?.box?.map(Math.round)));
  check("crop detections mapped to the original at [505,285,534,314] and [552,322,579,349]", mapped.length === 2 && near(mapped[0], [505, 285, 534, 314]) && near(mapped[1], [552, 322, 579, 349]), JSON.stringify(mapped.map((b) => b.map(Math.round))));
  await workspace("visual-03-detections-on-zoomed-crop");
  await evaluate(`[...document.querySelectorAll('#tool-action .ta-panel')].find((p) => /Original context/.test(p.textContent)).scrollIntoView({block: 'center'}); true`);
  await shot("visual-04-crop-detections-mapped-to-original");
  // selecting a box highlights it in both views
  await evaluate(`document.querySelector('#tool-action .ta-panel .ta-shape.det').dispatchEvent(new MouseEvent('click', {bubbles: true})); true`); await frames(); await sleep(300); await frames();
  const selected = await evaluate(`[...document.querySelectorAll('#tool-action .ta-shape.det.selected')].length`);
  check("selecting a box highlights it on the crop and on the original", selected === 2, `${selected} highlighted`);
  // 5: expanded story step with lineage
  await evaluate(`(() => { const n = document.querySelector('.story-step.selected'); n.querySelector('details').open = true; n.scrollIntoView({block: 'center'}); return true; })()`); await frames();
  const details = await evaluate(`document.querySelector('.story-step.selected details').textContent`);
  check("expanded step states the input is the crop produced by the earlier Zoom step", /Input image.*Zoom crop · tool_generated_image_2 · 202×170 — output of step \d+ \(Zoom In\)/.test(details), details.slice(0, 220));
  const thumbs = await evaluate(`document.querySelectorAll('.story-step.selected .ta-thumb img').length`);
  check("story card carries input → output thumbnails", thumbs === 2, `${thumbs} thumbnails`);
  await evaluate(`document.querySelector('.workspace').scrollIntoView({block: 'start'}); window.scrollBy(0, -170); true`);
  await shot("visual-05-expanded-tool-step");
  // 8: nested chain: original -> crop A -> crop B -> detection
  await selectTool("worker_01", 4);
  output = await measure("Detections on the processed image"); const nested = await measure("Original context");
  const nav = await evaluate(`[...document.querySelectorAll('#tool-action .ta-nav button')].map((b) => b.textContent)`);
  check("nested detection runs on crop B (47×45)", near(output.img, [47, 45], 0), JSON.stringify(output.img));
  check("nested crop-B box maps through two crops to [552,322,579,349]", nested.rects.filter((r) => r.cls.startsWith("det")).some((r) => near(r.box, [552, 322, 579, 349])), JSON.stringify(nested.rects.map((r) => r.box.map(Math.round))));
  check("producing step is navigable", nav.some((t) => /Producing step/.test(t)), nav.join(" | "));
  await workspace("visual-08-sequential-evidence-chain");
  // concurrency: worker 2's own crop and boxes
  await selectTool("worker_02", 0);
  input = await measure("Actual input"); output = await measure("Actual zoomed image");
  check("concurrent worker 2 zoom keeps its own crop [158,20,332,170] → 174×150", input.rects.some((r) => r.cls === "crop" && near(r.box, [158, 20, 332, 170])) && near(output.img, [174, 150], 0));
  // 6-7 + replay: running state before the result, completed after, no future leakage
  const pos = await evaluate(`(() => { const s = storySteps().filter((x) => x.kind === "tool" && x.agent === "worker_01")[2]; const ids = s.source_event_ids;
    const req = state.events.findIndex((e) => ids.includes(e.event_id) && e.event_type === "TOOL_CALL_REQUESTED"); const done = state.events.findIndex((e) => ids.includes(e.event_id) && e.event_type === "TOOL_CALL_COMPLETED"); return {req, done}; })()`);
  await evaluate(`setReplayIndex(${pos.req + 1}); true`); await frames();
  await evaluate(`state.selectedEventId = state.events[${pos.req}].event_id; renderAll(); true`); await frames(); await sleep(400); await frames();
  const running = await evaluate(`({output: [...document.querySelectorAll('#tool-action .ta-panel')].map((p) => p.textContent).join(' | '), boxes: document.querySelectorAll('#tool-action .ta-shape.det').length})`);
  check("replay at the request: crop shown as input, no boxes yet", /Running — the tool has not returned yet/.test(running.output) && running.boxes === 0 && /tool_generated_image_2/.test(running.output), running.output.slice(0, 160));
  await workspace("visual-06b-replay-at-request");
  await evaluate(`setReplayIndex(${pos.done + 1}); true`); await frames(); await sleep(400); await frames();
  const done = await evaluate(`document.querySelectorAll('#tool-action .ta-shape.det').length`);
  check("after the result the same step shows the boxes", done >= 2, `${done} boxes`);
  await workspace("visual-07b-replay-after-result");
  await evaluate(`goLive(); true`);
  // live: a run being written now, observed while a Zoom executes
  const liveRun = `visual_live_${Date.now()}`;
  const producer = spawn("python", ["scripts/studio_config_matrix.py", "run", "--scenario", "visual", "--workers", "1", "--mode", "cooperative",
    "--output-dir", RUNS, "--run-id", liveRun, "--step-delay", "0.3", "--tool-delay", "3"], {stdio: "ignore"});
  for (let i = 0; i < 100; i += 1) { const listed = await fetch(`${BASE}/api/runs`, {headers: {"X-Studio-Token": TOKEN}}).then((r) => r.json()); if (listed.runs.some((r) => r.run_id === liveRun)) break; await sleep(300); }
  await open(liveRun, {waitEvents: 2});
  const zoomRunning = `state.live && (() => { const ev = state.events; const req = ev.filter((e) => e.event_type === "TOOL_CALL_REQUESTED" && e.tool_name === "Zoom_In_Tool");
    return req.length >= 1 && !ev.some((e) => e.event_type === "TOOL_CALL_COMPLETED" && e.payload.invocation_id === req[0].payload.invocation_id); })()`;
  check("live: Zoom request observed before its result", await waitFor(zoomRunning, 60000));
  await waitFor(`/Running — the tool has not returned yet/.test(document.querySelector('#tool-action')?.textContent || '') && [...document.querySelectorAll('#tool-action img')].every((i) => i.complete && i.naturalWidth > 0)`, 8000);
  await frames();
  const live = await measure("Actual input");
  check("live running step shows the input image and the requested ROI", live && near(live.img, [640, 400], 0) && live.rects.some((r) => r.cls === "roi" && near(r.box, [469.76, 250, 620.16, 380])) && /Running/.test(await evaluate(`document.querySelector('#tool-action').textContent`)), JSON.stringify(live?.rects?.map((r) => r.cls)));
  await workspace("visual-06-live-running-action");
  check("live: the same step updates when the crop returns", await waitFor(`/Actual zoomed image/.test(document.querySelector('#tool-action')?.textContent || '')`, 20000));
  await waitFor(`[...document.querySelectorAll('#tool-action img')].every((i) => i.complete && i.naturalWidth > 0)`, 8000); await frames();
  await workspace("visual-07-completed-tool-result");
  producer.kill();
  // 10: dark theme
  await open(RUN, {theme: "dark"});
  await waitFor(`storySteps().filter((s) => s.kind === "tool").length >= 7`, 30000);
  await selectTool("worker_01", 2);
  check("dark theme applied", (await evaluate(`getComputedStyle(document.body).backgroundColor`)) === "rgb(14, 19, 26)");
  await workspace("visual-10-dark");
  await open(RUN, {theme: "light"});
  await waitFor(`storySteps().filter((s) => s.kind === "tool").length >= 7`, 30000);
  await selectTool("worker_01", 2);
  await workspace("visual-09-light");
  // real persisted run: grounding on a derived image
  if (REAL) {
    await open(REAL, {theme: "light"});
    await waitFor(`storySteps().filter((s) => s.kind === "tool").length >= 1`, 30000);
    const derived = await evaluate(`(() => { const lin = lineage(); const inv = [...lin.invocations.values()].find((i) => i.detections && lin.images.get(i.inputKeys[0])?.kind !== "input");
      if (!inv) return null; const s = stepForInvocation(inv); selectStep(s); return {tool: inv.tool, input: lin.images.get(inv.inputKeys[0]).registryId}; })()`);
    await waitFor(`(() => { const imgs = [...document.querySelectorAll('#tool-action img')]; return imgs.length && imgs.every((i) => i.complete && i.naturalWidth > 0); })()`, 15000); await frames();
    const real = await measure("Detections on the processed image");
    check("real run: detection on a derived image is drawn on that image", derived && real && real.img && real.rects.length > 0, JSON.stringify({derived, img: real?.img, boxes: real?.rects.length}));
    await workspace("visual-real-run-derived-detection");
  }
  const unexpected = problems.filter((item) => !/status of 40[13]/.test(item));
  check("no console errors or exceptions", unexpected.length === 0, unexpected.slice(0, 5).join(" | "));
  writeFileSync(join(OUT, "browser-visual-report.json"), `${JSON.stringify({checks, problems}, null, 2)}\n`);
  socket.close(); chrome.kill("SIGTERM"); await sleep(300); rmSync(profile, {recursive: true, force: true});
  const failed = checks.filter((item) => !item.ok);
  console.log(`${checks.length - failed.length}/${checks.length} browser checks passed`);
  process.exit(failed.length ? 1 : 0);
}

// ---- optional: semantic investigation story (default view, grouping, trace) -------------
if (args.story) {
  const [REAL, REV, FAIL, PEER] = args.story.split(",");
  const stepByTitle = (pattern) => `[...document.querySelectorAll('#story-list .story-step')].find((n) => ${pattern}.test(n.querySelector('.story-title').textContent))`;
  const workspace = async (name) => {
    await evaluate(`document.querySelector('.story-step.selected')?.scrollIntoView({block: 'center'}); document.querySelector('.workspace').scrollIntoView({block: 'start'}); window.scrollBy(0, -170); true`);
    await shot(name);
  };
  // 1 + 7: main story on a real run (light)
  await open(REAL, {theme: "light"});
  await waitFor(`Boolean(state.reference) && document.querySelector('#story-list .story-step')`, 30000);
  const story = await evaluate(`({tab: state.tab, traceHidden: document.querySelector('#log-view').classList.contains('hidden'),
    steps: document.querySelectorAll('#story-list .story-step:not(.minor)').length, raw: state.events.length,
    titles: [...document.querySelectorAll('#story-list .story-title')].map((n) => n.textContent),
    numbered: [...document.querySelectorAll('#story-list .story-step:not(.minor) .story-number')].map((n) => n.textContent)})`);
  check("Investigation Story is the default view", story.tab === "story" && story.traceHidden);
  check("story is much shorter than the raw event log", story.steps > 0 && story.steps * 4 < story.raw, `${story.steps} steps for ${story.raw} raw events`);
  check("story titles are sentences, never raw event-type names", story.titles.every((t) => !/^[A-Z_]{6,}$/.test(t) && !/TOOL_CALL|MODEL_REQUEST|BUDGET_UPDATED/.test(t)), story.titles.slice(0, 4).join(" | "));
  check("main steps are numbered sequentially", story.numbered.every((n, i) => Number(n) === i + 1), story.numbered.join(","));
  check("worker answer revision preserved", story.titles.some((t) => /revised its answer from 50 to 46/.test(t)));
  await workspace("story-01-main-story");
  await evaluate(`window.scrollTo(0, 0); true`);
  await shot("story-07-light");
  // 2: expanded tool investigation, synchronized with graph and ROI
  await evaluate(`(() => { const n = ${stepByTitle("/used Visual Grounding/")}; n.querySelector('.story-title').click(); return true; })()`);
  await frames(); await sleep(500); await frames();
  await evaluate(`document.querySelector('.story-step.selected details').open = true; true`); await frames();
  const tool = await evaluate(`(() => { const sel = document.querySelector('.story-step.selected'); const agent = sel.dataset.agent;
    return {details: [...sel.querySelectorAll('dt')].map((n) => n.textContent), rois: document.querySelectorAll('#image-stage .overlay rect').length + document.querySelectorAll('#tool-action .ta-shape.det rect').length,
      chip: Boolean(document.querySelector('#team-view .harness[data-agent="' + agent + '"] .chip.active[data-tool="tool:Visual_Grounding_Tool"]')), agent}; })()`);
  check("expanded tool step shows why, tool, input, result, and assessment", ["Why", "Tool", "Input", "Result", "Agent's assessment"].every((k) => tool.details.includes(k)), tool.details.join(","));
  check("selected tool step shows its ROI on the original image", tool.rois >= 1, `${tool.rois} regions`);
  check("selected tool step highlights that worker's tool chip", tool.chip, tool.agent);
  await workspace("story-02-expanded-tool-investigation");
  await evaluate(`document.querySelectorAll('[data-graph-mode]')[1].click(); true`); await frames();
  const path = await evaluate(`[...state.graph.elements.overlays].filter(([, v]) => (v.path.getAttribute('class') || '').includes('level-selected')).map(([k]) => k)`);
  check("selected step highlights its exact graph path (tool → worker)", path.some((k) => k.includes("tool:Visual_Grounding_Tool")) && path.every((k) => !k.includes("model_service")), path.join(" | "));
  await evaluate(`document.querySelectorAll('[data-graph-mode]')[0].click(); true`); await frames();
  // graph -> story: clicking a tool chip opens that worker's latest step for the tool
  const reverse = await evaluate(`(() => { const chip = document.querySelector('#team-view .harness[data-agent="worker_02"] .chip[data-tool="tool:Visual_Grounding_Tool"]'); chip.click(); return true; })()`);
  await frames();
  const opened = await evaluate(`(() => { const sel = document.querySelector('.story-step.selected'); return sel ? sel.dataset.agent + ' | ' + sel.querySelector('.story-title').textContent : null; })()`);
  check("clicking a worker's tool chip opens its story step", reverse && /^worker_02 \| Worker 2 used Visual Grounding/.test(opened || ""), opened);
  // A requested tool is one running card, updated with its result at that prefix.
  const replayTool = await evaluate(`(() => {
    const step = storySteps().find((s) => s.id === state.selectedStepId);
    const resultAt = state.events.findIndex((e) => e.event_id === step.resultEventId);
    const requestAt = state.events.findIndex((e) => step.source_event_ids.includes(e.event_id) && e.event_type === 'TOOL_CALL_REQUESTED');
    setReplayIndex(requestAt + 1);
    const running = storySteps().find((s) => s.id === step.id);
    const before = {id: running?.id, status: running?.status, result: running?.observation};
    setReplayIndex(resultAt + 1);
    const done = storySteps().find((s) => s.id === step.id);
    const after = {id: done?.id, status: done?.status, result: done?.observation};
    goLive(); return {before, after};
  })()`);
  check("replay updates the same tool card without revealing a future result", replayTool.before.id === replayTool.after.id
    && replayTool.before.status === "running" && replayTool.before.result === null && replayTool.after.status === "completed" && replayTool.after.result,
  JSON.stringify(replayTool));
  await frames();
  // 6: technical trace for one step
  const selectedSources = await evaluate(`storySteps().find((s) => s.id === state.selectedStepId).source_event_ids.length`);
  await evaluate(`document.querySelector('.story-step.selected details').open = true; document.querySelector('.story-step.selected .trace-link').click(); true`); await frames();
  const trace = await evaluate(`({tab: state.tab, cards: document.querySelectorAll('#timeline .event-card').length, banner: !document.querySelector('#trace-filter').classList.contains('hidden'),
    meta: document.querySelector('#timeline .event-card .trace-meta')?.textContent || ''})`);
  check("“View underlying events” opens exactly that step's raw events", trace.tab === "log" && trace.banner && trace.cards === selectedSources, `${trace.cards} of ${selectedSources}`);
  check("technical trace exposes event IDs, tool-call IDs, and status", /id evt_/.test(trace.meta) && /status /.test(trace.meta), trace.meta.slice(0, 120));
  await evaluate(`(() => { const card = [...document.querySelectorAll('#timeline .event-card')].find((n) => state.eventIndex.get(n.dataset.eventId)?.event_type === 'TOOL_CALL_COMPLETED'); card.querySelector('details').open = true; return true; })()`); await frames();
  const completePayload = await evaluate(`(() => {
    const card = [...document.querySelectorAll('#timeline .event-card')].find((n) => state.eventIndex.get(n.dataset.eventId)?.event_type === 'TOOL_CALL_COMPLETED');
    const shown = JSON.parse(card.querySelector('pre').textContent);
    const actual = state.eventIndex.get(card.dataset.eventId);
    const count = (value) => {
      if (!value || typeof value !== 'object') return 0;
      const own = Math.max(0, ...['boxes', 'pred_boxes', 'bounding_boxes', 'bboxes'].map((key) => Array.isArray(value[key]) ? value[key].length : 0));
      return Math.max(own, ...Object.values(value).map(count));
    };
    return {shown: count(shown.payload), actual: count(actual.payload), exact: JSON.stringify(shown) === JSON.stringify(safeValue(actual, 0, true)), timestamp: shown.timestamp};
  })()`);
  check("expanded trace keeps the full result and timestamp beyond the 30-region preview limit", completePayload.exact
    && completePayload.shown === completePayload.actual && completePayload.actual > 30 && completePayload.timestamp,
  JSON.stringify(completePayload));
  await evaluate(`document.querySelector('#timeline .event-card details').open = true; true`); await frames();
  await workspace("story-06-technical-trace");
  await evaluate(`document.querySelector('#trace-filter-clear').click(); true`); await frames();
  const all = await evaluate(`document.querySelectorAll('#timeline .event-card').length`);
  check("full technical trace keeps every raw event", all === story.raw, `${all}/${story.raw}`);
  const graphNoise = await evaluate(`(() => {
    const saved = state.technical;
    const routine = state.events.filter((e) => ['MEMORY_WRITTEN', 'OPTIONAL_MEMORY_WRITTEN', 'MESSAGE_DELIVERED'].includes(e.event_type));
    state.technical = false; const silent = routine.every((e) => !isMeaningful(e));
    state.technical = true; const inspectable = routine.every((e) => isMeaningful(e));
    state.technical = saved;
    return {count: routine.length, silent, inspectable};
  })()`);
  check("folded bookkeeping stays silent on the story graph and available in technical mode", graphNoise.count > 0 && graphNoise.silent && graphNoise.inspectable,
  `${graphNoise.count} bookkeeping events`);
  // 8: dark mode, same run
  await open(REAL, {theme: "dark"});
  await waitFor(`document.querySelector('#story-list .story-step')`, 30000);
  const dark = await evaluate(`({bg: getComputedStyle(document.body).backgroundColor, text: getComputedStyle(document.querySelector('.story-title')).color})`);
  check("dark theme story is readable", dark.bg === "rgb(14, 19, 26)" && dark.text !== "rgb(23, 33, 44)", JSON.stringify(dark));
  await evaluate(`window.scrollTo(0, 0); true`);
  await shot("story-08-dark");
  // 3: worker-to-worker communication
  await open(PEER, {theme: "light"});
  await waitFor(`document.querySelector('#story-list .story-step')`, 30000);
  const comm = await evaluate(`(() => { const review = ${stepByTitle("/reviewed \\d+ peer claim/")}; const shared = [...document.querySelectorAll('#story-list .story-meta')].find((n) => /shared with Worker/.test(n.textContent));
    if (review) { review.querySelector('details').open = true; review.querySelector('.story-title').click(); } return {review: review?.querySelector('.story-title').textContent, shared: shared?.textContent}; })()`);
  await frames(); await sleep(300); await frames();
  check("peer communication is one human-readable step per act", Boolean(comm.review && comm.shared), JSON.stringify(comm));
  await workspace("story-03-worker-communication");
  // 4: coordinator estimate revision
  await open(REV, {theme: "light"});
  await waitFor(`document.querySelector('#story-list .story-step')`, 30000);
  await evaluate(`(() => { const n = ${stepByTitle("/revised its estimate: 4 → 5/")}; n.querySelector('details').open = true; n.querySelector('.story-title').click(); return true; })()`);
  await frames(); await sleep(500); await frames();
  const revision = await evaluate(`({linked: document.querySelectorAll('.story-step.linked').length, est: document.querySelector('#est-value').textContent})`);
  check("coordinator estimate revision is visible and linked to its evidence", revision.linked >= 1, JSON.stringify(revision));
  await workspace("story-04-coordinator-estimate-revision");
  // 5: important failures (tool failure and budget stop)
  await open(FAIL, {theme: "light"});
  await waitFor(`document.querySelector('#story-list .story-step')`, 30000);
  const failures = await evaluate(`(() => { const nodes = [...document.querySelectorAll('#story-list .story-step.outcome-execution_failure, #story-list .story-step.outcome-budget')];
    for (const n of nodes.slice(0, 2)) n.querySelector('details').open = true; nodes[0]?.querySelector('.story-title').click();
    return nodes.map((n) => n.querySelector('.story-title').textContent); })()`);
  await frames(); await sleep(300); await frames();
  check("tool failures and budget stops remain visible", failures.some((t) => /call failed/.test(t)) && failures.some((t) => /budget exhausted/.test(t)), failures.join(" | "));
  await workspace("story-05-failure-and-budget-stop");
  const unexpected = problems.filter((item) => !/status of 40[13]/.test(item));
  check("no console errors or exceptions", unexpected.length === 0, unexpected.slice(0, 5).join(" | "));
  writeFileSync(join(OUT, "browser-story-report.json"), `${JSON.stringify({checks, problems}, null, 2)}\n`);
  socket.close(); chrome.kill("SIGTERM"); await sleep(300); rmSync(profile, {recursive: true, force: true});
  const failed = checks.filter((item) => !item.ok);
  console.log(`${checks.length - failed.length}/${checks.length} browser checks passed`);
  process.exit(failed.length ? 1 : 0);
}

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
    // Story + evidence with the coordinator's first estimate selected (linked evidence highlighted).
    const picked = await evaluate(`(() => { const step = [...document.querySelectorAll('.story-step')].find((n) => /formed a provisional estimate|revised its estimate/.test(n.textContent)); if (step) step.querySelector('.story-title').click(); return Boolean(step); })()`);
    if (picked) {
      await frames(); await sleep(500); await frames();
      await evaluate(`document.querySelector('.story-step.selected')?.scrollIntoView({block: 'center'}); document.querySelector('.workspace').scrollIntoView({block: 'start'}); window.scrollBy(0, -170); true`);
      await shot(`${run}-story`);
    }
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
await evaluate(`window.scrollTo(0, 0); [...document.querySelectorAll('.story-step')].find((n) => n.textContent.includes('revised its estimate')).querySelector('.story-title').click(); true`);
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
const liveProgress = await waitFor(`state.events.some((e) => e.event_type === 'TOOL_CALL_COMPLETED')
  && !state.events.some((e) => e.event_type === 'RUN_COMPLETED')`, 30000);
const liveStory = await evaluate(`({ids: storySteps().map((s) => s.id), count: state.events.length,
  completedTools: storySteps().filter((s) => s.kind === 'tool' && s.status === 'completed').length,
  visibleCards: document.querySelectorAll('#story-list .story-step').length})`);
check("live SSE shows completed investigation steps before the run finishes", liveProgress && liveStory.completedTools > 0 && liveStory.visibleCards > 0,
`${liveStory.completedTools} completed tool steps at ${liveStory.count} raw events`);
await waitFor(`state.events.some((e) => e.event_type === 'RUN_COMPLETED')`, 180000);
const liveStable = await evaluate(`storySteps().map((s) => s.id).slice(0, ${liveStory.ids.length})`);
check("live story step identities remain stable as SSE appends results", JSON.stringify(liveStable) === JSON.stringify(liveStory.ids));
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
