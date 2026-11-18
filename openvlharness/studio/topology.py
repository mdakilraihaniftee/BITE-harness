"""Sanitized architecture topology and event-to-graph activity mapping.

The Studio draws one canonical graph for both live streaming and replay. This
module builds that graph from authoritative run metadata (the run manifest's
``topology`` section written by the orchestrator, with fallbacks for older
manifests) and annotates each recorded event with the graph path it actually
travelled.

Provenance vocabulary used on nodes and edges:

``configured``
    Declared by the run manifest or resolved run configuration.
``observed``
    Not declared, but referenced by a recorded event (for example a tool name
    in an older run that predates the topology manifest).
``inferred``
    A structural component that the runtime always creates (for example a
    worker harness) but that an older manifest did not describe explicitly.

Every activity annotation is computed from the event itself plus *earlier*
events only, so a replay prefix never learns about a future response.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

TOPOLOGY_SCHEMA = "studio.topology.v1"
ACTIVITY_SCHEMA = "studio.activity.v1"

_SECRET_KEY = re.compile(
    r"(key|token|secret|password|authorization|credential)", re.IGNORECASE
)
_WORKER_ID = re.compile(r"^worker_[0-9]{2,}$")


# ---------------------------------------------------------------------------
# Sanitization


def display_endpoint(value: Any) -> str | None:
    """Return a scheme/host/port/path view of a URL without credentials or query."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if not parts.scheme or not parts.hostname:
        return None
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = f"{host}:{port}" if port else host
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def sanitize(value: Any, depth: int = 0) -> Any:
    """Recursively drop secret-looking keys and strip credentials from URLs."""
    if depth > 8:
        return None
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if _SECRET_KEY.search(str(key)):
                clean[key] = "<redacted>"
            elif str(key).lower() in {"endpoint", "server_url", "base_url", "url"}:
                clean[key] = display_endpoint(item) if item else item
            else:
                clean[key] = sanitize(item, depth + 1)
        return clean
    if isinstance(value, list):
        return [sanitize(item, depth + 1) for item in value[:200]]
    if isinstance(value, str) and re.match(
        r"^[a-z][a-z0-9+.-]*://", value, re.IGNORECASE
    ):
        shown = display_endpoint(value)
        return shown if shown is not None else "<redacted-url>"
    return value


def _service_key(model_id: Any, endpoint: Any) -> str:
    material = f"{model_id or ''}|{display_endpoint(endpoint) or ''}"
    return hashlib.sha256(material.encode()).hexdigest()[:12]


TEMPLATE_WORKER = "worker_template"


def agent_label(agent_id: str) -> str:
    if agent_id == "coordinator":
        return "Coordinator"
    if agent_id == TEMPLATE_WORKER:
        return "Worker template"
    if _WORKER_ID.fullmatch(agent_id):
        return f"Worker {int(agent_id.split('_')[1])}"
    return agent_id or "unknown"


def _tool_node_id(name: str) -> str:
    return "tool:" + re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:96]


# ---------------------------------------------------------------------------
# Topology construction


def _actor_ids(manifest: dict[str, Any], events: list[dict[str, Any]]) -> list[str]:
    topo = (
        manifest.get("topology") if isinstance(manifest.get("topology"), dict) else {}
    )
    ids: list[str] = []
    for actor_id in topo.get("actors") or {}:
        ids.append(str(actor_id))
    for actor_id in manifest.get("actors") or {}:
        ids.append(str(actor_id))
    count = manifest.get("worker_count")
    if isinstance(count, int) and 0 < count < 1000:
        ids.extend(f"worker_{index:02d}" for index in range(1, count + 1))
    for event in events:
        agent = str(event.get("agent_id") or "")
        if agent == "coordinator" or _WORKER_ID.fullmatch(agent):
            ids.append(agent)
        payload = event.get("payload") or {}
        for key in ("recipient_id", "sender_id", "worker_id"):
            other = str(payload.get(key) or "")
            if other == "coordinator" or _WORKER_ID.fullmatch(other):
                ids.append(other)
    unique = list(dict.fromkeys(ids))
    workers = sorted(item for item in unique if _WORKER_ID.fullmatch(item))
    if not workers and TEMPLATE_WORKER in unique:
        workers = [TEMPLATE_WORKER]
    return ["coordinator", *workers]


