"use strict";
/*
 * Fold a visible event prefix into architecture activity state.
 *
 * Pure and deterministic: given a topology and the first K annotated events,
 * the result never depends on event K+1 or later. Each event carries the
 * server-computed `activity` annotation (studio.activity.v1); this module
 * resolves its hops to topology edges and tracks open (running) work by the
 * annotation's correlation ID, so concurrent calls never merge.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.StudioActivity = api;
})(typeof self !== "undefined" ? self : this, function () {
  const OPENING = new Set(["open"]);
  const CLOSING = new Set(["close"]);
  const AGENT_EVENTS = {
    WORKER_STARTED: "running",
    PEER_REVIEW_STARTED: "reviewing",
    PEER_REVIEW_FINISHED: "completed",
  };

  /** Classify an activity kind into a visual flow style. */
  function flowStyle(kind) {
    switch (kind) {
      case "tool_request": case "tool_running": return "request";
      case "tool_result": case "evidence": return "response";
      case "tool_failure": case "tool_denied": case "budget_deny": case "message_rejected": case "model_failure": return "failure";
      case "tool_cancelled": return "cancelled";
      case "memory_write": case "memory_read": return "memory";
      case "model_request": return "model";
      case "model_response": return "model-return";
      case "budget_grant": return "budget";
      case "assignment": case "verification_request": case "cancellation": return "control";
      case "reply": case "report": case "failure_report": return "message-return";
      case "message_delivery": return "delivery";
      case "question": case "peer_message": case "message": return "message";
      default: return "lifecycle";
    }
  }

  function createIndex(topology) {
    const nodes = new Map((topology?.nodes || []).map((node) => [node.id, node]));
    const edges = new Map((topology?.edges || []).map((edge) => [edge.id, edge]));
    return {nodes, edges};
  }

  /** Map a directed hop to a structural edge and travel direction. */
  function resolveHop(index, hop) {
    if (!hop || !hop.from || !hop.to) return null;
    const forward = `${hop.from}->${hop.to}`;
    if (index.edges.has(forward)) return {edgeId: forward, direction: "forward", from: hop.from, to: hop.to};
    const reverse = `${hop.to}->${hop.from}`;
    if (index.edges.has(reverse)) return {edgeId: reverse, direction: "reverse", from: hop.from, to: hop.to};
    return null;
  }

  function createState(topology) {
    const index = createIndex(topology);
    const state = {
      index,
      count: 0,
      nodes: new Map(),
      edges: new Map(),
      open: new Map(),
      agents: new Map(),
      runStatus: null,
      lastEvent: null,
      unresolvedHops: 0,
    };
    for (const node of topology?.nodes || []) {
      state.nodes.set(node.id, {status: "idle", events: [], failures: 0, requests: 0, lastEventId: null});
    }
    for (const id of topology?.agents || []) {
      state.agents.set(id, {status: "idle", subtask: null, candidate: null, tools: new Map()});
    }
    return state;
  }

  function touchNode(state, id, event) {
    if (!id) return null;
    let node = state.nodes.get(id);
    if (!node) {
      node = {status: "idle", events: [], failures: 0, requests: 0, lastEventId: null, unknown: true};
      state.nodes.set(id, node);
    }
    if (node.lastEventId === event.event_id) return node;
    node.lastEventId = event.event_id;
    node.touches = (node.touches || 0) + 1;
    node.events.push(event.event_id);
    if (node.events.length > 60) node.events.shift();
    return node;
  }

  function hopsFor(state, activity) {
    const resolved = [];
    for (const hop of activity?.path || []) {
      const value = resolveHop(state.index, hop);
      if (value) resolved.push(value); else state.unresolvedHops += 1;
    }
    return resolved;
  }

  function agentRecord(state, id) {
    if (!state.agents.has(id)) state.agents.set(id, {status: "idle", subtask: null, candidate: null, tools: new Map()});
    return state.agents.get(id);
  }

  /** Apply one annotated event (the (count)th visible event). */
  function applyEvent(state, event) {
    const activity = event.activity || null;
    const position = state.count;
    state.count += 1;
    state.lastEvent = event;
    if (!activity) return state;
    const hops = hopsFor(state, activity);
    const style = flowStyle(activity.kind);
    for (const hop of hops) {
      let edge = state.edges.get(hop.edgeId);
      if (!edge) { edge = {events: [], last: null, failures: 0}; state.edges.set(hop.edgeId, edge); }
      edge.events.push(event.event_id);
      if (edge.events.length > 80) edge.events.shift();
      edge.last = {eventId: event.event_id, direction: hop.direction, style, kind: activity.kind, position};
      if (style === "failure") edge.failures += 1;
    }
    for (const id of activity.nodes || []) touchNode(state, id, event);

    const corr = activity.correlation_id;
    if (corr && OPENING.has(activity.phase)) {
      state.open.set(corr, {
        correlationId: corr, kind: activity.kind, agentId: event.agent_id, startedEventId: event.event_id,
        latestEventId: event.event_id, hops, nodes: [...(activity.nodes || [])], toolNode: activity.tool_node || null,
        label: activity.label, style: style === "request" ? "request" : style, position,
      });
    } else if (corr && activity.phase === "progress" && state.open.has(corr)) {
      const open = state.open.get(corr);
      open.hops = [...open.hops, ...hops];
      open.nodes = [...new Set([...open.nodes, ...(activity.nodes || [])])];
      open.latestEventId = event.event_id;
      open.kind = activity.kind;
      open.toolNode = activity.tool_node || open.toolNode;
      open.label = activity.label;
    } else if (corr && activity.phase === "progress") {
      // A progress event whose opening event is outside the visible prefix
      // (should not happen for ordered logs) still marks real running work.
      state.open.set(corr, {
        correlationId: corr, kind: activity.kind, agentId: event.agent_id, startedEventId: event.event_id,
        latestEventId: event.event_id, hops, nodes: [...(activity.nodes || [])], toolNode: activity.tool_node || null,
        label: activity.label, style: "request", position,
      });
    } else if (corr && CLOSING.has(activity.phase)) {
      state.open.delete(corr);
    }

    // Tool node bookkeeping.
    if (activity.tool_node) {
      const tool = touchNode(state, activity.tool_node, event);
      if (activity.kind === "tool_running") tool.requests += 1;
      if (activity.kind === "tool_failure") tool.failures += 1;
    }

    // Agent lifecycle derived only from recorded events.
    const agent = event.agent_id;
    if (state.agents.has(agent) || /^worker_\d+$/.test(agent) || agent === "coordinator") {
      const record = agentRecord(state, agent);
      const payload = event.payload || {};
      if (AGENT_EVENTS[event.event_type]) record.status = AGENT_EVENTS[event.event_type];
      if (event.event_type === "WORKER_FINISHED") record.status = String(payload.status || event.status || "completed").toLowerCase();
      if (event.event_type === "HYPOTHESIS_UPDATED" && payload.hypothesis !== undefined) record.candidate = payload.hypothesis;
      if (event.event_type === "FINAL_ANSWER_RECORDED") { record.status = "completed"; record.candidate = payload.final_answer ?? payload.answer ?? record.candidate; }
      if (event.event_type === "COORDINATOR_SYNTHESIS" || event.event_type === "FINAL_SYNTHESIZED") record.status = "synthesizing";
      if (event.event_type === "COORDINATOR_PLAN_RECORDED" || event.event_type === "PLAN_CREATED") {
        record.status = "delegating";
        for (const item of payload.assignments || []) {
          if (item && item.worker_id) {
            const worker = agentRecord(state, item.worker_id);
            worker.subtask = item.scope || worker.subtask;
            if (worker.status === "idle") worker.status = "assigned";
          }
        }
      }
      if (activity.kind === "tool_running" && event.tool_name) {
        record.tools.set(event.tool_name, (record.tools.get(event.tool_name) || 0) + 1);
      }
    }
    if (event.event_type === "RUN_STATE_CHANGED") {
      state.runStatus = event.payload?.to || state.runStatus;
      const coordinator = agentRecord(state, "coordinator");
      if (state.runStatus === "PLANNING") coordinator.status = "planning";
      if (state.runStatus === "SYNTHESIZING") coordinator.status = "synthesizing";
    }
    if (event.event_type === "RUN_COMPLETED") state.runStatus = "COMPLETED";
    if (event.event_type === "RUN_FAILED") state.runStatus = "FAILED";
    if (event.event_type === "RUN_CANCELLED") state.runStatus = "CANCELLED";
    return state;
  }

  /** Compute state for the first `count` events. */
  function computeState(topology, events, count) {
    const state = createState(topology);
    const limit = Math.max(0, Math.min(events.length, count ?? events.length));
    for (let i = 0; i < limit; i += 1) applyEvent(state, events[i]);
    return state;
  }

  /** Running work per node: open correlations touching each node. */
  function runningByNode(state) {
    const result = new Map();
    for (const open of state.open.values()) {
      const targets = new Set([...open.nodes, open.toolNode].filter(Boolean));
      for (const id of targets) {
        if (!result.has(id)) result.set(id, []);
        result.get(id).push(open);
      }
    }
    return result;
  }

  /** Human status line for an agent node. */
  function agentStatusLine(state, agentId) {
    const record = state.agents.get(agentId);
    if (!record) return "Idle";
    const tools = [...state.open.values()].filter((open) => open.agentId === agentId && open.toolNode && open.kind.startsWith("tool"));
    if (tools.length) return `Running: ${tools.map((open) => open.toolNode.replace(/^tool:/, "")).join(", ")}`;
    const model = [...state.open.values()].some((open) => open.agentId === agentId && open.kind === "model_request");
    if (model) return "Awaiting model response";
    const status = record.status || "idle";
    return status.charAt(0).toUpperCase() + status.slice(1).replace(/_/g, " ");
  }

  /** Visual highlights for an activity annotation (selected or latest event). */
  function highlightFor(state, event) {
    if (!event || !event.activity) return {hops: [], nodes: [], style: null};
    const hops = [];
    for (const hop of event.activity.path || []) {
      const value = resolveHop(state.index, hop);
      if (value) hops.push(value);
    }
    return {hops, nodes: [...(event.activity.nodes || [])], style: flowStyle(event.activity.kind), activity: event.activity};
  }

  return {flowStyle, resolveHop, createIndex, createState, applyEvent, computeState, runningByNode, agentStatusLine, highlightFor};
});
