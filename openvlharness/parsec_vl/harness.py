"""Run an agent's tool calls through the PARSEC-VL scheduler.

Integration path (``MainAgent`` calls ``ToolScheduling.run_turn`` when its
``tool_scheduler`` is set)::

    worker agent ── proposes calls (model output, unchanged)
        │  announce: DECISION_SUMMARY_RECORDED, TOOL_CALL_REQUESTED (agent thread)
        │  prepare:  argument validation + memory-reference resolution (agent thread, read-only)
        ▼
    Scheduler ── run_backend on a worker slot when dependencies, resource
        │        capacity and the run budget allow (TOOL_CALL_STARTED at real start)
        ▼
    agent thread ── finish: publish into the agent's own memory, in call order
                    (TOOL_CALL_COMPLETED/FAILED, EVIDENCE_OBSERVED, MEMORY_WRITTEN)

The scheduler decides only *when* a call runs. Calls, arguments and their
order of publication are exactly the agent's. Memory has one writer (the
agent thread), so registry IDs match sequential execution.

Dependencies between calls of one turn are conservative:

* calls whose image/URL references all resolve before the turn are independent;
* a call whose reference does not resolve yet waits for every earlier call of
  the turn to be published, then is prepared again (it may name an image an
  earlier call produces);
* tools that read memory in their backend (``parallel_safe = False``), agents
  with the BITE observer, and capability objects without the prepare/run/finish
  phases run alone, after earlier calls are published.

These waits are barriers in the agent thread, not scheduler dependencies, so a
failed earlier call never prevents a later one from running — the same
semantics as the sequential loop. Barriers are recorded in task metadata.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import urlparse

from ..capabilities._base import BaseCapability, Prepared, failure
from ..contracts import CapabilityResult
from .dag import Task, TaskStatus
from .scheduler import Scheduler

REMOTE_IO_MODULES = ("text_search", "image_search", "web_visit")
DEFAULT_CAPACITIES = {"cpu": 4, "remote_io": 4, "model_service": 2}


def resource_pool(capability: Any, overrides: Mapping[str, str] | None = None, name: str | None = None) -> str:
    """Resource pool of a capability: one pool per backend server, else cpu/remote_io/model_service.

    Calls to one server share its pool (e.g. depth and camera pose served by
    the same process). Explicit ``overrides`` (by public tool name) win.
    """
    if overrides and name in overrides:
        return overrides[name]
    if not isinstance(capability, BaseCapability):
        return "cpu"
    module = type(capability).__module__.rsplit(".", 1)[-1]
    if module in REMOTE_IO_MODULES:
        return "remote_io"
    if getattr(capability, "service_config", {}).get("model_service"):
        return "model_service"
    url = getattr(capability, "service_config", {}).get("server_url")
    if isinstance(url, str) and url and "${" not in url:
        parsed = urlparse(url)
        return f"service:{parsed.netloc or url}"
    return "cpu"


def pools_for(agents: Iterable[Any], *, service_capacity: int = 1, capacities: Mapping[str, int] | None = None,
              overrides: Mapping[str, str] | None = None) -> dict[str, int]:
    """Capacities for every pool the agents' tools need (unverified services get ``service_capacity``)."""
    result = dict(DEFAULT_CAPACITIES)
    for agent in agents:
        for name, capability in getattr(agent, "capabilities", {}).items():
            pool = resource_pool(capability, overrides, name)
            result.setdefault(pool, service_capacity if pool.startswith("service:") else 1)
    result.update(capacities or {})
    return result


def _may_need_earlier_output(prepared: Any) -> bool:
    """True when a reference did not resolve exactly against the current memory.

    Either it failed to resolve, or it was resolved by a fallback (for example a
    single-image registry maps any unknown ID to its only image). In both cases
    the call may name an output that an earlier call of the same turn has not
    published yet, so it must be prepared again after those calls finish.
    """
    if isinstance(prepared, CapabilityResult):
        return (prepared.error or {}).get("code") == "unresolved_image_reference"
    return any(rewrite.get("fallback_mode") for rewrite in prepared.resolution.get("rewrites", []))


