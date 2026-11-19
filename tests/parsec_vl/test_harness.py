"""Scheduler integration with the real agent loop and capabilities.

Agents are real ``MainAgent`` instances with the real Zoom capability (argument
validation, image-ID resolution, crop, registration, evidence). Only the model
(a scripted policy that issues several tool calls in one turn) and the tool
transport (in-process crop with an injected delay and recorded intervals) are
local. The same agents run with and without the scheduler and are compared.
"""

import json
import threading
import time
from pathlib import Path

import pytest

from openvlharness.agent.agent import MainAgent
from openvlharness.capabilities import zoom
from openvlharness.memory.store import MemoryStore
from openvlharness.multi_agent.budget import AgentBudgetGuard, BudgetManager
from openvlharness.multi_agent.visual_fixture import LocalZoomClient, create_visual_scene
from openvlharness.parsec_vl import BudgetAdapter, Scheduler
from openvlharness.parsec_vl.harness import ToolScheduling, pools_for, resource_pool
from openvlharness.services.models import ModelAdapter

DELAY = 0.25


def test_paper_protocol_still_rejects_multiple_calls_by_default():
    adapter = ModelAdapter({"alias": "qwen3-vl-8b-instruct", "base": "http://fixture.invalid/v1", "max_tokens": 256})
    response = TurnScript([{"image_id": "input_image_1", "coords": [0, 0, 10, 10]}] * 2)({})
    _, calls, _ = adapter.parse(response, 0)
    assert [c["parse_error"]["code"] for c in calls] == ["multiple_tool_calls_not_allowed"] * 2


class RecordingZoomClient(LocalZoomClient):
    """Real in-process crop; records each backend execution interval."""

    def __init__(self, delay, log):
        super().__init__(delay)
        self.log = log

    def execute(self, tool_name, args, *, tool_call_id):
        began = time.monotonic()
        result = super().execute(tool_name, args, tool_call_id=tool_call_id)
        self.log.append({"call": tool_call_id, "start": began, "end": time.monotonic(),
                         "thread": threading.get_ident()})
        return result


