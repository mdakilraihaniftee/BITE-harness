"""Runtime profile of a recorded multi-agent run, from its ``events.jsonl``.

No new instrumentation is needed for the baseline profile: the runtime already
records model requests (``MODEL_REQUEST_STARTED`` / ``MODEL_RESPONSE_RECEIVED``
with a monotonic ``latency_seconds``), tool calls (``TOOL_CALL_REQUESTED`` /
``STARTED`` / ``COMPLETED`` with monotonic latency), memory publication
(``MEMORY_WRITTEN``), messages, and orchestrator phase changes. Runs executed
with the PARSEC-VL scheduler also carry ``SCHEDULER_TASK_*`` records (queue
waiting, worker slot, resource pool).

Durations use the recorded monotonic latencies; interval placement uses the
wall-clock event timestamps (end = completion timestamp, start = end - latency).

Dependency reconstruction (for T1 / Tinf) is explicit about what it assumes:

* an agent is sequential: model request -> its tool calls -> next model request;
* tool calls proposed in the same model turn are independent siblings
  ("ideal") or serialized as they are today ("current");
* orchestrator phase changes (rounds, run-state changes) are full barriers.

These are fixed-workload numbers for the recorded trajectory, not bounds on an
adaptive agent's unknown future work.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

BARRIER_EVENTS = {"RUN_STATE_CHANGED", "INVESTIGATION_ROUND_STARTED", "INVESTIGATION_ROUND_COMPLETED"}


def _ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def _inv(event: dict[str, Any]) -> str:
    """Invocation identity; runs recorded before invocation IDs fall back to agent + call ID."""
    p = event.get("payload") or {}
    return p.get("invocation_id") or f"{event.get('agent_id')}|{p.get('tool_call_id')}"


def load_events(run_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(run_dir) / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "total": 0.0, "mean": None, "median": None, "max": None}
    return {"count": len(values), "total": round(sum(values), 4), "mean": round(statistics.fmean(values), 4),
            "median": round(statistics.median(values), 4), "max": round(max(values), 4)}


def _peak(intervals: Iterable[tuple[float, float]]) -> int:
    edges = sorted([(s, 1) for s, _ in intervals] + [(e, -1) for _, e in intervals], key=lambda x: (x[0], x[1]))
    level = peak = 0
    for _, delta in edges:
        level += delta
        peak = max(peak, level)
    return peak


def _union(intervals: list[tuple[float, float]]) -> float:
    total, end = 0.0, None
    start = None
    for s, e in sorted(intervals):
        if end is None or s > end:
            if end is not None:
                total += end - start
            start, end = s, e
        else:
            end = max(end, e)
    if end is not None:
        total += end - start
    return total


def intervals(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Model, tool, waiting, publication, and scheduler intervals (seconds from run start)."""
    t0 = _ts(events[0]["timestamp"])
    # With the PARSEC-VL scheduler, TOOL_CALL_COMPLETED is emitted at in-order publication,
    # which can be later than the backend finished; use the scheduler's own interval then.
    executed_at: dict[str, tuple[float, float]] = {}
    for e in events:
        p = e.get("payload") or {}
        if e["event_type"] == "SCHEDULER_TASK_FINISHED" and p.get("start_wall") and p.get("finish_wall"):
            inv = (p.get("metadata") or {}).get("invocation_id")
            if inv:
                executed_at[inv] = (_ts(p["start_wall"]) - t0, _ts(p["finish_wall"]) - t0)
    model_start: dict[str, dict] = {}
    model: list[dict[str, Any]] = []
    requested: dict[str, dict] = {}
    started: dict[str, dict] = {}
    tools: list[dict[str, Any]] = []
    published: list[dict[str, Any]] = []
    completed_at: dict[str, float] = {}
    scheduler: list[dict[str, Any]] = []
    messages = 0
    barriers: list[float] = []
    for e in events:
        etype, p, at = e["event_type"], e.get("payload") or {}, _ts(e["timestamp"]) - t0
        agent = e.get("agent_id")
        if etype in BARRIER_EVENTS:
            barriers.append(at)
        elif etype == "MODEL_REQUEST_STARTED":
            model_start[p.get("request_id")] = {"agent": agent, "at": at, "phase": p.get("phase")}
        elif etype in ("MODEL_RESPONSE_RECEIVED", "MODEL_REQUEST_FAILED") and p.get("request_id") in model_start:
            begin = model_start.pop(p["request_id"])
            latency = p.get("latency_seconds")
            duration = float(latency) if isinstance(latency, (int, float)) else at - begin["at"]
            model.append({"agent": agent, "start": at - duration, "end": at, "duration": duration,
                          "ok": etype == "MODEL_RESPONSE_RECEIVED", "kind": "model"})
        elif etype == "TOOL_CALL_REQUESTED":
            requested[_inv(e)] = {"agent": agent, "at": at, "tool": e.get("tool_name")}
        elif etype == "TOOL_CALL_STARTED":
            started[_inv(e)] = {"at": at}
        elif etype in ("TOOL_CALL_COMPLETED", "TOOL_CALL_FAILED") and _inv(e) in requested:
            inv = _inv(e)
            req = requested[inv]
            latency = p.get("latency_seconds")
            end = at
            if inv in executed_at:
                begin, end = executed_at[inv]
                duration = end - begin
            elif isinstance(latency, (int, float)):
                duration = float(latency)
                begin = at - duration
            else:  # parse error, unknown tool, budget denial: nothing executed
                duration, begin = 0.0, at
            tools.append({"agent": agent, "tool": e.get("tool_name"), "requested": req["at"],
                          "started": started.get(inv, {}).get("at"), "start": begin, "end": end, "duration": duration,
                          "ok": bool(p.get("ok")), "invocation_id": inv, "kind": "tool",
                          "error": (p.get("error") or {}).get("code") if isinstance(p.get("error"), dict) else None})
            completed_at[inv] = at
        elif etype == "MEMORY_WRITTEN" and _inv(e) in completed_at:
            published.append({"agent": agent, "seconds": at - completed_at[_inv(e)]})
        elif etype == "SCHEDULER_TASK_FINISHED":
            scheduler.append(p)
        elif etype == "MESSAGE_SENT":
            messages += 1
    end = _ts(events[-1]["timestamp"]) - t0
    return {"model": model, "tools": tools, "published": published, "scheduler": scheduler,
            "messages": messages, "barriers": barriers, "wall": end}


