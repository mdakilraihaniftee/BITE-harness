"use strict";
/*
 * Compact, harness-centred team view.
 *
 * Each agent is one harness card; its model client, optional memory, peer
 * channel and tools are indicators inside the card instead of separate
 * blocks. Shared services are a small strip. The DOM is built once per
 * (topology fingerprint, effective configuration); update() only toggles
 * classes and replaces short text, so streaming events never rebuild it.
 */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.StudioTeam = api;
})(typeof self !== "undefined" ? self : this, function (root) {
  function agentLabel(id) {
    if (id === "coordinator") return "Coordinator";
    const match = /^worker_(\d+)$/.exec(id || "");
    return match ? `Worker ${Number(match[1])}` : (id || "unknown");
  }
  const shortModel = (id) => (id ? String(id).split("/").at(-1) : null);
  const toolNodeId = (name) => `tool:${String(name).replace(/[^A-Za-z0-9_.-]/g, "_").slice(0, 96)}`;

  /** Pure description of the team, from topology and the recorded run configuration. */
  function teamModel(topology, effective) {
    const nodes = new Map((topology?.nodes || []).map((node) => [node.id, node]));
    const agents = topology?.agents || [];
    const workers = agents.filter((id) => id !== "coordinator");
    const comm = nodes.get("comm_bus")?.metadata || {};
    let peer = "unknown"; let peerSource = "not recorded";
    if (effective) { peer = effective.peer_communication_enabled ? "on" : "off"; peerSource = "run configuration"; }
    else if (typeof comm.peer_communication_enabled === "boolean") { peer = comm.peer_communication_enabled ? "on" : "off"; peerSource = "run manifest"; }
    else if (typeof comm.enabled === "boolean") { peer = comm.enabled && comm.peer_to_peer ? "on" : "off"; peerSource = "run manifest"; }
    const reportChannel = effective ? (effective.communication_enabled ? "message bus" : "direct result handoff")
      : (typeof comm.enabled === "boolean" ? (comm.enabled ? "message bus" : "direct result handoff") : "not recorded");
    const memoryOf = (id) => {
      const meta = nodes.get(`${id}.memory`)?.metadata || {};
      if (meta.optional_notebook === true) return "on";
      if (meta.optional_notebook === false) return "off";
      if (effective) return effective.optional_worker_memory_enabled ? "on" : "off";
      return "unknown";
    };
    const describe = (id) => {
      const model = nodes.get(`${id}.model_client`)?.metadata || {};
      const harness = nodes.get(`${id}.harness`)?.metadata || {};
      const memory = nodes.get(`${id}.memory`)?.metadata || {};
      const router = nodes.get(`${id}.tool_router`);
      const group = (topology?.groups || []).find((item) => item.agent_id === id) || {};
      return {
        id, label: agentLabel(id), role: group.role || nodes.get(id)?.metadata?.role || null,
        model: model.kind === "fixture" ? "Fixture policy" : (shortModel(model.model_id) || "model not recorded"),
        modelDetail: [model.model_id, model.protocol, model.endpoint].filter(Boolean).join(" · ") || "not recorded",
        modelKind: model.kind || null,
        harness: [harness.implementation || "agent loop", harness.max_iterations ? `max ${harness.max_iterations} iterations` : null].filter(Boolean).join(" · "),
        memory: id === "coordinator" ? "record" : memoryOf(id),
        memoryModules: memory.modules || [],
        peer: id === "coordinator" ? "n/a" : (workers.length < 2 && peer === "on" ? "on_single" : peer),
        tools: router ? (router.metadata?.tools || []) : [],
        toolAccess: Boolean(router),
        provenance: nodes.get(id)?.provenance || "configured",
      };
    };
    const services = (topology?.nodes || []).filter((node) => node.type === "model_service").map((node) => ({
      id: node.id, label: node.label, clients: node.metadata?.clients || [], fixture: node.metadata?.kind === "fixture"}));
    const tools = (topology?.nodes || []).filter((node) => node.type === "tool").map((node) => ({
      id: node.id, label: node.label, users: node.metadata?.users || [], shared: Boolean(node.shared)}));
    return {
      coordinator: agents.includes("coordinator") ? describe("coordinator") : null,
      workers: workers.map(describe), peer, peerSource, reportChannel, services, tools,
      limits: nodes.get("budget")?.metadata?.limits || {},
      estimateUpdates: effective?.coordinator_estimate_updates || null,
      scope: topology?.scope || "run",
    };
  }

  function h(tag, className, text) {
    const node = root.document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  const MEMORY_TEXT = {on: ["●", "Memory on"], off: ["○", "Memory off"], unknown: ["?", "Memory unknown"], record: ["◆", "Run record"]};
  const PEER_TEXT = {on: ["●", "Peer on"], off: ["○", "Peer off"], on_single: ["◌", "Peer on · no peers"], unknown: ["?", "Peer unknown"]};

  class TeamView {
    constructor(host, handlers = {}) {
      this.host = host; this.handlers = handlers; this.key = null; this.model = null;
      this.cards = new Map(); this.expanded = new Set();
    }

    setTopology(topology, effective) {
      const key = JSON.stringify([topology?.fingerprint, topology?.scope, effective || null]);
      if (key === this.key) return false;
      this.key = key;
      this.model = teamModel(topology, effective);
      this.build();
      return true;
    }

    badge(className, glyph, text, title, onClick) {
      const button = h("button", `badge ${className}`);
      button.type = "button";
      button.append(h("span", "glyph", glyph), h("span", "badge-text", text));
      button.title = title;
      button.setAttribute("aria-label", `${text}. ${title}`);
      if (onClick) button.addEventListener("click", (event) => { event.stopPropagation(); onClick(); });
      return button;
    }

    buildCard(agent, isCoordinator) {
      const card = h("article", `harness ${isCoordinator ? "coordinator" : "worker"} prov-${agent.provenance}`);
      card.dataset.agent = agent.id; card.tabIndex = 0;
      card.setAttribute("role", "button");
      card.setAttribute("aria-label", `${agent.label} harness`);
      const parts = {card};
      if (!isCoordinator) {
        const link = h("div", "link"); link.setAttribute("aria-hidden", "true");
        link.append(h("span", "link-line"), h("span", "link-label"));
        parts.link = link; card.append(link);
      }
      const head = h("header", "harness-head");
      head.append(h("strong", "harness-name", agent.label), h("span", "harness-kind", isCoordinator ? "coordinator harness" : "harness"));
      parts.state = h("span", "state-pill", "Idle"); head.append(parts.state);
      card.append(head);
      if (!isCoordinator) { parts.subtask = h("p", "subtask", agent.role ? `Role: ${agent.role}` : "Awaiting assignment"); card.append(parts.subtask); }
      const badges = h("div", "badges");
      parts.model = this.badge(`model${agent.modelKind === "fixture" ? " fixture" : ""}`, "◆", agent.model, `Model client: ${agent.modelDetail}`,
        () => this.handlers.onSelectNode?.(`${agent.id}.model_client`));
      const [mg, mt] = MEMORY_TEXT[agent.memory] || MEMORY_TEXT.unknown;
      parts.memory = this.badge(`memory m-${agent.memory}`, mg, mt, agent.memory === "record"
        ? "Coordinator run record (plan, reassessments, synthesis). Click to open the authorized memory view."
        : agent.memory === "unknown" ? "This run did not record its optional-memory policy. Click to open the authorized memory view."
          : `Optional private notebook ${agent.memory.toUpperCase()}; working context is always on. Click to open the authorized memory view.`,
      () => this.handlers.onMemory?.(agent.id));
      badges.append(parts.model, parts.memory);
      if (!isCoordinator) {
        const [pg, pt] = PEER_TEXT[agent.peer] || PEER_TEXT.unknown;
        parts.peer = this.badge(`peer p-${agent.peer}`, pg, pt, `Worker-to-worker messages ${agent.peer === "on" ? "allowed" : agent.peer === "on_single" ? "allowed, but this run has no other worker" : agent.peer === "off" ? "disabled" : "not recorded"}; coordinator assignment/reporting stays on (${this.model.reportChannel}). Click for this worker's messages.`,
          () => this.handlers.onPeer?.(agent.id));
        badges.append(parts.peer);
      } else {
        badges.append(this.badge("tools-none", "◇", agent.toolAccess ? `${agent.tools.length} tools` : "No tools", agent.toolAccess ? "Coordinator tool access" : "The coordinator coordinates from worker reports only"));
      }
      card.append(badges);
      parts.tools = new Map();
      if (!isCoordinator) {
        const chips = h("div", "tool-chips");
        if (!agent.tools.length) chips.append(h("span", "muted", "No tools recorded"));
        for (const name of agent.tools) {
          const chip = h("button", "chip tool"); chip.type = "button";
          const id = toolNodeId(name);
          chip.dataset.tool = id;
          chip.append(h("span", "dir", ""), h("span", "chip-name", name), h("span", "count", ""));
          chip.title = `${name} — click to inspect this tool`;
          chip.addEventListener("click", (event) => { event.stopPropagation(); this.handlers.onSelectNode?.(id, agent.id); });
          parts.tools.set(id, chip); chips.append(chip);
        }
        card.append(chips);
      } else {
        parts.estimate = h("div", "coord-estimate");
        parts.estimateValue = h("strong", "", "—"); parts.estimateNote = h("span", "muted", "");
        parts.estimate.append(h("span", "", "Current estimate"), parts.estimateValue, parts.estimateNote);
        card.append(parts.estimate);
      }
      parts.activity = h("div", "activity-line", ""); card.append(parts.activity);
      const foot = h("footer", "harness-foot");
      parts.candidate = h("span", "candidate-text", isCoordinator ? "" : "Candidate: —");
      parts.calls = h("span", "calls", "");
      const expand = h("button", "expand quiet", "Details"); expand.type = "button";
      expand.setAttribute("aria-expanded", "false");
      expand.addEventListener("click", (event) => { event.stopPropagation(); this.toggle(agent.id); });
      parts.expand = expand;
      foot.append(parts.candidate, parts.calls, expand); card.append(foot);
      parts.details = h("div", "harness-details"); parts.details.hidden = true;
      card.append(parts.details);
      card.addEventListener("click", () => this.handlers.onSelectNode?.(agent.id));
      card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); this.handlers.onSelectNode?.(agent.id); } });
      parts.agent = agent;
      this.cards.set(agent.id, parts);
      return card;
    }

    build() {
      const m = this.model;
      this.cards = new Map();
      const wrap = h("div", `team n${Math.min(m.workers.length, 4)}${m.workers.length > 4 ? " many" : ""}`);
      wrap.style.setProperty("--workers", String(Math.max(1, m.workers.length)));
      const top = h("div", "team-top");
      const task = h("div", "team-task"); task.append(h("span", "glyph", "▣"), h("span", "", "Original task"), h("span", "arrow", "→"));
      top.append(task);
      if (m.coordinator) top.append(this.buildCard(m.coordinator, true));
      wrap.append(top);
      const channel = h("div", "channel-bar");
      this.channelLabel = h("span", "channel-label", `Coordinator ⇅ workers · assignments & reports (${m.reportChannel})`);
      channel.append(h("span", "channel-line"), this.channelLabel, h("span", "channel-line"));
      wrap.append(channel);
      const grid = h("div", "team-workers");
      if (!m.workers.length) grid.append(h("div", "empty-state", m.scope === "run" ? "No workers recorded for this run yet." : "Worker slots appear when a run starts."));
      for (const worker of m.workers) grid.append(this.buildCard(worker, false));
      wrap.append(grid);
      this.peerLane = h("div", `peer-lane p-${m.peer}`);
      this.peerText = h("span", "peer-text", "");
      this.peerLane.append(h("span", "peer-title", m.peer === "on" ? (m.workers.length > 1 ? "Peer channel ON" : "Peer channel ON · no other worker in this run") : m.peer === "off" ? "Peer channel OFF" : "Peer channel not recorded"),
        this.peerText);
      wrap.append(this.peerLane);
      const shared = h("div", "shared-strip");
      shared.append(h("span", "strip-label", "Shared services"));
      for (const service of m.services) {
        const chip = h("button", "chip service", ""); chip.type = "button";
        chip.append(h("span", "glyph", "◆"), h("span", "", service.fixture ? "Fixture model (no service)" : service.label), h("span", "count", `${service.clients.length} client${service.clients.length === 1 ? "" : "s"}`));
        chip.title = `One shared model-serving backend used by ${service.clients.map(agentLabel).join(", ")}`;
        chip.addEventListener("click", () => this.handlers.onSelectNode?.(service.id));
        shared.append(chip);
      }
      this.sharedTools = new Map();
      for (const tool of m.tools) {
        const chip = h("button", `chip service tool${tool.shared ? " shared" : ""}`); chip.type = "button";
        chip.append(h("span", "glyph", "⚙"), h("span", "", tool.label), h("span", "count", tool.shared ? `shared ×${tool.users.length}` : agentLabel(tool.users[0])));
        chip.title = `${tool.label}: used by ${tool.users.map(agentLabel).join(", ") || "—"}`;
        chip.addEventListener("click", () => this.handlers.onSelectNode?.(tool.id));
        this.sharedTools.set(tool.id, chip); shared.append(chip);
      }
      this.budgetChip = h("span", "chip budget", "Budget —");
      shared.append(this.budgetChip);
      const infra = h("span", "chip infra", "Event recorder · Evidence store");
      infra.title = "Every event is persisted; images are stored by content ID.";
      shared.append(infra);
      wrap.append(shared);
      this.host.replaceChildren(wrap);
      this.root = wrap;
      for (const id of this.expanded) if (this.cards.has(id)) this.renderDetails(id, true);
    }

    toggle(agentId) {
      const open = !this.expanded.has(agentId);
      if (open) this.expanded.add(agentId); else this.expanded.delete(agentId);
      this.renderDetails(agentId, open);
      this.handlers.onLayoutChange?.();
    }

    renderDetails(agentId, open) {
      const parts = this.cards.get(agentId); if (!parts) return;
      parts.details.hidden = !open;
      parts.expand.textContent = open ? "Hide" : "Details";
      parts.expand.setAttribute("aria-expanded", String(open));
      parts.card.classList.toggle("expanded", open);
      if (!open) return;
      const a = parts.agent;
      const dl = h("dl");
      const rows = [["Harness", a.harness], ["Model client", a.modelDetail], ["Working context", "Conversation + per-question image registry (always on)"],
        ["Optional memory", a.memory === "record" ? "Coordinator run record" : a.memory === "unknown" ? "Not recorded (legacy run)" : `Private notebook ${a.memory.toUpperCase()}`],
        ["Memory modules", a.memoryModules.join(", ") || "not recorded"]];
      if (a.id !== "coordinator") rows.push(["Peer messages", a.peer === "on_single" ? "Allowed; no other worker" : a.peer], ["Tools", a.tools.join(", ") || "none"]);
      parts.budgetRow = h("dd", "", "—");
      for (const [k, v] of rows) dl.append(h("dt", "", k), h("dd", "", v));
      dl.append(h("dt", "", "Actor budget"), parts.budgetRow);
      const actions = h("div", "detail-actions");
      const full = h("button", "", "Show in full architecture"); full.type = "button";
      full.addEventListener("click", (event) => { event.stopPropagation(); this.handlers.onShowFull?.(agentId); });
      const memory = h("button", "", "Open permitted memory"); memory.type = "button";
      memory.addEventListener("click", (event) => { event.stopPropagation(); this.handlers.onMemory?.(agentId); });
      actions.append(full, memory);
      parts.details.replaceChildren(dl, actions);
      if (this.lastCtx) this.applyBudget(agentId, parts, this.lastCtx);
    }

    applyBudget(agentId, parts, ctx) {
      const budget = ctx.actorBudget?.get(agentId);
      const text = budget ? Object.entries(budget).map(([k, v]) => `${k.replaceAll("_", " ")}: ${v} left`).join(" · ") : "no reservations yet";
      parts.card.title = `${parts.agent.label} — budget ${text}`;
      if (parts.budgetRow) parts.budgetRow.textContent = text;
    }

    /**
     * ctx: {activity, latest, selected (annotated events or null), lastByAgent: Map,
     *       answer (StudioAnswer state), budget: {tool_calls: {used, limit}, ...}, actorBudget: Map}
     */
    update(ctx) {
      if (!this.root) return;
      this.lastCtx = ctx;
      const A = root.StudioActivity;
      const activity = ctx.activity;
      const focus = [ctx.selected, ctx.latest].filter(Boolean);
      const focusKinds = new Map();
      for (const event of focus) if (event.activity) focusKinds.set(event.event_id, event.activity);
      for (const [id, parts] of this.cards) {
        const record = activity?.agents.get(id) || {};
        const status = activity ? A.agentStatusLine(activity, id) : (this.model.scope === "run" ? "Idle" : "Configured");
        if (parts.state.textContent !== status) parts.state.textContent = status;
        const statusKey = String(record.status || "idle").toLowerCase();
        parts.card.dataset.status = statusKey;
        if (parts.subtask && record.subtask) { const text = `Subtask: ${record.subtask}`; if (parts.subtask.textContent !== text) { parts.subtask.textContent = text; parts.subtask.title = record.subtask; } }
        if (id !== "coordinator") {
          const candidate = record.candidate === null || record.candidate === undefined ? "—" : String(record.candidate).slice(0, 40);
          parts.candidate.textContent = `Candidate: ${candidate}`;
          let total = 0;
          for (const [toolId, chip] of parts.tools) {
            const name = chip.querySelector(".chip-name").textContent;
            const n = record.tools?.get(name) || 0; total += n;
            chip.querySelector(".count").textContent = n ? `×${n}` : "";
          }
          parts.calls.textContent = `${total} tool call${total === 1 ? "" : "s"}`;
        }
        const last = ctx.lastByAgent?.get(id);
        const line = last ? (last.activity?.label || last.summary || "") : "";
        if (parts.activity.textContent !== line) parts.activity.textContent = line;
        this.applyBudget(id, parts, ctx);
        // Reset transient flow classes.
        parts.card.classList.remove("flow-out", "flow-in", "is-focus", "peer-source", "peer-target", "is-selected");
        parts.model.classList.remove("active", "dir-out", "dir-in", "failure");
        parts.memory.classList.remove("active", "dir-out", "dir-in");
        if (parts.link) parts.link.className = "link";
        for (const chip of parts.tools.values()) {
          chip.classList.remove("active", "request", "response", "failure", "running");
          chip.querySelector(".dir").textContent = "";
        }
      }
      for (const chip of this.sharedTools?.values() || []) chip.classList.remove("active", "running");
      this.peerLane.classList.remove("active");
      // Persistent running work (open correlations).
      for (const open of activity?.open.values() || []) {
        const parts = this.cards.get(open.agentId);
        if (!parts) continue;
        if (open.toolNode && parts.tools.has(open.toolNode)) { parts.tools.get(open.toolNode).classList.add("running"); this.sharedTools.get(open.toolNode)?.classList.add("running"); }
        if (open.kind === "model_request" && ctx.technical) parts.model.classList.add("active", "dir-out");
      }
      // Latest and selected flows, selected drawn last so it wins.
      for (const event of [ctx.latest, ctx.selected]) {
        if (!event?.activity) continue;
        this.applyFlow(event, event === ctx.selected);
      }
      if (this.cards.get("coordinator")) this.renderEstimate(ctx.answer);
      if (ctx.budget) {
        const b = ctx.budget;
        const fmt = (key, label) => (b[key] ? `${label} ${b[key].used}/${b[key].limit}` : null);
        this.budgetChip.textContent = ["Budget", fmt("tool_calls", "tools"), fmt("model_requests", "model"), fmt("messages", "msgs")].filter(Boolean).join(" · ");
      }
      this.root.classList.toggle("has-focus", Boolean(ctx.latest || ctx.selected));
    }

    applyFlow(event, selected) {
      const act = event.activity; const kind = act.kind || "";
      const agentParts = this.cards.get(event.agent_id);
      const mark = (parts, ...classes) => { if (parts) parts.card.classList.add(...classes, selected ? "is-selected" : "is-focus"); };
      if (kind.startsWith("tool") || kind === "decision" || kind === "evidence") {
        mark(agentParts, kind === "tool_result" || kind === "evidence" ? "flow-in" : "flow-out");
        const chip = act.tool_node && agentParts?.tools.get(act.tool_node);
        if (chip) {
          chip.classList.add("active", kind === "tool_failure" || kind === "tool_denied" ? "failure" : kind === "tool_result" || kind === "evidence" ? "response" : "request");
          chip.querySelector(".dir").textContent = kind === "tool_result" || kind === "evidence" ? "←" : kind === "tool_failure" ? "✕" : "→";
        }
        this.sharedTools.get(act.tool_node)?.classList.add("active");
      } else if (kind === "model_request" || kind === "model_response" || kind === "model_failure") {
        mark(agentParts, kind === "model_request" ? "flow-out" : "flow-in");
        agentParts?.model.classList.add("active", kind === "model_request" ? "dir-out" : "dir-in", ...(kind === "model_failure" ? ["failure"] : []));
      } else if (kind === "memory_write" || kind === "memory_read") {
        mark(agentParts);
        agentParts?.memory.classList.add("active", kind === "memory_write" ? "dir-out" : "dir-in");
      } else if (["assignment", "verification_request", "report", "failure_report", "message_delivery", "peer_message", "question", "reply", "message", "delegation"].includes(kind)) {
        const sender = act.sender || event.agent_id; const recipient = act.recipient || (kind === "message_delivery" ? event.agent_id : null);
        const senderIsWorker = /^worker_/.test(sender || ""); const recipientIsWorker = /^worker_/.test(recipient || "");
        if (senderIsWorker && recipientIsWorker) {
          this.peerLane.classList.add("active");
          this.peerText.textContent = `${agentLabel(sender)} → ${agentLabel(recipient)}: ${String(act.message_type || "message").toLowerCase().replaceAll("_", " ")}`;
          mark(this.cards.get(sender), "peer-source"); mark(this.cards.get(recipient), "peer-target");
        } else {
          const worker = senderIsWorker ? sender : recipientIsWorker ? recipient : (kind === "delegation" ? (event.payload?.worker_id) : null);
          const parts = this.cards.get(worker);
          if (parts?.link) {
            const up = senderIsWorker;
            parts.link.className = `link active ${up ? "up" : "down"}`;
            parts.link.querySelector(".link-label").textContent = up ? `↑ ${String(act.message_type || "report").toLowerCase().replaceAll("_", " ")}` : `↓ ${String(act.message_type || kind).toLowerCase().replaceAll("_", " ")}`;
            mark(parts, up ? "flow-out" : "flow-in");
          }
          mark(this.cards.get("coordinator"), senderIsWorker ? "flow-in" : "flow-out");
        }
      } else if (kind === "estimate" || kind === "assessment" || kind === "plan" || kind === "synthesis" || kind === "final") {
        mark(this.cards.get("coordinator"));
      } else if (agentParts) {
        mark(agentParts);
      }
    }

    renderEstimate(answer) {
      const parts = this.cards.get("coordinator"); if (!parts || !parts.estimateValue) return;
      if (!answer) { parts.estimateValue.textContent = "—"; parts.estimateNote.textContent = ""; return; }
      const e = answer.estimate;
      const value = e.value === null || e.value === undefined ? (e.status === "unresolved" ? "Unresolved" : e.status === "abstained" ? "Abstained" : "No estimate yet") : String(e.value);
      parts.estimateValue.textContent = value;
      parts.estimate.dataset.status = e.status;
      parts.estimateNote.textContent = e.status === "none"
        ? (answer.mode === "legacy" ? "not recorded for this run" : answer.mode === "final_only" ? "estimate updates off" : "")
        : `${root.StudioAnswer ? root.StudioAnswer.statusText(e.status) : e.status} · r${e.revision}`;
    }
  }

  return {teamModel, TeamView, agentLabel};
});
