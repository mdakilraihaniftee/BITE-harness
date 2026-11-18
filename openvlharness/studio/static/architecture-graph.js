"use strict";
/*
 * Architecture graph: deterministic layout plus a stable-identity SVG renderer.
 *
 * Layout is a pure function of (topology, options) so node positions never
 * jitter while events stream. The renderer builds DOM once per layout and
 * afterwards only toggles classes and overlay visibility on update().
 */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.StudioGraph = api;
})(typeof self !== "undefined" ? self : this, function (root) {
  const SVG = "http://www.w3.org/2000/svg";
  const L = {
    colA: {x: 24, w: 176},
    bus: {x: 244, w: 14},
    groups: {x: 300, w: 560},
    services: {x: 912, w: 224},
    top: 84,
    groupGap: 22,
  };
  const INNER = {
    agent: {dx: 16, dy: 56, w: 156, h: 56},
    harness: {dx: 198, dy: 61, w: 130, h: 46},
    model_client: {dx: 358, dy: 36, w: 188, h: 40},
    tool_router: {dx: 358, dy: 84, w: 188, h: 40},
    memory: {dx: 358, dy: 132, w: 188, h: 40},
  };
  const GROUP_H = 184;
  const COLLAPSED_H = 76;

  /** Compute stable positions for every visible node. */
  function layoutTopology(topology, options = {}) {
    const collapsed = options.collapsed || new Set();
    const showMemory = options.showMemory !== false;
    const nodes = new Map();
    const groups = new Map();
    const byId = new Map((topology?.nodes || []).map((node) => [node.id, node]));
    const place = (id, x, y, w, h, extra = {}) => { if (byId.has(id)) nodes.set(id, {id, x, y, w, h, ...extra}); };

    let y = L.top;
    const agentCenters = [];
    for (const group of topology?.groups || []) {
      const agentId = group.agent_id;
      const isCollapsed = collapsed.has(agentId);
      const height = isCollapsed ? COLLAPSED_H : GROUP_H;
      groups.set(group.id, {id: group.id, agentId, kind: group.kind, label: group.label, role: group.role,
        x: L.groups.x, y, w: L.groups.w, h: height, collapsed: isCollapsed});
      if (isCollapsed) {
        place(agentId, L.groups.x + 16, y + 32, L.groups.w - 32, 34, {collapsedGroup: true});
        for (const suffix of ["harness", "model_client", "tool_router", "memory"]) {
          if (byId.has(`${agentId}.${suffix}`)) nodes.set(`${agentId}.${suffix}`, {id: `${agentId}.${suffix}`, proxy: agentId, hidden: true});
        }
        agentCenters.push(y + 32 + 17);
      } else {
        for (const [suffix, spec] of Object.entries(INNER)) {
          const id = suffix === "agent" ? agentId : `${agentId}.${suffix}`;
          if (suffix === "memory" && !showMemory) {
            if (byId.has(id)) nodes.set(id, {id, proxy: `${agentId}.harness`, hidden: true});
            continue;
          }
          place(id, L.groups.x + spec.dx, y + spec.dy, spec.w, spec.h);
        }
        agentCenters.push(y + INNER.agent.dy + INNER.agent.h / 2);
      }
      y += height + L.groupGap;
    }
    const groupsBottom = y - L.groupGap;

    // Run column.
    place("task", L.colA.x, L.top, L.colA.w, 50);
    place("orchestrator", L.colA.x, L.top + 92, L.colA.w, 50);
    let infraY = Math.max(L.top + 210, groupsBottom - 3 * 60 + 14);
    infraY = Math.min(infraY, L.top + 260);
    for (const id of ["budget", "event_log", "artifact_store"]) { place(id, L.colA.x, infraY, L.colA.w, 46); infraY += 62; }

    // Communication bus spans every agent tap point.
    const busTop = (agentCenters.length ? Math.min(...agentCenters) : L.top + 40) - 26;
    const busBottom = (agentCenters.length ? Math.max(...agentCenters) : L.top + 80) + 26;
    place("comm_bus", L.bus.x, busTop, L.bus.w, busBottom - busTop, {bus: true});

    // Shared services column.
    place("result", L.services.x, 18, L.services.w, 44);
    let sy = L.top + 22;
    const models = (topology?.nodes || []).filter((node) => node.type === "model_service");
    const tools = (topology?.nodes || []).filter((node) => node.type === "tool");
    const servicesHeaders = [];
    if (models.length) { servicesHeaders.push({label: "Model services", y: sy - 8}); }
    for (const node of models) { place(node.id, L.services.x, sy, L.services.w, 52); sy += 64; }
    if (tools.length) { sy += 18; servicesHeaders.push({label: "Tool services", y: sy - 8}); }
    for (const node of tools) { place(node.id, L.services.x, sy, L.services.w, 42); sy += 52; }

    // Any remaining node (future component types) goes in the run column.
    let extraY = infraY + 10;
    for (const node of topology?.nodes || []) {
      if (!nodes.has(node.id)) { place(node.id, L.colA.x, extraY, L.colA.w, 42); extraY += 54; }
    }
    const visible = [...nodes.values()].filter((item) => !item.hidden);
    const width = L.services.x + L.services.w + 24;
    const height = Math.max(...visible.map((item) => item.y + item.h), groupsBottom, sy) + 28;
    return {nodes, groups, width, height, busTop, busBottom, servicesHeaders,
      servicesX: L.services.x, servicesW: L.services.w};
  }

  /** Resolve a node id to the node actually drawn (collapsed proxies). */
  function visibleNode(layout, id) {
    let item = layout.nodes.get(id);
    let guard = 0;
    while (item && item.hidden && item.proxy && guard < 4) { item = layout.nodes.get(item.proxy); guard += 1; }
    return item && !item.hidden ? item : null;
  }

  const cx = (n) => n.x + n.w / 2;
  const cy = (n) => n.y + n.h / 2;

  /** Orthogonal polyline with rounded corners, as cubic segments. */
  function orthogonal(points, radius = 10) {
    const out = [points[0]];
    const line = (p, q) => [[p[0] + (q[0] - p[0]) / 3, p[1] + (q[1] - p[1]) / 3], [p[0] + 2 * (q[0] - p[0]) / 3, p[1] + 2 * (q[1] - p[1]) / 3], q];
    let cursor = points[0];
    for (let i = 1; i < points.length; i += 1) {
      const corner = points[i]; const next = points[i + 1];
      if (!next) { out.push(line(cursor, corner)); break; }
      const toward = (from, to, distance) => {
        const length = Math.hypot(to[0] - from[0], to[1] - from[1]) || 1;
        const d = Math.min(distance, length / 2);
        return [from[0] + (to[0] - from[0]) * d / length, from[1] + (to[1] - from[1]) * d / length];
      };
      const before = toward(corner, cursor, radius); const after = toward(corner, next, radius);
      out.push(line(cursor, before));
      out.push([corner, corner, after]);
      cursor = after;
    }
    return out;
  }

  /** Geometry as cubic segments so it can be reversed exactly. */
  function edgeGeometry(edge, a, b, layout) {
    if (!a || !b || a === b) return null;
    let points;
    if (b.bus || a.bus) {
      const bus = b.bus ? b : a; const other = b.bus ? a : b;
      const yy = Math.max(bus.y + 8, Math.min(bus.y + bus.h - 8, cy(other)));
      const otherRight = other.x > bus.x;
      const busPort = [otherRight ? bus.x + bus.w : bus.x, yy];
      const otherPort = [otherRight ? other.x : other.x + other.w, cy(other)];
      const start = b.bus ? otherPort : busPort; const end = b.bus ? busPort : otherPort;
      const mid = (start[0] + end[0]) / 2;
      points = [start, [[mid, start[1]], [mid, end[1]], end]];
    } else if (edge.edge_type === "synthesis") {
      // Rise through the free part of the group header, then run along the top lane.
      const lane = cy(b);
      const start = [cx(a), a.y];
      const riseX = a.w > 300 ? cx(a) : a.x + a.w + 60;
      const corners = a.w > 300
        ? [start, [start[0], lane], [b.x, lane]]
        : [start, [start[0], a.y - 12], [riseX, a.y - 12], [riseX, lane], [b.x, lane]];
      points = orthogonal(corners);
    } else if (b.x >= a.x + a.w - 4) {
      const start = [a.x + a.w, cy(a)]; const end = [b.x, cy(b)];
      const k = Math.max(24, (end[0] - start[0]) / 2);
      points = [start, [[start[0] + k, start[1]], [end[0] - k, end[1]], end]];
    } else if (b.x + b.w <= a.x + 4) {
      const start = [a.x, cy(a)]; const end = [b.x + b.w, cy(b)];
      const k = Math.max(24, (start[0] - end[0]) / 2);
      points = [start, [[start[0] - k, start[1]], [end[0] + k, end[1]], end]];
    } else if (b.y >= a.y + a.h) {
      const start = [cx(a), a.y + a.h]; const end = [cx(b), b.y];
      const k = Math.max(14, (end[1] - start[1]) / 2);
      points = [start, [[start[0], start[1] + k], [end[0], end[1] - k], end]];
    } else {
      const start = [cx(a), a.y]; const end = [cx(b), b.y + b.h];
      const k = Math.max(14, (start[1] - end[1]) / 2);
      points = [start, [[start[0], start[1] - k], [end[0], end[1] + k], end]];
    }
    return points;
  }

  function pathData(points, reverse = false) {
    let segments = points;
    if (reverse) {
      const anchors = [points[0], ...points.slice(1).map((seg) => seg[2])];
      const out = [anchors[anchors.length - 1]];
      for (let i = points.length - 1; i >= 1; i -= 1) {
        const [c1, c2] = points[i];
        out.push([c2, c1, anchors[i - 1]]);
      }
      segments = out;
    }
    const f = (p) => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`;
    return `M ${f(segments[0])} ${segments.slice(1).map((seg) => `C ${f(seg[0])}, ${f(seg[1])}, ${f(seg[2])}`).join(" ")}`;
  }

  function truncate(text, width, size = 12) {
    const value = String(text ?? "");
    const max = Math.max(4, Math.floor(width / (size * 0.56)));
    return value.length > max ? `${value.slice(0, max - 1)}…` : value;
  }

  const TYPE_GLYPH = {
    coordinator: "C", worker: "W", harness: "H", model_client: "M", model_service: "LLM", tool_router: "R",
    tool: "T", memory: "Mem", communication: "Bus", budget: "$", event_log: "Log", artifact_store: "Art",
    orchestrator: "O", task: "In", result: "Out",
  };
  const TECHNICAL_OPEN = new Set(["model_request"]);
  const FLOW_STYLES = ["idle", "request", "response", "failure", "cancelled", "memory", "model", "model-return",
    "budget", "control", "message", "message-return", "delivery", "lifecycle", "pending", "selected"];

  function svgEl(tag, attrs = {}, className) {
    const node = root.document.createElementNS(SVG, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    if (className) node.setAttribute("class", className);
    return node;
  }

  class ArchitectureGraph {
    constructor(host, handlers = {}) {
      this.host = host;
      this.handlers = handlers;
      this.options = {collapsed: new Set(), showMemory: true, showMemoryFlows: true, showInfra: false, mode: "full", animate: true, technical: false};
      this.topology = null;
      this.layout = null;
      this.view = null;
      this.layoutKey = null;
      this.elements = {nodes: new Map(), edges: new Map(), overlays: new Map(), groups: new Map()};
      this.selection = {nodeId: null, edgeId: null};
      this.svg = null;
      this.drag = null;
    }

    setOptions(patch) {
      const before = this.layoutSignature();
      Object.assign(this.options, patch);
      if (this.layoutSignature() !== before && this.topology) this.build();
      this.applyRootClasses();
    }

    layoutSignature() {
      return JSON.stringify([this.topology?.fingerprint, [...this.options.collapsed].sort(), this.options.showMemory]);
    }

    setTopology(topology) {
      if (!topology) return;
      const changed = topology.fingerprint !== this.topology?.fingerprint;
      this.topology = topology;
      if (changed) {
        if ((topology.agents || []).length > 5 && !this.options.userCollapsed) {
          this.options.collapsed = new Set((topology.agents || []).filter((id) => id !== "coordinator"));
        }
        this.build();
      }
    }

    build() {
      const keepView = this.view;
      this.layout = layoutTopology(this.topology, this.options);
      this.layoutKey = this.layoutSignature();
      this.elements = {nodes: new Map(), edges: new Map(), overlays: new Map(), groups: new Map()};
      const svg = svgEl("svg", {role: "group", "aria-label": "System architecture graph", focusable: "false"}, "arch-svg");
      const defs = svgEl("defs");
      for (const style of FLOW_STYLES) {
        const marker = svgEl("marker", {id: `arrow-${style}`, viewBox: "0 0 10 10", refX: "9", refY: "5",
          markerWidth: style === "idle" ? "6" : "4.6", markerHeight: style === "idle" ? "6" : "4.6", orient: "auto-start-reverse",
          markerUnits: "strokeWidth"});
        marker.append(svgEl("path", {d: "M 0 1 L 9 5 L 0 9 z"}, `marker-${style}`));
        defs.append(marker);
      }
      svg.append(defs);
      const background = svgEl("rect", {x: -5000, y: -5000, width: 10000, height: 10000}, "arch-bg");
      svg.append(background);
      const layers = {};
      for (const name of ["groups", "labels", "edges", "overlays", "nodes", "signals"]) { layers[name] = svgEl("g", {}, `layer-${name}`); svg.append(layers[name]); }
      this.layers = layers;

      for (const header of this.layout.servicesHeaders) {
        const text = svgEl("text", {x: this.layout.servicesX, y: header.y}, "section-label"); text.textContent = header.label.toUpperCase(); layers.labels.append(text);
      }
      const runLabel = svgEl("text", {x: L.colA.x, y: L.top - 10}, "section-label"); runLabel.textContent = "RUN"; layers.labels.append(runLabel);
      const infra = this.layout.nodes.get("budget");
      if (infra && !infra.hidden) { const t = svgEl("text", {x: L.colA.x, y: infra.y - 10}, "section-label"); t.textContent = "SHARED INFRASTRUCTURE"; layers.labels.append(t); }
      const agentsLabel = svgEl("text", {x: L.groups.x, y: L.top - 10}, "section-label"); agentsLabel.textContent = "AGENTS · LOGICAL HARNESSES"; layers.labels.append(agentsLabel);

      for (const group of this.layout.groups.values()) this.buildGroup(group);
      for (const edge of this.topology.edges || []) this.buildEdge(edge);
      for (const node of this.topology.nodes || []) this.buildNode(node);

      this.host.replaceChildren(svg);
      this.svg = svg;
      this.installNavigation(svg, background);
      if (keepView) this.setView(keepView); else this.fit();
      this.applyRootClasses();
    }

    buildGroup(group) {
      const g = svgEl("g", {"data-group": group.id}, `group group-${group.kind}${group.collapsed ? " collapsed" : ""}`);
      g.append(svgEl("rect", {x: group.x, y: group.y, width: group.w, height: group.h, rx: 12}, "group-box"));
      const title = svgEl("text", {x: group.x + 16, y: group.y + 22}, "group-title");
      title.textContent = group.label.toUpperCase();
      const role = svgEl("text", {x: group.x + 16 + group.label.length * 9.4 + 14, y: group.y + 22}, "group-role");
      role.textContent = group.role ? truncate(group.role, group.w - 210, 11) : "";
      const toggle = svgEl("g", {role: "button", tabindex: "0", "aria-label": `${group.collapsed ? "Expand" : "Collapse"} ${group.label}`}, "group-toggle");
      toggle.append(svgEl("rect", {x: group.x + group.w - 92, y: group.y + 8, width: 80, height: 20, rx: 10}));
      const label = svgEl("text", {x: group.x + group.w - 52, y: group.y + 22, "text-anchor": "middle"});
      label.textContent = group.collapsed ? "Expand" : "Collapse";
      toggle.append(label);
      const activate = (event) => { event.stopPropagation(); this.toggleGroup(group.agentId); };
      toggle.addEventListener("click", activate);
      toggle.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(event); } });
      g.append(title, role, toggle);
      this.layers.groups.append(g);
      this.elements.groups.set(group.id, g);
    }

    toggleGroup(agentId) {
      const collapsed = new Set(this.options.collapsed);
      if (collapsed.has(agentId)) collapsed.delete(agentId); else collapsed.add(agentId);
      this.options.userCollapsed = true;
      this.setOptions({collapsed});
      this.handlers.onLayoutChange?.();
    }

    setAllCollapsed(value) {
      const ids = (this.topology?.agents || []);
      this.options.userCollapsed = true;
      this.setOptions({collapsed: new Set(value ? ids : [])});
      this.handlers.onLayoutChange?.();
    }

    buildNode(node) {
      const item = this.layout.nodes.get(node.id);
      if (!item || item.hidden) return;
      const g = svgEl("g", {"data-node": node.id, role: "button", tabindex: "0",
        "aria-label": `${node.label} (${node.type.replace(/_/g, " ")})`},
      `node node-${node.type} prov-${node.provenance}${node.shared ? " shared" : ""}${item.collapsedGroup ? " collapsed-agent" : ""}`);
      if (item.bus) {
        g.append(svgEl("rect", {x: item.x, y: item.y, width: item.w, height: item.h, rx: 7}, "node-box"));
        const text = svgEl("text", {x: item.x + item.w / 2, y: item.y - 8, "text-anchor": "middle"}, "node-title bus-title");
        text.textContent = "Communication bus";
        g.append(text);
        const sub = svgEl("text", {x: item.x + item.w / 2, y: item.y + item.h + 16, "text-anchor": "middle"}, "node-sub");
        g.append(sub);
        this.elements.nodes.set(node.id, {g, sub, item, node});
      } else {
        g.append(svgEl("rect", {x: item.x, y: item.y, width: item.w, height: item.h, rx: 9}, "node-box"));
        g.append(svgEl("rect", {x: item.x, y: item.y, width: 4, height: item.h, rx: 2}, "node-accent"));
        const compact = item.h < 40;
        const titleY = compact ? item.y + item.h / 2 + 4 : item.y + Math.min(21, item.h / 2 - 1);
        const glyph = svgEl("text", {x: item.x + 12, y: titleY}, "node-glyph");
        glyph.textContent = TYPE_GLYPH[node.type] || "•";
        const glyphWidth = String(glyph.textContent).length * 7.2 + 12;
        const sharedBadge = node.shared && (node.type === "tool" || node.type === "model_service");
        // Preview elements are labelled at canvas level and by their dotted outline.
        const badgeText = !["configured", "preview"].includes(node.provenance) ? node.provenance : (sharedBadge ? "shared" : null);
        // Narrow nodes rely on the dashed outline (see legend) instead of a text badge.
        const badgeWidth = badgeText && !compact && item.w >= 170 ? badgeText.length * 6.6 + 12 : 0;
        const titleRoom = compact ? item.w * 0.42 : item.w - glyphWidth - 22 - badgeWidth;
        const title = svgEl("text", {x: item.x + 12 + glyphWidth, y: titleY}, "node-title");
        title.textContent = truncate(node.label, titleRoom, 13);
        const sub = svgEl("text", {x: compact ? item.x + item.w - 10 : item.x + 12, y: compact ? titleY : item.y + item.h - (item.h >= 50 ? 13 : 9),
          "text-anchor": compact ? "end" : "start"}, "node-sub");
        g.append(glyph, title, sub);
        if (badgeWidth) {
          const badge = svgEl("text", {x: item.x + item.w - 9, y: titleY - 1, "text-anchor": "end"}, badgeText === "shared" ? "node-badge" : "node-prov");
          badge.textContent = badgeText; g.append(badge);
        }
        const ring = svgEl("rect", {x: item.x - 3, y: item.y - 3, width: item.w + 6, height: item.h + 6, rx: 11}, "node-ring");
        g.insertBefore(ring, g.firstChild);
        this.elements.nodes.set(node.id, {g, sub, item, node});
      }
      const tip = svgEl("title"); tip.textContent = `${node.label} — ${node.type.replace(/_/g, " ")} · ${node.provenance}${node.shared ? " · shared" : ""}`; g.append(tip);
      const select = (event) => { event.stopPropagation(); this.handlers.onSelectNode?.(node.id); };
      g.addEventListener("click", select);
      g.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(event); } });
      this.layers.nodes.append(g);
    }

    buildEdge(edge) {
      const a = visibleNode(this.layout, edge.source); const b = visibleNode(this.layout, edge.target);
      if (!a || !b || a === b) return;
      const points = edgeGeometry(edge, a, b, this.layout);
      if (!points) return;
      const memoryEdge = edge.edge_type === "memory";
      const g = svgEl("g", {"data-edge": edge.id}, `edge edge-${edge.edge_type} prov-${edge.provenance}${edge.infra ? " infra" : ""}${memoryEdge ? " memory-edge" : ""}`);
      const base = svgEl("path", {d: pathData(points), "marker-end": "url(#arrow-idle)"}, "edge-line");
      const hit = svgEl("path", {d: pathData(points)}, "edge-hit");
      const tip = svgEl("title"); tip.textContent = `${edge.source} → ${edge.target} · ${edge.edge_type}${edge.label ? ` · ${edge.label}` : ""}`;
      hit.append(tip);
      hit.addEventListener("click", (event) => { event.stopPropagation(); this.handlers.onSelectEdge?.(edge.id); });
      g.append(base, hit);
      this.layers.edges.append(g);
      this.elements.edges.set(edge.id, {g, base, points, edge});
    }

    overlay(edgeId, direction) {
      const key = `${edgeId}|${direction}`;
      if (this.elements.overlays.has(key)) return this.elements.overlays.get(key);
      const edge = this.elements.edges.get(edgeId);
      if (!edge) return null;
      const id = `flow-${this.elements.overlays.size}`;
      const path = svgEl("path", {id, d: pathData(edge.points, direction === "reverse")}, "flow");
      this.layers.overlays.append(path);
      const value = {path, id};
      this.elements.overlays.set(key, value);
      return value;
    }

    applyRootClasses() {
      if (!this.svg) return;
      const o = this.options;
      this.svg.classList.toggle("mode-live", o.mode === "live");
      for (const scope of ["preview", "configured", "run"]) this.svg.classList.toggle(`scope-${scope}`, (this.topology?.scope || "run") === scope);
      this.svg.classList.toggle("hide-memory-flows", !o.showMemoryFlows);
      this.svg.classList.toggle("show-infra", Boolean(o.showInfra));
      const motion = !root.StudioTheme || root.StudioTheme.animationEnabled();
      this.svg.classList.toggle("animate", Boolean(o.animate) && motion);
    }

    /**
     * Update activity visuals without rebuilding nodes or edges.
     * `focus` = {selected: highlight|null, latest: highlight|null}
     */
    update(state, focus, labels) {
      if (!this.svg || !state) return;
      const A = root.StudioActivity;
      // Internal machinery (model requests in flight) is drawn only in technical mode.
      const shown = (open) => this.options.technical || !TECHNICAL_OPEN.has(open.kind);
      const running = new Map([...A.runningByNode(state)].map(([id, list]) => [id, list.filter(shown)]).filter(([, list]) => list.length));
      const overlayStyle = new Map();
      const setOverlay = (hop, style, level) => {
        const key = `${hop.edgeId}|${hop.direction}`;
        const rank = {running: 1, pending: 1, latest: 2, selected: 3}[level];
        const current = overlayStyle.get(key);
        if (!current || current.rank <= rank) overlayStyle.set(key, {style, level, rank, hop});
      };
      for (const open of state.open.values()) {
        if (!shown(open)) continue;
        const pending = ["assignment", "verification_request", "question", "peer_message", "message", "report", "reply", "failure_report", "cancellation"].includes(open.kind);
        for (const hop of open.hops) setOverlay(hop, pending ? "pending" : (open.style || "request"), pending ? "pending" : "running");
      }
      if (focus.latest) for (const hop of focus.latest.hops) setOverlay(hop, focus.latest.style, "latest");
      if (focus.selected) for (const hop of focus.selected.hops) setOverlay(hop, focus.selected.style, "selected");

      for (const [key, value] of this.elements.overlays) {
        if (!overlayStyle.has(key)) value.path.setAttribute("class", "flow");
      }
      for (const [key, value] of overlayStyle) {
        const overlay = this.overlay(value.hop.edgeId, value.hop.direction);
        if (!overlay) continue;
        overlay.path.setAttribute("class", `flow on flow-${value.style} level-${value.level}`);
        overlay.path.setAttribute("marker-end", `url(#arrow-${value.style})`);
        overlay.key = key;
      }
      const activeEdges = new Set([...overlayStyle.values()].map((value) => value.hop.edgeId));
      for (const [id, edge] of this.elements.edges) edge.g.classList.toggle("is-active", activeEdges.has(id));

      const focusNodes = new Set([...(focus.latest?.nodes || []), ...(focus.selected?.nodes || [])].map((id) => this.drawnId(id)));
      const selectedNodes = new Set((focus.selected?.nodes || []).map((id) => this.drawnId(id)));
      const runningDrawn = new Map();
      for (const [id, list] of running) { const drawn = this.drawnId(id); if (drawn) runningDrawn.set(drawn, [...(runningDrawn.get(drawn) || []), ...list]); }
      for (const [id, entry] of this.elements.nodes) {
        const nodeState = state.nodes.get(id) || {};
        const runs = runningDrawn.get(id) || [];
        const toolRuns = runs.filter((open) => open.kind === "tool_running" || open.kind === "tool_request");
        entry.g.classList.toggle("is-active", focusNodes.has(id));
        entry.g.classList.toggle("is-selected-path", selectedNodes.has(id));
        entry.g.classList.toggle("is-running", runs.some((open) => !["assignment", "verification_request", "question", "peer_message", "message", "report", "reply"].includes(open.kind)));
        entry.g.classList.toggle("is-queued", runs.some((open) => ["assignment", "verification_request", "question", "peer_message", "message", "report", "reply"].includes(open.kind)));
        entry.g.classList.toggle("has-failures", (nodeState.failures || 0) > 0);
        entry.g.classList.toggle("is-touched", Boolean(nodeState.lastEventId));
        entry.g.classList.toggle("is-picked", this.selection.nodeId === id);
        const text = labels(entry.node, state, toolRuns, runs);
        if (entry.sub.textContent !== text) entry.sub.textContent = truncate(text, entry.item.bus ? 200 : entry.item.h < 40 ? entry.item.w * 0.5 : entry.item.w - 24, 11);
      }
      for (const [id, edge] of this.elements.edges) edge.g.classList.toggle("is-picked", this.selection.edgeId === id);
      this.svg.classList.toggle("has-focus", focusNodes.size > 0 || state.open.size > 0);
    }

    drawnId(id) { const item = visibleNode(this.layout, id); return item ? item.id : null; }

    /** One-shot traveling signal along each hop, in travel order. */
    pulse(highlight) {
      if (!this.svg || !this.options.animate || !highlight?.hops?.length) return;
      if (root.StudioTheme && !root.StudioTheme.animationEnabled()) return;
      highlight.hops.forEach((hop, index) => {
        const overlay = this.overlay(hop.edgeId, hop.direction);
        if (!overlay) return;
        const dot = svgEl("circle", {r: 4.5}, `signal signal-${highlight.style}`);
        const motion = svgEl("animateMotion", {dur: "0.55s", begin: "indefinite", fill: "freeze", rotate: "auto"});
        const mpath = svgEl("mpath"); mpath.setAttribute("href", `#${overlay.id}`);
        motion.append(mpath); dot.append(motion);
        this.layers.signals.append(dot);
        root.setTimeout(() => { try { motion.beginElement(); } catch { /* SMIL unavailable */ } }, index * 420);
        root.setTimeout(() => dot.remove(), index * 420 + 900);
      });
    }

    // ---- navigation -----------------------------------------------------
    setView(view) {
      this.view = {...view};
      this.svg?.setAttribute("viewBox", `${view.x.toFixed(1)} ${view.y.toFixed(1)} ${view.w.toFixed(1)} ${view.h.toFixed(1)}`);
    }

    fit() {
      if (!this.layout) return;
      this.setView({x: 0, y: 0, w: this.layout.width, h: this.layout.height});
    }

    zoom(factor, centerX, centerY) {
      if (!this.view) return;
      const v = this.view;
      const w = Math.max(240, Math.min(this.layout.width * 3, v.w / factor));
      const h = w * (v.h / v.w);
      const fx = centerX ?? v.x + v.w / 2; const fy = centerY ?? v.y + v.h / 2;
      this.setView({x: fx - (fx - v.x) * (w / v.w), y: fy - (fy - v.y) * (h / v.h), w, h});
    }

    focusNodes(ids) {
      const items = ids.map((id) => visibleNode(this.layout, id)).filter(Boolean);
      if (!items.length) return false;
      const x1 = Math.min(...items.map((n) => n.x)) - 60; const y1 = Math.min(...items.map((n) => n.y)) - 60;
      const x2 = Math.max(...items.map((n) => n.x + n.w)) + 60; const y2 = Math.max(...items.map((n) => n.y + n.h)) + 60;
      const ratio = this.layout.height / this.layout.width;
      let w = Math.max(420, x2 - x1); let h = Math.max(w * ratio, y2 - y1); w = Math.max(w, h / ratio);
      this.setView({x: (x1 + x2) / 2 - w / 2, y: (y1 + y2) / 2 - h / 2, w, h});
      return true;
    }

    clientToGraph(event) {
      const rect = this.svg.getBoundingClientRect();
      const scale = Math.max(this.view.w / rect.width, this.view.h / rect.height);
      const offsetX = (rect.width * scale - this.view.w) / 2; const offsetY = (rect.height * scale - this.view.h) / 2;
      return {x: this.view.x + (event.clientX - rect.left) * scale - offsetX, y: this.view.y + (event.clientY - rect.top) * scale - offsetY, scale};
    }

    installNavigation(svg, background) {
      svg.addEventListener("wheel", (event) => {
        if (!event.ctrlKey && !event.metaKey && !this.options.wheelZoom) return;
        event.preventDefault();
        const point = this.clientToGraph(event);
        this.zoom(event.deltaY < 0 ? 1.12 : 1 / 1.12, point.x, point.y);
      }, {passive: false});
      svg.addEventListener("pointerdown", (event) => {
        if (event.target !== background && event.target !== svg) return;
        this.drag = {start: this.clientToGraph(event), view: {...this.view}, id: event.pointerId, moved: false};
        svg.setPointerCapture(event.pointerId);
        svg.classList.add("panning");
      });
      svg.addEventListener("pointermove", (event) => {
        if (!this.drag || event.pointerId !== this.drag.id) return;
        const rect = svg.getBoundingClientRect();
        const scale = Math.max(this.drag.view.w / rect.width, this.drag.view.h / rect.height);
        const dx = (event.clientX - (this.drag.clientX ?? event.clientX)) * scale;
        const dy = (event.clientY - (this.drag.clientY ?? event.clientY)) * scale;
        this.drag.clientX = event.clientX; this.drag.clientY = event.clientY;
        if (Math.abs(dx) + Math.abs(dy) > 0) this.drag.moved = true;
        this.setView({...this.view, x: this.view.x - dx, y: this.view.y - dy});
      });
      const end = (event) => {
        if (!this.drag) return;
        const moved = this.drag.moved;
        this.drag = null; svg.classList.remove("panning");
        try { svg.releasePointerCapture(event.pointerId); } catch { /* already released */ }
        if (!moved) this.handlers.onBackground?.();
      };
      svg.addEventListener("pointerup", end);
      svg.addEventListener("pointercancel", end);
    }
  }

  /**
   * Generic, non-sensitive framework preview shown before authentication.
   * Every element has provenance "preview": it describes component kinds, not
   * a configuration or a run, and it never carries activity.
   */
  function previewTopology() {
    const nodes = []; const edges = [];
    const node = (id, type, label, group, owner = null, shared = false) => nodes.push(
      {id, type, label, group, owner_agent_id: owner, shared, provenance: "preview", status: "preview", metadata: {}});
    const edge = (source, target, type, infra = false) => edges.push(
      {id: `${source}->${target}`, source, target, edge_type: type, direction: "source_to_target", provenance: "preview", infra, label: null, metadata: {}});
    node("task", "task", "Task input", "run"); node("orchestrator", "orchestrator", "Run orchestrator", "run");
    node("result", "result", "Final answer", "run");
    node("budget", "budget", "Global budget manager", "infrastructure", null, true);
    node("event_log", "event_log", "Event recorder", "infrastructure", null, true);
    node("artifact_store", "artifact_store", "Shared evidence store", "infrastructure", null, true);
    node("comm_bus", "communication", "Communication bus", "communication", null, true);
    node("model_service:preview", "model_service", "Model service", "services", null, true);
    node("tool:preview", "tool", "Visual tools", "services", null, true);
    edge("task", "orchestrator", "input"); edge("orchestrator", "coordinator", "control");
    edge("orchestrator", "event_log", "record", true); edge("event_log", "artifact_store", "evidence", true);
    edge("coordinator", "result", "synthesis"); edge("comm_bus", "budget", "budget", true);
    for (const [id, type, label] of [["coordinator", "coordinator", "Coordinator"], ["worker_template", "worker", "Worker agent"]]) {
      const group = `group:${id}`;
      node(id, type, label, group, id);
      node(`${id}.harness`, "harness", "Harness", group, id);
      node(`${id}.model_client`, "model_client", "Model client", group, id);
      node(`${id}.memory`, "memory", id === "coordinator" ? "Coordinator memory" : "Private memory", group, id);
      edge(id, `${id}.harness`, "invocation"); edge(`${id}.harness`, `${id}.model_client`, "model");
      edge(`${id}.harness`, `${id}.memory`, "memory"); edge(id, "comm_bus", "message");
      edge(`${id}.harness`, "budget", "budget", true); edge(`${id}.model_client`, "model_service:preview", "model");
    }
    node("worker_template.tool_router", "tool_router", "Tool router", "group:worker_template", "worker_template");
    edge("worker_template.harness", "worker_template.tool_router", "tool");
    edge("worker_template.tool_router", "tool:preview", "tool");
    return {
      schema_version: "studio.topology.v1", scope: "preview", run_id: null, source: "preview",
      agents: ["coordinator", "worker_template"],
      groups: [
        {id: "group:coordinator", agent_id: "coordinator", kind: "coordinator", label: "Coordinator", role: "plans · delegates · synthesizes"},
        {id: "group:worker_template", agent_id: "worker_template", kind: "worker_template", label: "Worker agents ×N", role: "each worker: isolated harness, client, memory"},
      ],
      nodes, edges, fingerprint: "preview-v1",
    };
  }

  return {layoutTopology, visibleNode, edgeGeometry, pathData, ArchitectureGraph, truncate, previewTopology, LAYOUT: L};
});