class _Entry:
    __slots__ = ("slot", "capability", "prepared", "task", "result", "full")

    def __init__(self, slot, capability=None, prepared=None, task=None, result=None, full=False):
        self.slot, self.capability, self.prepared = slot, capability, prepared
        self.task, self.result, self.full = task, result, full


class ToolScheduling:
    """Per-agent adapter between ``MainAgent`` and a (shared) ``Scheduler``."""

    def __init__(self, scheduler: Scheduler, agent_id: str, *, overrides: Mapping[str, str] | None = None) -> None:
        self.scheduler = scheduler
        self.agent_id = agent_id
        self.overrides = dict(overrides or {})
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._latency: dict[str, tuple[int, float]] = {}  # operation -> (n, mean) from finished calls

    # Online duration estimate for E2: mean of this agent's past calls of the operation.
    def _estimate(self, operation: str) -> float | None:
        with self._lock:
            entry = self._latency.get(operation)
        return entry[1] if entry else None

    def _observe(self, operation: str, seconds: float) -> None:
        with self._lock:
            n, mean = self._latency.get(operation, (0, 0.0))
            self._latency[operation] = (n + 1, mean + (seconds - mean) / (n + 1))

    def _task(self, agent, entry: _Entry, body: Callable[[dict[str, Any]], Any], barrier: list[str], reason: str | None) -> Task:
        call = entry.slot["call"]
        task_id = f"{self.agent_id}.call{next(self._ids):04d}"

        def on_start(task: Task) -> None:
            capability = entry.capability
            entry.slot["started_event"] = agent._emit(
                "TOOL_CALL_STARTED",
                {"tool_call_id": call["id"], "invocation_id": entry.slot["invocation_id"],
                 "backend": getattr(capability, "backend", None), "scheduler_task_id": task.task_id},
                summary=f"Started {call['name']}.", status="running",
                parent_event_id=(entry.slot["request_event"] or {}).get("event_id"), tool_name=call["name"],
            )

        metadata = {"invocation_id": entry.slot["invocation_id"], "tool_call_id": call["id"],
                    "request_event_id": (entry.slot["request_event"] or {}).get("event_id"),
                    "on_start": on_start}
        if barrier:
            metadata.update(after=list(barrier), barrier_reason=reason)
        return Task(task_id=task_id, operation=call["name"], body=body, agent_id=self.agent_id,
                    arguments=dict(call.get("args") or {}), resource_type=resource_pool(entry.capability, self.overrides, call["name"]),
                    estimated_cost=self._estimate(call["name"]), budget_resource="tool_calls", metadata=metadata)

    def run_turn(self, agent, calls: list[dict[str, Any]], memory, observer, publish: Callable[[dict, CapabilityResult], None]) -> None:
        pending: list[_Entry] = []
        state = {"previous": [], "reason": None}

        def flush() -> None:
            tasks = [e.task for e in pending if e.task is not None]
            if tasks:
                ids = self.scheduler.submit(tasks)
                self.scheduler.wait(ids)
            for entry in pending:
                publish(entry.slot, self._resolve(agent, entry, memory))
            state["previous"] = [t.task_id for t in tasks] or state["previous"]
            pending.clear()

        for call in calls:
            capability = agent.capabilities.get(call["name"])
            if call["name"] == "Execute_Action_Plan" and getattr(agent, "plan_controller", None) is not None \
                    and not call.get("parse_error"):
                # A declared plan runs its own actions on this scheduler; earlier calls publish first.
                if pending:
                    flush()
                slot = agent._announce_tool_call(call, memory, observer)
                pending.append(_Entry(slot, result=agent.plan_controller.execute_call(agent, slot, memory)))
                flush()
                continue
            if call.get("parse_error") or capability is None:
                # Parse errors and unknown tools fail exactly as in the sequential loop.
                slot = agent._announce_tool_call(call, memory, observer)
                pending.append(_Entry(slot, result=agent._execute_tool_call(slot, memory, observer)))
                continue
            splittable = isinstance(capability, BaseCapability) and observer is None and capability.parallel_safe
            if splittable:
                from ..contracts import VirtualCall

                virtual = VirtualCall(call["id"], call["name"], call["args"])
                prepared = capability.prepare(virtual, memory)
                if _may_need_earlier_output(prepared) and any(e.task is not None for e in pending):
                    state["reason"] = "references an output of an earlier call in this turn"
                    flush()
                    prepared = capability.prepare(virtual, memory)
                barrier = list(state["previous"]) if state["reason"] else []
                slot = agent._announce_tool_call(call, memory, observer)
                entry = _Entry(slot, capability, prepared)
                if isinstance(prepared, CapabilityResult):
                    # Invalid/unresolvable arguments: charged and reported like the sequential path.
                    entry.task = self._task(agent, entry, lambda inputs, r=prepared: r, barrier, state["reason"])
                else:
                    entry.task = self._task(
                        agent, entry, lambda inputs, c=capability, v=slot["virtual"], p=prepared: c.run_backend(v, memory, p),
                        barrier, state["reason"])
                pending.append(entry)
                continue
            # Runs alone, after everything earlier in the turn is published.
            if pending:
                state["reason"] = "tool reads memory state" if isinstance(capability, BaseCapability) else "no phase split"
                flush()
            barrier = list(state["previous"]) if state["previous"] else []
            slot = agent._announce_tool_call(call, memory, observer)
            entry = _Entry(slot, capability, full=True)

            def whole(inputs, entry=entry, capability=capability):
                virtual = entry.slot["virtual"]
                if observer is not None and not isinstance(capability, BaseCapability):
                    observer.dispatch(virtual, capability, memory)
                entry.slot["images_before"] = agent._registry_ids(memory)
                return observer.invoke(capability, virtual, memory) if observer is not None else capability.invoke(virtual, memory)

            entry.task = self._task(agent, entry, whole, barrier, state["reason"] or "runs alone")
            pending.append(entry)
            flush()
            state["reason"] = "after a call that runs alone"
        flush()

    def _resolve(self, agent, entry: _Entry, memory) -> CapabilityResult:
        """Turn a finished task into the call's CapabilityResult, publishing it into memory."""
        if entry.task is None:
            return entry.result
        task = self.scheduler.task(entry.task.task_id)
        virtual = entry.slot["virtual"]
        start, finish = task.timing.get("start_time"), task.timing.get("finish_time")
        if start is not None and finish is not None:
            entry.slot["tool_latency"] = finish - start
            if task.status is TaskStatus.COMPLETED:
                self._observe(task.operation, finish - start)
        if task.status is TaskStatus.COMPLETED:
            value = task.result
            if entry.full or isinstance(value, CapabilityResult):
                return value
            entry.slot["images_before"] = agent._registry_ids(memory)
            return entry.capability.finish(virtual, value, memory, entry.prepared)
        reason = task.failure_reason or task.status.value.lower()
        if reason.startswith("budget_denied"):
            return failure(virtual, "budget_denied", "The actor or global multi-agent tool-call budget is exhausted.")
        if task.status is TaskStatus.FAILED:
            return failure(virtual, "tool_execution_error", reason)
        return failure(virtual, "tool_execution_error", f"Tool call was not executed: {reason}")


