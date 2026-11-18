"use strict";
/*
 * Simple team picture: one card per agent, the tools it actually used inside
 * the card, arrows for recorded traffic (assign ↓, report ↑, peer ⇄) with
 * counts, and one strip for the shared machinery. Everything shown comes from
 * the visible event prefix; the DOM is built once per topology and updated in
 * place. Technical detail lives in the "Technical details" section.
 */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.StudioSimpleTeam = api;
})(typeof self !== "undefined" ? self : this, function (root) {
  const label = (id) => (id === "coordinator" ? "Coordinator" : /^worker_(\d+)$/.test(id || "") ? `Worker ${Number(id.slice(7))}` : id);
  const badge = (id) => (id === "coordinator" ? "C" : /^worker_(\d+)$/.test(id || "") ? `W${Number(id.slice(7))}` : "?");
  const toolLabel = (name) => String(name || "tool").replace(/_Tool$/i, "").replace(/_/g, " ");
  const STATUS = {idle: "Waiting", assigned: "Assigned", running: "Working", reviewing: "Reviewing peers", completed: "Done",
    failed: "Failed", delegating: "Assigning work", synthesizing: "Deciding", planning: "Planning", cancelled: "Stopped"};

  /** Recorded traffic between agents in the visible events. */
  function traffic(events) {
    const assign = new Map(); const report = new Map(); const peer = new Map(); const hyp = new Map();
    const add = (map, key) => map.set(key, (map.get(key) || 0) + 1);
    for (const e of events) {
      const p = e.payload || {};
      if (e.event_type === "HYPOTHESIS_UPDATED") add(hyp, e.agent_id);
      if (e.event_type !== "MESSAGE_SENT") continue;
      const from = e.agent_id; const to = p.recipient_id || "";
      if (from === "coordinator" && /^worker_/.test(to)) add(assign, to);
      else if (/^worker_/.test(from) && to === "coordinator") add(report, from);
      else if (/^worker_/.test(from) && /^worker_/.test(to)) add(peer, [from, to].sort().join("|"));
    }
    // Without a message bus, reports reach the coordinator directly; count recorded answers instead.
    for (const [worker, n] of hyp) if (!report.has(worker)) report.set(worker, n);
    return {assign, report, peer};
  }

  /** The latest flow worth highlighting, from one annotated event. */
  function activeFlow(event) {
    const act = event?.activity; if (!act) return null;
    const kind = act.kind || "";
    if (kind.startsWith("tool")) return {type: "tool", agent: event.agent_id, tool: event.tool_name};
    const sender = act.sender || event.agent_id; const recipient = act.recipient;
    if (!recipient) return null;
    if (sender === "coordinator" && /^worker_/.test(recipient)) return {type: "assign", worker: recipient};
    if (/^worker_/.test(sender) && recipient === "coordinator") return {type: "report", worker: sender};
    if (/^worker_/.test(sender) && /^worker_/.test(recipient)) return {type: "peer", key: [sender, recipient].sort().join("|")};
    return null;
  }

  function h(tag, className, text) {
    const node = root.document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  class SimpleTeam {
    constructor(host, handlers = {}) { this.host = host; this.handlers = handlers; this.key = null; this.cards = new Map(); }

    setTopology(topology) {
      const agents = topology?.agents || [];
      const key = `${topology?.fingerprint}|${agents.join(",")}`;
      if (key === this.key) return;
      this.key = key;
      const nodes = new Map((topology?.nodes || []).map((n) => [n.id, n]));
      const workers = agents.filter((id) => id !== "coordinator");
      this.cards = new Map();
      const stage = h("div", `st-stage n${Math.min(workers.length, 4)}`);
      this.svg = root.document.createElementNS("http://www.w3.org/2000/svg", "svg");
      this.svg.setAttribute("class", "st-routes"); this.svg.setAttribute("aria-hidden", "true");
      stage.append(this.svg);
      const top = h("div", "st-row st-top");
      if (agents.includes("coordinator")) top.append(this.card("coordinator", "Splits the task, reviews the reports, decides the answer"));
      const row = h("div", "st-row st-workers");
      row.style.setProperty("--n", String(Math.max(1, workers.length)));
      for (const id of workers) row.append(this.card(id, null));
      if (!agents.length) row.append(h("p", "muted", "No agents recorded yet."));
      stage.append(top, row);
      // Shared machinery in one line.
      const models = (topology?.nodes || []).filter((n) => n.type === "model_service");
      const tools = (topology?.nodes || []).filter((n) => n.type === "tool").map((n) => toolLabel(n.label));
      const infra = h("div", "st-infra");
      infra.append(h("span", "st-infra-label", "Shared behind the scenes"));
      for (const m of models) infra.append(h("span", "st-chip", `Model: ${m.metadata?.kind === "fixture" ? "scripted test policy" : m.label} · used by ${m.metadata?.clients?.length || 0} agents`));
      if (tools.length) infra.append(h("span", "st-chip", `Tool services: ${tools.join(", ")}`));
      infra.append(h("span", "st-chip", "Message bus"));
      this.budget = h("span", "st-chip", "Budget —"); infra.append(this.budget);
      stage.append(infra);
      this.stage = stage;
      this.host.replaceChildren(stage);
      if (root.ResizeObserver) { this.observer?.disconnect(); this.observer = new root.ResizeObserver(() => this.drawRoutes()); this.observer.observe(stage); }
      this.nodes = nodes;
    }

    card(id, role) {
      const card = h("article", `st-card ${id === "coordinator" ? "coordinator" : "worker"}`);
      card.dataset.agent = id; card.tabIndex = 0; card.setAttribute("role", "button");
      card.setAttribute("aria-label", `${label(id)}: show only its steps`);
      const head = h("header", "st-head");
      const who = h("div", "st-who"); who.append(h("b", "", label(id)), h("small", "st-role", role || "Waiting for an assignment"));
      const state = h("span", "st-state", "Waiting");
      head.append(h("span", "st-badge", badge(id)), who, state);
      const now = h("p", "st-now", "");
      const tools = h("div", "st-tools");
      const answer = h("p", "st-answer", "");
      card.append(head, now);
      if (id !== "coordinator") card.append(tools);
      card.append(answer);
      card.addEventListener("click", () => this.handlers.onAgent?.(id));
      card.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this.handlers.onAgent?.(id); } });
      this.cards.set(id, {card, role: who.querySelector(".st-role"), state, now, tools, answer, toolKey: ""});
      return card;
    }

    /** ctx: {agents: Map(id -> {status, subtask, tools: Map}), now: Map(id -> text), answers: Map(id -> text), estimate, events, latest, focusAgent, budget} */
    update(ctx) {
      if (!this.stage) return;
      for (const [id, parts] of this.cards) {
        const record = ctx.agents?.get(id) || {};
        const running = ctx.running?.get(id);
        const status = running || STATUS[String(record.status || "idle").toLowerCase()] || "Working";
        if (parts.state.textContent !== status) parts.state.textContent = status;
        parts.card.dataset.state = running ? "active" : String(record.status || "idle").toLowerCase();
        if (id !== "coordinator" && record.subtask) parts.role.textContent = record.subtask;
        const now = ctx.now?.get(id); parts.now.textContent = now || "No steps yet";
        parts.now.classList.toggle("muted", !now);
        if (id === "coordinator") {
          const e = ctx.estimate; const value = e && e.value !== null && e.value !== undefined ? e.value : null;
          parts.answer.textContent = value !== null ? `Current estimate: ${value}${e.status === "final" ? " (final)" : ""}` : "No estimate yet";
        } else {
          const a = ctx.answers?.get(id); parts.answer.textContent = a ? `Answer: ${a}` : "No answer yet";
        }
        parts.answer.classList.toggle("muted", parts.answer.textContent.startsWith("No "));
        if (id !== "coordinator") {
          const tools = [...(record.tools || new Map())];
          const key = tools.map(([n, c]) => `${n}:${c}`).join("|");
          if (key !== parts.toolKey) {
            parts.toolKey = key; parts.tools.replaceChildren();
            if (!tools.length) parts.tools.append(h("span", "muted", "No tools used yet"));
            for (const [name, count] of tools) {
              const chip = h("button", "st-tool", `${toolLabel(name)} ×${count}`); chip.type = "button"; chip.dataset.tool = name;
              chip.title = `Open ${label(id)}'s latest ${toolLabel(name)} step`;
              chip.addEventListener("click", (event) => { event.stopPropagation(); this.handlers.onTool?.(id, name); });
              parts.tools.append(chip);
            }
          }
          for (const chip of parts.tools.querySelectorAll(".st-tool")) chip.classList.toggle("active", ctx.flow?.type === "tool" && ctx.flow.agent === id && ctx.flow.tool === chip.dataset.tool);
        }
        parts.card.classList.toggle("active", Boolean((ctx.flow?.type === "tool" && ctx.flow.agent === id) || (ctx.flow?.worker === id) || (ctx.flow?.type === "peer" && ctx.flow.key.split("|").includes(id)) || (id === "coordinator" && ["assign", "report"].includes(ctx.flow?.type))));
        parts.card.classList.toggle("focused", ctx.focusAgent === id);
        parts.card.classList.toggle("dimmed", Boolean(ctx.focusAgent) && ctx.focusAgent !== id);
      }
      if (ctx.budget) this.budget.textContent = ctx.budget;
      this.traffic = ctx.traffic; this.flow = ctx.flow;
      this.drawRoutes();
    }

    drawRoutes() {
      const svg = this.svg; if (!svg || !this.stage) return;
      const box = this.stage.getBoundingClientRect(); if (!box.width) return;
      svg.setAttribute("viewBox", `0 0 ${box.width} ${box.height}`);
      const pos = (id) => { const c = this.cards.get(id)?.card.getBoundingClientRect(); return c ? {x: c.left - box.left, y: c.top - box.top, w: c.width, h: c.height} : null; };
      const t = this.traffic || {assign: new Map(), report: new Map(), peer: new Map()};
      const parts = [];
      const coord = pos("coordinator");
      const workers = [...this.cards.keys()].filter((id) => id !== "coordinator");
      const ns = svg.namespaceURI;
      const path = (d, cls, text, x, y) => {
        const g = root.document.createElementNS(ns, "g"); g.setAttribute("class", `st-route ${cls}`);
        const p = root.document.createElementNS(ns, "path"); p.setAttribute("d", d); g.append(p);
        if (text) { const tx = root.document.createElementNS(ns, "text"); tx.setAttribute("x", x); tx.setAttribute("y", y); tx.setAttribute("text-anchor", "middle"); tx.textContent = text; g.append(tx); }
        parts.push(g);
      };
      if (coord) {
        workers.forEach((id, i) => {
          const w = pos(id); if (!w) return;
          const x1 = coord.x + coord.w * (i + 1) / (workers.length + 1); const y1 = coord.y + coord.h;
          const x2 = w.x + w.w / 2; const y2 = w.y; const mid = (y1 + y2) / 2;
          const a = t.assign.get(id) || 0; const r = t.report.get(id) || 0;
          const active = this.flow && (this.flow.worker === id) ? ` active ${this.flow.type}` : "";
          path(`M ${x1} ${y1} C ${x1} ${mid}, ${x2} ${mid}, ${x2} ${y2}`, `st-link${a || r ? "" : " idle"}${active}`,
            a || r ? `↓${a}  ↑${r}` : "", (x1 + x2) / 2, mid - 3);
        });
      }
      if (t.peer.size === 1) {
        // One pair: a single arc with its message count.
        const [[key, n]] = [...t.peer];
        const [a, b] = key.split("|").map(pos);
        if (a && b) {
          const x1 = a.x + a.w / 2; const x2 = b.x + b.w / 2; const y = Math.max(a.y + a.h, b.y + b.h);
          const depth = Math.min(34, 18 + Math.abs(x2 - x1) * 0.05);
          const active = this.flow?.type === "peer" && this.flow.key === key ? " active" : "";
          path(`M ${x1} ${y} C ${x1} ${y + depth}, ${x2} ${y + depth}, ${x2} ${y}`, `peer${active}`, `⇄ ${n} peer message${n === 1 ? "" : "s"}`, (x1 + x2) / 2, y + depth * 0.75 + 4);
        }
      } else if (t.peer.size > 1) {
        // Several pairs: one shared line under the workers instead of a tangle of arcs.
        const members = new Set([...t.peer.keys()].flatMap((key) => key.split("|")));
        const boxes = [...members].map((id) => [id, pos(id)]).filter(([, p]) => p);
        if (boxes.length > 1) {
          const y = Math.max(...boxes.map(([, p]) => p.y + p.h)) + 16;
          const xs = boxes.map(([, p]) => p.x + p.w / 2);
          const total = [...t.peer.values()].reduce((sum, n) => sum + n, 0);
          const activeIds = this.flow?.type === "peer" ? this.flow.key.split("|") : [];
          for (const [id, p] of boxes) path(`M ${p.x + p.w / 2} ${p.y + p.h} L ${p.x + p.w / 2} ${y}`, `peer${activeIds.includes(id) ? " active" : ""}`, "", 0, 0);
          path(`M ${Math.min(...xs)} ${y} L ${Math.max(...xs)} ${y}`, `peer${activeIds.length ? " active" : ""}`,
            `⇄ ${total} peer messages among ${boxes.length} workers`, (Math.min(...xs) + Math.max(...xs)) / 2, y + 14);
        }
      }
      svg.replaceChildren(...parts);
    }
  }

  return {SimpleTeam, traffic, activeFlow, label, badge, toolLabel, STATUS};
});