class TurnScript:
    """First request: the given tool calls in one turn. Later requests: a final answer."""

    def __init__(self, calls):
        self.calls, self.requests = calls, 0

    def __call__(self, payload):
        self.requests += 1
        if self.requests == 1:
            message = {"role": "assistant", "content": "", "tool_calls": [
                {"id": f"call_{i}", "type": "function", "function": {"name": "Zoom_In_Tool", "arguments": json.dumps(args)}}
                for i, args in enumerate(self.calls)]}
        else:
            message = {"role": "assistant", "content": "<answer>3</answer>"}
        return {"choices": [{"message": message}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


class Zoom(zoom.Capability):
    pass


class MemoryReadingZoom(zoom.Capability):
    parallel_safe = False  # stands in for tools whose backend reads memory (e.g. coding)


def make_agent(calls, log, events, *, capability=Zoom):
    adapter = ModelAdapter({"alias": "qwen3-vl-8b-instruct", "base": "http://fixture.invalid/v1", "max_tokens": 256},
                           requester=TurnScript(calls))
    # The paper protocol rejects several calls per message; these tests opt in so that a
    # turn contains a DAG of calls (the opt-in is off everywhere by default).
    adapter.allow_multiple_tool_calls = True
    tool = capability(backend="zoom_in_image_by_bbox", client_config={}, client=RecordingZoomClient(DELAY, log))
    agent = MainAgent(adapter, {"Zoom_In_Tool": tool}, MemoryStore, "You count objects.", "Question: {user_query}",
                      max_iterations=3)

    def sink(event_type, payload, **meta):
        event = {"event_type": event_type, "payload": payload, "event_id": f"e{len(events)}", **meta}
        events.append(event)
        return event

    agent.event_sink = sink
    return agent


@pytest.fixture(scope="module")
def scene(tmp_path_factory) -> Path:
    return create_visual_scene(tmp_path_factory.mktemp("scene") / "scene.png")


def ask(agent, scene):
    return agent.generate([{"type": "image", "value": str(scene)}, {"type": "text", "value": "How many objects?"}])


def tool_results(events):
    """(call, ok, produced registry IDs + sizes, consumed image, canonical result) per finished call."""
    rows = []
    for e in events:
        if e["event_type"] not in ("TOOL_CALL_COMPLETED", "TOOL_CALL_FAILED"):
            continue
        p = e["payload"]
        outputs = [(o.get("registry_id"), o.get("width"), o.get("height")) for o in (p.get("visual") or {}).get("outputs", [])]
        consumed = [r.get("image_ref") for r in ((p.get("meta") or {}).get("image_resolution") or {}).get("rewrites", [])]
        rows.append((p["tool_call_id"], p["ok"], outputs, consumed,
                     json.dumps(p.get("canonical_result"), sort_keys=True, default=str)))
    return rows


def overlap(a, b):
    return a["start"] < b["end"] and b["start"] < a["end"]


INDEPENDENT = [{"image_id": "input_image_1", "coords": [0, 0, 500, 500]},
               {"image_id": "input_image_1", "coords": [500, 500, 1000, 1000]},
               {"image_id": "input_image_1", "coords": [250, 250, 750, 750]}]


def run_pair(scene, calls, capability=Zoom, policy="e1", workers=4):
    seq_log, seq_events = [], []
    sequential = make_agent(calls, seq_log, seq_events, capability=capability)
    seq_answer = ask(sequential, scene)
    par_log, par_events = [], []
    scheduled = make_agent(calls, par_log, par_events, capability=capability)
    scheduler = Scheduler(policy=policy, workers=workers, capacities=pools_for([scheduled]))
    scheduled.tool_scheduler = ToolScheduling(scheduler, "worker_01")
    par_answer = ask(scheduled, scene)
    summary = scheduler.summary()
    scheduler.shutdown()
    return (seq_answer, seq_log, seq_events), (par_answer, par_log, par_events), summary


def test_independent_calls_of_one_turn_overlap_and_publish_identically(scene):
    (seq_answer, seq_log, seq_events), (par_answer, par_log, par_events), summary = run_pair(scene, INDEPENDENT)
    # Sequential path: backend executions never overlap.
    assert not any(overlap(a, b) for i, a in enumerate(seq_log) for b in seq_log[i + 1:])
    # Scheduler path: the three independent backend executions really overlap.
    assert len(par_log) == 3 and all(overlap(a, b) for i, a in enumerate(par_log) for b in par_log[i + 1:])
    assert summary["peak_concurrency"] == 3
    assert max(r["end"] for r in par_log) - min(r["start"] for r in par_log) < 2.5 * DELAY
    # Same logical outputs: same calls, same registry IDs in call order, same canonical results.
    assert tool_results(par_events) == tool_results(seq_events)
    assert [[o[0] for o in r[2]] for r in tool_results(par_events)] == [["tool_generated_image_1"], ["tool_generated_image_2"], ["tool_generated_image_3"]]
    assert par_answer["prediction"] == seq_answer["prediction"] == "3"
    # Model-visible history is identical too (same tool messages in the same order).
    seq_history = seq_answer["extra_records"]["trajectory"]["chat_history"]
    par_history = par_answer["extra_records"]["trajectory"]["chat_history"]
    assert json.dumps(seq_history, sort_keys=True, default=str) == json.dumps(par_history, sort_keys=True, default=str)


def test_studio_events_keep_their_order_and_correlation(scene):
    _, (_, _, events), _ = run_pair(scene, INDEPENDENT)
    started = [e for e in events if e["event_type"] == "TOOL_CALL_STARTED"]
    assert len(started) == 3 and all(e["payload"]["scheduler_task_id"].startswith("worker_01.call") for e in started)
    completed = [e["payload"]["tool_call_id"] for e in events if e["event_type"] == "TOOL_CALL_COMPLETED"]
    assert completed == ["call_0", "call_1", "call_2"]  # published in call order
    for e in started:
        request = next(r for r in events if r["event_type"] == "TOOL_CALL_REQUESTED"
                       and r["payload"]["invocation_id"] == e["payload"]["invocation_id"])
        assert e["parent_event_id"] == request["event_id"]


def test_call_using_an_earlier_output_of_the_same_turn_waits_for_it(scene):
    calls = [{"image_id": "input_image_1", "coords": [0, 0, 600, 600]},
             {"image_id": "tool_generated_image_1", "coords": [0, 0, 500, 500]}]  # the first call's crop
    (seq_answer, _, seq_events), (par_answer, par_log, par_events), _ = run_pair(scene, calls)
    assert [r[1] for r in tool_results(par_events)] == [True, True]
    assert tool_results(par_events) == tool_results(seq_events)
    assert tool_results(par_events)[1][3] == ["tool_generated_image_1"]  # it zoomed into the first crop
    first, second = sorted(par_log, key=lambda r: r["start"])
    assert second["start"] >= first["end"]  # complete-before-consume


def test_tool_that_reads_memory_runs_alone(scene):
    (_, _, seq_events), (_, par_log, par_events), _ = run_pair(scene, INDEPENDENT, capability=MemoryReadingZoom)
    ordered = sorted(par_log, key=lambda r: r["start"])
    assert all(b["start"] >= a["end"] for a, b in zip(ordered, ordered[1:]))
    assert tool_results(par_events) == tool_results(seq_events)


def test_e0_policy_serializes_the_same_turn(scene):
    _, (_, par_log, par_events), summary = run_pair(scene, INDEPENDENT, policy="e0")
    ordered = sorted(par_log, key=lambda r: r["start"])
    assert all(b["start"] >= a["end"] for a, b in zip(ordered, ordered[1:]))
    assert summary["peak_concurrency"] == 1


def test_scheduler_uses_the_runs_budget_ledger(scene):
    log, events = [], []
    agent = make_agent(INDEPENDENT, log, events)
    manager = BudgetManager({"tool_calls": 2, "model_requests": 10}, {"worker_01": {"tool_calls": 5, "model_requests": 10}})
    agent.budget_guard = AgentBudgetGuard(manager, "worker_01")
    scheduler = Scheduler(policy="e1", workers=4, capacities=pools_for([agent]), budget=BudgetAdapter(manager))
    agent.tool_scheduler = ToolScheduling(scheduler, "worker_01")
    ask(agent, scene)
    scheduler.shutdown()
    results = tool_results(events)
    assert [row[1] for row in results].count(True) == 2
    denied = [e for e in events if e["event_type"] == "TOOL_CALL_FAILED"]
    assert len(denied) == 1 and denied[0]["payload"]["error"]["code"] == "budget_denied"
    assert len(log) == 2  # the denied call never reached the backend
    snapshot = manager.snapshot()
    assert snapshot["global"]["tool_calls"] == {"limit": 2, "used": 2, "remaining": 0}
    assert snapshot["actors"]["worker_01"]["tool_calls"]["used"] == 2


def test_two_agents_share_one_scheduler_with_isolated_memories(scene):
    calls_a = [{"image_id": "input_image_1", "coords": [0, 0, 400, 400]}, {"image_id": "input_image_1", "coords": [0, 0, 900, 300]}]
    calls_b = [{"image_id": "input_image_1", "coords": [600, 600, 1000, 1000]}, {"image_id": "input_image_1", "coords": [100, 500, 300, 900]}]
    expected = {}
    for name, calls in (("worker_01", calls_a), ("worker_02", calls_b)):
        events = []
        ask(make_agent(calls, [], events), scene)
        expected[name] = tool_results(events)
    shared_log = []
    agents = {name: make_agent(calls, shared_log, events := [])
              for name, calls in (("worker_01", calls_a), ("worker_02", calls_b))}
    event_logs = {name: agent.event_sink.__closure__ for name, agent in agents.items()}  # noqa: F841 - keep sinks alive
    scheduler = Scheduler(policy="e1", workers=4, capacities={**pools_for(agents.values()), "cpu": 4})
    for name, agent in agents.items():
        agent.tool_scheduler = ToolScheduling(scheduler, name)
    collected = {name: [] for name in agents}
    for name, agent in agents.items():
        def sink(event_type, payload, _name=name, **meta):
            event = {"event_type": event_type, "payload": payload, "event_id": f"{_name}{len(collected[_name])}", **meta}
            collected[_name].append(event)
            return event
        agent.event_sink = sink
    answers = {}
    threads = [threading.Thread(target=lambda n=name, a=agent: answers.__setitem__(n, ask(a, scene))) for name, agent in agents.items()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    summary = scheduler.summary()
    scheduler.shutdown()
    # Each agent's outputs are exactly what it produces alone: correct ownership and correlation.
    for name in agents:
        assert tool_results(collected[name]) == expected[name]
    # Tasks are attributed to their agent and the agents' calls overlapped.
    assert summary["peak_concurrency"] >= 3
    assert all(r["agent_id"] in agents for r in scheduler.records())


def test_resource_pools_follow_the_backend_server(monkeypatch):
    from openvlharness.bootstrap import build_capabilities, load_agent_config

    # This is a configuration test, not a deployment test. Do not depend on
    # another suite loading the developer's .env as an import side effect.
    for key, value in {
        "TOOL_SERVER_URL": "http://127.0.0.1:8101", "SAM3_SERVER_URL": "http://127.0.0.1:8086",
        "OCR_SERVER_URL": "http://127.0.0.1:8085", "DEPTH_ESTIMATION_SERVER_URL": "http://127.0.0.1:8087",
        "MODEL_BASE_URL": "http://127.0.0.1:8222/v1", "MODEL_API_KEY": "offline-test",
    }.items():
        monkeypatch.setenv(key, value)
    caps = build_capabilities(load_agent_config("examples/local_grounding_tools.yaml"))
    pools = {name: resource_pool(cap, name=name) for name, cap in caps.items()}
    assert pools["Zoom_In_Tool"] == "cpu"
    assert pools["Python_Coding_Agent_Tool"] == "model_service"
    assert pools["Depth_Estimation_Tool"] == pools["Camera_Trajectory_Tool"]  # one server, one pool
    assert pools["Visual_Grounding_Tool"].startswith("service:") and pools["Visual_Grounding_Tool"] != pools["OCR_Tool"]