def build_topology(
    manifest: dict[str, Any] | None,
    events: list[dict[str, Any]],
    *,
    run_id: str,
) -> dict[str, Any]:
    """Build the canonical, sanitized architecture graph for one run."""
    manifest = manifest if isinstance(manifest, dict) else {}
    declared = (
        manifest.get("topology") if isinstance(manifest.get("topology"), dict) else {}
    )
    declared_actors = (
        declared.get("actors") if isinstance(declared.get("actors"), dict) else {}
    )
    legacy_actors = (
        manifest.get("actors") if isinstance(manifest.get("actors"), dict) else {}
    )

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    groups: list[dict[str, Any]] = []

    def node(
        node_id: str,
        node_type: str,
        label: str,
        *,
        group: str,
        provenance: str,
        owner: str | None = None,
        shared: bool = False,
        metadata: dict | None = None,
    ) -> None:
        if node_id in nodes:
            return
        nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "group": group,
            "owner_agent_id": owner,
            "shared": shared,
            "provenance": provenance,
            "status": "idle",
            "metadata": sanitize(metadata or {}),
        }

    def edge(
        source: str,
        target: str,
        edge_type: str,
        *,
        provenance: str,
        infra: bool = False,
        label: str | None = None,
    ) -> str:
        edge_id = f"{source}->{target}"
        if edge_id not in edges:
            edges[edge_id] = {
                "id": edge_id,
                "source": source,
                "target": target,
                "edge_type": edge_type,
                "direction": "source_to_target",
                "provenance": provenance,
                "infra": infra,
                "label": label,
                "metadata": {},
            }
        return edge_id

    # Run-level components.
    has_task = bool(manifest.get("original_task")) or any(
        e.get("event_type") == "TASK_RECEIVED" for e in events
    )
    node(
        "task",
        "task",
        "Original task",
        group="run",
        provenance="configured" if has_task else "inferred",
        metadata={"inputs": declared.get("inputs") or []},
    )
    node(
        "orchestrator",
        "orchestrator",
        "Run orchestrator",
        group="run",
        provenance="configured",
        metadata={"execution_mode": manifest.get("execution_mode")},
    )
    node(
        "budget",
        "budget",
        "Global budget manager",
        group="infrastructure",
        provenance=("configured" if declared.get("budget") else "inferred"),
        shared=True,
        metadata={"limits": declared.get("budget") or {}},
    )
    node(
        "event_log",
        "event_log",
        "Event recorder",
        group="infrastructure",
        provenance="configured",
        shared=True,
        metadata={"schema": "studio.event.v1"},
    )
    node(
        "artifact_store",
        "artifact_store",
        "Shared evidence store",
        group="infrastructure",
        provenance="configured",
        shared=True,
        metadata={"addressing": "sha256 content IDs"},
    )
    node(
        "comm_bus",
        "communication",
        "Communication bus",
        group="communication",
        provenance="configured" if declared.get("communication") else "inferred",
        shared=True,
        metadata=declared.get("communication") or {},
    )
    node("result", "result", "Final answer", group="run", provenance="configured")
    edge(
        "task", "orchestrator", "input", provenance="configured", label="task + inputs"
    )
    edge(
        "orchestrator",
        "coordinator",
        "control",
        provenance="configured",
        label="start run",
    )
    edge("orchestrator", "event_log", "record", provenance="configured", infra=True)
    edge(
        "event_log",
        "artifact_store",
        "evidence",
        provenance="configured",
        infra=True,
        label="extract visual artifacts",
    )
    edge(
        "coordinator",
        "result",
        "synthesis",
        provenance="configured",
        label="final answer",
    )
    # CommunicationBus.send reserves message budget on the sender's behalf.
    edge(
        "comm_bus",
        "budget",
        "budget",
        provenance="configured",
        infra=True,
        label="message reservations",
    )

    actor_ids = _actor_ids(manifest, events)
    observed_tools: dict[str, set[str]] = {}
    for event in events:
        name = event.get("tool_name")
        agent = str(event.get("agent_id") or "")
        if isinstance(name, str) and name:
            observed_tools.setdefault(name, set()).add(agent)

    model_services: dict[str, dict[str, Any]] = {}
    tool_services: dict[str, dict[str, Any]] = {}

    for actor_id in actor_ids:
        is_coordinator = actor_id == "coordinator"
        spec = (
            declared_actors.get(actor_id)
            if isinstance(declared_actors.get(actor_id), dict)
            else {}
        )
        legacy = (
            legacy_actors.get(actor_id)
            if isinstance(legacy_actors.get(actor_id), dict)
            else {}
        )
        actor_prov = "configured" if (spec or legacy) else "observed"
        structural = "configured" if spec else "inferred"
        group_id = f"group:{actor_id}"
        label = agent_label(actor_id)
        role = spec.get("role") or ("coordinator" if is_coordinator else None)
        groups.append(
            {
                "id": group_id,
                "agent_id": actor_id,
                "kind": "coordinator"
                if is_coordinator
                else ("worker_template" if actor_id == TEMPLATE_WORKER else "worker"),
                "label": label,
                "role": role,
            }
        )
        node(
            actor_id,
            "coordinator" if is_coordinator else "worker",
            label,
            group=group_id,
            owner=actor_id,
            provenance=actor_prov,
            metadata={"role": role},
        )
        harness = spec.get("harness") or {}
        node(
            f"{actor_id}.harness",
            "harness",
            "Harness",
            group=group_id,
            owner=actor_id,
            provenance=structural,
            metadata={
                "implementation": harness.get("implementation"),
                "max_iterations": harness.get("max_iterations"),
            },
        )
        model = spec.get("model_client") or {}
        model_id = model.get("model_id") or legacy.get("model_id")
        endpoint = model.get("endpoint") or legacy.get("endpoint")
        node(
            f"{actor_id}.model_client",
            "model_client",
            "Model client",
            group=group_id,
            owner=actor_id,
            provenance="configured" if (model or legacy) else "inferred",
            metadata={
                "model_id": model_id,
                "protocol": model.get("protocol"),
                "endpoint": display_endpoint(endpoint),
                "generation_options": legacy.get("generation_options")
                or model.get("generation_options")
                or {},
                "kind": model.get("kind") or ("remote" if endpoint else "unknown"),
            },
        )
        memory = spec.get("memory") or {}
        node(
            f"{actor_id}.memory",
            "memory",
            "Coordinator memory" if is_coordinator else "Private memory",
            group=group_id,
            owner=actor_id,
            provenance=structural,
            metadata={
                "scope": "private",
                "modules": memory.get("modules") or [],
                # Working context is always on; the optional notebook follows
                # the recorded run policy (None = not recorded, legacy run).
                "working_context": True,
                "optional_notebook": memory.get("optional_notebook"),
            },
        )
        edge(actor_id, f"{actor_id}.harness", "invocation", provenance=structural)
        edge(
            f"{actor_id}.harness",
            f"{actor_id}.model_client",
            "model",
            provenance=structural,
        )
        edge(
            f"{actor_id}.harness", f"{actor_id}.memory", "memory", provenance=structural
        )
        edge(actor_id, "comm_bus", "message", provenance="configured")
        edge(
            f"{actor_id}.harness",
            "budget",
            "budget",
            provenance="configured",
            infra=True,
        )

        if endpoint or model_id or model.get("kind"):
            key = (
                _service_key(model_id, endpoint)
                if (endpoint or model_id)
                else f"fixture-{actor_id}"
            )
            if model.get("kind") == "fixture":
                key = "fixture"
            service = model_services.setdefault(
                key,
                {
                    "id": f"model_service:{key}",
                    "model_id": model_id,
                    "endpoint": display_endpoint(endpoint),
                    "kind": model.get("kind") or "remote",
                    "clients": [],
                },
            )
            service["clients"].append(actor_id)
            edge(
                f"{actor_id}.model_client",
                service["id"],
                "model",
                provenance="configured",
            )

        declared_tools = (
            spec.get("tools") if isinstance(spec.get("tools"), list) else None
        )
        tools: list[tuple[dict[str, Any], str]] = []
        for tool in declared_tools or []:
            if isinstance(tool, dict) and tool.get("name"):
                tools.append((tool, "configured"))
        for name, agents in sorted(observed_tools.items()):
            if actor_id in agents and not any(
                item["name"] == name for item, _ in tools
            ):
                tools.append(({"name": name}, "observed"))
        if tools or spec.get("tool_access"):
            node(
                f"{actor_id}.tool_router",
                "tool_router",
                "Tool router",
                group=group_id,
                owner=actor_id,
                provenance=structural if declared_tools is not None else "inferred",
                metadata={"tools": [item["name"] for item, _ in tools]},
            )
            edge(
                f"{actor_id}.harness",
                f"{actor_id}.tool_router",
                "tool",
                provenance=structural,
            )
        for tool, provenance in tools:
            name = str(tool["name"])
            entry = tool_services.setdefault(
                name,
                {
                    "id": _tool_node_id(name),
                    "name": name,
                    "backend": tool.get("backend"),
                    "service": display_endpoint(tool.get("service")),
                    "users": [],
                    "provenance": provenance,
                },
            )
            entry["users"].append(actor_id)
            if provenance == "configured":
                entry["provenance"] = "configured"
                entry["backend"] = entry["backend"] or tool.get("backend")
                entry["service"] = entry["service"] or display_endpoint(
                    tool.get("service")
                )
            edge(f"{actor_id}.tool_router", entry["id"], "tool", provenance=provenance)

    for service in model_services.values():
        label = (
            "Fixture model (no service)"
            if service["kind"] == "fixture"
            else (str(service["model_id"] or "Model service").split("/")[-1])
        )
        node(
            service["id"],
            "model_service",
            label,
            group="services",
            provenance="configured",
            shared=True,
            metadata={
                "model_id": service["model_id"],
                "endpoint": service["endpoint"],
                "kind": service["kind"],
                "clients": service["clients"],
                "physical_instances": 1,
            },
        )
    for tool in sorted(tool_services.values(), key=lambda item: item["name"]):
        node(
            tool["id"],
            "tool",
            tool["name"],
            group="services",
            provenance=tool["provenance"],
            shared=len(tool["users"]) > 1,
            metadata={
                "backend": tool["backend"],
                "service": tool["service"],
                "users": tool["users"],
                "stateless_shared_service": True,
            },
        )

    return {
        "schema_version": TOPOLOGY_SCHEMA,
        "scope": "run",
        "run_id": run_id,
        "source": "manifest.topology"
        if declared
        else ("manifest.actors" if legacy_actors else "events"),
        "agents": actor_ids,
        "groups": groups,
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "fingerprint": hashlib.sha256(
            "|".join(sorted(nodes) + sorted(edges)).encode()
        ).hexdigest()[:16],
    }