def _turns(agent_nodes: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split one agent's chronological nodes into [model, tool, tool, ...] turns."""
    turns: list[list[dict[str, Any]]] = []
    for node in agent_nodes:
        if node["kind"] == "model" or not turns:
            turns.append([node])
        else:
            turns[-1].append(node)
    return turns


def dependency_metrics(data: dict[str, Any]) -> dict[str, Any]:
    """T1, Tinf (current structure and with independent same-turn tools), and parallelism."""
    nodes = [*data["model"], *[t for t in data["tools"] if t["duration"] > 0]]
    barriers = sorted(data["barriers"])

    def segment(node):  # index of the last barrier at or before the node's start
        return sum(1 for b in barriers if b <= node["start"] + 1e-6)

    by_segment: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for node in sorted(nodes, key=lambda n: n["start"]):
        by_segment[segment(node)][node["agent"]].append(node)
    t1 = sum(n["duration"] for n in nodes)
    tinf_current = tinf_ideal = 0.0
    multi_call_turns = turns_with_tools = 0
    for agents in by_segment.values():
        current = ideal = 0.0
        for agent_nodes in agents.values():
            chain_current = chain_ideal = 0.0
            for turn in _turns(agent_nodes):
                model_part = sum(n["duration"] for n in turn if n["kind"] == "model")
                tool_parts = [n["duration"] for n in turn if n["kind"] == "tool"]
                chain_current += model_part + sum(tool_parts)
                chain_ideal += model_part + max(tool_parts, default=0.0)
                if tool_parts:
                    turns_with_tools += 1
                    multi_call_turns += len(tool_parts) > 1
            current, ideal = max(current, chain_current), max(ideal, chain_ideal)
        tinf_current += current
        tinf_ideal += ideal
    return {
        "T1": round(t1, 4),
        "Tinf_current": round(tinf_current, 4),
        "Tinf_independent_same_turn_tools": round(tinf_ideal, 4),
        "available_parallelism_current": round(t1 / tinf_current, 3) if tinf_current else None,
        "available_parallelism_ideal": round(t1 / tinf_ideal, 3) if tinf_ideal else None,
        "segments": len(by_segment),
        "turns_with_tools": turns_with_tools,
        "multi_call_turns": multi_call_turns,
        "assumptions": "agent-sequential turns; same-turn tool calls independent (ideal) or serialized (current); "
                       "orchestrator phase changes are barriers",
    }


def _uses_real_model(run_dir: Path, events: list[dict[str, Any]]) -> bool:
    """True when the run called a real model service (scripted fixtures use ``*.invalid`` endpoints)."""
    if not any(e["event_type"] == "MODEL_RESPONSE_RECEIVED" for e in events):
        return False
    manifest = run_dir / "run_manifest.json"
    if manifest.is_file():
        actors = json.loads(manifest.read_text()).get("actors") or {}
        endpoints = [str(a.get("endpoint") or "") for a in actors.values() if isinstance(a, dict)]
        if endpoints:
            return not any(".invalid" in endpoint for endpoint in endpoints)
    return False  # unknown provenance: not counted as a real measurement


def profile_run(run_dir: str | Path) -> dict[str, Any]:
    events = load_events(run_dir)
    data = intervals(events)
    model, tools = data["model"], data["tools"]
    executed = [t for t in tools if t["duration"] > 0]
    model_ids = {(e.get("payload") or {}).get("model_id") for e in events if e["event_type"] == "MODEL_REQUEST_STARTED"}
    real_model = _uses_real_model(Path(run_dir), events)
    busy_union = _union([(n["start"], n["end"]) for n in [*model, *executed]])
    by_tool: dict[str, list[float]] = defaultdict(list)
    for t in executed:
        by_tool[t["tool"]].append(t["duration"])
    waits = [t["started"] - t["requested"] for t in tools if t["started"] is not None]
    config = next(((e.get("payload") or {}).get("effective_config") for e in events
                   if e["event_type"] == "RUN_CONFIGURATION_RECORDED"), {}) or {}
    return {
        "run_id": events[0].get("run_id"),
        "model_ids": sorted(m for m in model_ids if m),
        "real_model_service": bool(real_model),
        "workers": config.get("num_workers"),
        "execution_mode": config.get("execution_mode"),
        "tool_scheduler": (config.get("tool_scheduler") or {}).get("policy", "off"),
        "wall_seconds": round(data["wall"], 4),
        "model_requests": _stats([m["duration"] for m in model]),
        "model_requests_by_agent": {a: _stats([m["duration"] for m in model if m["agent"] == a])
                                    for a in sorted({m["agent"] for m in model})},
        "tool_calls": _stats([t["duration"] for t in executed]),
        "tool_calls_by_tool": {k: _stats(v) for k, v in sorted(by_tool.items())},
        "tool_calls_not_executed": sum(1 for t in tools if t["duration"] == 0),
        "tool_request_to_start": _stats(waits),
        "memory_publication": _stats([p["seconds"] for p in data["published"]]),
        "scheduler_queue_wait": _stats([s["start_time"] - s["enqueue_time"] for s in data["scheduler"]
                                        if s.get("start_time") is not None and s.get("enqueue_time") is not None]),
        "messages": data["messages"],
        # Busy time / wall time; can exceed 1 when calls of different agents overlap.
        "share_of_wall": {
            "model": round(sum(m["duration"] for m in model) / data["wall"], 4) if data["wall"] else None,
            "tools": round(sum(t["duration"] for t in executed) / data["wall"], 4) if data["wall"] else None,
            "neither (orchestration, queueing, I/O outside calls)": round(1 - busy_union / data["wall"], 4) if data["wall"] else None,
        },
        "peak_concurrent_model_requests": _peak([(m["start"], m["end"]) for m in model]),
        "peak_concurrent_tool_calls": _peak([(t["start"], t["end"]) for t in executed]),
        "dependencies": dependency_metrics(data),
    }


def aggregate(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """Pooled per-call statistics across runs (durations pooled, not averaged per run)."""
    def pooled(key):
        return [p[key]["mean"] for p in profiles if p[key]["count"]]
    by_tool: dict[str, list[float]] = defaultdict(list)
    for p in profiles:
        for tool, st in p["tool_calls_by_tool"].items():
            by_tool[tool] += [st["mean"]] * st["count"]
    return {
        "runs": len(profiles),
        "model_request_mean_of_run_means": round(statistics.fmean(pooled("model_requests")), 3) if pooled("model_requests") else None,
        "tool_call_mean_by_tool": {t: round(statistics.fmean(v), 3) for t, v in sorted(by_tool.items())},
        "model_share_of_wall_mean": round(statistics.fmean(p["share_of_wall"]["model"] for p in profiles), 3),
        "tool_share_of_wall_mean": round(statistics.fmean(p["share_of_wall"]["tools"] for p in profiles), 3),
        "runs_with_multi_call_turns": sum(1 for p in profiles if p["dependencies"]["multi_call_turns"]),
        "multi_call_turns_total": sum(p["dependencies"]["multi_call_turns"] for p in profiles),
        "turns_with_tools_total": sum(p["dependencies"]["turns_with_tools"] for p in profiles),
        "peak_concurrent_tool_calls_max": max((p["peak_concurrent_tool_calls"] for p in profiles), default=0),
        "peak_concurrent_model_requests_max": max((p["peak_concurrent_model_requests"] for p in profiles), default=0),
    }
