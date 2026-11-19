"use strict";
/*
 * PARSEC-VL view: parallel execution Gantt timeline, plan/dependency DAG,
 * speculation, budget and resource monitor, and recorded-experiment comparison.
 *
 * buildModel(events) is a pure fold over the visible event prefix (replay-safe:
 * nothing after the replay position exists for it). Task intervals come from
 * SCHEDULER_TASK_STARTED/FINISHED records, all measured on the run's single
 * scheduler clock (monotonic seconds); other events are placed on that clock
 * through the wall-clock anchor (start_wall - start_time) of a recorded task.
 * Nothing is inferred from tool-call order: DAG edges come from declared plan
 * dependencies only.
 */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.StudioParsec = api;
})(typeof self !== "undefined" ? self : this, function (root) {
  const NO_DATA = "No PARSEC-VL planning or scheduler data was recorded for this run.";
  const toolShort = (name) => String(name || "task").replace(/_Tool$/, "").replace(/_/g, " ");
  const agentName = (id) => (id === "coordinator" ? "Coordinator" : /^worker_(\d+)$/.test(id || "") ? `Worker ${Number(id.slice(7))}` : id || "—");
  const wall = (iso) => (iso ? Date.parse(iso) / 1000 : null);

  function buildModel(events) {
    const tasks = new Map();
    const plans = new Map();
    const toolEvent = new Map();      // invocation id -> event id (completed preferred)
    const budget = [];
    const pools = [];
    const modelOpen = new Map();      // request id -> {agent, wall}
    const modelCalls = [];
    let offset = null, lastWall = null, config = null, scheduler = null, planning = null;
    const planOf = (id) => {
      if (!plans.has(id)) plans.set(id, {plan_id: id, plan: null, agent: null, eventId: null, decision: null, evaluations: [],
        replans: [], adopted: new Set(), speculative: new Set(), pruned: new Set(), cancelRequested: new Set(), execution: null});
      return plans.get(id);
    };
    for (const e of events) {
      const p = e.payload || {};
      const t = wall(e.timestamp);
      if (t !== null) lastWall = lastWall === null ? t : Math.max(lastWall, t);
      switch (e.event_type) {
        case "RUN_CONFIGURATION_RECORDED": config = p.effective_config || null; break;
        case "SCHEDULER_CONFIGURED": scheduler = p; break;
        case "PLANNING_CONFIGURED": planning = p; break;
        case "PLANNING_POOL_STARTED": pools.push({wall: t, seconds: p.startup_seconds, processes: p.processes, eventId: e.event_id}); break;
        case "SCHEDULER_TASK_STARTED": case "SCHEDULER_TASK_FINISHED": {
          const finished = e.event_type === "SCHEDULER_TASK_FINISHED";
          const prior = tasks.get(p.task_id) || {};
          tasks.set(p.task_id, {...prior, ...p, finished, eventId: e.event_id});
          if (offset === null && p.start_wall && typeof p.start_time === "number") offset = wall(p.start_wall) - p.start_time;
          break;
        }
        case "PLAN_CANDIDATES_GENERATED": {
          const entry = planOf(p.plan?.plan_id);
          Object.assign(entry, {plan: p.plan, agent: e.agent_id, eventId: e.event_id, mode: p.mode});
          break;
        }
        case "PLAN_SELECTED": Object.assign(planOf(p.plan_id), {decision: p.decision, lead: p.lead_branch, selectedEventId: e.event_id}); break;
        case "PLAN_EVALUATION_STARTED": case "PLAN_EVALUATION_COMPLETED": case "PLAN_EVALUATION_SKIPPED":
          planOf(p.plan_id).evaluations.push({...p, kind: e.event_type, wall: t, eventId: e.event_id}); break;
        case "SPECULATIVE_TASK_ADMITTED": planOf(p.plan_id).speculative.add(p.task_id); break;
        case "SPECULATIVE_TASK_PRUNED": case "PLAN_TASK_PRUNED": planOf(p.plan_id).pruned.add(p.task_id); break;
        case "SPECULATIVE_TASK_CANCEL_REQUESTED": planOf(p.plan_id).cancelRequested.add(p.task_id); break;
        case "SPECULATIVE_RESULT_ADOPTED": planOf(p.plan_id).adopted.add(p.branch_id); break;
        case "REPLAN_TRIGGERED": case "REPLAN_COMPLETED": planOf(p.plan_id).replans.push({...p, kind: e.event_type}); break;
        case "PLAN_EXECUTION_COMPLETED": planOf(p.plan_id).execution = p; break;
        case "MODEL_REQUEST_STARTED": modelOpen.set(p.request_id, {agent: e.agent_id, wall: t, eventId: e.event_id}); break;
        case "MODEL_RESPONSE_RECEIVED": case "MODEL_REQUEST_FAILED": {
          const begin = modelOpen.get(p.request_id);
          if (begin) {
            modelOpen.delete(p.request_id);
            // End = response timestamp; start = end - recorded monotonic latency (falls back to the start event).
            const start = typeof p.latency_seconds === "number" ? t - p.latency_seconds : begin.wall;
            modelCalls.push({agent: begin.agent, startWall: start, endWall: t, ok: e.event_type === "MODEL_RESPONSE_RECEIVED", eventId: e.event_id});
          }
          break;
        }
        case "BUDGET_UPDATED":
          if (p.resource === "tool_calls") budget.push({wall: t, granted: p.granted, released: Boolean(p.released), amount: p.amount || 1,
            remaining: p.global_remaining, agent: e.agent_id});
          break;
        case "TOOL_CALL_REQUESTED": case "TOOL_CALL_COMPLETED": case "TOOL_CALL_FAILED":
          if (p.invocation_id && (e.event_type !== "TOOL_CALL_REQUESTED" || !toolEvent.has(p.invocation_id))) toolEvent.set(p.invocation_id, e.event_id);
          break;
        default: break;
      }
    }
    const toSched = (w) => (offset === null || w === null ? null : w - offset);
    const now = toSched(lastWall);
    // Branch statuses: the plan as proposed, updated by the final record once execution completed.
    for (const entry of plans.values()) {
      if (!entry.plan || !entry.execution?.branches) continue;
      const final = new Map(entry.execution.branches.map((b) => [b.branch_id, b]));
      entry.plan = {...entry.plan, branches: entry.plan.branches.map((b) => ({...b, ...(final.get(b.branch_id) ? {status: final.get(b.branch_id).status,
        pruning_reason: final.get(b.branch_id).pruning_reason} : {})}))};
    }
    const list = [...tasks.values()].map((t) => {
      const meta = t.metadata || {};
      const entry = meta.plan_id ? plans.get(meta.plan_id) : null;
      const speculative = Boolean(meta.speculative);
      const adopted = Boolean(entry && meta.branch_id && entry.adopted.has(meta.branch_id));
      const started = typeof t.start_time === "number";
      const running = started && !t.finished;
      const done = entry?.execution || null;
      const prunedBranch = done && speculative && !adopted;
      let state = running ? "running" : String(t.status || "").toLowerCase();
      if (entry?.cancelRequested.has(t.task_id)) state = t.finished ? "cancel-requested (ran, unused)" : "cancel-requested";
      else if (entry?.pruned.has(t.task_id) || (t.status === "CANCELLED" && !started)) state = "pruned";
      else if (prunedBranch && t.status === "COMPLETED") state = "completed, unused";
      return {
        id: t.task_id, agent: t.agent_id, operation: t.operation, pool: t.resource_pool, slot: t.worker_id,
        enqueue: t.enqueue_time ?? t.created_time ?? null, start: started ? t.start_time : null,
        // A running bar ends at "now" (the latest visible event on the scheduler clock), never at its future finish.
        // Event timestamps and scheduler anchors can differ by microseconds, so it never ends before its own start.
        end: started ? (t.finished ? (t.finish_time ?? null) : Math.max(t.start_time, now ?? t.start_time)) : (t.finish_time ?? null), open: running,
        status: t.status, state, speculative, adopted, budget: t.budget_used || 0, failure: t.failure_reason,
        plan: meta.plan_id || null, branch: meta.branch_id || null, action: meta.action_id || null,
        invocation: meta.logical_request_id || meta.invocation_id || null,
        evidenceEvent: toolEvent.get(meta.logical_request_id || meta.invocation_id) || null, eventId: t.eventId,
      };
    }).sort((a, b) => (a.enqueue ?? a.start ?? 0) - (b.enqueue ?? b.start ?? 0));
    const evaluations = [];
    for (const entry of plans.values()) {
      const open = [];
      for (const ev of entry.evaluations) {
        if (ev.kind === "PLAN_EVALUATION_STARTED") open.push(ev);
        else if (ev.kind === "PLAN_EVALUATION_COMPLETED") {
          const begin = open.shift();
          const end = toSched(ev.wall);
          const span = typeof ev.wall_seconds === "number" ? ev.wall_seconds : null;
          evaluations.push({plan: entry.plan_id, agent: entry.agent, purpose: ev.purpose, processes: ev.processes,
            start: begin ? toSched(begin.wall) : (end !== null && span !== null ? end - span : null), end,
            seconds: span, backend: begin?.gate?.backend || (ev.processes ? "parallel" : "sequential"), complete: ev.complete, eventId: ev.eventId});
        }
      }
      for (const ev of open) evaluations.push({plan: entry.plan_id, agent: entry.agent, purpose: ev.purpose, processes: ev.processes,
        start: toSched(ev.wall), end: now, open: true, backend: ev.gate?.backend, eventId: ev.eventId});
    }
    // Budget: limit from the recorded configuration, used = limit - last reported remaining.
    const limit = config?.budgets?.global_tool_calls ?? null;
    const last = budget.filter((b) => typeof b.remaining === "number").at(-1);
    const used = limit !== null && last ? limit - last.remaining : null;
    const spent = list.filter((t) => t.start !== null).reduce((s, t) => s + (t.budget || 0), 0);
    const speculativeTasks = list.filter((t) => t.speculative);
    const summary = {
      limit, used, spent, reservedNotStarted: used !== null ? Math.max(0, used - spent) : null,
      available: limit !== null && used !== null ? limit - used : null,
      speculativeCharged: speculativeTasks.reduce((s, t) => s + (t.start !== null ? t.budget || 1 : 0), 0),
      unusedCharged: list.filter((t) => t.speculative && !t.adopted && t.start !== null && t.state !== "running").length,
      cancelledBeforeStart: list.filter((t) => t.start === null && (t.state === "pruned" || t.status === "CANCELLED")).length,
      denied: list.filter((t) => String(t.failure || "").startsWith("budget_denied")).length,
      logical: list.length, physical: list.filter((t) => t.start !== null).length,
      grants: budget.filter((b) => b.granted && !b.released).length, releases: budget.filter((b) => b.released).length,
      rejections: budget.filter((b) => !b.granted).length,
    };
    const budgetSeries = [];
    if (limit !== null) for (const b of budget) if (typeof b.remaining === "number") budgetSeries.push({t: toSched(b.wall), used: limit - b.remaining});
    return {
      available: tasks.size > 0 || plans.size > 0 || Boolean(scheduler), message: NO_DATA, tasks: list,
      plans: [...plans.values()].filter((p) => p.plan), evaluations, pools: pools.map((p) => ({...p, start: toSched(p.wall)})),
      model: [...modelCalls.map((m) => ({...m, start: toSched(m.startWall), end: toSched(m.endWall)})),
        ...[...modelOpen.values()].map((m) => ({agent: m.agent, start: toSched(m.wall), end: now, open: true, eventId: m.eventId}))]
        .filter((m) => m.start !== null),
      budget: summary, budgetSeries, now, offset, config, scheduler, planning,
      capacities: scheduler?.capacities || {}, policy: config?.tool_scheduler?.policy || scheduler?.policy || null,
    };
  }

  // ---- derived views ----------------------------------------------------------------------
  function lanes(model, mode) {
    const groups = new Map();
    const add = (key, label, task) => { if (!groups.has(key)) groups.set(key, {key, label, rows: []}); place(groups.get(key), task); };
    const place = (group, task) => {  // interval packing: each row holds non-overlapping executions
      const from = task.start ?? task.enqueue ?? 0;
      const row = group.rows.find((r) => r.every((o) => (o.end ?? Infinity) <= from + 1e-9 || (o.start ?? o.enqueue ?? 0) >= (task.end ?? Infinity) - 1e-9));
      if (row) row.push(task); else group.rows.push([task]);
    };
    for (const task of model.tasks) {
      if (mode === "pool") add(`pool:${task.pool}`, `${task.pool}${model.capacities[task.pool] ? ` (capacity ${model.capacities[task.pool]})` : ""}`, task);
      else if (mode === "agent") add(`agent:${task.agent}`, agentName(task.agent), task);
      else add(`slot:${task.slot ?? "queued"}`, task.slot === null || task.slot === undefined ? "not dispatched" : `scheduler slot ${task.slot}`, task);
    }
    const ordered = [...groups.values()].sort((a, b) => a.label.localeCompare(b.label, undefined, {numeric: true}));
    if (model.model.length && model.tasks.length) {
      const group = {key: "model", label: "model service", rows: [], planning: true};
      for (const m of model.model) {
        const item = {...m, kind: "model", label: `model · ${agentName(m.agent)}`};
        const row = group.rows.find((r) => r.every((o) => (o.end ?? Infinity) <= item.start || o.start >= (item.end ?? Infinity)));
        if (row) row.push(item); else group.rows.push([item]);
      }
      ordered.push(group);
    }
    if (model.evaluations.length || model.pools.length) {
      const group = {key: "planning", label: "planning (CPU)", rows: [], planning: true};
      for (const ev of [...model.pools.map((p) => ({kind: "pool", start: p.start, end: p.start !== null ? p.start + (p.seconds || 0) : null,
        label: `pool start ${p.processes}p`, eventId: p.eventId})), ...model.evaluations.map((e) => ({...e, kind: "evaluation",
        label: `${e.purpose} · ${e.backend || "?"}${e.processes ? ` ${e.processes}p` : ""}`}))]) {
        const row = group.rows.find((r) => r.every((o) => (o.end ?? Infinity) <= (ev.start ?? 0) || (o.start ?? 0) >= (ev.end ?? Infinity)));
        if (row) row.push(ev); else group.rows.push([ev]);
      }
      ordered.push(group);
    }
    return ordered;
  }

  function planGraph(entry, tasks) {
    const nodes = [], edges = [];
    if (!entry?.plan) return {nodes, edges};
    const byAction = new Map(tasks.filter((t) => t.plan === entry.plan_id).map((t) => [t.action, t]));
    let column = 0;
    entry.plan.branches.forEach((branch) => {
      const depth = new Map();
      const level = (a) => {
        if (!depth.has(a.id)) depth.set(a.id, 1 + Math.max(0, ...a.depends_on.map((d) => level(branch.actions.find((x) => x.id === d) || {id: d, depends_on: []}))));
        return depth.get(a.id);
      };
      const perLevel = new Map();
      for (const action of branch.actions) perLevel.set(level(action), (perLevel.get(level(action)) || 0) + 1);
      const width = Math.max(1, ...perLevel.values());
      const used = new Map();
      for (const action of branch.actions) {
        const task = byAction.get(action.id) || null;
        const state = task ? task.state : branch.status === "pruned" ? "never started" : "not started";
        const row = level(action);
        const slot = used.get(row) || 0;
        used.set(row, slot + 1);
        nodes.push({id: `${branch.branch_id}:${action.id}`, action: action.id, tool: action.tool, branch: branch.name,
          branchStatus: branch.status, origin: branch.origin_type, column: column + slot, branchColumn: column, branchWidth: width, row, task, state,
          goal: branch.goal === action.id, speculative: Boolean(task?.speculative)});
        for (const dep of action.depends_on) edges.push({from: `${branch.branch_id}:${dep}`, to: `${branch.branch_id}:${action.id}`});
        if (!action.depends_on.length) edges.push({from: "input", to: `${branch.branch_id}:${action.id}`});
      }
      column += width;
    });
    return {nodes, edges};
  }

  function criticalPath(entry, tasks) {
    const {nodes, edges} = planGraph(entry, tasks);
    const dur = (n) => (n.task && n.task.start !== null && n.task.end !== null ? n.task.end - n.task.start : 0);
    const memo = new Map();
    const best = (id) => {
      if (memo.has(id)) return memo.get(id);
      const node = nodes.find((n) => n.id === id);
      const next = edges.filter((e) => e.from === id).map((e) => best(e.to));
      const tail = next.reduce((a, b) => (b.length > a.length ? b : a), {length: 0, ids: []});
      const value = {length: (node ? dur(node) : 0) + tail.length, ids: node ? [id, ...tail.ids] : tail.ids};
      memo.set(id, value);
      return value;
    };
    return new Set(best("input").ids);
  }

  function originLabel(entry, branch) {
    const origin = branch?.origin_type || entry.plan?.origin_type;
    if (origin === "controller_heuristic") return "Controller heuristic";
    if (origin === "fixture") return "Scripted fixture";
    if (origin === "model") return entry.plan?.estimates?.proposer === "scripted fixture policy" ? "Scripted policy (fixture)" : "Model-generated";
    return origin || "unknown";
  }

  function decisionText(entry) {
    const d = entry.decision || {};
    const lines = [];
    if (d.selection) lines.push(`Lead branch: ${d.selection.lead} (${d.selection.method.replace("_", " ")}).`);
    const spec = d.speculation;
    if (spec) {
      if (!spec.chosen?.length) lines.push(`No speculation (${spec.policy}).`);
      else if (spec.policy === "S1") lines.push(`Fixed-width policy S1 started ${spec.chosen.join(", ")} early.`);
      else lines.push(`Selective policy S2 started ${spec.chosen.join(", ")} early (${spec.method?.replace("_", " ")}).`);
      for (const [branch, terms] of Object.entries(spec.terms || {})) {
        if (terms.rejected) lines.push(`${branch}: not started (${terms.rejected}).`);
        else if ("score" in terms) lines.push(`${branch}: expected score ${terms.score} with speculation vs ${terms.baseline_score} without (latency + weighted tool calls).`);
        else if ("gain" in terms) lines.push(`${branch}: expected hidden latency ${terms.gain} vs expected waste ${terms.loss} (q=${terms.q}).`);
      }
    }
    for (const ev of entry.evaluations) if (ev.kind === "PLAN_EVALUATION_SKIPPED") lines.push(`Simulation skipped for ${ev.purpose}: ${ev.reason}.`);
    for (const r of entry.replans) if (r.kind === "REPLAN_COMPLETED") lines.push(`Replanned after a failed branch → ${r.next_branch} (${r.method}${r.was_speculative ? ", already running speculatively" : ""}).`);
    return lines;
  }

  function predictedVsObserved(entry, tasks) {
    const completed = entry.evaluations.filter((e) => e.kind === "PLAN_EVALUATION_COMPLETED" && e.estimates?.length);
    const exec = entry.execution;
    if (!exec) return null;
    const mine = tasks.filter((t) => t.plan === entry.plan_id);
    const chosen = completed.length ? completed.at(-1).estimates[0] : null;
    return {
      predicted: chosen ? {latency: chosen.latency_mean, calls: chosen.cost_mean, p: chosen.p_operational, source: completed.at(-1).outcome_model} : null,
      observed: {latency: exec.decision_latency_s, calls: mine.filter((t) => t.start !== null).length, satisfied: exec.satisfied, winner: exec.winning_branch},
    };
  }

  // ---- rendering --------------------------------------------------------------------------
  const SVG = "http://www.w3.org/2000/svg";
  function h(tag, cls, text) { const n = root.document.createElement(tag); if (cls) n.className = cls; if (text !== undefined && text !== null) n.textContent = String(text); return n; }
  function s(tag, attrs = {}, text) { const n = root.document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) n.setAttribute(k, v); if (text !== undefined) n.textContent = text; return n; }
  const fmt = (x, d = 3) => (x === null || x === undefined || Number.isNaN(x) ? "—" : Number(x).toFixed(d));

  class ParsecView {
    constructor(host, handlers = {}) {
      this.host = host; this.handlers = handlers; this.tab = "timeline"; this.mode = "slot";
      this.view = null; this.selected = null; this.showCritical = true; this.planIndex = -1; this.experiments = null;
    }

    update(model) {
      this.model = model;
      this.render();
    }

    setTab(tab) { this.tab = tab; this.render(); }

    render() {
      const model = this.model;
      const host = this.host;
      host.replaceChildren();
      const tabs = h("div", "pv-tabs");
      for (const [key, label] of [["timeline", "Timeline"], ["plans", "Plan & DAG"], ["budget", "Budget & resources"], ["compare", "Compare"]]) {
        const b = h("button", `pv-tab${this.tab === key ? " active" : ""}`, label); b.type = "button"; b.dataset.tab = key;
        b.addEventListener("click", () => this.setTab(key));
        tabs.append(b);
      }
      host.append(tabs);
      const body = h("div", `pv-body pv-${this.tab}`);
      host.append(body);
      if (this.tab === "compare") return this.renderCompare(body);
      if (!model || !model.available) { body.append(h("p", "pv-empty", model ? model.message : "Select a run.")); return; }
      if (this.tab === "timeline") this.renderTimeline(body);
      else if (this.tab === "plans") this.renderPlans(body);
      else this.renderBudget(body);
    }

    // -- timeline --
    renderTimeline(body) {
      const model = this.model;
      const bar = h("div", "pv-controls");
      for (const [key, label] of [["slot", "Scheduler slots"], ["pool", "Resource pools"], ["agent", "Agents"]]) {
        const b = h("button", `quiet pv-mode${this.mode === key ? " active" : ""}`, label); b.type = "button"; b.dataset.mode = key;
        b.addEventListener("click", () => { this.mode = key; this.render(); });
        bar.append(b);
      }
      const fit = h("button", "quiet", "Fit"); fit.type = "button"; fit.addEventListener("click", () => { this.view = null; this.render(); });
      const crit = h("label", "pv-check"); const box = h("input"); box.type = "checkbox"; box.checked = this.showCritical;
      box.addEventListener("change", () => { this.showCritical = box.checked; this.render(); }); crit.append(box, " critical path");
      bar.append(fit, crit, h("span", "pv-legend", "▮ executing   ▯ queued   ▨ speculative   ◻ adopted   ░ unused / cancelled"));
      body.append(bar);
      const groups = lanes(model, this.mode);
      const times = [];
      for (const t of model.tasks) for (const x of [t.enqueue, t.start, t.end]) if (typeof x === "number") times.push(x);
      for (const e of model.evaluations) for (const x of [e.start, e.end]) if (typeof x === "number") times.push(x);
      if (typeof model.now === "number") times.push(model.now);
      if (!times.length) { body.append(h("p", "pv-empty", "Tasks are queued; no execution interval has been recorded yet.")); return; }
      const lo = Math.min(...times), hi = Math.max(...times, lo + 1e-3);
      const [v0, v1] = this.view || [lo, hi];
      const rows = groups.reduce((n, g) => n + Math.max(1, g.rows.length), 0);
      const W = Math.max(480, this.host.clientWidth - 24), L = 150, R = 12, rowH = 22, top = 22;
      const H = top + rows * rowH + 22;
      const x = (t) => L + ((t - v0) / Math.max(1e-9, v1 - v0)) * (W - L - R);
      const svg = s("svg", {class: "pv-gantt", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
        "aria-label": `Execution timeline, ${model.tasks.length} scheduler tasks`});
      const defs = s("defs");
      const pattern = s("pattern", {id: "pv-hatch", patternUnits: "userSpaceOnUse", width: 6, height: 6, patternTransform: "rotate(45)"});
      pattern.append(s("rect", {width: 6, height: 6, class: "pv-hatch-bg"}), s("line", {x1: 0, y1: 0, x2: 0, y2: 6, class: "pv-hatch-line"}));
      defs.append(pattern); svg.append(defs);
      // axis
      const span = v1 - v0; const step = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 30, 60].find((s_) => span / s_ <= 10) || 60;
      for (let t = Math.ceil(v0 / step) * step; t <= v1 + 1e-9; t += step) {
        svg.append(s("line", {x1: x(t), x2: x(t), y1: top - 4, y2: H - 18, class: "pv-grid"}), s("text", {x: x(t), y: 12, class: "pv-tick", "text-anchor": "middle"}, `${t.toFixed(step < 0.1 ? 2 : 1)}s`));
      }
      const critical = this.showCritical ? new Set(model.plans.flatMap((p) => [...criticalPath(p, model.tasks)])) : new Set();
      const related = this.relatedIds();
      let y = top;
      for (const group of groups) {
        svg.append(s("text", {x: 6, y: y + 15, class: `pv-lane${group.planning ? " planning" : ""}`}, group.label));
        const rowsHere = Math.max(1, group.rows.length);
        group.rows.forEach((row, r) => {
          for (const item of row) this.drawItem(svg, item, x, y + r * rowH, rowH, group.planning, critical, related);
        });
        svg.append(s("line", {x1: 0, x2: W, y1: y + rowsHere * rowH, y2: y + rowsHere * rowH, class: "pv-sep"}));
        y += rowsHere * rowH;
      }
      if (typeof model.now === "number" && model.tasks.some((t) => t.open)) {
        svg.append(s("line", {x1: x(model.now), x2: x(model.now), y1: top - 4, y2: H - 18, class: "pv-now"}), s("text", {x: x(model.now) + 3, y: H - 6, class: "pv-tick"}, "now"));
      }
      svg.addEventListener("wheel", (ev) => {
        ev.preventDefault();
        const box = svg.getBoundingClientRect(); const at = v0 + ((ev.clientX - box.left) * (W / box.width) - L) / (W - L - R) * (v1 - v0);
        const k = ev.deltaY > 0 ? 1.25 : 0.8; this.view = [at - (at - v0) * k, at + (v1 - at) * k]; this.render();
      }, {passive: false});
      let drag = null;
      svg.addEventListener("pointerdown", (ev) => { if (ev.target.closest(".pv-task")) return; drag = {x: ev.clientX, view: [v0, v1]}; });
      svg.addEventListener("pointerup", (ev) => {
        if (!drag) return; const box = svg.getBoundingClientRect(); const dt = -(ev.clientX - drag.x) * (W / box.width) / (W - L - R) * (drag.view[1] - drag.view[0]);
        drag = null; if (Math.abs(dt) > 1e-6) { this.view = [v0 + dt, v1 + dt]; this.render(); }
      });
      const wrap = h("div", "pv-gantt-wrap"); wrap.append(svg); body.append(wrap);
      body.append(this.detailCard());
    }

    drawItem(svg, item, x, y, rowH, planning, critical, related) {
      if (planning) {
        if (typeof item.start !== "number") return;
        const end = typeof item.end === "number" ? item.end : item.start;
        const g = s("g", {class: `pv-plan-bar${item.kind === "model" ? " model" : ""}${item.open ? " open" : ""}`});
        g.append(s("rect", {x: x(item.start), y: y + 4, width: Math.max(2, x(end) - x(item.start)), height: rowH - 8, rx: 3}));
        g.append(s("title", {}, `${item.label}${item.seconds ? ` · ${item.seconds.toFixed(3)} s` : ""}`));
        if (x(end) - x(item.start) > 70) g.append(s("text", {x: x(item.start) + 4, y: y + rowH / 2 + 4, class: "pv-bar-label"}, item.label));
        svg.append(g);
        return;
      }
      const task = item;
      const g = s("g", {class: ["pv-task", `st-${task.state.replace(/[^a-z]+/g, "-")}`, task.speculative ? "spec" : "", task.adopted ? "adopted" : "",
        critical.has(`${task.branch}:${task.action}`) ? "critical" : "", this.selected === task.id ? "selected" : "",
        related.has(task.id) ? "related" : ""].filter(Boolean).join(" "), "data-task": task.id, tabindex: 0});
      if (typeof task.enqueue === "number" && typeof task.start === "number" && task.start - task.enqueue > 0) {
        g.append(s("rect", {x: x(task.enqueue), y: y + rowH / 2 - 2, width: Math.max(1, x(task.start) - x(task.enqueue)), height: 4, class: "pv-queue"}));
      } else if (typeof task.enqueue === "number" && task.start === null) {
        g.append(s("rect", {x: x(task.enqueue), y: y + rowH / 2 - 2, width: 6, height: 4, class: "pv-queue"}));
      }
      if (typeof task.start === "number") {
        const end = typeof task.end === "number" ? task.end : task.start;
        const w = Math.max(2, x(end) - x(task.start));
        g.append(s("rect", {x: x(task.start), y: y + 3, width: w, height: rowH - 6, rx: 3, class: "pv-exec"}));
        if (task.speculative) g.append(s("rect", {x: x(task.start), y: y + 3, width: w, height: rowH - 6, rx: 3, class: "pv-spec-overlay", fill: "url(#pv-hatch)"}));
        if (w > 46) g.append(s("text", {x: x(task.start) + 4, y: y + rowH / 2 + 4, class: "pv-bar-label"}, `${toolShort(task.operation)}${task.open ? " …" : ""}`));
      }
      g.append(s("title", {}, `${toolShort(task.operation)} · ${agentName(task.agent)} · ${task.pool} · ${task.state}${typeof task.start === "number" && typeof task.end === "number" ? ` · ${(task.end - task.start).toFixed(3)} s` : ""}`));
      g.addEventListener("click", () => this.select(task.id));
      g.addEventListener("keydown", (ev) => { if (ev.key === "Enter") this.select(task.id); });
      svg.append(g);
    }

    relatedIds() {
      const ids = new Set();
      const task = this.model?.tasks.find((t) => t.id === this.selected);
      if (!task || !task.plan) return ids;
      const entry = this.model.plans.find((p) => p.plan_id === task.plan);
      const {edges} = planGraph(entry, this.model.tasks);
      const key = `${task.branch}:${task.action}`;
      const linked = new Set(edges.filter((e) => e.from === key || e.to === key).flatMap((e) => [e.from, e.to]));
      for (const t of this.model.tasks) if (linked.has(`${t.branch}:${t.action}`) && t.id !== task.id) ids.add(t.id);
      return ids;
    }

    select(taskId, force = false) {
      this.selected = !force && this.selected === taskId ? null : taskId;
      const task = this.model.tasks.find((t) => t.id === taskId);
      if (task?.plan) this.planIndex = this.model.plans.findIndex((p) => p.plan_id === task.plan);
      this.render();
      if (this.selected && task?.evidenceEvent && this.handlers.onEvidence) this.handlers.onEvidence(task.evidenceEvent);
    }

    detailCard() {
      const card = h("div", "pv-detail");
      const task = this.model.tasks.find((t) => t.id === this.selected);
      if (!task) { card.append(h("p", "muted", "Select a bar to see its interval, queue wait, resource, and evidence.")); return card; }
      const dl = h("dl");
      const rows = [["Operation", toolShort(task.operation)], ["Agent", agentName(task.agent)], ["Resource pool", task.pool],
        ["Scheduler slot", task.slot ?? "—"], ["Queued", `${fmt(task.enqueue)} s`], ["Started", task.start === null ? "not started" : `${fmt(task.start)} s`],
        ["Finished", task.open ? "running" : task.end === null ? "—" : `${fmt(task.end)} s`],
        ["Queue wait", task.start !== null && task.enqueue !== null ? `${fmt(task.start - task.enqueue)} s` : "—"],
        ["Execution", task.start !== null && task.end !== null ? `${fmt(task.end - task.start)} s${task.open ? " so far" : ""}` : "—"],
        ["State", task.state], ["Speculative", task.speculative ? (task.adopted ? "yes — adopted" : "yes") : "no"],
        ["Plan / branch / action", task.plan ? `${task.plan.split(".").at(-1)} / ${String(task.branch).split(".").at(-1)} / ${task.action}` : "—"],
        ["Budget charged", task.budget], ["Scheduler task", task.id]];
      if (task.failure) rows.push(["Failure", task.failure]);
      for (const [k, v] of rows) dl.append(h("dt", "", k), h("dd", "", v));
      card.append(dl);
      if (task.evidenceEvent && this.handlers.onEvidence) {
        const b = h("button", "quiet pv-evidence", "Show tool evidence"); b.type = "button";
        b.addEventListener("click", () => this.handlers.onEvidence(task.evidenceEvent));
        card.append(b);
      } else if (task.speculative && !task.adopted) card.append(h("p", "muted", "Speculative result not adopted: it never entered the agent's evidence."));
      return card;
    }

    // -- plans and DAG --
    renderPlans(body) {
      const plans = this.model.plans;
      if (!plans.length) { body.append(h("p", "pv-empty", "No action plan was proposed in this run (scheduler data only).")); return; }
      const index = this.planIndex >= 0 && this.planIndex < plans.length ? this.planIndex : plans.length - 1;
      const entry = plans[index];
      const pick = h("div", "pv-controls");
      plans.forEach((p, i) => {
        const b = h("button", `quiet pv-plan-pick${i === index ? " active" : ""}`, `${agentName(p.agent)} · ${p.plan_id.split(".").at(-1)}`); b.type = "button";
        b.addEventListener("click", () => { this.planIndex = i; this.render(); });
        pick.append(b);
      });
      body.append(pick);
      const grid = h("div", "pv-plan-grid");
      const left = h("div", "pv-dag-wrap"); left.append(this.renderDag(entry));
      const right = h("div", "pv-plan-info");
      right.append(h("h3", "", entry.plan.objective || "Action plan"));
      const badges = h("div", "pv-badges");
      for (const b of entry.plan.branches) {
        const tag = h("span", `pv-badge branch-${b.status}`, `${b.name}: ${b.status}${b.pruning_reason ? ` (${b.pruning_reason})` : ""}`);
        tag.title = originLabel(entry, b);
        badges.append(tag);
      }
      right.append(badges);
      right.append(h("p", "pv-origin", `Origin: ${[...new Set(entry.plan.branches.map((b) => originLabel(entry, b)))].join(" + ")}`));
      if (entry.plan.estimates?.inferred_dependencies) right.append(h("p", "muted", `Dependencies added from "$id" references: ${entry.plan.estimates.inferred_dependencies.map((d) => `${d.action} after ${d.depends_on.join(", ")}`).join("; ")}.`));
      const decision = decisionText(entry);
      if (decision.length) { const ul = h("ul", "pv-decision"); for (const line of decision) ul.append(h("li", "", line)); right.append(ul); }
      const pvo = predictedVsObserved(entry, this.model.tasks);
      if (pvo) {
        const table = h("table", "pv-table"); const head = h("tr"); for (const c of ["", "Predicted (Monte Carlo)", "Observed"]) head.append(h("th", "", c)); table.append(head);
        const rows = [["Latency", pvo.predicted ? `${fmt(pvo.predicted.latency)} s` : "not simulated", `${fmt(pvo.observed.latency)} s`],
          ["Tool calls", pvo.predicted ? fmt(pvo.predicted.calls, 2) : "—", pvo.observed.calls],
          ["Operational goal", pvo.predicted ? `p = ${fmt(pvo.predicted.p, 2)}` : "—", pvo.observed.satisfied ? `reached (${pvo.observed.winner})` : "not reached"]];
        for (const r of rows) { const tr = h("tr"); for (const c of r) tr.append(h("td", "", c)); table.append(tr); }
        right.append(table);
        right.append(h("p", "muted", `Predictions use the ${pvo.predicted?.source || "declared"} outcome model; they estimate an operational condition, not answer correctness.`));
      } else right.append(h("p", "muted", "Execution in progress."));
      grid.append(left, right); body.append(grid);
    }

    renderDag(entry) {
      const {nodes, edges} = planGraph(entry, this.model.tasks);
      const critical = this.showCritical ? criticalPath(entry, this.model.tasks) : new Set();
      const columns = Math.max(1, ...nodes.map((n) => n.column + 1));
      const rows = Math.max(1, ...nodes.map((n) => n.row));
      const colW = 190, rowH = 66, W = columns * colW + 20, H = (rows + 1) * rowH + 30;
      const pos = new Map([["input", {x: W / 2, y: 24}]]);
      for (const n of nodes) pos.set(n.id, {x: 20 + n.column * colW + colW / 2 - 10, y: 24 + n.row * rowH});
      const svg = s("svg", {class: "pv-dag", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": `Plan DAG with ${nodes.length} actions`});
      for (const e of edges) {
        const a = pos.get(e.from), b = pos.get(e.to); if (!a || !b) continue;
        svg.append(s("path", {d: `M ${a.x} ${a.y + 14} C ${a.x} ${(a.y + b.y) / 2}, ${b.x} ${(a.y + b.y) / 2}, ${b.x} ${b.y - 16}`,
          class: `pv-edge${critical.has(e.from) && critical.has(e.to) ? " critical" : ""}${e.from === "input" ? " input" : ""}`}));
      }
      const input = s("g", {class: "pv-node input"}); input.append(s("rect", {x: W / 2 - 55, y: 10, width: 110, height: 28, rx: 14}), s("text", {x: W / 2, y: 28, "text-anchor": "middle"}, "input image"));
      svg.append(input);
      for (const b of entry.plan.branches) {
        const mine = nodes.filter((n) => n.branch === b.name);
        if (!mine.length) continue;
        const left = Math.min(...mine.map((n) => pos.get(n.id).x)), right = Math.max(...mine.map((n) => pos.get(n.id).x));
        svg.append(s("text", {x: (left + right) / 2, y: H - 8, "text-anchor": "middle", class: `pv-branch-label branch-${b.status}`}, `${b.name} (${b.status})`));
      }
      for (const n of nodes) {
        const p = pos.get(n.id);
        const g = s("g", {class: ["pv-node", `st-${String(n.state).replace(/[^a-z]+/g, "-")}`, n.speculative ? "spec" : "", n.goal ? "goal" : "",
          critical.has(n.id) ? "critical" : "", n.task && n.task.id === this.selected ? "selected" : ""].filter(Boolean).join(" "), "data-action": n.action, tabindex: 0});
        g.append(s("rect", {x: p.x - 78, y: p.y - 16, width: 156, height: 34, rx: 6}));
        g.append(s("text", {x: p.x, y: p.y - 2, "text-anchor": "middle", class: "pv-node-title"}, `${n.action} · ${toolShort(n.tool)}`));
        g.append(s("text", {x: p.x, y: p.y + 12, "text-anchor": "middle", class: "pv-node-state"}, `${n.state}${n.goal ? " · goal" : ""}`));
        g.append(s("title", {}, `${n.branch}/${n.action}: ${n.tool} — ${n.state}`));
        g.addEventListener("click", () => { if (n.task) { this.tab = "timeline"; this.select(n.task.id, true); } });
        svg.append(g);
      }
      return svg;
    }

    // -- budget and resources --
    renderBudget(body) {
      const m = this.model, b = m.budget;
      const cards = h("div", "pv-cards");
      const card = (label, value, note) => { const c = h("div", "pv-card"); c.append(h("span", "pv-card-label", label), h("strong", "", value ?? "—")); if (note) c.append(h("small", "muted", note)); cards.append(c); };
      card("Tool budget", b.limit === null ? "—" : `${b.used ?? 0} / ${b.limit}`, "used (spent + reserved) / limit");
      card("Spent", b.spent, "charged at dispatch, non-refundable");
      card("Reserved, not started", b.reservedNotStarted ?? "—");
      card("Available", b.available ?? "—");
      card("Speculative charged", b.speculativeCharged, `${b.unusedCharged} unused (still charged)`);
      card("Cancelled before start", b.cancelledBeforeStart, "reservation released");
      card("Logical vs physical", `${b.logical} / ${b.physical}`, "scheduler requests / executions started");
      card("Admission denials", b.denied);
      body.append(cards);
      const charts = h("div", "pv-charts");
      if (m.budgetSeries.length) charts.append(this.stepChart("Tool budget used over time", [{label: "used", points: m.budgetSeries.filter((p) => p.t !== null).map((p) => [p.t, p.used])}], b.limit));
      const occupancy = new Map();
      for (const t of m.tasks) if (t.start !== null) {
        const list = occupancy.get(t.pool) || []; list.push([t.start, 1], [typeof t.end === "number" ? t.end : t.start, -1]); occupancy.set(t.pool, list);
      }
      const series = [...occupancy.entries()].map(([pool, edges]) => {
        edges.sort((a, b) => a[0] - b[0] || a[1] - b[1]); let level = 0; const pts = [];
        for (const [t, d] of edges) { level += d; pts.push([t, level]); }
        return {label: `${pool}${m.capacities[pool] ? ` (cap ${m.capacities[pool]})` : ""}`, points: pts};
      });
      if (series.length) charts.append(this.stepChart("Executing tasks per resource pool (occupancy proxy, not GPU utilization)", series,
        Math.max(1, ...Object.values(m.capacities || {}))));
      const planning = m.evaluations.filter((e) => typeof e.start === "number");
      if (planning.length) charts.append(h("p", "muted", `Planning: ${planning.length} evaluation(s), ${planning.filter((e) => e.backend === "parallel").length} on the process pool, ${m.pools.length} pool start(s)${m.pools.length ? ` (${m.pools.map((p) => `${fmt(p.seconds, 2)} s`).join(", ")})` : ""}.`));
      body.append(charts);
    }

    stepChart(title, series, ceiling) {
      const wrap = h("figure", "pv-chart"); wrap.append(h("figcaption", "", title));
      const pts = series.flatMap((s_) => s_.points);
      if (!pts.length) { wrap.append(h("p", "muted", "No data.")); return wrap; }
      const t0 = Math.min(...pts.map((p) => p[0])), t1 = Math.max(...pts.map((p) => p[0]), t0 + 1e-3);
      const ymax = Math.max(ceiling || 1, ...pts.map((p) => p[1]));
      const W = 520, H = 120, L = 34, B = 18;
      const x = (t) => L + (t - t0) / (t1 - t0) * (W - L - 8), y = (v) => H - B - v / ymax * (H - B - 8);
      const svg = s("svg", {class: "pv-step", viewBox: `0 0 ${W} ${H}`, width: "100%", height: H});
      svg.append(s("line", {x1: L, x2: W - 8, y1: H - B, y2: H - B, class: "pv-axis"}), s("text", {x: 2, y: y(ymax) + 4, class: "pv-tick"}, String(ymax)),
        s("text", {x: L, y: H - 4, class: "pv-tick"}, `${t0.toFixed(2)}s`), s("text", {x: W - 40, y: H - 4, class: "pv-tick"}, `${t1.toFixed(2)}s`));
      if (ceiling) svg.append(s("line", {x1: L, x2: W - 8, y1: y(ceiling), y2: y(ceiling), class: "pv-ceiling"}));
      series.forEach((s_, i) => {
        let d = ""; let prev = 0;
        for (const [t, v] of s_.points) { d += d ? ` H ${x(t)} V ${y(v)}` : `M ${x(t)} ${y(prev)} V ${y(v)}`; prev = v; }
        svg.append(s("path", {d, class: `pv-series c${i % 6}`}), s("text", {x: W - 160, y: 14 + i * 12, class: `pv-series-label c${i % 6}`}, s_.label));
      });
      wrap.append(svg);
      return wrap;
    }

    // -- recorded experiment comparison --
    renderCompare(body) {
      if (this.experiments === null) {
        body.append(h("p", "muted", "Loading recorded benchmark results…"));
        if (this.handlers.loadExperiments && !this._loading) {
          this._loading = true;
          this.handlers.loadExperiments().then((data) => { this.experiments = data?.experiments || []; this._loading = false; this.render(); })
            .catch((err) => { this.experiments = []; this._loadError = String(err); this._loading = false; this.render(); });
        }
        return;
      }
      if (!this.experiments.length) { body.append(h("p", "pv-empty", this._loadError ? `Could not load results: ${this._loadError}` : "No recorded benchmark results were found.")); return; }
      const index = Math.min(this.experimentIndex || 0, this.experiments.length - 1);
      const exp = this.experiments[index];
      const pick = h("select", "pv-select"); pick.setAttribute("aria-label", "Experiment");
      this.experiments.forEach((e, i) => { const o = h("option", "", `[${e.evidence}] ${e.title}`); o.value = i; if (i === index) o.selected = true; pick.append(o); });
      pick.addEventListener("change", () => { this.experimentIndex = Number(pick.value); this.baseline = 0; this.render(); });
      const base = h("select", "pv-select"); base.setAttribute("aria-label", "Baseline");
      exp.rows.forEach((r, i) => { const o = h("option", "", `baseline: ${r.label}`); o.value = i; if (i === (this.baseline || 0)) o.selected = true; base.append(o); });
      base.addEventListener("change", () => { this.baseline = Number(base.value); this.render(); });
      const controls = h("div", "pv-controls"); controls.append(pick, base, h("span", `pv-evidence-tag ev-${exp.evidence.toLowerCase()}`, exp.evidence));
      body.append(controls, h("p", "muted", exp.description));
      const metric = exp.primary_metric;
      const baseRow = exp.rows[this.baseline || 0];
      const max = Math.max(...exp.rows.map((r) => r.values[metric] || 0), 1e-9);
      const chart = h("div", "pv-bars");
      for (const row of exp.rows) {
        const v = row.values[metric];
        const line = h("div", `pv-bar-row${row === baseRow ? " baseline" : ""}`);
        const fill = h("div", "pv-bar-fill"); fill.style.width = `${Math.max(1, (v || 0) / max * 100)}%`;
        const delta = baseRow.values[metric] && v ? ((v - baseRow.values[metric]) / baseRow.values[metric]) * 100 : null;
        line.append(h("span", "pv-bar-name", row.label), fill, h("span", "pv-bar-value", `${fmt(v)} ${exp.units[metric] || ""}${row.sd?.[metric] ? ` ± ${fmt(row.sd[metric])}` : ""}${delta !== null && row !== baseRow ? ` (${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%)` : ""}`));
        chart.append(line);
      }
      body.append(h("p", "pv-metric-title", `${exp.metric_labels[metric] || metric} (lower is better${exp.higher_is_better?.includes(metric) ? " — except this metric: higher is better" : ""})`), chart);
      const table = h("table", "pv-table");
      const head = h("tr"); head.append(h("th", "", "Mode")); for (const k of exp.metrics) head.append(h("th", "", `${exp.metric_labels[k] || k}${exp.units[k] ? ` (${exp.units[k]})` : ""}`)); table.append(head);
      for (const row of exp.rows) {
        const tr = h("tr", row === baseRow ? "baseline" : ""); tr.append(h("td", "", row.label));
        for (const k of exp.metrics) tr.append(h("td", "", typeof row.values[k] === "number" ? fmt(row.values[k], k.includes("rate") || k.includes("speedup") ? 2 : 3) : (row.values[k] ?? "—")));
        table.append(tr);
      }
      body.append(table);
      if (exp.notes?.length) { const ul = h("ul", "pv-notes"); for (const n of exp.notes) ul.append(h("li", "", n)); body.append(ul); }
      body.append(h("p", "muted", `Source: ${exp.source}. Recorded results only; nothing is executed from this view.`));
    }
  }

  return {buildModel, lanes, planGraph, criticalPath, decisionText, predictedVsObserved, originLabel, ParsecView, NO_DATA};
});
