"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const Activity = window.StudioActivity;
const Theme = window.StudioTheme;
const Answer = window.StudioAnswer;
const Lineage = window.StudioLineage;
const SimpleTeamApi = window.StudioSimpleTeam;
const Geo = window.StudioGeometry;
const Story = window.StudioStory;

const state = {
  token: "", connected: false, runs: [], runId: null, snapshot: null, events: [], eventIndex: new Map(), selectedEventId: null,
  selectedAgent: "", replayIndex: 0, live: true, playing: false, timer: null,
  streamController: null, artifactUrls: new Map(), startedAt: null,
  pendingEvent: null,
  pendingRun: null,
  topology: null, graph: null, activityCache: null, selectedNode: null, selectedEdge: null,
  renderScheduled: false, pulseQueue: [], evidenceToken: 0, evidenceKey: null, topologyRefresh: null,
  backend: null, scope: "preview", displayTopology: null, configured: null, waitTimer: null, connectGeneration: 0,
  // Legacy header credential; new launch links use HttpOnly browser cookies.
  evaluatorToken: "", evaluatorAccess: false, reference: null, referenceKey: null, referenceLoading: false,
  team: null, tab: "story", answerCache: null, storyCache: null, selectedStepId: null, linkedSteps: new Set(),
  expandedSteps: new Set(), traceFilter: null, technical: false,
  lineageCache: null, ta: {boxes: true, labels: "auto", scores: false, view: "boxes", selectedBox: null, invocation: null},
  plan: {workers: "2", memory: "on", peer: "on", mode: "concurrent", estimates: "on"},
};

// The UI contract this frontend implements; the backend must advertise it in /api/info.
const UI_COMPATIBILITY = "studio.ui.v3";
const SCOPE_TEXT = {
  preview: ["Architecture preview — not live execution", "Generic framework components. Connect and select a run to watch actual tool calls, model responses, memory access, and agent communication."],
  configured: ["Configured architecture — no task running", "What this Studio's configuration can run. Worker slots are a template until a run instantiates them; nothing here is observed activity."],
  run: ["Run topology", ""],
};

const terminalStates = new Set(["COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"]);
const hiddenKeys = new Set(["thinking", "chain_of_thought", "internal_reasoning", "hidden_reasoning"]);
const PREFS_KEY = "studio.graph";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function safeValue(value, depth = 0, full = false) {
  if (!full && depth > 5) return "[nested value omitted]";
  if (Array.isArray(value)) return (full ? value : value.slice(0, 30)).map((item) => safeValue(item, depth + 1, full));
  if (value && typeof value === "object") {
    const result = {};
    for (const [key, item] of Object.entries(value)) {
      if (!hiddenKeys.has(key.toLowerCase())) result[key] = safeValue(item, depth + 1, full);
    }
    return result;
  }
  if (!full && typeof value === "string" && value.length > 5000) return `${value.slice(0, 5000)}…`;
  return value;
}

function pretty(value, limit = 1600) {
  let output;
  try { output = typeof value === "string" ? value : JSON.stringify(safeValue(value, 0, limit === Infinity), null, 2); }
  catch { output = String(value); }
  return output.length > limit ? `${output.slice(0, limit)}…` : output;
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  window.setTimeout(() => node.classList.remove("show"), 3000);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-Studio-Token", state.token);
  if (options.evaluator && state.evaluatorToken) headers.set("X-Studio-Evaluator-Token", state.evaluatorToken);
  delete options.evaluator;
  const response = await fetch(path, {...options, headers, cache: "no-store"});
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try { detail = (await response.json()).detail || detail; } catch { /* response was not JSON */ }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response;
}

function setConnection(label, kind = "idle") {
  const chip = $("#connection-state");
  chip.textContent = label;
  chip.className = `status-chip ${kind}`;
}

// ---- Legacy remembered sign-in -------------------------------------------------
// Keep older browser credentials compatible. New script links sign in with cookies,
// so reloads and new tabs do not need credentials in JavaScript or browser storage.
const SESSION_PREFIX = "studio.session.";
function sessionKey() { return state.backend?.instance_id ? `${SESSION_PREFIX}${state.backend.instance_id}` : null; }
function rememberedSession() {
  const key = sessionKey(); if (!key) return {};
  let viewer = null; let evaluator = null;
  try { viewer = window.localStorage.getItem(key); } catch { /* storage unavailable */ }
  try { evaluator = window.sessionStorage.getItem(`${key}.evaluator`); } catch { /* storage unavailable */ }
  return {viewer, evaluator};
}
function rememberSession() {
  const key = sessionKey(); if (!key) return;
  try {
    for (const name of Object.keys(window.localStorage)) if (name.startsWith(SESSION_PREFIX) && name !== key) window.localStorage.removeItem(name);
    if (state.token) window.localStorage.setItem(key, state.token);
  } catch { /* storage unavailable: sign-in still works for this page */ }
  try {
    if (state.evaluatorToken) window.sessionStorage.setItem(`${key}.evaluator`, state.evaluatorToken);
    else window.sessionStorage.removeItem(`${key}.evaluator`);
  } catch { /* storage unavailable */ }
}
function forgetSession() {
  const key = sessionKey(); if (!key) return;
  try { window.localStorage.removeItem(key); } catch { /* storage unavailable */ }
  try { window.sessionStorage.removeItem(`${key}.evaluator`); } catch { /* storage unavailable */ }
}

// ---- Display preferences (never credentials) -------------------------------
function loadPrefs() {
  try { return JSON.parse(window.localStorage.getItem(PREFS_KEY) || "{}") || {}; } catch { return {}; }
}
function savePrefs() {
  const o = state.graph?.options || {};
  const value = {mode: o.mode, viewMode: state.viewMode, showMemory: o.showMemory, showMemoryFlows: o.showMemoryFlows, showInfra: o.showInfra, technical: state.technical};
  try { window.localStorage.setItem(PREFS_KEY, JSON.stringify(value)); } catch { /* storage unavailable */ }
}

/** Show a persistent, specific notice for the current connection state. */
function setNotice(text, kind = "info") {
  const node = $("#graph-notice");
  node.textContent = text || "";
  node.className = `graph-notice ${kind}${text ? "" : " hidden"}`;
  // The same message in a banner under the top bar, so connection and link problems are
  // visible even while "Technical details" is collapsed. `code` spans become selectable.
  const banner = $("#app-notice");
  if (!banner) return;
  banner.replaceChildren(...String(text || "").split("`").map((part, index) => (index % 2 ? el("code", "", part) : document.createTextNode(part))));
  banner.className = `graph-notice app-notice ${kind}${text ? "" : " hidden"}`;
}