def attach(agents: Mapping[str, Any], scheduler: Scheduler, *, overrides: Mapping[str, str] | None = None) -> None:
    """Route every listed agent's tool calls through ``scheduler``."""
    for agent_id, agent in agents.items():
        agent.tool_scheduler = ToolScheduling(scheduler, agent_id, overrides=overrides)


__all__ = ["DEFAULT_CAPACITIES", "Prepared", "ToolScheduling", "attach", "pools_for", "resource_pool"]


# ---- Phase 2: declared multi-action plans (E3/E4/E5) --------------------------------------------


class HarnessRuntime:
    """Runs plan actions with the agent's real capabilities and memory.

    The primary branch commits into the agent's memory; alternative branches get
    an isolated copy of the memory state taken at plan start (same inputs, same
    registry numbering), so speculative outputs never reach the agent unless the
    branch is adopted. Adoption replays the stored backend payloads into the
    active memory with ``finish``: no tool runs twice.
    """

    def __init__(self, agent, memory, plan_call_id: str, overrides: Mapping[str, str] | None = None, model=None) -> None:
        self.agent = agent
        self.memory = memory
        self.plan_call_id = plan_call_id
        self.overrides = dict(overrides or {})
        self.model = model

    def context(self, isolated: bool):
        import copy as _copy

        from ..memory.store import MemoryStore
        from .controller import BranchContext

        if not isolated:
            return BranchContext(self.memory, {}, isolated=False)
        branch = MemoryStore(modules=self.memory.modules, emit_policy=self.memory.emit_policy,
                             webpage_env_update_limit=self.memory.webpage_env_update_limit)
        branch.state = _copy.deepcopy(self.memory.state)
        return BranchContext(branch, {}, isolated=True)

    def bind(self, action, ctx):
        args = dict(action.arguments)
        for key, producer, path in action.bindings():
            value = getattr(ctx.results.get(producer), "data", None)
            for part in path.split("."):
                if isinstance(value, list) and part.isdigit():
                    value = value[int(part)] if int(part) < len(value) else None
                elif isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
            if value is None or value == []:
                return f"${producer}.{path} produced no value"
            args[key] = [round(float(v), 3) for v in value] if key in ("coords", "bbox") else value
        return args

    def prepare(self, action, args, ctx, call_id):
        from ..contracts import VirtualCall

        capability = self.agent.capabilities[action.tool]
        virtual = VirtualCall(call_id, action.tool, args)
        prepared = capability.prepare(virtual, ctx.memory)
        if isinstance(prepared, CapabilityResult):
            return {"failure": prepared, "virtual": virtual, "args": args}
        if _may_need_earlier_output(prepared):  # a fallback resolution would silently use the wrong image
            return {"failure": failure(virtual, "unresolved_image_reference",
                                       "An image reference did not resolve exactly in this branch."), "virtual": virtual, "args": args}
        return {"virtual": virtual, "prepared": prepared, "args": args, "failure": None}

    def backend(self, action, prepared, ctx):
        capability = self.agent.capabilities[action.tool]
        return capability.run_backend(prepared["virtual"], ctx.memory, prepared["prepared"])

    def on_submit(self, action, prepared, meta) -> None:
        """Necessary work is visible in the Studio from submission (TOOL_CALL_REQUESTED/STARTED)."""
        call = {"id": prepared["virtual"].call_id, "name": action.tool, "args": prepared["args"]}
        request = self.agent._emit("TOOL_CALL_REQUESTED", {
            "tool_call_id": call["id"], "invocation_id": call["id"], "arguments": call["args"],
            "plan_call_id": self.plan_call_id, "plan_id": meta["plan_id"], "branch_id": meta["branch_id"],
            "action_id": meta["action_id"], **self.agent._visual_request(call["args"], self.memory)},
            summary=f"Plan action {meta['action_id']}: requested {action.tool}.", status="planned", tool_name=action.tool)
        prepared["request_event"] = request

        def started(task, call=call, prepared=prepared):
            prepared["started_event"] = self.agent._emit("TOOL_CALL_STARTED", {
                "tool_call_id": call["id"], "invocation_id": call["id"], "scheduler_task_id": task.task_id,
                "backend": getattr(self.agent.capabilities[action.tool], "backend", None)},
                summary=f"Started {action.tool} (plan action {meta['action_id']}).", status="running",
                parent_event_id=(request or {}).get("event_id"), tool_name=action.tool)
        meta["on_start"] = started

    def commit(self, action, prepared, payload, ctx, announce=None):
        if isinstance(payload, CapabilityResult):
            result = payload
        else:
            before = self.agent._registry_ids(ctx.memory)
            result = self.agent.capabilities[action.tool].finish(prepared["virtual"], payload, ctx.memory, prepared["prepared"])
            prepared["images_before"] = before
        if announce is not None:
            self._completed(action, prepared, result, announce, adopted=False)
        return result

    def adopt(self, action, prepared, payload, result, active, announce=None):
        """Replay a speculative branch's committed result into the agent's memory."""
        if prepared is None or payload is None or isinstance(payload, CapabilityResult) or not result.ok:
            adopted = result
        else:
            before = self.agent._registry_ids(active.memory)
            adopted = self.agent.capabilities[action.tool].finish(prepared["virtual"], payload, active.memory, prepared["prepared"])
            prepared["images_before"] = before
        if announce is not None and prepared is not None:
            self._completed(action, prepared, adopted, announce, adopted=True)
        return adopted

    def _completed(self, action, prepared, result, announce, *, adopted: bool) -> None:
        call = {"id": prepared["virtual"].call_id, "name": action.tool, "args": prepared["args"]}
        task = announce.get("task")
        timing = {k: (task.timing.get(k) if task else None) for k in ("start_time", "finish_time")}
        adopted = adopted or bool(announce.get("adopted"))
        if adopted and prepared.get("request_event") is None:
            prepared["request_event"] = self.agent._emit("TOOL_CALL_REQUESTED", {
                "tool_call_id": call["id"], "invocation_id": call["id"], "arguments": call["args"],
                "plan_call_id": self.plan_call_id, "plan_id": announce["plan_id"], "branch_id": announce["branch"].branch_id,
                "action_id": announce["action_id"], "adopted_from_speculation": True},
                summary=f"Adopted speculative {action.tool} (plan action {announce['action_id']}).", status="planned",
                tool_name=action.tool)
        self.agent._emit("TOOL_CALL_COMPLETED" if result.ok else "TOOL_CALL_FAILED", {
            "tool_call_id": call["id"], "invocation_id": call["id"],
            "latency_seconds": (timing["finish_time"] - timing["start_time"]) if None not in timing.values() else None,
            "ok": result.ok, "result": (result.payload or {}).get("result"), "canonical_result": result.data, "error": result.error,
            "meta": (result.payload or {}).get("meta", {}), "plan_id": announce["plan_id"], "branch_id": announce["branch"].branch_id,
            "action_id": announce["action_id"], "adopted_from_speculation": adopted, "executed_interval": timing,
            **self.agent._visual_result(call, self.agent.capabilities.get(action.tool), result, self.memory, prepared.get("images_before"))},
            summary=f"{action.tool} {'returned evidence' if result.ok else 'failed'} (plan action {announce['action_id']}).",
            status="completed" if result.ok else "failed",
            parent_event_id=((prepared.get("started_event") or prepared.get("request_event")) or {}).get("event_id"),
            tool_name=action.tool)

    def failed(self, action, reason):
        from ..contracts import VirtualCall

        return failure(VirtualCall(f"{self.plan_call_id}.{action.action_id}", action.tool, dict(action.arguments)),
                       "tool_execution_error", reason)

    def satisfied(self, action, result) -> bool:
        if not result.ok:
            return False
        data = result.data or {}
        if action.expect == "text":
            return bool(str(data.get("text") or "").strip())
        if action.expect == "detections":
            return bool(data.get("boxes_normalized") or data.get("boxes"))
        if action.expect == "image":
            return bool(data.get("image") or data.get("rendered_image"))
        return True

    def pool(self, action) -> str:
        return resource_pool(self.agent.capabilities.get(action.tool), self.overrides, action.tool)

    def estimate(self, action) -> float | None:
        return self.model.median(action.tool) if self.model is not None else None