# ---------------------------------------------------------------------------
# Event activity mapping

_MESSAGE_KINDS = {
    "TASK_ASSIGNMENT": "assignment",
    "VERIFICATION_REQUEST": "verification_request",
    "CANCELLATION": "cancellation",
    "CANDIDATE_ANSWER": "report",
    "STATUS_UPDATE": "report",
    "FINAL_RESULT": "report",
    "ERROR": "failure_report",
    "HYPOTHESIS": "peer_message",
    "EVIDENCE": "peer_message",
    "QUESTION": "question",
    "CONTRADICTION": "peer_message",
}

_TOOL_EVENTS = {
    "DECISION_SUMMARY_RECORDED",
    "TOOL_CALL_REQUESTED",
    "TOOL_CALL_STARTED",
    "TOOL_CALL_COMPLETED",
    "TOOL_CALL_FAILED",
    "TOOL_CALL_CANCELLED",
    "EVIDENCE_OBSERVED",
    "MEMORY_WRITTEN",
}


def _hop(source: str, target: str) -> dict[str, str]:
    """A directed hop along structural edge source->target or target->source."""
    return {"from": source, "to": target}


class ActivityMapper:
    """Stateful, prefix-only mapper from recorded events to graph activity.

    Instances are fed events in sequence order. State only grows from already
    seen events, so annotations for event K never depend on events after K.
    """

    def __init__(self, topology: dict[str, Any] | None = None) -> None:
        # Resolve each actor's shared model service from configured topology edges.
        self.model_service: dict[str, str] = {}
        for item in (topology or {}).get("edges", []):
            if item.get("source", "").endswith(".model_client") and str(
                item.get("target", "")
            ).startswith("model_service:"):
                self.model_service[item["source"].rsplit(".", 1)[0]] = item["target"]
        self.tool_corr_by_event: dict[str, str] = {}
        self.open_tool_by_key: dict[tuple[str, str], str] = {}
        self.tool_by_corr: dict[str, str] = {}
        self.messages: dict[str, dict[str, Any]] = {}
        self.open_model: dict[str, str] = {}

    _label = staticmethod(lambda agent_id: agent_label(agent_id))

    def _tool_correlation(self, event: dict[str, Any]) -> str:
        payload = event.get("payload") or {}
        agent = str(event.get("agent_id"))
        call_id = payload.get("tool_call_id")
        invocation = payload.get("invocation_id")
        etype = event["event_type"]
        corr: str | None = None
        if isinstance(invocation, str) and invocation:
            corr = f"inv:{invocation}"
        parent = event.get("parent_event_id")
        if corr is None and parent and parent in self.tool_corr_by_event:
            corr = self.tool_corr_by_event[parent]
        if (
            corr is None
            and call_id
            and etype not in {"DECISION_SUMMARY_RECORDED", "TOOL_CALL_REQUESTED"}
        ):
            corr = self.open_tool_by_key.get((agent, str(call_id)))
        if corr is None:
            corr = (
                f"call:{agent}:{call_id}:{event['event_id']}"
                if call_id
                else f"evt:{event['event_id']}"
            )
        self.tool_corr_by_event[event["event_id"]] = corr
        if call_id and etype in {
            "DECISION_SUMMARY_RECORDED",
            "TOOL_CALL_REQUESTED",
            "TOOL_CALL_STARTED",
        }:
            self.open_tool_by_key[(agent, str(call_id))] = corr
        return corr

    def annotate(self, event: dict[str, Any]) -> dict[str, Any] | None:
        etype = str(event.get("event_type"))
        agent = str(event.get("agent_id") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        tool = event.get("tool_name")
        actor = (
            agent if (agent == "coordinator" or _WORKER_ID.fullmatch(agent)) else None
        )
        name = self._label(agent)
        result: dict[str, Any] = {
            "schema_version": ACTIVITY_SCHEMA,
            "kind": "lifecycle",
            "phase": "instant",
            "path": [],
            "nodes": [],
            "correlation_id": None,
            "label": event.get("summary") or etype,
            "outcome": event.get("status"),
            "provenance": "recorded",
        }

        if etype in _TOOL_EVENTS and actor:
            corr = self._tool_correlation(event)
            tool_name = tool or self.tool_by_corr.get(corr)
            if tool_name:
                self.tool_by_corr[corr] = tool_name
            tool_node = _tool_node_id(tool_name) if tool_name else None
            harness, router = f"{actor}.harness", f"{actor}.tool_router"
            result["correlation_id"] = corr
            result["tool_node"] = tool_node
            if etype == "DECISION_SUMMARY_RECORDED":
                result.update(
                    kind="decision",
                    nodes=[actor],
                    label=f"{name} selected {tool_name or 'an action'}",
                )
            elif etype == "TOOL_CALL_REQUESTED":
                result.update(
                    kind="tool_request",
                    phase="open",
                    nodes=[actor, harness, router],
                    path=[_hop(actor, harness), _hop(harness, router)],
                    label=f"{name} → {tool_name}: request",
                )
            elif etype == "TOOL_CALL_STARTED":
                result.update(
                    kind="tool_running",
                    phase="progress",
                    nodes=[actor, router] + ([tool_node] if tool_node else []),
                    path=[_hop(router, tool_node)] if tool_node else [],
                    label=f"{name} → {tool_name}: invoking",
                )
            elif etype in {
                "TOOL_CALL_COMPLETED",
                "TOOL_CALL_FAILED",
                "TOOL_CALL_CANCELLED",
            }:
                error = (
                    payload.get("error")
                    if isinstance(payload.get("error"), dict)
                    else {}
                )
                code = error.get("code")
                denied = code == "budget_denied"
                never_reached = (
                    denied
                    or code in {"tool_not_found", "invalid_arguments"}
                    or bool(payload.get("parse_error"))
                )
                failed = etype == "TOOL_CALL_FAILED" or event.get("status") == "failed"
                cancelled = (
                    etype == "TOOL_CALL_CANCELLED" or event.get("status") == "cancelled"
                )
                path = [_hop(router, harness), _hop(harness, actor)]
                if tool_node and not never_reached:
                    path.insert(0, _hop(tool_node, router))
                kind = (
                    "tool_cancelled"
                    if cancelled
                    else (
                        "tool_denied"
                        if denied
                        else ("tool_failure" if failed else "tool_result")
                    )
                )
                verb = {
                    "tool_result": "result",
                    "tool_failure": "failed",
                    "tool_denied": "denied by budget",
                    "tool_cancelled": "cancelled",
                }[kind]
                nodes = [actor, harness, router] + (
                    [tool_node] if tool_node and not never_reached else []
                )
                if event.get("artifact_refs"):
                    nodes.append("artifact_store")
                result.update(
                    kind=kind,
                    phase="close",
                    nodes=nodes,
                    path=path,
                    label=f"{tool_name} → {name}: {verb}",
                    error_code=code,
                )
            elif etype == "EVIDENCE_OBSERVED":
                result.update(
                    kind="evidence",
                    nodes=[actor, harness],
                    path=[_hop(harness, actor)],
                    label=f"{tool_name or 'Tool'} evidence → {name} context",
                )
            elif etype == "MEMORY_WRITTEN":
                memory = f"{actor}.memory"
                result.update(
                    kind="memory_write",
                    nodes=[actor, harness, memory],
                    path=[_hop(harness, memory)],
                    label=f"{name} → private memory: write",
                )
            return result

        if etype in {"MEMORY_READ", "OPTIONAL_MEMORY_READ"} and actor:
            memory, harness = f"{actor}.memory", f"{actor}.harness"
            notebook = etype == "OPTIONAL_MEMORY_READ"
            result.update(
                kind="memory_read",
                nodes=[memory, harness, actor],
                path=[_hop(memory, harness)],
                label=f"{'Optional notebook' if notebook else 'Working memory'} → {name}: read",
                memory_kind="optional_episodic_notebook" if notebook else "working_context",
            )
            return result

        if etype == "OPTIONAL_MEMORY_WRITTEN" and actor:
            memory, harness = f"{actor}.memory", f"{actor}.harness"
            result.update(
                kind="memory_write",
                nodes=[actor, harness, memory],
                path=[_hop(harness, memory)],
                label=f"{name} → optional notebook: write",
                memory_kind="optional_episodic_notebook",
            )
            return result

        if (
            etype
            in {
                "MODEL_REQUEST_STARTED",
                "MODEL_RESPONSE_RECEIVED",
                "MODEL_REQUEST_FAILED",
            }
            and actor
        ):
            request_id = str(payload.get("request_id") or event["event_id"])
            corr = f"model:{actor}:{request_id}"
            harness, client = f"{actor}.harness", f"{actor}.model_client"
            service = self.model_service.get(actor)
            result["correlation_id"] = corr
            if etype == "MODEL_REQUEST_STARTED":
                path = [_hop(harness, client)] + (
                    [_hop(client, service)] if service else []
                )
                result.update(
                    kind="model_request",
                    phase="open",
                    nodes=[actor, harness, client] + ([service] if service else []),
                    path=path,
                    label=f"{name} → model: inference request",
                )
            else:
                failed = etype == "MODEL_REQUEST_FAILED"
                path = ([_hop(service, client)] if service else []) + [
                    _hop(client, harness)
                ]
                result.update(
                    kind="model_failure" if failed else "model_response",
                    phase="close",
                    nodes=[actor, harness, client] + ([service] if service else []),
                    path=path,
                    label=f"Model → {name}: {'request failed' if failed else 'response'}",
                )
            return result

        if etype in {"BUDGET_UPDATED", "BUDGET_RESERVATION"} and actor:
            granted = payload.get("granted") is not False
            resource = str(payload.get("resource") or "resource").replace("_", " ")
            origin = (
                actor if payload.get("resource") == "messages" else f"{actor}.harness"
            )
            if origin == actor:
                path = [_hop(actor, "comm_bus"), _hop("comm_bus", "budget")]
            else:
                path = [_hop(origin, "budget")]
            result.update(
                kind="budget_grant" if granted else "budget_deny",
                nodes=[actor, origin, "budget"],
                path=path,
                label=f"{name} ↔ budget: {resource} {'granted' if granted else 'denied'}",
                outcome="completed" if granted else "failed",
                resource=payload.get("resource"),
            )
            return result

        if etype in {"MESSAGE_SENT", "MESSAGE_REJECTED", "MESSAGE_DUPLICATE"} and actor:
            message_id = str(payload.get("message_id") or event["event_id"])
            recipient = str(
                payload.get("recipient_id")
                or self.messages.get(message_id, {}).get("recipient")
                or ""
            )
            mtype = str(
                payload.get("message_type")
                or self.messages.get(message_id, {}).get("type")
                or ""
            )
            reply_to = payload.get("correlation_id")
            kind = _MESSAGE_KINDS.get(mtype, "message")
            if isinstance(reply_to, str) and reply_to in self.messages:
                original = self.messages[reply_to]
                if original["sender"] == recipient and original["recipient"] == agent:
                    kind = "reply"
                else:
                    reply_to = None
            else:
                reply_to = None
            if etype == "MESSAGE_SENT":
                self.messages[message_id] = {
                    "sender": agent,
                    "recipient": recipient,
                    "type": mtype,
                    "event_id": event["event_id"],
                }
            rejected = etype != "MESSAGE_SENT"
            result.update(
                kind="message_rejected" if rejected else kind,
                phase="instant" if rejected else "open",
                correlation_id=f"msg:{message_id}",
                nodes=[actor, "comm_bus"]
                + ([recipient] if recipient and not rejected else []),
                path=[_hop(actor, "comm_bus")],
                label=(
                    f"{name} → {self._label(recipient)}: {mtype.replace('_', ' ').lower() or 'message'}"
                    + (" (rejected)" if rejected else "")
                ),
                sender=agent,
                recipient=recipient or None,
                message_type=mtype or None,
                reply_to=f"msg:{reply_to}" if reply_to else None,
                outcome="failed" if rejected else event.get("status"),
            )
            return result

        if etype in {"MESSAGE_DELIVERED", "MESSAGE_RECEIVED"} and actor:
            message_id = str(payload.get("message_id") or event["event_id"])
            known = self.messages.get(message_id, {})
            sender = str(payload.get("sender_id") or known.get("sender") or "")
            mtype = str(payload.get("message_type") or known.get("type") or "")
            result.update(
                kind="message_delivery",
                phase="close",
                correlation_id=f"msg:{message_id}",
                nodes=["comm_bus", actor] + ([sender] if sender else []),
                path=[_hop("comm_bus", actor)],
                label=f"{self._label(sender)} → {name}: {mtype.replace('_', ' ').lower() or 'message'} delivered",
                sender=sender or None,
                recipient=agent,
                message_type=mtype or None,
            )
            return result

        if etype == "TASK_RECEIVED":
            result.update(
                kind="task",
                nodes=["task", "orchestrator"],
                path=[_hop("task", "orchestrator")],
                label="Original task → orchestrator",
            )
        elif etype in {
            "RUN_STARTED",
            "RUN_STATE_CHANGED",
            "RUN_CANCELLED",
            "RUN_FAILED",
        }:
            result.update(kind="run_state", nodes=["orchestrator"])
            if etype == "RUN_STATE_CHANGED" and payload.get("to") == "PLANNING":
                result.update(
                    path=[_hop("orchestrator", "coordinator")],
                    nodes=["orchestrator", "coordinator"],
                    label="Orchestrator → coordinator: plan the task",
                )
        elif etype == "RUN_COMPLETED":
            result.update(kind="run_state", nodes=["orchestrator", "result"])
        elif etype in {"COORDINATOR_PLAN_RECORDED", "PLAN_CREATED"}:
            result.update(
                kind="plan",
                nodes=["coordinator"],
                label="Coordinator recorded assignments",
            )
        elif etype in {"COORDINATOR_SYNTHESIS", "FINAL_SYNTHESIZED"}:
            result.update(
                kind="synthesis",
                nodes=["coordinator"],
                label="Coordinator synthesized worker evidence",
            )
        elif etype == "FINAL_ANSWER_RECORDED":
            result.update(
                kind="final",
                nodes=["coordinator", "result"],
                path=[_hop("coordinator", "result")],
                label="Coordinator → final answer",
            )
        elif etype == "COORDINATOR_ESTIMATE_UPDATED":
            final = payload.get("status") in {"final", "abstained"}
            result.update(
                kind="estimate",
                nodes=["coordinator"] + (["result"] if final else []),
                path=[_hop("coordinator", "result")] if final else [],
                label=event.get("summary") or "Coordinator answer state updated",
            )
        elif etype == "COORDINATOR_REASSESSMENT_RECORDED":
            result.update(kind="assessment", nodes=["coordinator"])
        elif etype == "FOLLOW_UP_ASSIGNED":
            worker = str(payload.get("worker_id") or "")
            result.update(
                kind="delegation",
                nodes=["coordinator"] + ([worker] if worker else []),
                label=f"Coordinator delegated follow-up work to {self._label(worker)}",
            )
        elif etype in {
            "RUN_CONFIGURATION_RECORDED",
            "INVESTIGATION_ROUND_STARTED",
            "INVESTIGATION_ROUND_COMPLETED",
        }:
            result.update(kind="run_state", nodes=["orchestrator"])
        elif etype in {"VERIFICATION_REQUESTED", "VERIFICATION_REQUEST_REJECTED"}:
            worker = str(payload.get("worker_id") or "")
            result.update(
                kind="verification_request",
                nodes=["coordinator"] + ([worker] if worker else []),
                label=f"Coordinator requested verification from {self._label(worker)}",
                outcome="failed" if etype.endswith("REJECTED") else event.get("status"),
            )
        elif actor and etype in {
            "WORKER_STARTED",
            "WORKER_FINISHED",
            "PEER_REVIEW_STARTED",
            "PEER_REVIEW_FINISHED",
            "FOLLOW_UP_FINISHED",
            "HYPOTHESIS_UPDATED",
            "AGENT_ANSWER_RECORDED",
        }:
            result.update(kind="agent_status", nodes=[actor])
        elif actor:
            result.update(nodes=[actor])
        else:
            result.update(nodes=["orchestrator"] if agent == "orchestrator" else [])
        return result


def annotate_events(
    events: list[dict[str, Any]], topology: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Return shallow copies of ordered events with a prefix-only ``activity`` field."""
    mapper = ActivityMapper(topology)
    annotated = []
    for event in events:
        copy = dict(event)
        copy["activity"] = mapper.annotate(event)
        annotated.append(copy)
    return annotated


# ---------------------------------------------------------------------------
# Configured architecture (no run selected)


def _capability_name(name: str) -> str:
    """Public tool name declared by a capability class, without instantiating it."""
    try:
        import importlib

        module = importlib.import_module(f"openvlharness.capabilities.{name}")
        return str(module.Capability.name)
    except Exception:  # noqa: BLE001 - fall back to the configured key
        return name


def _resolved_endpoint(value: Any) -> str | None:
    """Expand ``${VAR}`` from the environment, then reduce to a display endpoint."""
    import os

    if not value:
        return None
    text = re.sub(
        r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
        lambda match: os.environ.get(match.group(1), match.group(0)),
        str(value),
    )
    return None if "${" in text else display_endpoint(text)


def _configured_agent(agent_config: Any) -> dict[str, Any]:
    """Describe one agent configuration: model, memory modules, and tools.

    Only declared configuration is read; no adapter, client, or service is
    contacted. Unresolved ``${VAR}`` placeholders are reported as unresolved.
    """
    import yaml

    raw: dict[str, Any] = {}
    if isinstance(agent_config, dict):
        raw = agent_config
    elif agent_config:
        try:
            with open(agent_config, encoding="utf-8") as stream:
                raw = yaml.safe_load(stream) or {}
        except (OSError, yaml.YAMLError):
            raw = {}
    services = raw.get("services") if isinstance(raw.get("services"), dict) else {}
    agent = raw.get("agent") if isinstance(raw.get("agent"), dict) else {}
    models = services.get("models") if isinstance(services.get("models"), dict) else {}
    model = models.get(agent.get("model_service")) or {}
    model_id = None
    if isinstance(model, dict) and model.get("alias"):
        try:
            from ..services.models import load_profile

            model_id = load_profile(model["alias"]).get("model_id")
        except Exception:  # noqa: BLE001 - unknown profile stays unknown
            model_id = None
    base = model.get("base") if isinstance(model, dict) else None
    endpoint = _resolved_endpoint(base)
    tools = []
    selected = (raw.get("capabilities") or {}).get("tools") or {}
    tool_services = (
        services.get("tools") if isinstance(services.get("tools"), dict) else {}
    )
    client = services.get("client") if isinstance(services.get("client"), dict) else {}
    for key, settings in sorted(selected.items()) if isinstance(selected, dict) else []:
        settings = settings if isinstance(settings, dict) else {}
        backend = settings.get("backend") or settings.get("generator")
        service_settings = (
            tool_services.get(backend)
            if isinstance(tool_services.get(backend), dict)
            else {}
        )
        url = service_settings.get("server_url") or client.get("base_url")
        tools.append(
            {
                "name": _capability_name(str(key)),
                "backend": backend,
                "service": _resolved_endpoint(url),
            }
        )
    modules = [
        str(entry.get("name"))
        for entry in ((raw.get("memory") or {}).get("modules") or [])
        if isinstance(entry, dict) and entry.get("name")
    ]
    return {
        "model_client": {
            "model_id": model_id
            or (model.get("alias") if isinstance(model, dict) else None),
            "endpoint": endpoint,
            "kind": "remote" if model else None,
        },
        "harness": {
            "implementation": raw.get("agent_name"),
            "max_iterations": agent.get("max_iterations"),
        },
        "memory": {"modules": modules},
        "tools": tools,
    }


def build_configured_topology(
    multi_agent_config: dict[str, Any] | None,
    *,
    agent_config: Any = None,
    source: str = "configuration",
) -> dict[str, Any]:
    """Configured architecture before any run: coordinator plus a worker template.

    Worker instances do not exist until a run starts, so a single labelled
    template stands for the configurable worker slots instead of inventing
    active workers. Nothing here is observed activity.
    """
    config = multi_agent_config if isinstance(multi_agent_config, dict) else {}
    workers = config.get("workers") if isinstance(config.get("workers"), dict) else {}
    default = workers.get("default") if isinstance(workers.get("default"), dict) else {}
    coordinator = (
        config.get("coordinator") if isinstance(config.get("coordinator"), dict) else {}
    )
    worker_spec = _configured_agent(agent_config or default.get("agent_config"))
    coordinator_spec = _configured_agent(
        agent_config or coordinator.get("agent_config")
    )
    tool_access = bool(coordinator.get("tool_access"))
    communication = (
        config.get("communication")
        if isinstance(config.get("communication"), dict)
        else {}
    )
    budget = config.get("budget") if isinstance(config.get("budget"), dict) else {}
    manifest = {
        "topology": {
            "communication": communication,
            "budget": {
                "tool_calls": budget.get("global_tool_calls"),
                "model_requests": budget.get("global_model_requests"),
                "messages": budget.get("global_messages"),
            },
            "actors": {
                "coordinator": {
                    **coordinator_spec,
                    "role": "coordinator",
                    "tool_access": tool_access,
                    "tools": coordinator_spec["tools"] if tool_access else [],
                },
                TEMPLATE_WORKER: {
                    **worker_spec,
                    "role": default.get("role") or "worker",
                    "tool_access": True,
                },
            },
        }
    }
    topology = build_topology(manifest, [], run_id="configured")
    for node in topology["nodes"]:
        if node["id"] == "task":
            node["label"] = "Task input"
            node["provenance"] = "configured"
        node["status"] = "configured"
    default_count = config.get("num_agents")
    max_count = config.get("max_agents")
    for group in topology["groups"]:
        if group["agent_id"] == TEMPLATE_WORKER:
            group["label"] = (
                f"Worker template ×{default_count or '?'} (up to {max_count or '?'})"
            )
    topology["scope"] = "configured"
    topology["source"] = source
    topology["worker_template"] = {
        "default_count": config.get("num_agents"),
        "max_count": config.get("max_agents"),
        "roles": {
            "default": default.get("role"),
            **{
                key: value.get("role")
                for key, value in (workers.get("overrides") or {}).items()
                if isinstance(value, dict) and value.get("role")
            },
        },
    }
    return topology