/** Compatibility handshake. Old backends lack /api/info and are never treated as connected. */
async function checkBackend() {
  try {
    const response = await fetch("/api/info", {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const info = await response.json();
    if (info.ui_compatibility !== UI_COMPATIBILITY) throw new Error(`backend UI contract ${info.ui_compatibility || "missing"}`);
    state.backend = info;
    return true;
  } catch (error) {
    state.backend = null;
    setConnection("Backend incompatible", "failed");
    setNotice(`Studio backend at ${location.host} is outdated or not an Investigation Studio (${error.message}). `
      + "It cannot provide the architecture data this page needs. Run `python scripts/studio_ctl.py status` to see instances, "
      + "stop the old one with `python scripts/studio_ctl.py stop --port " + (location.port || "80") + "`, or open the link printed by the newly launched Studio.", "error");
    return false;
  }
}

async function redeemTicket(ticket) {
  try {
    const response = await fetch("/api/launch-tickets/redeem", {
      method: "POST", cache: "no-store", headers: {"Content-Type": "application/json"}, body: JSON.stringify({ticket}),
    });
    if (!response.ok) throw new Error("expired");
    // The server sets HttpOnly session cookies; credentials never need a paste field.
    return true;
  } catch {
    // An existing browser session can still open an already-used launch link.
    return false;
  }
}

async function connect(credential = "") {
  if (!state.backend && !(await checkBackend())) return;
  state.token = credential;
  const generation = ++state.connectGeneration;
  state.connected = false;
  setConnection("Connecting", "idle");
  try {
    await refreshRunList();
  } catch (error) {
    if (generation !== state.connectGeneration) return;
    state.token = "";
    if (error.status === 401) {
      forgetSession();
      setConnection("Open run link", "idle");
      setNotice("Open the visualization link printed by your run script to connect automatically. "
        + `To reopen this Studio, run \`python scripts/studio_ctl.py --runs-dir <runs dir> url --port ${location.port || "80"} --open\`.`, "info");
    } else {
      setConnection("Connection failed", "failed");
      setNotice(`Could not reach the Studio API: ${error.message}`, "error");
    }
    showScope("preview");
    return;
  }
  setConnection("Connected", "live");
  state.connected = true;
  try { state.evaluatorAccess = (await (await api("/api/session", {evaluator: true})).json()).evaluator; } catch { state.evaluatorAccess = false; }
  rememberSession();
  await loadConfiguredArchitecture();
  if (state.pendingRun) return selectPendingRun(generation);
  if (state.runs.length) return loadRun(state.runs[0].run_id);
  showScope("configured");
  if (!state.configured) setNotice("Connected. This Studio has no readable multi-agent configuration, so a generic preview is shown.", "warning");
  else if (state.runs.length) setNotice(`Connected. Select one of ${state.runs.length} run(s) from the menu to load its recorded topology, events, and evidence.`, "info");
  else setNotice("Connected. No runs exist yet in this runs directory. Start one with `./scripts/run_studio_demo.sh` (no model servers needed).", "info");
}

async function refreshRunList() {
  const payload = await (await api("/api/runs")).json();
  state.runs = payload.runs || [];
  const select = $("#run-select");
  const current = state.runId || state.pendingRun;
  const signature = JSON.stringify(state.runs.map((run) => [run.run_id, run.status, run.event_count]));
  if (signature === state.runListSignature && select.options.length > 1) {
    if (current && state.runs.some((run) => run.run_id === current)) select.value = current;
    return;
  }
  state.runListSignature = signature;
  select.replaceChildren(new Option(state.runs.length ? "Select a run" : "No runs yet", ""));
  for (const run of state.runs) {
    const option = el("option", "", `${run.run_id} · ${run.status || "RUNNING"} · ${run.event_count || 0} events`);
    option.value = run.run_id;
    select.append(option);
  }
  select.disabled = !state.runs.length;
  if (current && state.runs.some((run) => run.run_id === current)) select.value = current;
}

async function loadConfiguredArchitecture() {
  try {
    const payload = await (await api("/api/architecture")).json();
    state.configured = payload.available ? payload.topology : null;
  } catch { state.configured = null; }
}

/** Wait (bounded) for a requested run that may not exist yet, e.g. a just-launched task. */
async function selectPendingRun(generation) {
  const runId = state.pendingRun;
  const deadline = Date.now() + 5 * 60 * 1000;
  showScope(state.configured ? "configured" : "preview");
  while (generation === state.connectGeneration && state.pendingRun === runId) {
    if (state.runs.some((run) => run.run_id === runId)) {
      state.pendingRun = null;
      $("#run-select").value = runId;
      return loadRun(runId);
    }
    if (Date.now() > deadline) {
      setConnection("Run unavailable", "failed");
      setNotice(`Run “${runId}” did not appear in this Studio's runs directory within 5 minutes. Check that the task and the Studio use the same runs directory, or select another run.`, "error");
      state.pendingRun = null;
      return;
    }
    setConnection("Waiting for run", "idle");
    setNotice(`Waiting for run “${runId}” to start… The graph switches to its live topology as soon as the run directory appears.`, "info");
    await new Promise((resolve) => { state.waitTimer = window.setTimeout(resolve, 1000); });
    try { await refreshRunList(); } catch { /* transient; keep waiting */ }
  }
}

/** Display the preview or configured architecture (never with activity). */
function showScope(scope) {
  const topology = scope === "configured" && state.configured ? state.configured : window.StudioGraph.previewTopology();
  state.scope = topology.scope === "configured" ? "configured" : "preview";
  state.displayTopology = topology;
  state.topology = null; state.runId = null; state.snapshot = null; state.events = []; state.eventIndex = new Map();
  state.activityCache = null; state.selectedEventId = null; state.selectedNode = null; state.selectedEdge = null;
  state.reference = null; state.referenceKey = null; state.answerCache = null; state.storyCache = null;
  state.graph.setTopology(topology);
  state.team?.setTopology(topology, null);
  renderAll();
}

async function loadRun(runId) {
  if (!runId) return;
  stopStream(); stopReplay(); releaseArtifactUrls();
  setConnection("Loading run", "idle");
  setNotice("");
  rememberRun(runId);
  state.runId = runId; state.selectedEventId = null; state.selectedAgent = ""; state.live = true;
  state.selectedNode = null; state.selectedEdge = null; state.activityCache = null; state.evidenceKey = null;
  state.reference = null; state.referenceKey = null; state.answerCache = null; state.storyCache = null;
  state.selectedStepId = null; state.linkedSteps = new Set(); state.expandedSteps = new Set(); state.traceFilter = null;
  try {
    state.snapshot = await (await api(`/api/runs/${encodeURIComponent(runId)}/snapshot`)).json();
    setEvents(state.snapshot.events || []);
    state.topology = state.snapshot.topology || null;
    if (state.pendingEvent && state.eventIndex.has(state.pendingEvent)) {
      state.selectedEventId = state.pendingEvent;
      state.pendingEvent = null;
    }
    state.replayIndex = state.events.length;
    state.startedAt = state.events[0]?.timestamp || state.snapshot.manifest?.created_at || null;
    if (state.topology) {
      state.graph.options.collapsed = new Set(); state.graph.options.userCollapsed = false;
      state.graph.topology = null; state.graph.view = null;
      state.graph.setTopology(state.topology);
      state.scope = "run"; state.displayTopology = state.topology;
    } else {
      // Compatible backends always send a topology; never draw a silent blank.
      setNotice("This run snapshot carried no topology. Showing the configured architecture instead.", "warning");
      showScope(state.configured ? "configured" : "preview");
      return;
    }
    renderAll();
    fetchReference();
    startStream();
  } catch (error) {
    setConnection(error.status === 404 ? "Run unavailable" : "Run failed to load", "failed");
    setNotice(error.status === 404 ? `Run “${runId}” was not found in this Studio's runs directory.` : `Could not load run “${runId}”: ${error.message}`, "error");
    if (error.status === 401) { setConnection("Invalid token", "failed"); }
  }
}

/** Keep the selected run in the URL fragment (never the token) so a refresh can restore it. */
function rememberRun(runId) {
  history.replaceState(null, "", `${location.pathname}${location.search}#${new URLSearchParams({run: runId})}`);
}

function setEvents(events) {
  const map = new Map();
  for (const event of events) map.set(event.event_id, event);
  state.events = [...map.values()].sort((a, b) => (a.sequence - b.sequence) || a.event_id.localeCompare(b.event_id));
  state.eventIndex = map;
}

function visibleCount() { return state.live ? state.events.length : state.replayIndex; }
function visibleEvents() { return state.events.slice(0, visibleCount()); }
function isVisible(eventId) {
  const event = state.eventIndex.get(eventId);
  if (!event) return false;
  const count = visibleCount();
  return count >= state.events.length || state.events.indexOf(event) < count;
}

function updateRunConnection() {
  const terminalEvent = state.events.findLast((event) => ["RUN_COMPLETED", "RUN_FAILED", "RUN_CANCELLED"].includes(event.event_type));
  const status = terminalEvent
    ? {RUN_COMPLETED: "COMPLETED", RUN_FAILED: "FAILED", RUN_CANCELLED: "CANCELLED"}[terminalEvent.event_type]
    : state.snapshot?.state?.status || state.snapshot?.final?.run_status;
  if (terminalStates.has(status)) {
    setConnection(`Run ${status.toLowerCase()} · recorded`, status === "FAILED" ? "failed" : status === "COMPLETED" ? "completed" : "idle");
    if (status === "FAILED") setNotice("This recorded run failed. Opening it replays saved events; it does not restart the investigation. Start a fresh run after the required services are ready.", "error");
  } else setConnection("Run loaded · live stream", "live");
}

async function startStream() {
  if (!state.runId) return;
  const controller = new AbortController();
  state.streamController = controller;
  const last = state.events.at(-1)?.sequence ?? -1;
  try {
    const response = await api(`/api/runs/${encodeURIComponent(state.runId)}/stream?cursor=${last}`, {signal: controller.signal});
    updateRunConnection();
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop();
      for (const chunk of chunks) {
        const data = chunk.split("\n").filter((line) => line.startsWith("data: ")).map((line) => line.slice(6)).join("\n");
        if (!data) continue;
        try { acceptEvent(JSON.parse(data)); } catch { /* ignore malformed in-flight message */ }
      }
    }
  } catch (error) {
    if (error.name !== "AbortError") {
      setConnection(error.status === 401 ? "Invalid token" : "Stream reconnecting", "idle");
      window.setTimeout(() => { if (state.streamController === controller) startStream(); }, 1200);
    }
  }
}

function stopStream() { if (state.streamController) state.streamController.abort(); state.streamController = null; }

function acceptEvent(event) {
  if (state.eventIndex.has(event.event_id)) return;
  const appended = !state.events.length || state.events.at(-1).sequence < event.sequence;
  if (appended) { state.events.push(event); state.eventIndex.set(event.event_id, event); }
  else setEvents([...state.events, event]);
  updateRunConnection();
  if (state.live) { state.replayIndex = state.events.length; state.pulseQueue.push(event.event_id); }
  if (referencesUnknownNode(event)) scheduleTopologyRefresh();
  if (["RUN_COMPLETED", "FINAL_ANSWER_RECORDED", "RUN_FAILED", "RUN_CANCELLED"].includes(event.event_type)) {
    refreshSnapshot().then(fetchReference);
    // Keep the run menu's "STATUS · N events" label in step with the stream.
    refreshRunList().catch(() => { /* transient; the next refresh will catch up */ });
  }
  renderAll();
}

function referencesUnknownNode(event) {
  if (!state.topology) return true;
  const known = state.activityCache?.state?.index?.nodes || new Map((state.topology.nodes || []).map((n) => [n.id, n]));
  const ids = [...(event.activity?.nodes || []), ...(event.activity?.path || []).flatMap((hop) => [hop.from, hop.to])];
  return ids.some((id) => id && !known.has(id));
}

function scheduleTopologyRefresh() {
  if (state.topologyRefresh) return;
  state.topologyRefresh = window.setTimeout(async () => {
    try {
      const topology = await (await api(`/api/runs/${encodeURIComponent(state.runId)}/topology`)).json();
      applyTopology(topology);
    } catch { /* keep the current topology; the stream remains authoritative */ }
    state.topologyRefresh = null;
  }, 400);
}

function applyTopology(topology) {
  if (!topology || topology.fingerprint === state.topology?.fingerprint) return;
  state.topology = topology;
  state.activityCache = null;
  state.graph.setTopology(topology);
  state.team?.setTopology(topology, state.snapshot?.effective_config || null);
  renderAll();
}

async function refreshSnapshot() {
  try {
    state.snapshot = await (await api(`/api/runs/${encodeURIComponent(state.runId)}/snapshot`)).json();
    const before = state.events.length;
    setEvents([...state.events, ...(state.snapshot.events || [])]);
    if (state.events.length !== before) state.activityCache = null;
    if (state.live) state.replayIndex = state.events.length;
    applyTopology(state.snapshot.topology);
    renderAll();
  } catch { /* current stream remains authoritative */ }
}

// ---- Rendering (batched to one frame) --------------------------------------
function renderAll() {
  if (state.renderScheduled) return;
  state.renderScheduled = true;
  window.requestAnimationFrame(() => { state.renderScheduled = false; renderNow(); });
}

function renderNow() {
  const activity = activityState();
  const answer = answerState();
  renderHeader(activity); renderFilters(); renderGraph(activity); renderTeam(activity, answer); renderReplay();
  renderAnswerStrip(answer); renderConfig(); renderEstimateHistory(answer); renderSimpleTeam(activity, answer); renderFocus(); renderParsec();
  if (state.tab === "log") renderTimeline(); else renderStory();
  renderMemoryTabs(); renderInspector(activity);
  const selected = state.selectedEventId && isVisible(state.selectedEventId) ? state.eventIndex.get(state.selectedEventId) : null;
  renderDetails(selected); renderEvidence(evidenceSelection(selected) || latestEvidenceEvent());
  flushPulses();
}

/** PARSEC-VL view: rebuilt only when the run or the visible prefix changes (replay-safe fold). */
function renderParsec() {
  if (!state.parsec || !window.StudioParsec) return;
  const inRun = state.scope === "run" && state.runId;
  const key = inRun ? `${state.runId}|${visibleCount()}` : `none|${state.scope}`;
  if (state.parsecKey === key) return;
  state.parsecKey = key;
  const model = inRun ? window.StudioParsec.buildModel(visibleEvents()) : null;
  state.parsec.update(model);
  $("#parsec-meta").textContent = model && model.available
    ? `${model.policy ? model.policy.toUpperCase() : "scheduler"} · ${model.tasks.length} scheduler task(s) · ${model.plans.length} plan(s)` : "";
}

/** Answer state for the visible prefix (cached per prefix length). */
function answerState() {
  if (state.scope !== "run" || !state.runId) return null;
  const count = visibleCount();
  const last = state.events[count - 1]?.event_id || null;
  if (state.answerCache && state.answerCache.count === count && state.answerCache.last === last) return state.answerCache.value;
  const value = Answer.foldAnswerState(state.events, count, {effectiveConfig: state.snapshot?.effective_config || null});
  state.answerCache = {count, last, value};
  return value;
}

function storySteps() {
  const count = visibleCount();
  const last = state.events[count - 1]?.event_id || null;
  if (state.storyCache && state.storyCache.count === count && state.storyCache.last === last) return state.storyCache.steps;
  const steps = Story.buildStory(visibleEvents());
  const attached = new Map();
  for (const step of steps) for (const id of step.source_event_ids) attached.set(id, step);
  state.storyCache = {count, last, steps, attached};
  return steps;
}

/** The story step that owns an event (null for technical-only events). */
function stepForEvent(eventId) { storySteps(); return state.storyCache?.attached.get(eventId) || null; }

/** Story-relevant events drive highlights unless technical activity is switched on. */
function isMeaningful(event) {
  if (!event) return false;
  if (state.technical) return true;
  // Attaching bookkeeping to a story card preserves provenance; it does not
  // turn that bookkeeping into a meaningful graph animation.
  if (event.status !== "failed" && ["MEMORY_WRITTEN", "MEMORY_READ", "OPTIONAL_MEMORY_WRITTEN",
    "MESSAGE_DELIVERED", "MESSAGE_RECEIVED", "WORKER_STARTED", "WORKER_FINISHED",
    "PEER_REVIEW_FINISHED", "FOLLOW_UP_FINISHED", "RUN_CONFIGURATION_RECORDED",
    "RUN_COMPLETED"].includes(event.event_type)) return false;
  if (event.event_type === "EVIDENCE_OBSERVED" && event.status !== "failed"
    && !event.payload?.supported_findings && !event.payload?.remaining_uncertainties && !event.payload?.decision_to_continue_or_stop) return false;
  const step = stepForEvent(event.event_id);
  return Boolean(step && step.level !== "divider");
}

/** The event that best shows a step on the graph: a tool step's result, or its request while running. */
function representative(step) {
  const get = (id) => (id && isVisible(id) ? state.eventIndex.get(id) : null);
  if (step.kind === "tool") {
    if (step.resultEventId && get(step.resultEventId)) return get(step.resultEventId);
    const started = step.source_event_ids.map(get).filter((e) => e && ["TOOL_CALL_STARTED", "TOOL_CALL_REQUESTED"].includes(e.event_type)).at(-1);
    if (started) return started;
  }
  return get(step.primaryEventId) || get(step.source_event_ids[0]);
}

/** Latest story-relevant activity (the raw latest event in technical mode). */
function latestMeaningful() {
  const count = visibleCount();
  if (state.technical) return state.events[count - 1] || null;
  for (let i = count - 1; i >= 0; i -= 1) {
    const step = stepForEvent(state.events[i].event_id);
    if (step && step.level !== "divider") return representative(step) || state.events[i];
  }
  return null;
}

/** Incrementally maintained activity state for the visible prefix. */
function activityState() {
  if (!state.topology) return null;
  const count = visibleCount();
  const fingerprint = state.topology.fingerprint;
  const cache = state.activityCache;
  const reusable = cache && cache.fingerprint === fingerprint && cache.count <= count
    && (cache.count === 0 || state.events[cache.count - 1]?.event_id === cache.lastId);
  let current = reusable ? cache : {fingerprint, count: 0, lastId: null, state: Activity.createState(state.topology)};
  for (let i = current.count; i < count; i += 1) Activity.applyEvent(current.state, state.events[i]);
  current = {...current, count, lastId: state.events[count - 1]?.event_id || null};
  state.activityCache = current;
  return current.state;
}

function renderHeader(activity) {
  if (state.scope !== "run" || !state.runId) {
    $("#task-title").textContent = state.scope === "configured" ? "No run selected — configured architecture shown" : "Connect to inspect a run";
    for (const id of ["#run-status", "#run-mode", "#agent-count", "#elapsed", "#tool-budget"]) $(id).textContent = "—";
    $("#final-status").textContent = "Pending"; $("#final-status").className = "status-chip idle";
    return;
  }
  const snapshot = state.snapshot || {};
  const manifest = snapshot.manifest || {};
  const events = visibleEvents();
  const recorded = snapshot.state?.status || snapshot.final?.run_status;
  // In replay, the header reflects only the visible prefix.
  // A snapshot is only authoritative once terminal; otherwise the live stream is newer.
  const status = state.live && terminalStates.has(recorded) ? recorded : (activity?.runStatus || recorded || "RUNNING");
  $("#task-title").textContent = manifest.original_task || eventPayload("TASK_RECEIVED", "original_task") || state.runId || "Unknown task";
  $("#run-status").textContent = status;
  $("#run-mode").textContent = manifest.execution_mode || manifest.mode || "multi-agent";
  $("#agent-count").textContent = String(agentIds().length || "—");
  const budget = snapshot.budgets?.global?.tool_calls;
  $("#tool-budget").textContent = state.live && budget ? `${budget.used} / ${budget.limit}` : budgetFromEvents(events);
  const chip = $("#final-status");
  chip.textContent = terminalStates.has(status) ? status : "Pending";
  chip.className = `status-chip ${status === "COMPLETED" ? "completed" : status === "FAILED" ? "failed" : "idle"}`;
  updateElapsed();
}

function eventPayload(type, key) { return state.events.find((e) => e.event_type === type)?.payload?.[key]; }

function budgetFromEvents(events) {
  const calls = events.filter((e) => e.event_type === "TOOL_CALL_STARTED").length;
  return calls ? `${calls} used` : "—";
}

function updateElapsed() {
  if (!state.startedAt) return $("#elapsed").textContent = "—";
  const end = state.events.findLast?.((e) => e.event_type === "RUN_COMPLETED")?.timestamp;
  const seconds = Math.max(0, Math.floor((new Date(end || Date.now()) - new Date(state.startedAt)) / 1000));
  $("#elapsed").textContent = seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function agentIds() {
  if (state.topology?.agents?.length) return [...state.topology.agents];
  const ids = new Set(["coordinator"]);
  for (const worker of state.snapshot?.workers || []) ids.add(worker.agent_id);
  for (const event of state.events) if (event.agent_id && !["orchestrator", "unknown"].includes(event.agent_id)) ids.add(event.agent_id);
  return [...ids];
}

function agentLabel(id) {
  if (id === "coordinator") return "Coordinator";
  const match = /^worker_(\d+)$/.exec(id || "");
  return match ? `Worker ${Number(match[1])}` : (id || "unknown");
}

function renderFilters() {
  const agent = $("#agent-filter");
  const previousAgent = agent.value;
  const ids = agentIds();
  const signature = ids.join("|");
  if (agent.dataset.signature !== signature) {
    agent.replaceChildren(new Option("All agents", ""));
    for (const id of ids) agent.append(new Option(id, id));
    agent.dataset.signature = signature;
  }
  agent.value = state.selectedAgent || previousAgent;
  const type = $("#type-filter");
  const previousType = type.value;
  const types = [...new Set(state.events.map((e) => e.event_type))].sort();
  if (type.dataset.signature !== types.join("|")) {
    type.replaceChildren(new Option("All event types", ""));
    for (const name of types) type.append(new Option(name.replaceAll("_", " "), name));
    type.dataset.signature = types.join("|");
  }
  type.value = previousType;
  $("#agent-filter-label").textContent = state.selectedAgent || "All agents";
}

// ---- Architecture graph -----------------------------------------------------
function highlightOf(activity, event) { return event ? Activity.highlightFor(activity, event) : null; }

function renderGraph(activity) {
  if (!state.graph) return;
  $("#architecture-title").textContent = state.scope === "run" && state.runId ? `Run topology · ${state.runId}` : SCOPE_TEXT[state.scope][0];
  if (state.scope !== "run" || !state.topology || !activity) {
    // Preview/configured: structure only, never activity.
    if (state.displayTopology && state.graph.topology === state.displayTopology) {
      state.graph.selection = {nodeId: state.selectedNode, edgeId: state.selectedEdge};
      state.graph.update(Activity.createState(state.displayTopology), {latest: null, selected: null}, scopeSubtitle);
    }
    const chip = $("#activity-kind");
    chip.className = "flow-chip lifecycle";
    chip.textContent = state.scope === "configured" ? "Configured" : "Preview";
    $("#activity-label").textContent = SCOPE_TEXT[state.scope][0];
    $("#activity-detail").textContent = SCOPE_TEXT[state.scope][1];
    $("#activity-running").textContent = "";
    return;
  }
  const latest = latestMeaningful();
  const selected = state.selectedEventId && isVisible(state.selectedEventId) ? state.eventIndex.get(state.selectedEventId) : null;
  state.graph.selection = {nodeId: state.selectedNode, edgeId: state.selectedEdge};
  state.graph.update(activity, {latest: highlightOf(activity, latest), selected: highlightOf(activity, selected)}, nodeSubtitle);
  renderCaption(activity, selected || latest);
}

const PREVIEW_SUBTITLES = {
  coordinator: "plans · delegates · synthesizes", worker: "investigates independently", harness: "agent loop",
  model_client: "per-agent client", memory: "private to its agent", tool_router: "selects and calls tools",
  model_service: "shared serving backend", tool: "grounding · zoom · OCR · …", communication: "",
  budget: "tool / model / message limits", event_log: "immutable event log", artifact_store: "content-addressed images",
  task: "image(s) + question", result: "coordinator synthesis", orchestrator: "run lifecycle",
};

function scopeSubtitle(node) {
  const meta = node.metadata || {};
  if (state.scope === "configured") {
    const template = state.displayTopology?.worker_template || {};
    if (node.type === "worker") return `${template.default_count ?? "?"} by default · up to ${template.max_count ?? "?"}`;
    if (node.type === "tool") return meta.backend ? `backend ${meta.backend}` : "registered tool";
    if (node.type === "model_service") return hostOf(meta.endpoint) || "endpoint not resolved";
    if (node.type === "model_client") return shortModel(meta.model_id) || "model not declared";
    if (node.type === "tool_router") return `${(meta.tools || []).length} tools registered`;
    if (node.type === "budget") return meta.limits?.tool_calls ? `tools ${meta.limits.tool_calls} · models ${meta.limits.model_requests ?? "—"}` : "limits";
    if (node.type === "memory") return (meta.modules || []).join(", ") || "private";
  }
  return PREVIEW_SUBTITLES[node.type] ?? "";
}

function nodeSubtitle(node, activity, toolRuns, runs) {
  const record = activity.nodes.get(node.id) || {};
  const meta = node.metadata || {};
  switch (node.type) {
    case "coordinator": case "worker": return Activity.agentStatusLine(activity, node.id);
    case "harness": return meta.implementation ? `${meta.implementation} loop` : "agent loop";
    case "model_client": return meta.kind === "fixture" ? "fixture policy" : shortModel(meta.model_id) || "model not recorded";
    case "model_service": {
      const inflight = runs.filter((open) => open.kind === "model_request").length;
      if (inflight) return `${inflight} request${inflight === 1 ? "" : "s"} in flight`;
      if (meta.kind === "fixture") return "no physical service";
      const clients = (meta.clients || []).length;
      return `${clients} client${clients === 1 ? "" : "s"} · ${hostOf(meta.endpoint) || "endpoint not recorded"}`;
    }
    case "tool": {
      if (toolRuns.length) return `Running ×${toolRuns.length}`;
      const users = (meta.users || []).length;
      return `${record.requests || 0} call${record.requests === 1 ? "" : "s"}${record.failures ? ` · ${record.failures} failed` : ""} · ${users} user${users === 1 ? "" : "s"}`;
    }
    case "tool_router": return `${(meta.tools || []).length} tool${(meta.tools || []).length === 1 ? "" : "s"} routed`;
    case "memory": return `private · ${record.touches || 0} access${record.touches === 1 ? "" : "es"}`;
    case "communication": {
      const queued = [...activity.open.values()].filter((open) => open.correlationId.startsWith("msg:")).length;
      return queued ? `${queued} queued` : "";
    }
    case "budget": { const limits = meta.limits || {}; return limits.tool_calls ? `tools ${limits.tool_calls} · models ${limits.model_requests ?? "—"}` : "reservations"; }
    case "result": {
      const coordinator = activity.agents.get("coordinator");
      return coordinator?.status === "completed" && coordinator.candidate !== null && coordinator.candidate !== undefined ? `Answer: ${pretty(coordinator.candidate, 60)}` : "pending";
    }
    case "task": return `${(state.snapshot?.artifact_aliases && Object.keys(state.snapshot.artifact_aliases).length) || 0} visual input(s)`;
    case "orchestrator": return (activity.runStatus || "idle").toLowerCase();
    case "event_log": return `${activity.count} events`;
    case "artifact_store": return `${artifactCount()} artifact(s) visible`;
    default: return "";
  }
}

function artifactCount() {
  const ids = new Set();
  for (const event of visibleEvents()) for (const ref of event.artifact_refs || []) ids.add(ref);
  return ids.size;
}

function shortModel(id) { return id ? String(id).split("/").at(-1) : null; }
function hostOf(endpoint) { try { return endpoint ? new URL(endpoint).host : null; } catch { return null; } }

function renderCaption(activity, event) {
  const chip = $("#activity-kind"); const label = $("#activity-label"); const detail = $("#activity-detail");
  const runningTools = [...activity.open.values()].filter((open) => open.kind.startsWith("tool") || (state.technical && open.kind === "model_request"));
  $("#activity-running").textContent = runningTools.length ? `${runningTools.length} running` : "";
  if (!event?.activity) { chip.className = "flow-chip lifecycle"; chip.textContent = "Idle"; label.textContent = "No activity at this position."; detail.textContent = ""; return; }
  const style = Activity.flowStyle(event.activity.kind);
  chip.className = `flow-chip ${style}`;
  chip.textContent = event.activity.kind.replaceAll("_", " ");
  const step = stepForEvent(event.event_id);
  label.textContent = step && step.level !== "divider" ? `${step.number ? `${String(step.number).padStart(2, "0")} · ` : ""}${step.title}` : (event.activity.label || event.summary || event.event_type);
  const selected = event.event_id === state.selectedEventId ? "Selected" : (state.live ? "Latest step" : "At replay position");
  detail.textContent = `${selected} · ${event.activity.label || event.summary || event.event_type} (event #${event.sequence})`;
}

function queuePulse(eventId) { state.pulseQueue.push(eventId); }
function flushPulses() {
  const ids = state.pulseQueue.splice(0).filter((id) => {
    const event = state.eventIndex.get(id);
    return event && isVisible(id) && (isMeaningful(event) || id === state.selectedEventId);
  }).slice(-3);
  const activity = state.activityCache?.state;
  if (!activity || !state.graph) return;
  for (const id of ids) {
    const event = state.eventIndex.get(id);
    state.graph.pulse(Activity.highlightFor(activity, event));
  }
}

// ---- Inspector -------------------------------------------------------------
function renderInspector(activity) {
  const host = $("#inspector");
  host.replaceChildren();
  if (state.scope !== "run") {
    const node = state.displayTopology?.nodes.find((item) => item.id === state.selectedNode);
    if (!node) { host.className = "inspector empty-state"; host.textContent = "Click a component to see what it is."; return; }
    host.className = "inspector";
    const heading = el("h3", "", node.label); heading.append(el("span", "prov-tag", node.provenance));
    host.append(heading, el("div", "kind", node.type.replaceAll("_", " ") + (node.shared ? " · shared" : "")));
    const rows = [["Description", PREVIEW_SUBTITLES[node.type] || "—"]];
    for (const [key, value] of Object.entries(safeValue(node.metadata || {}))) {
      if (value === null || value === undefined || (typeof value === "object" && !Object.keys(value).length)) continue;
      rows.push([key.replaceAll("_", " "), typeof value === "object" ? pretty(value, 300) : String(value)]);
    }
    host.append(definitionList(rows), el("p", "note", state.scope === "configured"
      ? "Configured component: declared by configuration. No run is selected, so nothing here has executed."
      : "Preview component: illustrates the framework. It is not a configuration and not live execution."));
    return;
  }
  const topology = state.topology;
  if (!topology || !activity || (!state.selectedNode && !state.selectedEdge)) {
    host.className = "inspector empty-state"; host.textContent = "Click a component or connection in the graph."; return;
  }
  host.className = "inspector";
  if (state.selectedEdge) return renderEdgeInspector(host, activity, topology.edges.find((e) => e.id === state.selectedEdge));
  const node = topology.nodes.find((n) => n.id === state.selectedNode);
  if (!node) { host.className = "inspector empty-state"; host.textContent = "The selected component is not part of this run."; return; }
  const heading = el("h3", "", node.label);
  heading.append(el("span", "prov-tag", node.provenance));
  host.append(heading, el("div", "kind", `${node.type.replaceAll("_", " ")}${node.shared ? " · shared" : ""}${node.owner_agent_id ? ` · owned by ${node.owner_agent_id}` : ""}`));
  const rows = [];
  const meta = node.metadata || {};
  const record = activity.nodes.get(node.id) || {};
  if (node.type === "worker" || node.type === "coordinator") {
    const agent = activity.agents.get(node.id) || {};
    const model = topology.nodes.find((n) => n.id === `${node.id}.model_client`)?.metadata || {};
    const harness = topology.nodes.find((n) => n.id === `${node.id}.harness`)?.metadata || {};
    const router = topology.nodes.find((n) => n.id === `${node.id}.tool_router`)?.metadata || {};
    const memory = topology.nodes.find((n) => n.id === `${node.id}.memory`)?.metadata || {};
    rows.push(["Agent ID", node.id], ["Role", meta.role || "—"], ["Status", Activity.agentStatusLine(activity, node.id)],
      ["Subtask", agent.subtask || "—"], ["Candidate", agent.candidate ?? "—"],
      ["Model", [model.model_id || "not recorded", model.protocol, model.endpoint].filter(Boolean).join(" · ")],
      ["Harness", [harness.implementation || "inferred", harness.max_iterations ? `max ${harness.max_iterations} iterations` : null].filter(Boolean).join(" · ")],
      ["Tools", (router.tools || []).join(", ") || "none"], ["Memory", `${memory.scope || "private"} · ${(memory.modules || []).join(", ") || "modules not recorded"}`]);
    if (agent.tools?.size) rows.push(["Tool usage", [...agent.tools].map(([name, n]) => `${name} ×${n}`).join(", ")]);
    host.append(definitionList(rows));
    host.append(eventList("Recent actions", visibleEvents().filter((e) => e.agent_id === node.id).slice(-8).reverse()));
    const actions = el("div", "actions");
    const memoryButton = el("button", "", "Open permitted memory");
    memoryButton.type = "button";
    memoryButton.addEventListener("click", () => { state.selectedAgent = node.id; renderMemoryTabs(); loadMemory(node.id); });
    const filterButton = el("button", "", "Filter timeline to agent");
    filterButton.type = "button";
    filterButton.addEventListener("click", () => selectAgent(node.id));
    actions.append(memoryButton, filterButton);
    host.append(actions, el("p", "note", "Memory contents are fetched only on request and authorized by the server."));
    return;
  }
  if (node.type === "tool") {
    const running = [...activity.open.values()].filter((open) => open.toolNode === node.id);
    const calls = visibleEvents().filter((e) => e.activity?.tool_node === node.id && ["TOOL_CALL_REQUESTED", "TOOL_CALL_COMPLETED", "TOOL_CALL_FAILED", "TOOL_CALL_CANCELLED"].includes(e.event_type));
    const artifacts = [...new Set(calls.flatMap((e) => e.artifact_refs || []))];
    rows.push(["Ownership", node.shared ? `shared by ${(meta.users || []).join(", ")}` : `used by ${(meta.users || []).join(", ") || "—"}`],
      ["Backend", meta.backend || "not recorded"], ["Service", meta.service || "not recorded"],
      ["Running now", running.length ? running.map((open) => agentLabel(open.agentId)).join(", ") : "none"],
      ["Calls started", String(record.requests || 0)], ["Failures", String(record.failures || 0)],
      ["Evidence", artifacts.length ? `${artifacts.length} artifact(s)` : "none"]);
    host.append(definitionList(rows), eventList("Recent requests and results", calls.slice(-10).reverse()));
    return;
  }
  if (node.type === "memory") {
    rows.push(["Owner", node.owner_agent_id], ["Scope", meta.scope || "private"], ["Modules", (meta.modules || []).join(", ") || "not recorded"], ["Accesses", String(record.touches || 0)]);
    host.append(definitionList(rows), eventList("Recorded reads and writes", (record.events || []).map((id) => state.eventIndex.get(id)).filter(Boolean).slice(-10).reverse()));
    const button = el("button", "", "Open permitted memory"); button.type = "button";
    button.addEventListener("click", () => { state.selectedAgent = node.owner_agent_id; renderMemoryTabs(); loadMemory(node.owner_agent_id); });
    const actions = el("div", "actions"); actions.append(button); host.append(actions);
    return;
  }
  const running = (Activity.runningByNode(activity).get(node.id) || []);
  for (const [key, value] of Object.entries(safeValue(meta))) {
    if (value === null || value === undefined || (Array.isArray(value) && !value.length) || (typeof value === "object" && !Array.isArray(value) && !Object.keys(value).length)) continue;
    rows.push([key.replaceAll("_", " "), typeof value === "object" ? pretty(value, 300) : String(value)]);
  }
  if (running.length) rows.push(["In flight", running.map((open) => open.label).join("; ")]);
  rows.push(["Recorded touches", String(record.touches || 0)]);
  host.append(definitionList(rows), eventList("Recent activity", (record.events || []).map((id) => state.eventIndex.get(id)).filter(Boolean).slice(-10).reverse()));
}

function renderEdgeInspector(host, activity, edge) {
  if (!edge) { host.className = "inspector empty-state"; host.textContent = "The selected connection is not part of this run."; return; }
  const record = activity.edges.get(edge.id) || {events: []};
  const label = (id) => state.topology.nodes.find((n) => n.id === id)?.label || id;
  const heading = el("h3", "", `${label(edge.source)} ⇄ ${label(edge.target)}`);
  heading.append(el("span", "prov-tag", edge.provenance));
  host.append(heading, el("div", "kind", `${edge.edge_type} connection`));
  const events = record.events.map((id) => state.eventIndex.get(id)).filter(Boolean);
  const correlations = [...new Set(events.map((e) => e.activity?.correlation_id).filter(Boolean))];
  const last = record.last;
  host.append(definitionList([
    ["Source", edge.source], ["Destination", edge.target], ["Type", edge.edge_type],
    ["Structural direction", `${label(edge.source)} → ${label(edge.target)}`],
    ["Most recent", last ? `${last.kind.replaceAll("_", " ")} · ${last.direction === "forward" ? `${label(edge.source)} → ${label(edge.target)}` : `${label(edge.target)} → ${label(edge.source)}`}` : "no recorded traffic at this position"],
    ["Traffic", `${events.length} event(s)${record.failures ? ` · ${record.failures} failure(s)` : ""}`],
    ["Correlations", correlations.slice(-6).join("\n") || "—"],
    ["Artifacts", [...new Set(events.flatMap((e) => e.artifact_refs || []))].length || "none"],
  ]));
  host.append(eventList("Related events", events.slice(-12).reverse()));
}

function definitionList(rows) {
  const dl = el("dl");
  for (const [key, value] of rows) dl.append(el("dt", "", key), el("dd", "", typeof value === "object" ? pretty(value, 400) : value));
  return dl;
}

function eventList(title, events) {
  const wrap = el("div");
  wrap.append(el("h4", "", title));
  if (!events.length) { wrap.append(el("p", "note", "No recorded events at this position.")); return wrap; }
  for (const event of events) {
    const button = el("button", "event-link");
    button.type = "button";
    button.append(el("span", "", `#${event.sequence}`), document.createTextNode(event.activity?.label || event.summary || event.event_type));
    button.addEventListener("click", () => selectEvent(event.event_id));
    wrap.append(button);
  }
  return wrap;
}

function selectNode(id, agentId = null) {
  state.selectedNode = state.selectedNode === id ? null : id;
  state.selectedEdge = null;
  if (state.selectedNode && state.runId) openStepForNode(id, agentId);
  renderAll();
}

/** Clicking an agent or tool opens its latest story step at the current position. */
function openStepForNode(nodeId, agentId = null) {
  const node = (state.topology?.nodes || []).find((n) => n.id === nodeId);
  const steps = Story.mainSteps(storySteps());
  let step = null;
  if (node?.type === "tool") {
    const name = node.label;
    step = [...steps].reverse().find((s) => s.kind === "tool" && s.tool === name && (!agentId || s.agent === agentId));
  } else if (node?.type === "worker" || node?.type === "coordinator") {
    step = [...steps].reverse().find((s) => s.agent === nodeId);
  }
  if (!step) return;
  state.selectedStepId = step.id;
  state.linkedSteps = Story.linkedSteps(step, storySteps());
  state.selectedEventId = step.primaryEventId;
  state.expandedSteps.add(step.id);
  if (state.tab !== "story") setTab("story");
}
function selectEdge(id) { state.selectedEdge = state.selectedEdge === id ? null : id; state.selectedNode = null; renderAll(); }
function selectEvent(id, {keepStep = false} = {}) {
  if (!keepStep) {
    const step = state.runId ? storySteps().find((s) => s.eventIds.includes(id)) : null;
    state.selectedStepId = step?.id || null;
    state.linkedSteps = step ? Story.linkedSteps(step, storySteps()) : new Set();
  }
  state.selectedEventId = id;
  queuePulse(id);
  renderAll();
  const card = document.querySelector(`.event-card[data-event-id="${CSS.escape(id)}"]`);
  card?.scrollIntoView({block: "nearest"});
}

function selectAgent(id) {
  state.selectedAgent = id; $("#agent-filter").value = id; renderAll(); if (id) loadMemory(id);
}

// ---- Timeline ----------------------------------------------------------------
function eventCategory(event) {
  const kind = event.activity?.kind || "";
  if (kind.startsWith("tool") || kind === "decision" || kind === "evidence") return "tool";
  if (kind.startsWith("memory")) return "memory";
  if (kind.startsWith("model")) return "model";
  if (kind.startsWith("budget")) return "budget";
  if (["estimate", "assessment"].includes(kind) || event.event_type.startsWith("COORDINATOR_")) return "estimate";
  if (["assignment", "verification_request", "cancellation", "report", "failure_report", "peer_message", "question", "reply", "message", "message_delivery", "message_rejected", "delegation"].includes(kind) || event.event_type.startsWith("MESSAGE")) return "message";
  if (event.tool_name) return "tool";
  return "lifecycle";
}

function renderTimeline() {
  const host = $("#timeline"); host.replaceChildren(); host.classList.remove("empty-state");
  const selectedAgent = $("#agent-filter").value;
  const selectedType = $("#type-filter").value;
  const category = $("#category-filter").value;
  const failuresOnly = $("#failure-filter").checked;
  if (!state.runId) { host.classList.add("empty-state"); host.textContent = "Select a run to see its event timeline."; $("#event-count").textContent = "0 events"; return; }
  const filter = state.traceFilter;
  const banner = $("#trace-filter");
  banner.classList.toggle("hidden", !filter);
  if (filter) $("#trace-filter-label").textContent = `Underlying events of ${filter.label}`;
  let events = visibleEvents().filter((e) => (!filter || filter.ids.has(e.event_id)) && (!selectedAgent || e.agent_id === selectedAgent) && (!selectedType || e.event_type === selectedType)
    && (!category || (category === "technical" ? !stepForEvent(e.event_id) : eventCategory(e) === category)) && (!failuresOnly || e.status === "failed"));
  $("#event-count").textContent = `${events.length} event${events.length === 1 ? "" : "s"}${filter ? "" : ` · ${storySteps().technicalEventIds.length} technical-only`}`;
  if (!events.length) { host.classList.add("empty-state"); host.textContent = "No events match the current filters."; return; }
  events = events.slice(-1000);
  for (const event of events) {
    const kind = event.event_type.includes("HYPOTHESIS") ? "hypothesis" : "";
    const card = el("article", `event-card cat-${eventCategory(event)} ${kind} ${event.status === "failed" ? "failed" : ""}${event.event_id === state.selectedEventId ? " selected" : ""}`);
    card.dataset.eventId = event.event_id;
    card.tabIndex = 0;
    const head = el("div", "event-head"); head.append(el("span", "", `#${event.sequence} · ${event.agent_id}`), el("time", "", formatTime(event.timestamp)));
    card.append(head, el("strong", "", event.event_type), el("p", "", event.summary || "Recorded event"));
    if (event.activity?.path?.length) card.append(el("div", "flow-line", event.activity.label));
    const owner = stepForEvent(event.event_id);
    const meta = [`id ${event.event_id}`, event.parent_event_id ? `parent ${event.parent_event_id}` : null, event.causal_refs?.length ? `causal ${event.causal_refs.length}` : null,
      event.tool_name ? `tool ${event.tool_name}` : null, event.payload?.tool_call_id ? `call ${event.payload.tool_call_id}` : null,
      event.artifact_refs?.length ? `artifacts ${event.artifact_refs.length}` : null, `status ${event.status}`,
      owner && owner.level !== "divider" ? `story ${owner.number ? `#${owner.number}` : "(routine)"}` : "technical only"].filter(Boolean);
    card.append(el("div", "trace-meta", meta.join(" · ")));
    const payload = el("details", "trace-payload"); payload.append(el("summary", "", "Payload"));
    payload.addEventListener("toggle", () => { if (payload.open && payload.childElementCount === 1) payload.append(el("pre", "", pretty(event, Infinity))); });
    payload.addEventListener("click", (e) => e.stopPropagation());
    card.append(payload);
    const choose = () => selectEvent(event.event_id);
    card.addEventListener("click", choose);
    card.addEventListener("keydown", (keyEvent) => { if (keyEvent.key === "Enter") choose(); });
    host.append(card);
  }
}

function formatTime(value) { const date = new Date(value); return Number.isNaN(date.valueOf()) ? "" : date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"}); }

// ---- Replay -------------------------------------------------------------------
function renderReplay() {
  const total = state.events.length; const current = state.live ? total : state.replayIndex;
  $("#replay-slider").max = String(total); $("#replay-slider").value = String(current);
  $("#replay-position").textContent = `${current} / ${total}`;
  $("#replay-mode").textContent = state.live ? "Live trajectory" : "Deterministic replay";
  $("#replay-play").textContent = state.playing ? "❚❚" : "▶";
  $("#go-live").disabled = state.live;
}

function setReplayIndex(index, {keepPlaying = false} = {}) {
  if (!keepPlaying) stopReplay();
  const previous = visibleCount();
  state.replayIndex = Math.max(0, Math.min(state.events.length, index));
  state.live = !keepPlaying && state.replayIndex >= state.events.length;
  if (state.replayIndex === previous + 1) queuePulse(state.events[state.replayIndex - 1]?.event_id);
  renderAll();
}

function toggleReplay() {
  if (state.playing) return stopReplay();
  if (state.live || state.replayIndex >= state.events.length) { state.live = false; state.replayIndex = 0; }
  state.playing = true; renderReplay();
  const tick = () => {
    if (!state.playing) return;
    setReplayIndex(state.replayIndex + 1, {keepPlaying: true});
    if (state.replayIndex >= state.events.length) { stopReplay(); goLive(); return; }
    state.timer = window.setTimeout(tick, Number($("#replay-speed").value));
  };
  state.timer = window.setTimeout(tick, Number($("#replay-speed").value));
}

function stopReplay() { state.playing = false; if (state.timer) window.clearTimeout(state.timer); state.timer = null; renderReplay(); }

function goLive() { stopReplay(); state.live = true; state.replayIndex = state.events.length; renderAll(); }

// ---- Step details -------------------------------------------------------------
/** Readable "key: value" lines for small structured inputs (never a raw JSON dump). */
function keyValues(value, limit = 8) {
  if (value === null || value === undefined) return null;
  if (typeof value !== "object") return String(value);
  const lines = [];
  for (const [key, item] of Object.entries(safeValue(value)).slice(0, limit)) {
    if (item && typeof item === "object" && item.artifact_ref) { lines.push(`${key.replaceAll("_", " ")}: [image artifact]`); continue; }
    const text = typeof item === "object" ? JSON.stringify(item) : String(item);
    lines.push(`${key.replaceAll("_", " ")}: ${text.length > 120 ? `${text.slice(0, 119)}…` : text}`);
  }
  return lines.join("\n") || null;
}

function regionText(payload) {
  const boxes = findBoxes(payload);
  const crop = deepFind(payload, ["crop_bounds"]);
  const parts = [];
  if (boxes.length) parts.push(`${boxes.length} region${boxes.length === 1 ? "" : "s"} in ${deepFind(payload, ["coordinate_system"]) || "recorded"} coordinates (drawn on the original image)`);
  if (Array.isArray(crop) && crop.length >= 4) parts.push(`crop [${crop.map((v) => Math.round(v)).join(", ")}]`);
  return parts.join(" · ") || null;
}

function renderDetails(event) {
  const host = $("#step-details"); host.replaceChildren();
  if (!event) { host.className = "detail-grid empty-state"; host.textContent = "Select a story step or event to see what it did, what it returned, and what changed."; return; }
  host.className = "detail-grid";
  const payload = event.payload || {};
  const steps = state.runId ? storySteps() : [];
  const step = steps.find((item) => item.eventIds.includes(event.event_id)) || null;
  const request = relatedEvent(event, "TOOL_CALL_REQUESTED");
  const result = step?.resultEventId ? state.eventIndex.get(step.resultEventId) : null;
  const decision = previousEvent(event, "DECISION_SUMMARY_RECORDED", event.agent_id);
  const citing = steps.filter((other) => (other.kind === "estimate" || other.kind === "assessment") && step && Story.linkedSteps(other, steps).has(step.id));
  const cards = [];
  cards.push(["What happened", step ? `${step.title}\n${step.text || ""}` : (event.activity?.label || event.summary || event.event_type), true]);
  const intent = step?.intent || payload.action_intent || payload.rationale || (decision?.payload?.rationale_recorded === false ? null : decision?.payload?.action_intent);
  cards.push(["Recorded intent", intent || "No explicit public rationale was recorded for this step.", false]);
  const input = step?.arguments || payload.arguments || request?.payload?.arguments;
  if (input) cards.push(["Tool request", keyValues(input), false]);
  const output = step?.observation || (payload.hypothesis !== undefined ? `Candidate: ${payload.hypothesis}` : null) || (payload.estimate !== undefined ? `Estimate: ${payload.estimate ?? "none"} (${payload.status || payload.outcome})` : null);
  if (output) cards.push(["What it returned", output, false]);
  const region = regionText(result?.payload || payload);
  if (region) cards.push(["Original-image region", region, false]);
  const facts = [...(step?.interpretation || []).map(([k, v]) => `Agent's assessment — ${k}: ${v}`), ...(step?.facts || []).map(([k, v]) => `${k}: ${v}`)];
  if (facts.length) cards.push(["Assessment and uncertainty", facts.join("\n"), true]);
  if (step?.memory?.length) cards.push(["Memory", [...new Set(step.memory)].join("; "), false]);
  const next = step?.next ? `${agentLabel(step.agent)} ${step.next}.` : effectText(event);
  cards.push(["What happened next", next, false]);
  if (step) cards.push(["Underlying events", `${step.source_event_ids.length} raw event(s) form this step. Use “View underlying events” in the story card to open them in the Technical Trace.`, false]);
  if (citing.length) cards.push(["Coordinator estimate impact", citing.map((other) => `${other.title.replace(/^Coordinator — /, "")} (step #${state.eventIndex.get(other.primaryEventId)?.sequence ?? "?"}): ${other.text}`).join("\n"), true]);
  else if (step && ["tool", "hypothesis"].includes(step.kind)) cards.push(["Coordinator estimate impact", "No recorded coordinator assessment cites this step at this position.", false]);
  for (const [title, value, wide] of cards) {
    const card = el("section", `detail-card${wide ? " wide" : ""}`); card.append(el("h3", "", title), el("p", "", value)); host.append(card);
  }
  const raw = el("section", "detail-card wide technical");
  const details = el("details");
  const flow = event.activity?.path?.length ? `Graph path: ${event.activity.path.map((hop) => `${hop.from} → ${hop.to}`).join(" · ")}\n` : "";
  details.append(el("summary", "", `Technical record (advanced) · ${event.event_type} #${event.sequence}`), el("pre", "", `${flow}${pretty(payload, 6000)}`));
  raw.append(details);
  host.append(raw);
}

function previousEvent(event, type, agent) { return [...visibleEvents()].reverse().find((e) => e.sequence < event.sequence && e.event_type === type && e.agent_id === agent); }
function nextEvent(event, type, agent) { return visibleEvents().find((e) => e.sequence > event.sequence && e.event_type === type && e.agent_id === agent); }
function relatedEvent(event, type) {
  const corr = event.activity?.correlation_id;
  if (!corr) return null;
  return visibleEvents().find((e) => e.activity?.correlation_id === corr && e.event_type === type) || null;
}
function effectText(event) { if (event.status === "failed") return "The step failed; downstream agents can continue with the recorded limitation."; if (event.event_type.startsWith("MESSAGE")) return "The message became available to its recorded recipient."; return "No explicit downstream hypothesis update was linked."; }

// ---- Evidence workspace --------------------------------------------------------
function latestEvidenceEvent() {
  const events = [...visibleEvents()].reverse();
  const tool = events.find((event) => ["TOOL_CALL_REQUESTED", "TOOL_CALL_STARTED", "TOOL_CALL_COMPLETED", "TOOL_CALL_FAILED"].includes(event.event_type) && invocationForEvent(event));
  return tool || events.find((event) => event.event_type === "TOOL_CALL_COMPLETED") || events.find((event) => event.event_type === "EVIDENCE_OBSERVED") || events.find((event) => event.artifact_refs?.length);
}

/** The event whose payload carries the evidence for a selected step (same invocation, visible prefix only). */
function evidenceEventFor(event) {
  const kind = event.activity?.kind;
  if (kind === "tool_running" || kind === "decision") return relatedEvent(event, "TOOL_CALL_REQUESTED") || event;
  if (kind === "evidence" || kind === "memory_write") {
    return relatedEvent(event, "TOOL_CALL_COMPLETED") || relatedEvent(event, "TOOL_CALL_FAILED") || event;
  }
  return event;
}

function sourceArtifactFor(event) {
  const aliases = state.snapshot?.artifact_aliases || {};
  const requested = event ? (relatedEvent(event, "TOOL_CALL_REQUESTED")?.payload?.arguments || event.payload?.arguments || {}) : {};
  const imageId = typeof requested.image_id === "string" ? requested.image_id : null;
  if (imageId && aliases[imageId]) return aliases[imageId];
  return aliases.input_image_1 || aliases.input_image || Object.values(state.snapshot?.artifacts || {}).find((a) => a.artifact_type === "source_image")?.artifact_id;
}

async function renderEvidence(selection) {
  if (state.runId && selection) {
    const inv = invocationForEvent(evidenceEventFor(selection) || selection) || invocationForEvent(selection);
    if (inv) return renderToolAction(inv, selection);
  }
  hideToolAction();
  if (!state.runId) {
    if (state.evidenceKey === "none") return;
    state.evidenceKey = "none"; state.evidenceToken += 1;
    const stage = $("#image-stage"); stage.replaceChildren(); stage.className = "image-stage empty-state"; stage.textContent = "Select a run to inspect its visual evidence.";
    const derived = $("#derived-stage"); derived.replaceChildren(); derived.className = "derived-stage empty-state"; derived.textContent = "No run selected.";
    $("#evidence-facts").replaceChildren(); $("#evidence-kind").textContent = "No evidence selected"; $("#evidence-kind").className = "status-chip idle";
    $("#artifact-meta").textContent = ""; $("#coordinate-label").textContent = "";
    return;
  }
  const event = selection ? evidenceEventFor(selection) : null;
  const sourceId = sourceArtifactFor(event);
  const key = `${state.runId}|${event?.event_id || ""}|${sourceId || ""}|${selection?.event_id || ""}|${selection?.linkedFrom?.event_id || ""}`;
  if (key === state.evidenceKey) return;
  state.evidenceKey = key;
  const token = ++state.evidenceToken;
  const ref = event?.artifact_refs?.find((id) => id !== sourceId);
  // Load every asset before touching the DOM so a slow response for an
  // earlier selection can never replace the current one.
  let sourceUrl = null; let derivedUrl = null; let derivedError = false;
  if (sourceId) { try { sourceUrl = await artifactUrl(sourceId); } catch { sourceUrl = null; } }
  if (ref) { try { derivedUrl = await artifactUrl(ref); } catch { derivedError = true; } }
  if (token !== state.evidenceToken) return;

  const stage = $("#image-stage"); const derived = $("#derived-stage"); const facts = $("#evidence-facts");
  stage.replaceChildren(); derived.replaceChildren(); facts.replaceChildren();
  const artifact = sourceId ? state.snapshot?.artifacts?.[sourceId] || {} : {};
  if (sourceId) {
    stage.className = "image-stage";
    const img = el("img"); img.alt = sourceUrl ? "Original investigation input" : "Source image unavailable";
    if (sourceUrl) img.src = sourceUrl;
    stage.append(img);
    if (event) drawOverlay(stage, event, artifact);
  } else { stage.className = "image-stage empty-state"; stage.textContent = "This run has no registered source image artifact."; }
  const dims = sourceDimensions(artifact);
  $("#coordinate-label").textContent = dims ? `${dims.width} × ${dims.height} source pixels` : "source dimensions unknown";
  if (!event) { derived.className = "derived-stage empty-state"; derived.textContent = "Select a tool or evidence event."; $("#evidence-kind").textContent = "No evidence selected"; $("#evidence-kind").className = "status-chip idle"; $("#artifact-meta").textContent = ""; return; }
  derived.className = "derived-stage";
  $("#evidence-kind").textContent = event.tool_name || event.event_type.replaceAll("_", " ");
  $("#evidence-kind").className = `status-chip ${event.status === "failed" ? "failed" : "completed"}`;
  if (derivedUrl) { const img = el("img"); img.alt = `${event.tool_name || "Tool"} visual output`; img.src = derivedUrl; derived.append(img); }
  else if (derivedError) derived.append(el("pre", "", "Artifact could not be loaded."));
  else derived.append(el("pre", "", pretty(rendererPayload(event), 5000)));
  const info = evidenceFacts(event, selection);
  for (const [name, value] of info) { const row = el("div", "fact"); row.append(el("span", "", name), el("span", "", value)); facts.append(row); }
  $("#artifact-meta").textContent = event.artifact_refs?.length ? `${event.artifact_refs.length} artifact${event.artifact_refs.length === 1 ? "" : "s"}` : "structured result";
}

function rendererPayload(event) {
  const payload = event.payload || {};
  const name = (event.tool_name || "").toLowerCase();
  if (name.includes("ocr")) return {recognized_text: deepFind(payload, ["text", "ocr_text", "recognized_text"]), result: payload.canonical_result || payload.result};
  if (name.includes("depth")) return {depth_summary: deepFind(payload, ["depth", "min_depth", "max_depth", "mean_depth"]), result: payload.canonical_result || payload.result};
  if (name.includes("zoom")) return {crop: deepFind(payload, ["bbox", "box", "crop_box", "crop_bounds"]), result: payload.canonical_result || payload.result};
  return payload.canonical_result || payload.result || payload.arguments || payload;
}

function evidenceFacts(event, selection) {
  const boxes = findBoxes(event.payload); const rows = [["Agent", event.agent_id], ["Tool", event.tool_name || "—"], ["Status", event.status]];
  if (event.linkedFrom) rows.push(["Shown for", `${event.linkedFrom.summary || "coordinator answer state"} (#${event.linkedFrom.sequence}), via recorded report references`]);
  else if (selection && selection.event_id !== event.event_id) rows.push(["Shown for", `${selection.event_type.replaceAll("_", " ")} #${selection.sequence}`]);
  if (event.activity?.label) rows.push(["Flow", event.activity.label]);
  if (boxes.length) rows.push(["Regions", String(boxes.length)]);
  const score = deepFind(event.payload, ["scores", "score", "confidence"]); if (score !== undefined) rows.push(["Confidence", pretty(score, 180)]);
  const latency = event.payload?.latency_seconds; if (typeof latency === "number") rows.push(["Latency", `${latency.toFixed(2)} s`]);
  if (event.activity?.correlation_id) rows.push(["Correlation", event.activity.correlation_id]);
  if (event.parent_event_id) rows.push(["Parent event", event.parent_event_id]);
  return rows;
}

function deepFind(value, keys, depth = 0) {
  if (!value || depth > 6) return undefined;
  if (Array.isArray(value)) { for (const item of value) { const found = deepFind(item, keys, depth + 1); if (found !== undefined) return found; } return undefined; }
  if (typeof value !== "object") return undefined;
  for (const key of keys) if (Object.hasOwn(value, key)) return value[key];
  for (const item of Object.values(value)) { const found = deepFind(item, keys, depth + 1); if (found !== undefined) return found; }
  return undefined;
}

function findBoxes(payload) {
  const candidate = deepFind(payload, ["boxes", "pred_boxes", "bounding_boxes", "bboxes", "bbox", "crop_bounds"]);
  if (!Array.isArray(candidate)) return [];
  if (candidate.length >= 4 && candidate.slice(0, 4).every(Number.isFinite)) return [candidate.slice(0, 4)];
  return candidate.filter((box) => Array.isArray(box) && box.length >= 4 && box.slice(0, 4).every(Number.isFinite)).map((box) => box.slice(0, 4));
}

/** Authoritative source dimensions from artifact metadata only; never guessed. */
function sourceDimensions(artifact) {
  const width = Number(artifact?.width); const height = Number(artifact?.height);
  return width > 0 && height > 0 ? {width, height} : null;
}

function drawOverlay(stage, event, artifact) {
  const boxes = findBoxes(event.payload); if (!boxes.length) return;
  const dims = sourceDimensions(artifact);
  const warn = (message) => stage.append(el("div", "overlay-warning", message));
  if (!dims) return warn("Regions not drawn: the source image dimensions were not recorded.");
  const {width, height} = dims;
  const payload = event.payload || {};
  let coordinateSystem = deepFind(payload, ["coordinate_system"]) || "source_pixels";
  let metadata = deepFind(payload, ["transform_metadata"]) || {};
  // A tool that reports its own input size in different units: scale explicitly.
  const reportedW = Number(deepFind(payload, ["orig_img_w", "image_width"])); const reportedH = Number(deepFind(payload, ["orig_img_h", "image_height"]));
  if (coordinateSystem === "source_pixels" && reportedW > 0 && reportedH > 0 && (reportedW !== width || reportedH !== height)) {
    coordinateSystem = "resized_pixels"; metadata = {coordinate_width: reportedW, coordinate_height: reportedH};
  }
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "overlay"); svg.setAttribute("viewBox", `0 0 ${width} ${height}`); svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  let drawn = 0;
  boxes.forEach((rawBox, index) => {
    const box = mapBox(rawBox, width, height, coordinateSystem, metadata); if (!box) return;
    const [x1, y1, x2, y2] = box;
    const rect = document.createElementNS(svg.namespaceURI, "rect"); rect.setAttribute("x", x1); rect.setAttribute("y", y1); rect.setAttribute("width", x2 - x1); rect.setAttribute("height", y2 - y1); svg.append(rect);
    const label = document.createElementNS(svg.namespaceURI, "text"); label.setAttribute("x", x1 + 4); label.setAttribute("y", Math.max(14, y1 + 14)); label.textContent = String(index + 1); svg.append(label);
    drawn += 1;
  });
  stage.append(svg);
  if (drawn < boxes.length) warn(`${boxes.length - drawn} region(s) not drawn: their coordinate system (${coordinateSystem}) could not be mapped exactly.`);
}

function mapBox(box, width, height, coordinateSystem, metadata) {
  let [x1, y1, x2, y2] = box.map(Number);
  if (coordinateSystem === "normalized_0_1") { x1 *= width; x2 *= width; y1 *= height; y2 *= height; }
  else if (coordinateSystem === "normalized_0_1000") { x1 *= width / 1000; x2 *= width / 1000; y1 *= height / 1000; y2 *= height / 1000; }
  else if (coordinateSystem === "resized_pixels") {
    if (!(metadata.coordinate_width > 0 && metadata.coordinate_height > 0)) return null;
    x1 *= width / metadata.coordinate_width; x2 *= width / metadata.coordinate_width; y1 *= height / metadata.coordinate_height; y2 *= height / metadata.coordinate_height;
  } else if (coordinateSystem === "crop_pixels") {
    const bounds = metadata.crop_bounds;
    if (!Array.isArray(bounds) || bounds.length < 4 || !(metadata.coordinate_width > 0 && metadata.coordinate_height > 0)) return null;
    const cropWidth = bounds[2] - bounds[0]; const cropHeight = bounds[3] - bounds[1];
    if (!(cropWidth > 0 && cropHeight > 0)) return null;
    x1 = bounds[0] + x1 * cropWidth / metadata.coordinate_width; x2 = bounds[0] + x2 * cropWidth / metadata.coordinate_width;
    y1 = bounds[1] + y1 * cropHeight / metadata.coordinate_height; y2 = bounds[1] + y2 * cropHeight / metadata.coordinate_height;
  } else if (coordinateSystem === "padded_resized_pixels") {
    if (!(metadata.content_width > 0 && metadata.content_height > 0)) return null;
    x1 = (x1 - (metadata.padding_left || 0)) * width / metadata.content_width; x2 = (x2 - (metadata.padding_left || 0)) * width / metadata.content_width;
    y1 = (y1 - (metadata.padding_top || 0)) * height / metadata.content_height; y2 = (y2 - (metadata.padding_top || 0)) * height / metadata.content_height;
  } else if (coordinateSystem !== "source_pixels") return null;
  x1 = Math.max(0, Math.min(width, x1)); x2 = Math.max(0, Math.min(width, x2)); y1 = Math.max(0, Math.min(height, y1)); y2 = Math.max(0, Math.min(height, y2));
  return x2 > x1 && y2 > y1 ? [x1, y1, x2, y2] : null;
}

async function artifactUrl(artifactId) {
  if (state.artifactUrls.has(artifactId)) return state.artifactUrls.get(artifactId);
  const runId = state.runId;
  const response = await api(`/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`);
  const url = URL.createObjectURL(await response.blob());
  if (runId !== state.runId) { URL.revokeObjectURL(url); throw new Error("Run changed while loading artifact"); }
  state.artifactUrls.set(artifactId, url); return url;
}

function releaseArtifactUrls() { for (const url of state.artifactUrls.values()) URL.revokeObjectURL(url); state.artifactUrls.clear(); }

// ---- Memory ------------------------------------------------------------------------
function renderMemoryTabs() {
  const host = $("#memory-tabs"); host.replaceChildren();
  if (!state.runId) return;
  for (const id of agentIds()) { const button = el("button", state.selectedAgent === id ? "active" : "", id); button.type = "button"; button.addEventListener("click", () => selectAgent(id)); host.append(button); }
}

async function loadMemory(agentId) {
  const host = $("#memory-content"); host.className = "memory-content empty-state"; host.textContent = "Requesting authorized memory…";
  const runId = state.runId;
  try {
    const payload = await (await api(`/api/runs/${encodeURIComponent(runId)}/memory/${encodeURIComponent(agentId)}`)).json();
    if (runId !== state.runId || state.selectedAgent !== agentId) return;
    host.replaceChildren(); host.className = "memory-content";
    const policy = payload.policy || {};
    const banner = el("p", `memory-policy mp-${policy.optional_memory || "unknown"}`);
    banner.append(el("strong", "", agentId === "coordinator" ? "Coordinator run record. " : `Optional memory: ${String(policy.optional_memory || "unknown").toUpperCase()}. `), document.createTextNode(policy.description || ""));
    host.append(banner);
    if (!payload.records?.length) {
      host.append(el("p", "muted", policy.optional_memory === "off"
        ? "No optional memory records exist because the optional notebook was disabled for this run."
        : "No permitted memory records were persisted for this agent."));
      return;
    }
    payload.records.forEach((record, index) => {
      const card = el("article", "memory-card"); card.append(el("strong", "", record.phase ? `Notebook entry ${index + 1} · ${String(record.phase).replaceAll("_", " ")}` : `Memory record ${index + 1}`));
      const dl = el("dl");
      for (const [key, value] of Object.entries(safeValue(record))) { const dt = el("dt", "", key.replaceAll("_", " ")); const dd = el("dd", "", pretty(value, 900)); dl.append(dt, dd); }
      card.append(dl); host.append(card);
    });
  } catch (error) { host.textContent = error.message; toast(`Memory view: ${error.message}`); }
}

// ---- Simple view: team picture and the selected-step card -------------------------------
function renderSimpleTeam(activity, answer) {
  if (!state.simple) return;
  const topology = state.scope === "run" ? state.topology : null;
  if (!topology) {
    state.simple.key = null;
    const host = $("#simple-team");
    if (!host.querySelector(".empty-state")) host.replaceChildren(el("div", "empty-state", state.scope === "configured" ? "Select a run to see who works on it." : "Connect, then select a run."));
    return;
  }
  state.simple.setTopology(topology);
  const events = visibleEvents();
  const now = new Map();
  for (const step of Story.mainSteps(storySteps())) {
    if (!step.agent) continue;
    const text = step.title.replace(/^(Worker \d+|Coordinator)('s)?\s*/, "");
    now.set(step.agent, step.status === "running" ? `Now: ${text.replace(/^is\s+/, "")}` : `Last step: ${text}`);
  }
  const answers = new Map();
  for (const event of events) if (event.event_type === "HYPOTHESIS_UPDATED") answers.set(event.agent_id, String(event.payload?.hypothesis ?? ""));
  const running = new Map();
  for (const open of activity?.open.values() || []) {
    if (open.toolNode && open.kind.startsWith("tool")) running.set(open.agentId, `Using ${Story.toolLabel(open.toolNode.replace(/^tool:/, ""))}`);
    else if (open.kind === "model_request" && !running.has(open.agentId)) running.set(open.agentId, "Thinking");
  }
  const b = budgetSummary().global;
  const selected = state.selectedEventId && isVisible(state.selectedEventId) ? state.eventIndex.get(state.selectedEventId) : null;
  state.simple.update({agents: activity?.agents, now, answers, estimate: answer?.estimate, running,
    traffic: SimpleTeamApi.traffic(events), flow: SimpleTeamApi.activeFlow(selected || latestMeaningful()),
    focusAgent: $("#story-agent").value || null,
    budget: b?.tool_calls ? `Tool budget used: ${b.tool_calls.used} of ${b.tool_calls.limit}` : "Budget —"});
}

function focusStep() {
  if (!state.runId) return null;
  const steps = storySteps();
  if (state.selectedStepId) return steps.find((step) => step.id === state.selectedStepId) || null;
  if (state.selectedEventId) return stepForEvent(state.selectedEventId);
  return Story.mainSteps(steps).at(-1) || null;
}

function focusRows(step) {
  if (step.kind === "tool") {
    const lin = lineage(); const ids = new Set(step.source_event_ids);
    const inv = lin ? [...lin.invocations.values()].find((i) => ids.has(i.requestEventId) || ids.has(i.resultEventId)) : null;
    const input = inv ? lin.images.get(inv.inputKeys[0]) : null;
    const where = input ? (input.kind === "input" ? "the original image" : `the ${input.kind === "crop" ? "zoomed crop" : "image"} made in ${producerText(input) || "an earlier step"}`) : "the image";
    const a = step.arguments || {};
    const tool = Story.toolLabel(step.tool);
    let request;
    if (/zoom/i.test(step.tool || "")) request = `Zoom into a selected region of ${where}.`;
    else if (/ground|detect/i.test(step.tool || "") && a.query) request = `Find “${a.query}” in ${where}.`;
    else request = `${tool}${Object.keys(a).length ? ` (${keyValues(a).replace(/\n/g, "; ")})` : ""}.`;
    const output = inv?.outputKeys?.length ? lin.images.get(inv.outputKeys[0]) : null;
    let result = step.status === "running" ? "Waiting for the tool to return…" : `${tool} ${step.observation || "finished"}.`;
    if (/zoom/i.test(step.tool || "") && output?.width && step.status === "completed") result = `Returned a ${output.width}×${output.height} zoomed image.`;
    const interpretation = step.interpretation?.length ? step.interpretation.map(([k, v]) => `${k}: ${v}`).join(" ") : "Not recorded.";
    return [["Why", step.intent || "Not recorded — the model did not state a reason."], ["Request", request], ["Result", result],
      ["Interpretation", interpretation], ["Next", step.next ? `${agentLabel(step.agent)} ${step.next}.` : step.status === "running" ? "—" : "No later action by this agent yet."]];
  }
  const rows = [["What happened", step.text || step.title]];
  if (step.list?.length) rows.push(["Assignments", step.list.join("\n")]);
  for (const [k, v] of (step.facts || []).slice(0, 3)) rows.push([k, String(v)]);
  if (step.delivery) rows.push(["Sent", step.delivery[0].toUpperCase() + step.delivery.slice(1)]);
  return rows;
}

function renderFocus() {
  const host = $("#focus-flow");
  const step = focusStep();
  const explicit = Boolean(state.selectedStepId || state.selectedEventId);
  $("#focus-mode").textContent = !state.runId || explicit ? "" : state.live ? "Following the latest step" : "Latest step at this replay position";
  $("#clear-event").hidden = !explicit;
  if (!step) {
    $("#focus-title").textContent = state.runId ? "No steps yet" : "Nothing selected yet";
    host.dataset.key = ""; host.replaceChildren(el("li", "empty-state", state.runId ? "Steps appear here as the agents work." : "Select a run, then pick a step on the left."));
    return;
  }
  const key = `${step.id}|${step.source_event_ids.length}|${step.status}|${step.next || ""}`;
  $("#focus-title").textContent = `${step.number ? `Step ${String(step.number).padStart(2, "0")} · ` : ""}${step.title}`;
  if (host.dataset.key === key) return;
  host.dataset.key = key; host.replaceChildren();
  for (const [label, text] of focusRows(step)) {
    const li = el("li", `fl-${label.toLowerCase().replace(/[^a-z]/g, "")}`);
    li.append(el("span", "fl-label", label), el("p", "", text));
    host.append(li);
  }
}

// ---- Visual lineage and the tool-action workspace ---------------------------------------
function lineage() {
  if (!state.runId || !Lineage) return null;
  const count = visibleCount(); const last = state.events[count - 1]?.event_id || null;
  if (state.lineageCache && state.lineageCache.count === count && state.lineageCache.last === last) return state.lineageCache.value;
  const value = Lineage.buildLineage(visibleEvents(), {artifacts: state.snapshot?.artifacts || {}, aliases: state.snapshot?.artifact_aliases || {}});
  state.lineageCache = {count, last, value};
  return value;
}

/** The tool invocation an event belongs to, if it involved recorded images. */
function invocationForEvent(event) {
  const lin = event ? lineage() : null;
  const key = lin?.byEvent.get(event.event_id);
  const inv = key ? lin.invocations.get(key) : null;
  return inv && (inv.inputKeys.length || inv.outputKeys.length) ? inv : null;
}

function stepForInvocation(inv) {
  if (!inv) return null;
  const ids = new Set([inv.requestEventId, inv.resultEventId].filter(Boolean));
  return storySteps().find((step) => step.kind === "tool" && step.source_event_ids.some((id) => ids.has(id))) || null;
}

function imageLabel(node) {
  if (!node) return "image not recorded";
  const size = node.width ? `${node.width}×${node.height}` : "size unknown";
  const kind = {input: "Original image", crop: "Zoom crop", annotation: "Annotated rendering", visualization: "Visualization", output: "Tool output"}[node.kind] || "Image";
  return `${kind} · ${node.registryId} · ${size}`;
}

function producerText(node) {
  const lin = lineage(); const inv = node?.producer ? lin.invocations.get(node.producer) : null;
  const step = stepForInvocation(inv);
  return step ? `step ${step.number ? String(step.number).padStart(2, "0") : "?"} (${Story.toolLabel(inv.tool)})` : null;
}

function hideToolAction() {
  $("#tool-action").classList.add("hidden");
  $("#legacy-viewer").classList.remove("hidden");
}

/** Shapes to draw, with boxes already expressed in the target image's pixels. */
function detectionShapes(inv, transform, prefix = "det") {
  const det = inv.detections; if (!det || !transform) return [];
  return det.boxes.map((box, index) => ({box: Geo.applyBox(transform, box), cls: prefix, index: index + 1,
    label: det.labels?.[index], score: det.scores?.[index]}));
}

function taFigure(title, node, shapes, {placeholder = null, note = null} = {}) {
  const figure = el("figure", "ta-panel");
  const caption = el("figcaption"); caption.append(el("strong", "", title), el("span", "muted", node ? imageLabel(node) : ""));
  figure.append(caption);
  const stageBox = el("div", "ta-stage");
  if (placeholder) { stageBox.classList.add("empty-state"); stageBox.textContent = placeholder; figure.append(stageBox); }
  else if (!node?.artifactId) { stageBox.classList.add("empty-state"); stageBox.textContent = "Visual artifact unavailable."; figure.append(stageBox); }
  else {
    const inner = el("div", "ta-zoom");
    const img = el("img"); img.alt = imageLabel(node); img.dataset.artifact = node.artifactId; img.draggable = false;
    inner.append(img);
    if (node.width && shapes.length) {
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "ta-overlay"); svg.setAttribute("viewBox", `0 0 ${node.width} ${node.height}`); svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
      for (const shape of shapes) {
        const clipped = Geo.clipBox(shape.box, node.width, node.height); if (!clipped) continue;
        if (shape.cls === "det" && !state.ta.boxes) continue;
        const g = document.createElementNS(svg.namespaceURI, "g");
        const selected = shape.index && shape.index === state.ta.selectedBox;
        g.setAttribute("class", `ta-shape ${shape.cls}${selected ? " selected" : ""}`);
        const rect = document.createElementNS(svg.namespaceURI, "rect");
        rect.setAttribute("x", clipped[0]); rect.setAttribute("y", clipped[1]); rect.setAttribute("width", clipped[2] - clipped[0]); rect.setAttribute("height", clipped[3] - clipped[1]);
        rect.dataset.box = clipped.map((v) => v.toFixed(2)).join(",");
        g.append(rect);
        const labels = state.ta.labels === "auto" ? shapes.filter((x) => x.cls === "det").length <= 30 : state.ta.labels;
        const text = [shape.index && (labels || selected) ? String(shape.index) : null, shape.cls === "det" && selected && shape.label ? shape.label : null,
          shape.cls === "det" && (state.ta.scores || selected) && typeof shape.score === "number" ? `score ${shape.score.toFixed(2)}` : null, shape.caption].filter(Boolean).join(" · ");
        if (text) { const t = document.createElementNS(svg.namespaceURI, "text"); t.setAttribute("x", clipped[0] + 2); t.setAttribute("y", Math.max(clipped[1] - 3, 9)); t.textContent = text; g.append(t); }
        if (shape.index) { g.addEventListener("click", (event) => { event.stopPropagation(); state.ta.selectedBox = state.ta.selectedBox === shape.index ? null : shape.index; state.evidenceKey = null; renderAll(); }); }
        svg.append(g);
      }
      inner.append(svg);
    }
    stageBox.append(inner);
    enableStageZoom(stageBox, inner);
    figure.append(stageBox);
  }
  if (note) figure.append(el("p", "ta-note", note));
  return figure;
}

function enableStageZoom(stageBox, inner) {
  let scale = 1; let x = 0; let y = 0; let drag = null;
  const apply = () => { inner.style.transform = `translate(${x}px, ${y}px) scale(${scale})`; stageBox.classList.toggle("zoomed", scale > 1); };
  stageBox.addEventListener("dblclick", (event) => {
    const rect = stageBox.getBoundingClientRect();
    if (scale > 1) { scale = 1; x = 0; y = 0; } else { scale = 2.5; x = -(event.clientX - rect.left) * 1.5; y = -(event.clientY - rect.top) * 1.5; }
    apply();
  });
  stageBox.addEventListener("wheel", (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault(); scale = Math.max(1, Math.min(8, scale * (event.deltaY < 0 ? 1.2 : 1 / 1.2))); if (scale === 1) { x = 0; y = 0; } apply();
  }, {passive: false});
  stageBox.addEventListener("pointerdown", (event) => { if (scale > 1) { drag = {x: event.clientX - x, y: event.clientY - y}; stageBox.setPointerCapture(event.pointerId); } });
  stageBox.addEventListener("pointermove", (event) => { if (drag) { x = event.clientX - drag.x; y = event.clientY - drag.y; apply(); } });
  stageBox.addEventListener("pointerup", () => { drag = null; });
}

async function renderToolAction(inv, selection) {
  const lin = lineage();
  if (state.ta.invocation !== inv.key) { state.ta.invocation = inv.key; state.ta.selectedBox = null; state.ta.view = "boxes"; state.ta.labels = "auto"; }
  const key = `ta|${state.runId}|${inv.key}|${inv.status}|${inv.outputKeys.join(",")}|${JSON.stringify(state.ta)}|${selection?.linkedFrom?.event_id || ""}`;
  if (key === state.evidenceKey) return;
  state.evidenceKey = key;
  const token = ++state.evidenceToken;
  const input = lin.images.get(inv.inputKeys[0]) || null;
  const outputs = inv.outputKeys.map((k) => lin.images.get(k)).filter(Boolean);
  const chain = input && input.kind !== "input" ? lin.chainToRoot(input.key) : null;
  const root = chain?.complete ? lin.images.get(chain.rootKey) : null;
  // Load every image before touching the DOM (a late response must not replace a newer selection).
  const wanted = [input, ...outputs, root].filter((n) => n?.artifactId).map((n) => n.artifactId);
  const urls = new Map();
  for (const id of new Set(wanted)) { try { urls.set(id, await artifactUrl(id)); } catch { /* shown as unavailable */ } }
  if (token !== state.evidenceToken) return;

  const isZoom = /zoom|crop/i.test(inv.tool || ""); const det = inv.detections;
  const step = stepForInvocation(inv);
  const host = $("#tool-action"); host.replaceChildren(); host.classList.remove("hidden");
  $("#legacy-viewer").classList.add("hidden");
  $("#evidence-kind").textContent = `${inv.tool} · ${inv.status}`;
  $("#evidence-kind").className = `status-chip ${inv.status === "failed" ? "failed" : inv.status === "completed" ? "completed" : "idle"}`;

  // Header: what ran, on which image, and how it connects to other steps.
  const head = el("div", "ta-head");
  const source = input ? `${imageLabel(input)}${producerText(input) ? ` — produced by ${producerText(input)}` : ""}` : "input image not recorded";
  head.append(el("strong", "", `${step?.number ? `Step ${String(step.number).padStart(2, "0")} · ` : ""}${Story.toolLabel(inv.tool)} · ${agentLabel(inv.agent)} · ${inv.status}`),
    el("span", "muted", `Input: ${source}`));
  const nav = el("div", "ta-nav");
  const go = (label, targetInv) => { const s2 = stepForInvocation(targetInv); if (!s2) return; const b = el("button", "quiet", label.replace("#", s2.number ? String(s2.number).padStart(2, "0") : "?")); b.type = "button"; b.addEventListener("click", () => selectStep(s2)); nav.append(b); };
  if (input?.producer) go("← Producing step #", lin.invocations.get(input.producer));
  for (const out of outputs) for (const consumer of out.consumers) go("Used by step # →", lin.invocations.get(consumer));
  if (selection?.linkedFrom) nav.append(el("span", "muted", `Shown for: ${selection.linkedFrom.summary || "coordinator answer state"}`));
  head.append(nav);
  host.append(head);

  // Controls (kept small; detection-only options appear only for detections).
  const controls = el("div", "ta-controls");
  const toggle = (name, label) => { const l = el("label", "check"); const c = el("input"); c.type = "checkbox"; c.checked = state.ta[name] === "auto" ? (det?.boxes.length || 0) <= 30 : Boolean(state.ta[name]); c.addEventListener("change", () => { state.ta[name] = c.checked; renderAll(); }); l.append(c, document.createTextNode(` ${label}`)); controls.append(l); };
  if (det) {
    toggle("boxes", "Boxes"); toggle("labels", "Labels"); toggle("scores", "Scores");
    if (outputs.length) {
      const select = el("select"); select.setAttribute("aria-label", "Output view");
      select.append(new Option("Boxes on the processed image", "boxes"), new Option("Tool's rendered image", "rendered")); select.value = state.ta.view;
      select.addEventListener("change", () => { state.ta.view = select.value; renderAll(); }); controls.append(select);
    }
  }
  const full = outputs.find((n) => n.artifactId) || input;
  if (full?.artifactId && urls.get(full.artifactId)) { const a = el("a", "ta-open", "Open full resolution"); a.href = urls.get(full.artifactId); a.target = "_blank"; a.rel = "noopener"; controls.append(a); }
  controls.append(el("span", "muted", "Double-click an image to zoom; drag to pan."));
  host.append(controls);

  // Input and output panels.
  const grid = el("div", "ta-grid");
  const inputShapes = [];
  if (isZoom && inv.roi?.requested) inputShapes.push({box: inv.roi.requested, cls: "roi", caption: "selected region"});
  if (isZoom && inv.roi?.cropBox && inv.roi.verified) inputShapes.push({box: inv.roi.cropBox, cls: "crop", caption: "crop boundary (with padding)"});
  grid.append(taFigure("Actual input", input, inputShapes, {note: !input ? "The tool's input image was not recorded for this call." : null}));
  let outputFigure;
  if (inv.status !== "completed" && inv.status !== "failed") outputFigure = taFigure("Actual output", null, [], {placeholder: "Running — the tool has not returned yet."});
  else if (inv.status === "failed") outputFigure = taFigure("Actual output", null, [], {placeholder: `Failed: ${String(inv.error).slice(0, 200)}. No output was produced.`});
  else if (det && state.ta.view === "boxes") {
    const shapes = det.toInput ? detectionShapes(inv, det.toInput) : [];
    outputFigure = taFigure(`Detections on the processed image (${det.boxes.length})`, input, shapes,
      {note: !det.boxes.length ? "No detections returned." : det.reason || (det.system === "resized_pixels" ? `Boxes reported in a ${det.frameSize.join("×")} frame and scaled to the processed image.` : null)});
  } else if (outputs.length) {
    const out = outputs[0];
    const note = isZoom ? (inv.roi?.verified ? `Crop of input pixels [${inv.roi.cropBox.join(", ")}] (${inv.roi.method === "recorded" ? "recorded by the capability" : "reconstructed with the tool's crop rule"}; verified against the returned ${out.width}×${out.height} crop).`
      : `Crop geometry unverified: ${inv.roi?.reason || "missing transform metadata"}. The crop is shown without alignment.`) : null;
    outputFigure = taFigure(isZoom ? "Actual zoomed image" : "Actual output", out, [], {note});
  } else outputFigure = taFigure("Actual output", null, [], {placeholder: "This tool returned no image; see the structured result below."});
  grid.append(outputFigure);
  host.append(grid);

  // Original context: where the processed image (and its result) sits in the original.
  if (input && input.kind !== "input") {
    if (root && chain.complete) {
      const shapes = [{box: Geo.applyBox(chain.transform, [0, 0, input.width, input.height]), cls: "footprint", caption: `${input.registryId} footprint`}];
      if (isZoom && inv.roi?.cropBox && inv.roi.verified) shapes.push({box: Geo.applyBox(chain.transform, inv.roi.cropBox), cls: "crop", caption: "this crop"});
      if (det?.toInput) shapes.push(...detectionShapes(inv, Geo.then(det.toInput, chain.transform), "det"));
      host.append(taFigure("Original context (mapped through verified transforms)", root, shapes));
    } else host.append(el("p", "ta-note warn", `Original context unavailable: ${chain?.reason || "the lineage is incomplete"}.`));
  }

  // Facts: input, operation, output, and the agent's recorded interpretation (kept distinct).
  const facts = el("dl", "ta-facts");
  const row = (k, v) => { if (v) facts.append(el("dt", "", k), el("dd", "", v)); };
  row("Operation", `${inv.tool}${inv.arguments ? ` · ${keyValues(inv.arguments).replace(/\n/g, " · ")}` : ""}`);
  row("Input source", inv.inputSource === "capability" ? "Recorded by the capability's image resolution" : inv.inputSource === "registry_alias_preview" ? "Requested image (resolved when the call was made)" : inv.inputSource === "argument" ? "Requested image ID (before execution)" : null);
  if (det) {
    row("Result", `${det.boxes.length} detection${det.boxes.length === 1 ? "" : "s"} in ${det.system === "input_pixels" ? "the processed image's pixels" : det.system}`);
    const selected = state.ta.selectedBox ? det.boxes[state.ta.selectedBox - 1] : null;
    if (selected) {
      const mapped = chain?.complete && det.toInput ? Geo.applyBox(Geo.then(det.toInput, chain.transform), selected) : input?.kind === "input" && det.toInput ? Geo.applyBox(det.toInput, selected) : null;
      row(`Box ${state.ta.selectedBox}`, `[${selected.map((v) => Math.round(v)).join(", ")}] in ${input?.registryId}${mapped ? ` → [${mapped.map((v) => Math.round(v)).join(", ")}] in the original` : ""}${typeof det.scores?.[state.ta.selectedBox - 1] === "number" ? ` · model score ${det.scores[state.ta.selectedBox - 1].toFixed(3)} (not a calibrated probability)` : ""}`);
    }
  }
  if (isZoom && inv.roi) row("Crop", inv.roi.verified ? `[${inv.roi.cropBox.join(", ")}] px of ${input?.registryId}, padding ${inv.roi.padding} (0-1000 scale)` : `unverified — ${inv.roi.reason}`);
  for (const note of inv.notes) row("Note", note);
  row("Agent's interpretation", step ? (step.interpretation?.length ? step.interpretation.map(([k, v]) => `${k}: ${v}`).join("\n") : "No interpretation of this result was recorded.") : null);
  row("Next", step?.next ? `${agentLabel(inv.agent)} ${step.next}.` : null);
  host.append(facts);
  for (const img of host.querySelectorAll("img[data-artifact]")) { const url = urls.get(img.dataset.artifact); if (url) img.src = url; else img.closest(".ta-stage")?.replaceChildren(document.createTextNode("Visual artifact unavailable.")); }
}

/** Thumbnails for a story card: input (with ROI or boxes) → output. */
function visualThumbs(step) {
  if (step.kind !== "tool") return null;
  const lin = lineage(); if (!lin) return null;
  const ids = new Set(step.source_event_ids);
  const inv = [...lin.invocations.values()].find((i) => ids.has(i.requestEventId) || ids.has(i.resultEventId));
  if (!inv || !(inv.inputKeys.length || inv.outputKeys.length)) return null;
  const input = lin.images.get(inv.inputKeys[0]); const output = lin.images.get(inv.outputKeys[0]);
  const strip = el("div", "ta-thumbs");
  const thumb = (node, shapes, label) => {
    const box = el("div", "ta-thumb"); box.title = label;
    if (node?.artifactId) {
      const img = el("img"); img.alt = label; img.dataset.thumb = node.artifactId; box.append(img);
      if (node.width && shapes.length) {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.setAttribute("viewBox", `0 0 ${node.width} ${node.height}`); svg.setAttribute("preserveAspectRatio", "xMidYMid meet"); svg.setAttribute("class", "ta-overlay");
        for (const s of shapes) { const c = Geo.clipBox(s.box, node.width, node.height); if (!c) continue; const g = document.createElementNS(svg.namespaceURI, "g"); g.setAttribute("class", `ta-shape ${s.cls}`); const r = document.createElementNS(svg.namespaceURI, "rect"); r.setAttribute("x", c[0]); r.setAttribute("y", c[1]); r.setAttribute("width", c[2] - c[0]); r.setAttribute("height", c[3] - c[1]); g.append(r); svg.append(g); }
        box.append(svg);
      }
    } else box.append(el("span", "muted", node ? "unavailable" : "—"));
    box.append(el("span", "ta-thumb-label", label));
    return box;
  };
  const isZoom = /zoom|crop/i.test(inv.tool || "");
  if (isZoom) {
    strip.append(thumb(input, [inv.roi?.requested && {box: inv.roi.requested, cls: "roi"}, inv.roi?.verified && {box: inv.roi.cropBox, cls: "crop"}].filter(Boolean), `${input?.registryId || "input"} + ROI`), el("span", "ta-arrow", "→"),
      inv.status === "completed" ? thumb(output, [], `${output?.registryId || "crop"}`) : el("span", "muted", inv.status === "failed" ? "failed" : "running…"));
  } else if (inv.detections) {
    strip.append(thumb(input, [], input?.registryId || "input"), el("span", "ta-arrow", "→"),
      thumb(input, inv.detections.toInput ? detectionShapes(inv, inv.detections.toInput) : [], `${inv.detections.boxes.length} box${inv.detections.boxes.length === 1 ? "" : "es"}`));
  } else {
    strip.append(thumb(input, [], input?.registryId || "input"));
    if (output) strip.append(el("span", "ta-arrow", "→"), thumb(output, [], output.registryId));
  }
  return strip;
}

async function hydrateThumbs(host) {
  for (const img of host.querySelectorAll("img[data-thumb]")) {
    try { const url = await artifactUrl(img.dataset.thumb); if (img.isConnected) img.src = url; } catch { /* unavailable */ }
  }
}

// ---- Answer status strip --------------------------------------------------------
const TERMINAL = new Set(["COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"]);
const GT_TEXT = {
  NOT_AVAILABLE: ["—", "No reference label available"], SEALED: ["Sealed", "Ground truth sealed until completion"],
  ACCESS_DENIED: ["Withheld", "Reference access not permitted"], REFERENCE_ERROR: ["Unverified", "Reference could not be verified"],
  LOADING: ["…", "Checking reference status"],
};

/** Fetch the reference status once per (run, terminal state, evaluator credential); never polled. */
async function fetchReference() {
  if (state.scope !== "run" || !state.runId) return;
  const terminal = TERMINAL.has(state.snapshot?.state?.status || state.snapshot?.final?.run_status || "");
  const key = `${state.runId}|${terminal}|${state.evaluatorAccess ? "e" : "v"}`;
  if (key === state.referenceKey || state.referenceLoading) return;
  state.referenceLoading = true;
  const runId = state.runId;
  try {
    const value = await (await api(`/api/runs/${encodeURIComponent(runId)}/reference`, {evaluator: true})).json();
    if (runId === state.runId) { state.reference = value; state.referenceKey = key; }
  } catch (error) {
    if (runId === state.runId) { state.reference = {state: "REFERENCE_ERROR", label: "Reference status unavailable", error: error.message}; state.referenceKey = key; }
  } finally { state.referenceLoading = false; renderAll(); }
}

function renderAnswerStrip(answer) {
  const gtCell = $("#gt-cell"); const estCell = $("#est-cell");
  if (!answer) {
    $("#as-task").textContent = state.scope === "configured" ? "No run selected" : "Connect to inspect a run";
    for (const id of ["#gt-value", "#est-value", "#final-value"]) $(id).textContent = "—";
    $("#gt-note").textContent = "No run selected"; $("#est-note").textContent = "No run selected"; $("#final-note").textContent = "Pending";
    gtCell.dataset.state = "NOT_AVAILABLE"; estCell.dataset.status = "none"; $("#eval-label").className = "eval-label hidden";
    for (const id of ["#as-round", "#as-evidence", "#as-status"]) $(id).textContent = "";
    $("#gt-provenance").replaceChildren();
    return;
  }
  const manifest = state.snapshot?.manifest || {};
  $("#as-task").textContent = manifest.original_task || eventPayload("TASK_RECEIVED", "original_task") || state.runId;
  // Ground truth (released by the backend only post-run to an evaluator).
  const ref = state.reference || {state: "LOADING"};
  gtCell.dataset.state = ref.state;
  const [value, note] = ref.state === "AVAILABLE" ? [ref.value, "Released for evaluation"] : (GT_TEXT[ref.state] || ["—", ref.label || ""]);
  $("#gt-value").textContent = value;
  $("#gt-note").textContent = ref.state === "AVAILABLE" ? `${ref.provenance?.reference_source || "Authorized reference"}` : note;
  const prov = $("#gt-provenance"); prov.replaceChildren();
  const rows = Object.entries(ref.provenance || {}).filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (ref.error) rows.push(["error", ref.error]);
  rows.push(["release policy", "after the run is terminal, evaluator only"]);
  for (const [k, v] of rows) { const row = el("div", "prov-row"); row.append(el("span", "", k.replaceAll("_", " ")), el("span", "", typeof v === "object" ? JSON.stringify(v) : v)); prov.append(row); }
  // Coordinator estimate (recorded answer state at this replay position only).
  const e = answer.estimate;
  estCell.dataset.status = e.status;
  const noValue = e.value === null || e.value === undefined;
  $("#est-value").textContent = noValue ? (e.status === "unresolved" ? "Unresolved" : e.status === "abstained" ? "Abstained" : "No estimate yet") : String(e.value);
  const at = e.sequence !== null && e.sequence !== undefined ? ` · updated at step #${e.sequence}` : "";
  $("#est-note").textContent = e.status === "none"
    ? (answer.mode === "legacy" ? "Provisional estimate history: not recorded (legacy run)" : answer.mode === "final_only" ? "Estimate updates are off for this run; only the final answer is recorded" : "The coordinator has not formed an estimate")
    : `${Answer.statusText(e.status)} · revision ${e.revision}${at}`;
  // Final answer (separate field; never shown before it is recorded in the visible prefix).
  const final = answer.final;
  $("#final-value").textContent = final ? (final.value === null ? "Abstained" : String(final.value)) : "—";
  $("#final-note").textContent = final ? `Recorded at step #${final.sequence}` : "Not recorded at this position";
  const evalLabel = $("#eval-label");
  const evaluation = ref.state === "AVAILABLE" ? ref.evaluation : null;
  if (final && evaluation && evaluation.valid) {
    evalLabel.className = `eval-label ${evaluation.correct ? "correct" : "incorrect"}`;
    evalLabel.textContent = evaluation.correct ? "Evaluation: Correct" : evaluation.parse_failed ? "Evaluation: Incorrect (unparseable)" : `Evaluation: Incorrect (|error| ${evaluation.absolute_error})`;
    evalLabel.title = `Rule: ${evaluation.rule}; parsed prediction ${evaluation.parsed_prediction ?? "none"}; reference ${evaluation.reference}`;
  } else evalLabel.className = "eval-label hidden";
  const kind = answer.roundKind ? ` (${answer.roundKind.replaceAll("_", " ")}${answer.roundOpen ? "" : ", finished"})` : "";
  $("#as-round").textContent = answer.round ? `Investigation: Round ${answer.round}${kind}` : "Investigation: not started";
  $("#as-evidence").textContent = `Evidence received: ${answer.evidenceReceived}`;
  const recorded = state.snapshot?.state?.status;
  const status = state.live && TERMINAL.has(recorded) ? recorded : (answer.runStatus || recorded || "RUNNING");
  $("#as-status").textContent = `Current status: ${status}`;
}

// ---- Run configuration ------------------------------------------------------------
function onOff(value) { return value === true ? "ON" : value === false ? "OFF" : "Unknown (not recorded)"; }

function renderConfig() {
  const chips = $("#config-chips"); const list = $("#cfg-effective");
  const config = state.scope === "run" ? state.snapshot?.effective_config : null;
  const comm = (state.topology?.nodes || []).find((n) => n.id === "comm_bus")?.metadata || {};
  const signature = JSON.stringify([state.runId, config, comm.enabled, comm.peer_to_peer]);
  if (chips.dataset.signature === signature) return;
  chips.dataset.signature = signature;
  chips.replaceChildren(); list.replaceChildren();
  if (state.scope !== "run" || !state.runId) { list.append(el("dt", "", "Run"), el("dd", "", "None selected")); $("#config-summary").textContent = "Effective settings of the selected run and a launcher for new runs"; return; }
  const legacyPeer = typeof comm.enabled === "boolean" ? comm.enabled && comm.peer_to_peer : null;
  const rows = config ? [
    ["Workers", String(config.num_workers)], ["Coordinator", "1 (always on)"],
    ["Optional worker memory", onOff(config.optional_worker_memory_enabled)],
    ["Peer communication", onOff(config.peer_communication_enabled) + (config.peer_communication_enabled && config.num_workers < 2 ? " (no effect: one worker)" : "")],
    ["Coordinator assignment/reporting", `ON (${config.coordinator_reporting_channel?.replaceAll("_", " ") || "message bus"})`],
    ["Execution mode", config.execution_mode],
    ["Coordinator estimates", config.coordinator_estimate_updates?.enabled ? `ON · ≤${config.coordinator_estimate_updates.max_reassessments} extra model call(s) · ${config.coordinator_estimate_updates.trigger.replaceAll("_", " ")}` : "OFF (final answer only)"],
    ["Follow-up rounds", String(config.max_follow_up_rounds ?? 0)],
    ["Budgets", `tools ${config.budgets?.global_tool_calls} · model ${config.budgets?.global_model_requests} · messages ${config.budgets?.global_messages}`],
  ] : [
    ["Workers", String((state.topology?.agents || []).filter((id) => id !== "coordinator").length || "—")],
    ["Optional worker memory", "Unknown (legacy run did not record it)"],
    ["Peer communication", legacyPeer === null ? "Unknown (not recorded)" : `${onOff(legacyPeer)} (from run manifest)`],
    ["Coordinator estimates", "Not recorded (legacy run)"],
  ];
  for (const [k, v] of rows) list.append(el("dt", "", k), el("dd", "", v));
  const chip = (label, value, kind) => { const node = el("span", `cfg-chip ${kind}`); node.append(el("span", "", label), el("strong", "", value)); chips.append(node); };
  const workers = config ? config.num_workers : (state.topology?.agents || []).filter((id) => id !== "coordinator").length;
  chip("Workers", String(workers || "—"), "neutral");
  const mem = config ? config.optional_worker_memory_enabled : null;
  chip("Memory", mem === null ? "?" : mem ? "● On" : "○ Off", mem === null ? "unknown" : mem ? "on" : "off");
  const peer = config ? config.peer_communication_enabled : legacyPeer;
  chip("Peer comm.", peer === null ? "?" : peer ? "● On" : "○ Off", peer === null ? "unknown" : peer ? "on" : "off");
  chip("Coord. reporting", "● On", "on");
  if (config) chip("Estimates", config.coordinator_estimate_updates?.enabled ? "● On" : "○ Off", config.coordinator_estimate_updates?.enabled ? "on" : "off");
  $("#config-summary").textContent = config ? `${workers} worker(s) · memory ${onOff(mem)} · peer ${onOff(peer)} · ${config.execution_mode}` : "Legacy run: some settings were not recorded";
}

function planCommand() {
  const p = state.plan;
  const env = [`STUDIO_NUM_AGENTS=${p.workers}`, `STUDIO_WORKER_MEMORY=${p.memory}`, `STUDIO_PEER_COMMUNICATION=${p.peer}`,
    `STUDIO_EXECUTION_MODE=${p.mode}`, `STUDIO_ESTIMATE_UPDATES=${p.estimates}`];
  if ($("#plan-target").value === "fixture") return `${env.join(" ")} \\\n  ./scripts/run_studio_demo.sh`;
  const row = Math.max(0, Number($("#plan-row").value) || 0);
  return `${env.join(" ")} \\\n  ./scripts/run_studio_dataset_task.sh FSC147_val ${row}`;
}

function renderPlan() {
  for (const [id, key] of [["#plan-workers", "workers"], ["#plan-memory", "memory"], ["#plan-peer", "peer"], ["#plan-mode", "mode"], ["#plan-estimates", "estimates"]]) {
    for (const button of $$(`${id} button`)) button.setAttribute("aria-checked", String(button.dataset.value === state.plan[key]));
  }
  $("#plan-row").hidden = $("#plan-target").value !== "dataset";
  $("#plan-command").textContent = planCommand();
  $("#plan-note").textContent = $("#plan-target").value === "dataset"
    ? "Runs real model inference through the approved runner; the browser cannot start it. Ground truth stays sealed from the agents."
    : "Deterministic test fixture: scripted policy and tools, no model servers. Not model performance.";
}

function setupPlanner() {
  for (const [id, key] of [["#plan-workers", "workers"], ["#plan-memory", "memory"], ["#plan-peer", "peer"], ["#plan-mode", "mode"], ["#plan-estimates", "estimates"]]) {
    for (const button of $$(`${id} button`)) button.addEventListener("click", () => { state.plan[key] = button.dataset.value; renderPlan(); });
  }
  $("#plan-target").addEventListener("change", renderPlan);
  $("#plan-row").addEventListener("input", renderPlan);
  $("#plan-copy").addEventListener("click", async () => {
    const text = planCommand().replace(" \\\n  ", " ");
    try { await navigator.clipboard.writeText(text); toast("Launch command copied."); }
    catch { const range = document.createRange(); range.selectNodeContents($("#plan-command")); const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range); toast("Select-all applied; copy with Ctrl/⌘+C."); }
  });
  renderPlan();
}

// ---- Compact team view --------------------------------------------------------------
function latestByAgent() {
  const map = new Map();
  for (const event of visibleEvents()) {
    if (!event.activity) continue;
    const agent = event.agent_id;
    if (agent === "coordinator" || /^worker_\d+$/.test(agent)) {
      if (state.technical) { map.set(agent, event); continue; }
      const step = stepForEvent(event.event_id);
      if (step && step.level !== "divider") {
        const shown = representative(step) || event;
        // The card's activity line reads as the story step, not a raw event summary.
        map.set(agent, {...shown, activity: {...(shown.activity || {}), label: step.title}});
      }
    }
  }
  return map;
}

function budgetSummary() {
  const limits = (state.topology?.nodes || []).find((n) => n.id === "budget")?.metadata?.limits || {};
  const result = {}; const actors = new Map();
  for (const key of ["tool_calls", "model_requests", "messages"]) if (limits[key] !== undefined && limits[key] !== null) result[key] = {used: 0, limit: limits[key]};
  for (const event of visibleEvents()) {
    if (event.event_type !== "BUDGET_UPDATED") continue;
    const p = event.payload || {};
    if (result[p.resource] && typeof p.global_remaining === "number") result[p.resource].used = result[p.resource].limit - p.global_remaining;
    if (typeof p.actor_remaining === "number") { const entry = actors.get(event.agent_id) || {}; entry[p.resource] = p.actor_remaining; actors.set(event.agent_id, entry); }
  }
  return {global: result, actors};
}

function renderTeam(activity, answer) {
  if (!state.team || state.viewMode !== "team") return;
  const topology = state.scope === "run" ? state.topology : state.displayTopology;
  if (!topology) return;
  state.team.setTopology(topology, state.scope === "run" ? state.snapshot?.effective_config || null : null);
  const selected = state.selectedEventId && isVisible(state.selectedEventId) ? state.eventIndex.get(state.selectedEventId) : null;
  const budget = state.scope === "run" ? budgetSummary() : {global: null, actors: new Map()};
  state.team.update({activity: state.scope === "run" ? activity : null, latest: state.scope === "run" ? latestMeaningful() : null, selected, technical: state.technical, lastByAgent: state.scope === "run" ? latestByAgent() : new Map(),
    answer, budget: budget.global, actorBudget: budget.actors});
}

function setViewMode(mode) {
  state.viewMode = mode;
  const team = mode === "team";
  $("#team-view").classList.toggle("hidden", !team);
  $("#agent-graph").classList.toggle("hidden", team);
  document.querySelector(".architecture-panel").classList.toggle("team-mode", team);
  if (!team) state.graph.setOptions({mode});
  for (const button of $$("[data-graph-mode]")) button.setAttribute("aria-checked", String(button.dataset.graphMode === mode));
  if (!team && state.graph.layout) state.graph.fit();
  savePrefs();
  renderAll();
}

// ---- Investigation story ------------------------------------------------------------
function detailRows(step) {
  const rows = [];
  if (step.kind === "tool") {
    rows.push(["Why", step.intent || "Action rationale was not recorded."]);
    rows.push(["Tool", `${Story.toolLabel(step.tool)} (${step.tool || "unknown"})`]);
    const lin = lineage(); const ids = new Set(step.source_event_ids);
    const inv = lin ? [...lin.invocations.values()].find((i) => ids.has(i.requestEventId) || ids.has(i.resultEventId)) : null;
    if (inv && (inv.inputKeys.length || inv.outputKeys.length)) {
      const input = lin.images.get(inv.inputKeys[0]);
      rows.push(["Input image", input ? `${imageLabel(input)}${producerText(input) ? ` — output of ${producerText(input)}` : ""}` : "not recorded"]);
      if (inv.outputKeys.length) rows.push(["Output image", inv.outputKeys.map((k) => imageLabel(lin.images.get(k))).join("\n")]);
    }
    if (step.arguments) rows.push(["Input", keyValues(step.arguments)]);
    rows.push(["Result", step.status === "running" ? "Waiting for the tool to return." : (step.observation || "No result recorded.")]);
    rows.push(["Agent's assessment", step.interpretation.length ? step.interpretation.map(([k, v]) => `${k}: ${v}`).join("\n") : "No interpretation of this result was recorded."]);
  } else if (step.interpretation?.length) rows.push(["Agent's assessment", step.interpretation.map(([k, v]) => `${k}: ${v}`).join("\n")]);
  for (const [k, v] of step.facts || []) rows.push([k, String(v)]);
  if (step.list?.length) rows.push(["Assignments", step.list.join("\n")]);
  if (step.delivery) rows.push(["Communication", step.delivery[0].toUpperCase() + step.delivery.slice(1)]);
  if (step.memory?.length) rows.push(["Memory", [...new Set(step.memory)].join("; ")]);
  if (step.next) rows.push(["Next", `${agentLabel(step.agent)} ${step.next}.`]);
  const related = (step.related_step_ids || []).map((id) => storySteps().find((s) => s.id === id)).filter(Boolean);
  if (related.length) rows.push(["Related", related.map((r) => `${r.number ? `#${r.number} ` : ""}${r.title}`).join("\n")]);
  return rows;
}

function openTrace(step) {
  state.traceFilter = {ids: new Set(step.source_event_ids), label: `${step.number ? `Step ${step.number}: ` : ""}${step.title}`};
  setTab("log");
}

function renderStory() {
  const host = $("#story-list");
  if (!state.runId) { host.className = "story-list empty-state"; host.replaceChildren(el("li", "", state.scope === "configured" ? "Select a run to read its investigation story." : "No run selected.")); $("#story-count").textContent = ""; return; }
  const steps = storySteps();
  const agent = $("#story-agent").value;
  const showMinor = $("#story-minor").checked;
  const select = $("#story-agent");
  const ids = agentIds(); const signature = ids.join("|");
  if (select.dataset.signature !== signature) { const current = select.value; select.replaceChildren(new Option("All agents", "")); for (const id of ids) select.append(new Option(agentLabel(id), id)); select.dataset.signature = signature; select.value = current; }
  const visible = steps.filter((step) => (step.level === "main" || (step.level === "minor" && showMinor) || (step.level === "divider" && !agent)) && (!agent || step.agent === agent));
  const mainCount = visible.filter((step) => step.level === "main").length;
  const fingerprint = steps.map((step) => `${step.id}:${step.source_event_ids.length}:${step.status}:${step.next || ""}`).join("|");
  const key = `${state.runId}|${fingerprint}|${agent}|${showMinor}|${state.selectedStepId}|${[...state.linkedSteps].join(",")}|${[...state.expandedSteps].join(",")}`;
  if (host.dataset.key === key) return;
  host.dataset.key = key;
  host.replaceChildren(); host.className = "story-list";
  $("#story-count").textContent = `${mainCount} step${mainCount === 1 ? "" : "s"} · ${visibleCount()} raw events`;
  if (!visible.length) { host.className = "story-list empty-state"; host.append(el("li", "", "No story steps at this position.")); return; }
  for (const step of visible) {
    if (step.level === "divider") {
      const divider = el("li", "story-divider"); divider.append(el("span", "", step.title), el("span", "muted", step.text || ""));
      host.append(divider); continue;
    }
    const item = el("li", `story-step kind-${step.kind} outcome-${step.outcome} status-${step.status}${step.minor ? " minor" : ""}${step.id === state.selectedStepId ? " selected" : ""}${state.linkedSteps.has(step.id) ? " linked" : ""}`);
    item.dataset.step = step.id; item.dataset.agent = step.agent;
    const head = el("div", "story-head");
    head.append(el("span", "story-number", step.number ? String(step.number).padStart(2, "0") : "·"));
    head.append(el("span", `story-agent a-${step.agent === "coordinator" ? "coordinator" : /^worker/.test(step.agent) ? "worker" : "run"}`, agentLabel(step.agent)));
    const title = el("button", "story-title", step.title); title.type = "button";
    head.append(title);
    if (step.outcomeText) head.append(el("span", `outcome-tag o-${step.outcome}`, step.outcomeText));
    item.append(head);
    if (step.text) item.append(el("p", "story-text", step.text));
    const thumbs = visualThumbs(step);
    if (thumbs) item.append(thumbs);
    if (step.delivery) item.append(el("p", "story-meta", step.delivery[0].toUpperCase() + step.delivery.slice(1)));
    const details = el("details", "story-details");
    details.open = state.expandedSteps.has(step.id);
    details.append(el("summary", "", "Details"));
    const dl = el("dl");
    for (const [k, v] of detailRows(step)) dl.append(el("dt", "", k), el("dd", "", v));
    details.append(dl);
    const trace = el("button", "trace-link quiet", `View underlying events (${step.source_event_ids.length})`); trace.type = "button";
    trace.addEventListener("click", (event) => { event.stopPropagation(); openTrace(step); });
    details.append(trace);
    details.addEventListener("toggle", () => { if (details.open) state.expandedSteps.add(step.id); else state.expandedSteps.delete(step.id); });
    item.append(details);
    title.addEventListener("click", () => selectStep(step));
    item.addEventListener("click", (event) => { if (!event.target.closest("details")) selectStep(step); });
    host.append(item);
  }
  host.querySelector(".story-step.selected")?.scrollIntoView({block: "nearest"});
  hydrateThumbs(host);
}

function selectStep(step) {
  state.selectedStepId = step.id;
  state.linkedSteps = Story.linkedSteps(step, storySteps());
  selectEvent(step.primaryEventId, {keepStep: true});
}

/** For an estimate/assessment selection, show the linked tool evidence (recorded references only). */
function evidenceSelection(selected) {
  if (!selected || !["COORDINATOR_ESTIMATE_UPDATED", "COORDINATOR_REASSESSMENT_RECORDED"].includes(selected.event_type)) return selected;
  const steps = storySteps();
  const step = steps.find((s) => s.eventIds.includes(selected.event_id));
  if (!step) return selected;
  const linked = Story.linkedSteps(step, steps);
  const tool = [...steps].reverse().find((s) => linked.has(s.id) && s.kind === "tool" && s.resultEventId && state.eventIndex.get(s.resultEventId)?.event_type === "TOOL_CALL_COMPLETED");
  if (!tool) return selected;
  const event = state.eventIndex.get(tool.resultEventId);
  return event ? {...event, linkedFrom: selected} : selected;
}

// ---- Estimate history ----------------------------------------------------------------
function renderEstimateHistory(answer) {
  const host = $("#estimate-history");
  const chip = $("#final-status");
  const node = $("#final-answer");
  const row = $("#candidate-row");
  if (!answer) {
    host.className = "estimate-history empty-state"; host.replaceChildren(el("li", "", "No run selected."));
    node.className = "final-answer empty-state"; node.textContent = "The coordinator has not recorded a final answer."; row.replaceChildren();
    return;
  }
  const status = answer.runStatus || "RUNNING";
  chip.textContent = TERMINAL.has(status) ? status : "Pending";
  chip.className = `status-chip ${status === "COMPLETED" ? "completed" : status === "FAILED" ? "failed" : "idle"}`;
  const key = `${answer.history.map((h) => h.eventId).join(",")}|${answer.mode}|${state.selectedEventId}|${answer.final?.eventId}`;
  if (host.dataset.key !== key) {
    host.dataset.key = key; host.replaceChildren(); host.className = "estimate-history";
    host.append(el("li", "eh-start", answer.mode === "legacy" ? "Provisional estimate history: not recorded (legacy run)" : answer.mode === "final_only" ? "Estimate updates were off; only the final state is recorded" : "No estimate"));
    for (const entry of answer.history) {
      const item = el("li", `eh-entry s-${entry.status}${entry.eventId === state.selectedEventId ? " selected" : ""}`);
      item.tabIndex = 0;
      const value = entry.value === null ? (entry.status === "unresolved" ? "Unresolved" : "—") : String(entry.value);
      item.append(el("strong", "", value), el("span", "eh-desc", Answer.describeEntry(entry)), el("span", "eh-meta", `r${entry.revision} · step #${entry.sequence}`));
      if (entry.reason || entry.summary) item.append(el("p", "", entry.reason || entry.summary));
      const choose = () => { const step = storySteps().find((s) => s.eventIds.includes(entry.eventId)); if (step) selectStep(step); else selectEvent(entry.eventId); };
      item.addEventListener("click", choose);
      item.addEventListener("keydown", (event) => { if (event.key === "Enter") choose(); });
      host.append(item);
    }
  }
  const final = answer.final;
  node.textContent = final ? `Final answer: ${final.value === null ? "abstained" : pretty(final.value, 2000)}` : "The coordinator has not recorded a final answer at this replay position.";
  node.className = final ? "final-answer" : "final-answer empty-state";
  row.replaceChildren();
  const reports = new Map();
  for (const event of visibleEvents().filter((e) => e.event_type === "HYPOTHESIS_UPDATED")) {
    const p = event.payload || {}; const prior = reports.get(event.agent_id);
    reports.set(event.agent_id, {value: p.hypothesis, first: prior ? prior.first : p.hypothesis, revised: (prior?.revised || 0) + (p.revision_kind === "revised" ? 1 : 0), limitation: p.uncertainty || null});
  }
  for (const [agent, r] of [...reports].sort(([a], [b]) => a.localeCompare(b))) {
    const card = el("article", "report-card");
    const head = el("header"); head.append(el("span", "st-badge", SimpleTeamApi ? SimpleTeamApi.badge(agent) : ""), el("b", "", agentLabel(agent)));
    card.append(head, el("strong", "report-answer", pretty(r.value, 60)));
    if (r.revised) card.append(el("p", "report-note", `Changed from ${pretty(r.first, 30)} after checking`));
    if (r.limitation) card.append(el("p", "report-note muted", `Said: ${pretty(r.limitation, 140)}`));
    row.append(card);
  }
  if (!reports.size) row.append(el("span", "muted", "No worker has answered at this position."));
}

// ---- Bootstrapping --------------------------------------------------------------------
async function bootstrapFragment() {
  const params = new URLSearchParams(location.hash.slice(1));
  const token = params.get("token"); const ticket = params.get("ticket");
  state.pendingRun = params.get("run");
  state.pendingEvent = params.get("event");
  // Remove credentials from the address bar and history immediately; keep only the run.
  history.replaceState(null, "", `${location.pathname}${location.search}${state.pendingRun ? `#${new URLSearchParams({run: state.pendingRun})}` : ""}`);
  showScope("preview");
  setConnection("Not connected", "idle");
  if (!(await checkBackend())) return;
  // A new ticket sets browser scope exactly, clearing any prior evaluator cookie for
  // a viewer-only link. Reloads and bare URLs reuse the existing browser session;
  // older header credentials remain a fallback.
  const remembered = rememberedSession();
  const explicit = Boolean(token || ticket);
  state.evaluatorToken = explicit ? null : (remembered.evaluator || null);
  const redeemed = ticket ? await redeemTicket(ticket) : false;
  return connect(token || (redeemed ? "" : remembered.viewer) || "");
}

function setupTheme() {
  const sync = () => { const choice = Theme.preference(); for (const button of $$("[data-theme-choice]")) button.setAttribute("aria-checked", String(button.dataset.themeChoice === choice)); };
  for (const button of $$("[data-theme-choice]")) button.addEventListener("click", () => { Theme.setPreference(button.dataset.themeChoice); sync(); });
  Theme.watchSystem(() => sync());
  sync();
}

function setupGraph() {
  state.graph = new window.StudioGraph.ArchitectureGraph($("#agent-graph"), {
    onSelectNode: selectNode, onSelectEdge: selectEdge,
    onBackground: () => { if (state.selectedNode || state.selectedEdge) { state.selectedNode = null; state.selectedEdge = null; renderAll(); } },
    onLayoutChange: () => renderAll(),
  });
  const prefs = loadPrefs();
  if (window.StudioParsec) {
    state.parsec = new window.StudioParsec.ParsecView($("#parsec-view"), {
      onEvidence: (eventId) => { if (isVisible(eventId)) { selectEvent(eventId); document.querySelector(".evidence-panel")?.scrollIntoView({block: "nearest"}); } },
      loadExperiments: () => api("/api/parsec/experiments").then((response) => response.json()),
    });
  }
  state.simple = new SimpleTeamApi.SimpleTeam($("#simple-team"), {
    onAgent: (id) => { const select = $("#story-agent"); select.value = select.value === id ? "" : id; renderAll(); },
    onTool: (agent, tool) => { openStepForNode(`tool:${String(tool).replace(/[^A-Za-z0-9_.-]/g, "_").slice(0, 96)}`, agent); renderAll(); },
  });
  state.team = new window.StudioTeam.TeamView($("#team-view"), {
    onSelectNode: (id, agentId) => { state.selectedNode = null; selectNode(id, agentId); },
    onMemory: (id) => { state.selectedAgent = id; renderMemoryTabs(); loadMemory(id); document.querySelector(".memory-panel").scrollIntoView({behavior: "smooth", block: "nearest"}); },
    onPeer: (id) => { setTab("log"); $("#agent-filter").value = id; $("#category-filter").value = "message"; state.selectedAgent = id; renderAll(); },
    onShowFull: (id) => { setViewMode("full"); state.graph.setAllCollapsed(false); state.graph.focusNodes([id, `${id}.harness`, `${id}.model_client`, `${id}.memory`, `${id}.tool_router`]); state.selectedNode = id; renderAll(); },
    onLayoutChange: () => renderAll(),
  });
  state.viewMode = ["team", "full", "live"].includes(prefs.viewMode) ? prefs.viewMode : "team";
  state.technical = prefs.technical === true;
  state.graph.options.technical = state.technical;
  $("#toggle-technical").checked = state.technical;
  $("#toggle-technical").addEventListener("change", (event) => { state.technical = event.target.checked; state.graph.setOptions({technical: state.technical}); state.pulseQueue = []; savePrefs(); renderAll(); });
  Object.assign(state.graph.options, {
    mode: prefs.mode === "live" ? "live" : "full",
    showMemory: prefs.showMemory !== false, showMemoryFlows: prefs.showMemoryFlows !== false, showInfra: Boolean(prefs.showInfra),
    animate: Theme.animationPreference(),
  });
  $("#toggle-memory-nodes").checked = state.graph.options.showMemory;
  $("#toggle-memory-flows").checked = state.graph.options.showMemoryFlows;
  $("#toggle-infra").checked = state.graph.options.showInfra;
  $("#toggle-animation").checked = state.graph.options.animate;
  for (const button of $$("[data-graph-mode]")) button.addEventListener("click", () => setViewMode(button.dataset.graphMode));
  setViewMode(state.viewMode);
  const toggle = (id, key, after) => $(id).addEventListener("change", (event) => { state.graph.setOptions({[key]: event.target.checked}); after?.(event.target.checked); savePrefs(); renderAll(); });
  toggle("#toggle-memory-nodes", "showMemory");
  toggle("#toggle-memory-flows", "showMemoryFlows");
  toggle("#toggle-infra", "showInfra");
  toggle("#toggle-animation", "animate", (value) => Theme.setAnimation(value));
  $("#graph-zoom-in").addEventListener("click", () => state.graph.zoom(1.25));
  $("#graph-zoom-out").addEventListener("click", () => state.graph.zoom(1 / 1.25));
  $("#graph-fit").addEventListener("click", () => state.graph.fit());
  $("#graph-expand").addEventListener("click", () => state.graph.setAllCollapsed(false));
  $("#graph-collapse").addEventListener("click", () => state.graph.setAllCollapsed(true));
  $("#graph-focus-activity").addEventListener("click", () => {
    const activity = state.activityCache?.state; if (!activity) return;
    const latest = state.events[visibleCount() - 1];
    const ids = [...new Set([...[...activity.open.values()].flatMap((open) => [...open.nodes, open.toolNode]), ...(latest?.activity?.nodes || [])].filter(Boolean))];
    if (!state.graph.focusNodes(ids)) toast("No current activity to focus.");
  });
  $("#graph-focus-selection").addEventListener("click", () => {
    const selected = state.selectedEventId && isVisible(state.selectedEventId) ? state.eventIndex.get(state.selectedEventId) : null;
    const edge = state.topology?.edges.find((e) => e.id === state.selectedEdge);
    const ids = state.selectedNode ? [state.selectedNode] : edge ? [edge.source, edge.target] : selected?.activity?.nodes || [];
    if (!state.graph.focusNodes(ids)) toast("Select a component, connection, or event first.");
  });
}

$("#run-select").addEventListener("change", (event) => { state.pendingRun = null; loadRun(event.target.value); });
$("#agent-filter").addEventListener("change", (event) => { state.selectedAgent = event.target.value; renderAll(); });
$("#type-filter").addEventListener("change", renderTimeline);
$("#category-filter").addEventListener("change", renderTimeline);
$("#failure-filter").addEventListener("change", renderTimeline);
$("#clear-event").addEventListener("click", () => { state.selectedEventId = null; state.selectedNode = null; state.selectedEdge = null; state.selectedStepId = null; state.linkedSteps = new Set(); renderAll(); });
function setTab(tab) {
  state.tab = tab;
  for (const other of $$("[data-tab]")) { const on = other.dataset.tab === tab; other.setAttribute("aria-selected", String(on)); other.setAttribute("aria-checked", String(on)); }
  $("#story-view").classList.toggle("hidden", tab !== "story"); $("#log-view").classList.toggle("hidden", tab !== "log");
  if (tab === "story") state.traceFilter = null;
  renderAll();
}
for (const button of $$("[data-tab]")) button.addEventListener("click", () => setTab(button.dataset.tab));
$("#story-agent").addEventListener("change", renderAll);
$("#trace-filter-clear").addEventListener("click", () => { state.traceFilter = null; renderAll(); });
$("#story-minor").addEventListener("change", renderAll);
$("#est-history-toggle").addEventListener("click", () => $("#estimate-history-panel").scrollIntoView({behavior: "smooth", block: "center"}));
const syncTopbar = () => {
  const top = document.querySelector(".topbar"); const strip = $("#answer-strip");
  document.documentElement.style.setProperty("--topbar-height", `${getComputedStyle(top).position === "sticky" ? top.offsetHeight : 0}px`);
  document.documentElement.style.setProperty("--strip-height", `${getComputedStyle(strip).position === "sticky" ? strip.offsetHeight : 0}px`);
};
if (window.ResizeObserver) { const observer = new ResizeObserver(syncTopbar); observer.observe(document.querySelector(".topbar")); observer.observe($("#answer-strip")); }
window.addEventListener("resize", syncTopbar); syncTopbar();
$("#replay-slider").addEventListener("input", (event) => setReplayIndex(Number(event.target.value)));
$("#replay-start").addEventListener("click", () => setReplayIndex(0));
$("#replay-prev").addEventListener("click", () => setReplayIndex(visibleCount() - 1));
$("#replay-next").addEventListener("click", () => setReplayIndex(visibleCount() + 1));
$("#replay-play").addEventListener("click", toggleReplay);
$("#go-live").addEventListener("click", goLive);
document.addEventListener("keydown", (event) => { if (["INPUT", "SELECT", "BUTTON", "SUMMARY"].includes(event.target.tagName) || event.target.closest?.(".node, .group-toggle")) return; if (event.key === "ArrowLeft") setReplayIndex(visibleCount() - 1); if (event.key === "ArrowRight") setReplayIndex(visibleCount() + 1); if (event.key === " ") { event.preventDefault(); toggleReplay(); } });
window.addEventListener("beforeunload", () => { stopStream(); releaseArtifactUrls(); });
window.setInterval(updateElapsed, 1000);
setupTheme();
setupGraph();
setupPlanner();
bootstrapFragment();
// Opening another Studio link in an already-open tab changes only the #fragment (no page
// load), so react to it: a new ticket, token, or run in the fragment is applied here.
window.addEventListener("hashchange", () => {
  const params = new URLSearchParams(location.hash.slice(1));
  if (params.has("ticket") || params.has("token") || (params.get("run") && params.get("run") !== state.runId)) bootstrapFragment();
});
// New runs appear in the run menu on their own while this page is open and signed in.
window.setInterval(() => {
  if (state.connected && !document.hidden) {
    refreshRunList().then(() => {
      if (!state.runId && !state.pendingRun && state.runs.length) loadRun(state.runs[0].run_id);
    }).catch(() => { /* transient */ });
  }
}, 5000);