class PlanController:
    """Handles ``Execute_Action_Plan`` calls for one agent (decision protocol ``declared_multi_action_plan``)."""

    def __init__(self, scheduler: Scheduler, agent_id: str, config, *, evaluator=None, model=None, budget=None,
                 run_id: str = "", overrides: Mapping[str, str] | None = None) -> None:
        from .montecarlo import PROBE_PRIORS
        from .plans import PlanLimits

        self.scheduler = scheduler
        self.agent_id = agent_id
        self.config = config
        self.evaluator = evaluator
        self.model = model or PROBE_PRIORS
        self.budget = budget
        self.run_id = run_id
        self.overrides = dict(overrides or {})
        self.limits = PlanLimits(max_plan_depth=config.max_plan_depth, max_candidate_plans=config.candidate_plan_limit,
                                 beam_width=config.beam_width)
        self.stats = {"plans": 0, "valid": 0, "invalid": 0, "empty": 0, "no_independent_work": 0,
                      "with_alternatives": 0, "heuristic_alternatives_added": 0, "rejection_reasons": {}}
        self.reports: list[dict[str, Any]] = []
        self.schema = "current"  # model-facing plan schema: current | simple (set by attach_plan_mode)

    def execute_call(self, agent, slot: dict, memory) -> CapabilityResult:
        from .controller import PlanExecutor
        from .plans import PLAN_TOOL, PlanError, heuristic_alternatives, parse_plan, validate_plan

        call, virtual = slot["call"], slot["virtual"]
        self.stats["plans"] += 1
        slot["started_event"] = agent._emit("TOOL_CALL_STARTED", {
            "tool_call_id": call["id"], "invocation_id": slot["invocation_id"], "backend": "parsec_vl.plan_controller"},
            summary="Started a declared action plan.", status="running",
            parent_event_id=(slot["request_event"] or {}).get("event_id"), tool_name=PLAN_TOOL)
        images = memory.state.images
        available = set(images.registry) | set(getattr(images, "alias_to_ref", {}) or {})
        from .plans import normalize_simple_plan

        try:
            raw = call.get("args") or {}
            if isinstance(raw, Mapping) and "steps" in raw:  # simple schema -> canonical plan
                raw = normalize_simple_plan(raw)
            plan = parse_plan(raw, run_id=self.run_id, agent_id=self.agent_id, origin_type="model")
            validate_plan(plan, agent.capabilities, available, self.limits)
        except PlanError as exc:
            key = "empty" if exc.reason == "empty" else "invalid"
            self.stats[key] += 1
            self.stats["rejection_reasons"][exc.reason] = self.stats["rejection_reasons"].get(exc.reason, 0) + 1
            agent._emit("PLAN_REJECTED", {"tool_call_id": call["id"], "reason": exc.reason, "message": str(exc)},
                        summary=f"Plan rejected: {exc}", status="failed", tool_name=PLAN_TOOL)
            return failure(virtual, f"invalid_plan:{exc.reason}", str(exc))
        self.stats["valid"] += 1
        # Who proposed it: a scripted test policy or a model service (shown as the plan's origin in the Studio).
        client = (getattr(agent, "studio_topology", None) or {}).get("model_client") or {}
        plan.estimates["proposer"] = "scripted fixture policy" if client.get("kind") == "fixture" else "model service"
        if plan.alternatives:
            self.stats["with_alternatives"] += 1
        if self.config.heuristic_alternatives:
            extra = heuristic_alternatives(plan, agent.capabilities)
            if extra:
                plan.branches.extend(extra)
                self.stats["heuristic_alternatives_added"] += 1
        if not _has_independent_work(plan):
            self.stats["no_independent_work"] += 1
        runtime = HarnessRuntime(agent, memory, call["id"], self.overrides, self.model)
        executor = PlanExecutor(self.scheduler, runtime, self.config, agent_id=self.agent_id,
                                emit=lambda event_type, payload: agent._emit(event_type, payload, tool_name=PLAN_TOOL),
                                evaluator=self.evaluator, model=self.model, budget=self.budget)
        report = executor.execute(plan)
        self.reports.append({k: v for k, v in report.items() if k != "observations"})
        return _plan_result(virtual, plan, report)


def _has_independent_work(plan) -> bool:
    """True when the plan offers anything to overlap: two unordered actions, or an alternative."""
    if plan.alternatives:
        return True
    actions = plan.primary.actions
    ancestors = {a.action_id: set(a.depends_on) for a in actions}
    changed = True
    while changed:
        changed = False
        for aid, anc in ancestors.items():
            grown = anc.union(*(ancestors[d] for d in anc if d in ancestors))
            if grown != anc:
                ancestors[aid], changed = grown, True
    return any(a not in ancestors[b] and b not in ancestors[a] for a in ancestors for b in ancestors if a < b)


def _plan_result(virtual, plan, report) -> CapabilityResult:
    """One tool result for the agent: each executed action's evidence, in commit order."""
    from ..contracts import ArtifactRef

    lines = [f"Action plan {plan.plan_id}: {'goal reached' if report['satisfied'] else 'goal not reached'}"
             f" (branch {report['winning_branch'] or 'none'})."]
    evidence: list[dict[str, Any]] = [{"type": "text", "text": lines[0]}]
    artifacts, summary = [], []
    for branch, aid, result in report["observations"]:
        action = next(a for a in branch.actions if a.action_id == aid)
        summary.append({"action_id": aid, "branch": branch.name, "tool": action.tool, "ok": result.ok,
                        "canonical_result": result.data, "error": result.error})
        evidence.append({"type": "text", "text": f"[{branch.name}/{aid}] {action.tool}:"})
        if result.ok:
            evidence.extend(result.evidence or [{"type": "text", "text": "(no evidence)"}])
            artifacts.extend(result.artifact_refs or [])
        else:
            evidence.append({"type": "text", "text": f"failed: {(result.error or {}).get('message', 'no result')}"})
    payload = {"ok": True, "tool_name": virtual.name, "tool_call_id": virtual.call_id, "error": None,
               "result": {"plan_id": plan.plan_id, "satisfied": report["satisfied"], "actions": summary},
               "meta": {"winning_branch": report["winning_branch"], "replans": report["replans"],
                        "speculative_tool_calls": report["speculative_tool_calls"]}}
    image_refs = [ref.id for ref in artifacts if ref.kind == "image"]
    return CapabilityResult(ok=True, data={"plan_id": plan.plan_id, "satisfied": report["satisfied"], "actions": summary},
                            evidence=evidence, artifact_refs=artifacts, payload=payload,
                            prepared={"image_refs": image_refs}, processor_info={"mode": "parsec_vl.plan"})


PLAN_PROMPT = (
    "Action plans: when several tool actions do not depend on each other, or when you want a fallback if the "
    "first approach fails, you may call Execute_Action_Plan once instead of calling the tools one by one. "
    "List each action with an id, the tool, its arguments, and depends_on for actions that need an earlier "
    "result (write \"$<id>.boxes_normalized.0\" for a grounding box or \"$<id>.image\" for a Zoom crop). "
    "Independent actions run in parallel; each action counts as one tool call.")


SIMPLE_PLAN_PROMPT = (
    "Action plans: if two or more tool steps are useful and do not depend on each other, or you want a fallback in "
    "case the first approach fails, call Execute_Action_Plan once with a list of steps instead of calling tools one by "
    "one. Steps without \"after\" run at the same time. Otherwise call a single tool as usual.")


def attach_plan_mode(agent, controller: PlanController, schema: str = "current") -> None:
    """Switch an agent to the declared multi-action plan protocol (explicit opt-in).

    ``schema`` selects the model-facing form: ``current`` (Phase 2: nested arguments,
    alternatives) or ``simple`` (Phase 3: flat steps, ``after``, ``$id.box``).
    """
    from .plans import PLAN_TOOL, PLAN_TOOL_SCHEMA, SIMPLE_PLAN_TOOL_SCHEMA

    if schema not in ("current", "simple"):
        raise ValueError("plan schema must be current or simple")
    agent.plan_controller = controller
    controller.schema = schema
    agent.decision_protocol = "declared_multi_action_plan"
    prompt = PLAN_PROMPT if schema == "current" else SIMPLE_PLAN_PROMPT
    if prompt not in agent.system_prompt:
        agent.system_prompt = f"{agent.system_prompt}\n\n{prompt}"
    tool = PLAN_TOOL_SCHEMA if schema == "current" else SIMPLE_PLAN_TOOL_SCHEMA
    agent.json_schema = [*[s for s in agent.json_schema if s["function"]["name"] != PLAN_TOOL], tool]
    agent.adapter.json_schema = agent.json_schema
