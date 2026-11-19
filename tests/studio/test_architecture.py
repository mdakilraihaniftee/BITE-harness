"""Architecture topology, directed activity mapping, and Studio integrity tests."""

from __future__ import annotations

import asyncio
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from openvlharness.agent.agent import MainAgent
from openvlharness.contracts import CapabilityResult
from openvlharness.memory.store import MemoryStore
from openvlharness.multi_agent.budget import AgentBudgetGuard, BudgetManager
from openvlharness.services.models import ModelAdapter
from openvlharness.studio.replay import (
    RunEventCache,
    public_manifest,
    public_snapshot,
)
from openvlharness.studio.server import create_app
from openvlharness.studio.topology import (
    ActivityMapper,
    annotate_events,
    build_topology,
    display_endpoint,
    sanitize,
)

ROOT = Path(__file__).resolve().parents[2]
SECRET_ENDPOINT = (
    "http://alice:hunter2@10.0.0.5:8222/v1/chat/completions?api_key=sk-SECRET#frag"
)


def manifest_for(
    workers: int, *, tools=("Visual_Grounding_Tool", "Zoom_In_Tool")
) -> dict:
    model = {
        "model_id": "Qwen/Qwen3-VL-8B-Instruct",
        "protocol": "chat_completions",
        "endpoint": SECRET_ENDPOINT,
    }
    actors = {
        "coordinator": {
            "role": "coordinator",
            "tool_access": False,
            "model_client": model,
            "tools": [],
            "harness": {"implementation": "MainAgent"},
            "memory": {"modules": ["image"]},
        }
    }
    for index in range(1, workers + 1):
        actors[f"worker_{index:02d}"] = {
            "role": "investigator",
            "tool_access": True,
            "model_client": model,
            "harness": {"implementation": "MainAgent", "max_iterations": 15},
            "memory": {"modules": ["image", "tool_context"]},
            "tools": [
                {
                    "name": name,
                    "backend": "sam3_segment",
                    "service": "http://bob:pw@127.0.0.1:8101/?token=t",
                }
                for name in tools
            ],
        }
    return {
        "worker_count": workers,
        "original_task": "Count objects",
        "topology": {
            "actors": actors,
            "communication": {"enabled": True, "peer_to_peer": True},
            "budget": {"tool_calls": 10, "model_requests": 20, "messages": 30},
        },
    }


def event(
    seq: int, agent: str, etype: str, payload: dict | None = None, **extra
) -> dict:
    return {
        "schema_version": "studio.event.v1",
        "run_id": "r",
        "task_id": "t",
        "agent_id": agent,
        "event_id": extra.pop("event_id", f"evt_{seq}"),
        "sequence": seq,
        "timestamp": "",
        "event_type": etype,
        "parent_event_id": extra.pop("parent", None),
        "causal_refs": [],
        "tool_name": extra.pop("tool", None),
        "status": extra.pop("status", "completed"),
        "summary": "",
        "artifact_refs": extra.pop("refs", []),
        "payload": payload or {},
    }


def hops(activity: dict) -> list[tuple[str, str]]:
    return [(hop["from"], hop["to"]) for hop in activity["path"]]


# ---------------------------------------------------------------------------
# Topology


@pytest.mark.parametrize("workers", [1, 2, 3, 4, 8])
def test_topology_represents_every_component_with_ownership(workers: int) -> None:
    topology = build_topology(manifest_for(workers), [], run_id="r")
    nodes = {node["id"]: node for node in topology["nodes"]}
    agents = ["coordinator", *[f"worker_{i:02d}" for i in range(1, workers + 1)]]
    assert topology["agents"] == agents
    for agent in agents:
        assert nodes[agent]["type"] == (
            "coordinator" if agent == "coordinator" else "worker"
        )
        for suffix, kind in (
            ("harness", "harness"),
            ("model_client", "model_client"),
            ("memory", "memory"),
        ):
            assert nodes[f"{agent}.{suffix}"]["type"] == kind
            assert nodes[f"{agent}.{suffix}"]["owner_agent_id"] == agent
        assert (f"{agent}.tool_router" in nodes) == (agent != "coordinator")
    for shared in (
        "comm_bus",
        "budget",
        "artifact_store",
        "event_log",
        "orchestrator",
        "task",
        "result",
    ):
        assert shared in nodes
    services = [node for node in topology["nodes"] if node["type"] == "model_service"]
    assert len(services) == 1 and services[0]["shared"] is True
    assert sorted(services[0]["metadata"]["clients"]) == agents
    tools = [node for node in topology["nodes"] if node["type"] == "tool"]
    assert sorted(node["label"] for node in tools) == [
        "Visual_Grounding_Tool",
        "Zoom_In_Tool",
    ]
    assert all(node["shared"] is (workers > 1) for node in tools)
    ids = [node["id"] for node in topology["nodes"]]
    assert len(ids) == len(set(ids))
    for edge in topology["edges"]:
        assert edge["source"] in nodes and edge["target"] in nodes
    assert f"worker_01.model_client->{services[0]['id']}" in {
        e["id"] for e in topology["edges"]
    }


def test_topology_ids_are_stable_and_deterministic() -> None:
    first = build_topology(manifest_for(3), [], run_id="r")
    second = build_topology(copy.deepcopy(manifest_for(3)), [], run_id="r")
    assert first == second
    assert first["fingerprint"] == second["fingerprint"]


def test_distinct_model_endpoints_are_distinct_services() -> None:
    manifest = manifest_for(2)
    manifest["topology"]["actors"]["worker_02"]["model_client"] = {
        "model_id": "other",
        "endpoint": "http://h:1/v1",
    }
    services = [
        n
        for n in build_topology(manifest, [], run_id="r")["nodes"]
        if n["type"] == "model_service"
    ]
    assert len(services) == 2


def test_topology_contains_no_secrets() -> None:
    manifest = manifest_for(2)
    manifest["topology"]["actors"]["worker_01"]["model_client"]["api_key"] = "sk-SECRET"
    serialized = json.dumps(build_topology(manifest, [], run_id="r"))
    for secret in (
        "hunter2",
        "alice",
        "sk-SECRET",
        "api_key=",
        "token=t",
        "bob:pw",
        "#frag",
    ):
        assert secret not in serialized
    assert "http://10.0.0.5:8222/v1/chat/completions" in serialized
    assert (
        display_endpoint(SECRET_ENDPOINT) == "http://10.0.0.5:8222/v1/chat/completions"
    )
    assert sanitize(
        {"nested": {"Authorization": "Bearer x", "url": SECRET_ENDPOINT}}
    ) == {
        "nested": {
            "Authorization": "<redacted>",
            "url": "http://10.0.0.5:8222/v1/chat/completions",
        }
    }


def test_public_manifest_strips_process_identifiers_and_credentials() -> None:
    clean = public_manifest(
        {
            "pid": 1,
            "actors": {
                "worker_01": {
                    "endpoint": SECRET_ENDPOINT,
                    "agent_object_id": 9,
                    "adapter_object_id": 8,
                }
            },
        }
    )
    assert "pid" not in clean
    assert clean["actors"]["worker_01"] == {
        "endpoint": "http://10.0.0.5:8222/v1/chat/completions"
    }


def test_legacy_manifest_marks_tools_as_observed_not_configured() -> None:
    manifest = {
        "worker_count": 1,
        "actors": {
            "coordinator": {"model_id": "m", "endpoint": "http://h:1/v1"},
            "worker_01": {"model_id": "m", "endpoint": "http://h:1/v1"},
        },
    }
    events = [
        event(
            0,
            "worker_01",
            "TOOL_CALL_REQUESTED",
            {"tool_call_id": "c"},
            tool="Zoom_In_Tool",
        )
    ]
    topology = build_topology(manifest, events, run_id="r")
    nodes = {node["id"]: node for node in topology["nodes"]}
    assert topology["source"] == "manifest.actors"
    assert nodes["tool:Zoom_In_Tool"]["provenance"] == "observed"
    assert nodes["worker_01.harness"]["provenance"] == "inferred"
    assert nodes["worker_01"]["provenance"] == "configured"


# ---------------------------------------------------------------------------
# Directed activity mapping


def tool_lifecycle(
    agent: str,
    start: int,
    call: str = "call_1",
    *,
    invocation: str | None = None,
    tool: str = "Visual_Grounding_Tool",
    outcome: str = "TOOL_CALL_COMPLETED",
    error=None,
) -> list[dict]:
    extra = {"invocation_id": invocation} if invocation else {}
    requested = event(
        start,
        agent,
        "TOOL_CALL_REQUESTED",
        {"tool_call_id": call, **extra},
        tool=tool,
        event_id=f"req_{agent}_{start}",
        status="planned",
    )
    started = event(
        start + 1,
        agent,
        "TOOL_CALL_STARTED",
        {"tool_call_id": call, **extra},
        tool=tool,
        event_id=f"start_{agent}_{start}",
        parent=requested["event_id"],
        status="running",
    )
    closed = event(
        start + 2,
        agent,
        outcome,
        {"tool_call_id": call, "error": error, **extra},
        tool=tool,
        event_id=f"close_{agent}_{start}",
        parent=started["event_id"],
        status={"TOOL_CALL_FAILED": "failed", "TOOL_CALL_CANCELLED": "cancelled"}.get(
            outcome, "completed"
        ),
    )
    return [requested, started, closed]


def test_tool_request_and_result_travel_in_opposite_directions() -> None:
    topology = build_topology(manifest_for(2), [], run_id="r")
    request, started, result = annotate_events(tool_lifecycle("worker_02", 0), topology)
    assert hops(request["activity"]) == [
        ("worker_02", "worker_02.harness"),
        ("worker_02.harness", "worker_02.tool_router"),
    ]
    assert (
        request["activity"]["phase"] == "open"
        and request["activity"]["kind"] == "tool_request"
    )
    assert hops(started["activity"]) == [
        ("worker_02.tool_router", "tool:Visual_Grounding_Tool")
    ]
    assert hops(result["activity"]) == [
        ("tool:Visual_Grounding_Tool", "worker_02.tool_router"),
        ("worker_02.tool_router", "worker_02.harness"),
        ("worker_02.harness", "worker_02"),
    ]
    assert (
        result["activity"]["kind"] == "tool_result"
        and result["activity"]["phase"] == "close"
    )
    assert (
        len(
            {
                request["activity"]["correlation_id"],
                started["activity"]["correlation_id"],
                result["activity"]["correlation_id"],
            }
        )
        == 1
    )


def test_failed_denied_and_cancelled_tool_calls_are_distinct() -> None:
    topology = build_topology(manifest_for(1), [], run_id="r")
    failed = annotate_events(
        tool_lifecycle(
            "worker_01", 0, outcome="TOOL_CALL_FAILED", error={"code": "timeout"}
        ),
        topology,
    )[-1]["activity"]
    assert (
        failed["kind"] == "tool_failure"
        and hops(failed)[0][0] == "tool:Visual_Grounding_Tool"
    )
    cancelled = annotate_events(
        tool_lifecycle("worker_01", 0, outcome="TOOL_CALL_CANCELLED"), topology
    )[-1]["activity"]
    assert cancelled["kind"] == "tool_cancelled" and cancelled["phase"] == "close"
    request = event(
        0,
        "worker_01",
        "TOOL_CALL_REQUESTED",
        {"tool_call_id": "c"},
        tool="Zoom_In_Tool",
        event_id="r0",
    )
    denied = event(
        1,
        "worker_01",
        "TOOL_CALL_FAILED",
        {"tool_call_id": "c", "error": {"code": "budget_denied"}},
        tool="Zoom_In_Tool",
        parent="r0",
        status="failed",
    )
    activity = annotate_events([request, denied], topology)[-1]["activity"]
    assert activity["kind"] == "tool_denied"
    assert all(
        "tool:Zoom_In_Tool" not in hop for hop in hops(activity)
    )  # never reached the tool


def test_concurrent_same_tool_calls_from_different_workers_never_merge() -> None:
    topology = build_topology(manifest_for(2), [], run_id="r")
    first = tool_lifecycle("worker_01", 0, call="call_0")
    second = tool_lifecycle(
        "worker_02", 10, call="call_0"
    )  # identical model-provided call ID
    interleaved = [first[0], second[0], first[1], second[1], second[2], first[2]]
    for index, item in enumerate(interleaved):
        item["sequence"] = index
    annotated = annotate_events(interleaved, topology)
    corr = {item["event_id"]: item["activity"]["correlation_id"] for item in annotated}
    assert (
        corr["req_worker_01_0"]
        == corr["start_worker_01_0"]
        == corr["close_worker_01_0"]
    )
    assert (
        corr["req_worker_02_10"]
        == corr["start_worker_02_10"]
        == corr["close_worker_02_10"]
    )
    assert corr["req_worker_01_0"] != corr["req_worker_02_10"]
    # Even without parent links, (agent, call id) keeps the workers apart.
    for item in interleaved:
        item["parent_event_id"] = None
    annotated = annotate_events(interleaved, topology)
    by_agent = {}
    for item in annotated:
        by_agent.setdefault(item["agent_id"], set()).add(
            item["activity"]["correlation_id"]
        )
    assert all(len(values) == 1 for values in by_agent.values())
    assert by_agent["worker_01"] != by_agent["worker_02"]


def test_invocation_ids_separate_repeated_call_ids_within_one_worker() -> None:
    topology = build_topology(manifest_for(1), [], run_id="r")
    first = tool_lifecycle("worker_01", 0, call="dup", invocation="inv_a")
    second = tool_lifecycle("worker_01", 3, call="dup", invocation="inv_b")
    annotated = annotate_events(
        [first[0], first[1], second[0], second[1], first[2], second[2]], topology
    )
    assert [item["activity"]["correlation_id"] for item in annotated] == [
        "inv:inv_a",
        "inv:inv_a",
        "inv:inv_b",
        "inv:inv_b",
        "inv:inv_a",
        "inv:inv_b",
    ]


def message(
    seq: int,
    sender: str,
    recipient: str,
    kind: str,
    message_id: str,
    correlation: str | None = None,
) -> dict:
    return event(
        seq,
        sender,
        "MESSAGE_SENT",
        {
            "message_id": message_id,
            "recipient_id": recipient,
            "message_type": kind,
            "correlation_id": correlation,
        },
    )


def test_messages_replies_assignments_and_reports() -> None:
    topology = build_topology(manifest_for(3), [], run_id="r")
    events = [
        message(0, "coordinator", "worker_01", "TASK_ASSIGNMENT", "m0"),
        event(
            1,
            "worker_01",
            "MESSAGE_DELIVERED",
            {"message_id": "m0", "sender_id": "coordinator"},
        ),
        message(2, "worker_01", "worker_03", "QUESTION", "m1"),
        message(3, "worker_03", "worker_01", "EVIDENCE", "m2", correlation="m1"),
        message(
            4, "worker_02", "worker_01", "EVIDENCE", "m3", correlation="m1"
        ),  # not a party to m1
        message(5, "worker_01", "coordinator", "CANDIDATE_ANSWER", "m4"),
        message(6, "coordinator", "worker_02", "VERIFICATION_REQUEST", "m5"),
        message(7, "worker_02", "worker_03", "EVIDENCE", "m6", correlation="unknown"),
    ]
    activity = [item["activity"] for item in annotate_events(events, topology)]
    assert activity[0]["kind"] == "assignment" and hops(activity[0]) == [
        ("coordinator", "comm_bus")
    ]
    assert activity[1]["kind"] == "message_delivery" and hops(activity[1]) == [
        ("comm_bus", "worker_01")
    ]
    assert activity[1]["correlation_id"] == activity[0]["correlation_id"] == "msg:m0"
    assert activity[2]["kind"] == "question" and activity[2]["recipient"] == "worker_03"
    assert activity[3]["kind"] == "reply" and activity[3]["reply_to"] == "msg:m1"
    assert hops(activity[3]) == [("worker_03", "comm_bus")]
    assert activity[4]["kind"] != "reply" and activity[4]["reply_to"] is None
    assert activity[5]["kind"] == "report"
    assert activity[6]["kind"] == "verification_request"
    assert activity[7]["kind"] != "reply"


def test_reply_cannot_reference_a_later_message() -> None:
    topology = build_topology(manifest_for(2), [], run_id="r")
    events = [
        message(0, "worker_02", "worker_01", "EVIDENCE", "m2", correlation="m1"),
        message(1, "worker_01", "worker_02", "QUESTION", "m1"),
    ]
    assert annotate_events(events, topology)[0]["activity"]["kind"] != "reply"


def test_memory_model_and_budget_directions() -> None:
    topology = build_topology(manifest_for(1), [], run_id="r")
    service = next(n["id"] for n in topology["nodes"] if n["type"] == "model_service")
    events = [
        event(0, "worker_01", "MEMORY_WRITTEN", {"tool_call_id": "c"}),
        event(1, "worker_01", "MEMORY_READ", {"read_kind": "environment_update"}),
        event(
            2,
            "worker_01",
            "MODEL_REQUEST_STARTED",
            {"request_id": "q"},
            status="running",
            event_id="m",
        ),
        event(
            3, "worker_01", "MODEL_RESPONSE_RECEIVED", {"request_id": "q"}, parent="m"
        ),
        event(
            4,
            "worker_01",
            "BUDGET_UPDATED",
            {"resource": "tool_calls", "granted": True},
        ),
        event(
            5,
            "worker_01",
            "BUDGET_UPDATED",
            {"resource": "tool_calls", "granted": False},
            status="failed",
        ),
        event(
            6, "worker_01", "BUDGET_UPDATED", {"resource": "messages", "granted": True}
        ),
    ]
    a = [item["activity"] for item in annotate_events(events, topology)]
    assert a[0]["kind"] == "memory_write" and hops(a[0]) == [
        ("worker_01.harness", "worker_01.memory")
    ]
    assert a[1]["kind"] == "memory_read" and hops(a[1]) == [
        ("worker_01.memory", "worker_01.harness")
    ]
    assert hops(a[2]) == [
        ("worker_01.harness", "worker_01.model_client"),
        ("worker_01.model_client", service),
    ]
    assert hops(a[3]) == [
        (service, "worker_01.model_client"),
        ("worker_01.model_client", "worker_01.harness"),
    ]
    assert (
        a[2]["correlation_id"] == a[3]["correlation_id"]
        and a[2]["phase"] == "open"
        and a[3]["phase"] == "close"
    )
    assert a[4]["kind"] == "budget_grant" and hops(a[4]) == [
        ("worker_01.harness", "budget")
    ]
    assert a[5]["kind"] == "budget_deny" and a[5]["outcome"] == "failed"
    assert hops(a[6]) == [("worker_01", "comm_bus"), ("comm_bus", "budget")]


def test_memory_read_is_never_inferred_from_a_write() -> None:
    topology = build_topology(manifest_for(1), [], run_id="r")
    annotated = annotate_events([event(0, "worker_01", "MEMORY_WRITTEN", {})], topology)
    assert all(item["activity"]["kind"] != "memory_read" for item in annotated)


@pytest.fixture(scope="module")
def recorded_runs(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("runs")
    for script, run in (
        ("scripts/studio_protocol_fixture.py", "fixture"),
        ("scripts/multi_agent_smoke.py", "demo"),
    ):
        done = subprocess.run(
            [sys.executable, script, "--output-dir", str(root), "--run-id", run],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert done.returncode == 0, done.stderr
    return root


@pytest.mark.parametrize("run", ["fixture", "demo"])
def test_every_recorded_hop_resolves_to_a_topology_edge(
    recorded_runs: Path, run: str
) -> None:
    snapshot = public_snapshot(recorded_runs, run)
    edges = {edge["id"] for edge in snapshot["topology"]["edges"]}
    for item in snapshot["events"]:
        for source, target in hops(item["activity"]):
            assert f"{source}->{target}" in edges or f"{target}->{source}" in edges, (
                item["event_type"],
                source,
                target,
            )


@pytest.mark.parametrize("run", ["fixture", "demo"])
def test_annotations_depend_only_on_the_event_prefix(
    recorded_runs: Path, run: str
) -> None:
    snapshot = public_snapshot(recorded_runs, run)
    raw = [
        {key: value for key, value in item.items() if key != "activity"}
        for item in snapshot["events"]
    ]
    full = annotate_events(raw, snapshot["topology"])
    for cut in range(0, len(raw) + 1, 7):
        assert annotate_events(raw[:cut], snapshot["topology"]) == full[:cut]


def test_demo_run_declares_fixture_policy_not_a_model_service(
    recorded_runs: Path,
) -> None:
    topology = public_snapshot(recorded_runs, "demo")["topology"]
    services = [node for node in topology["nodes"] if node["type"] == "model_service"]
    assert len(services) == 1 and services[0]["metadata"]["kind"] == "fixture"
    tools = sorted(
        node["label"] for node in topology["nodes"] if node["type"] == "tool"
    )
    assert tools == ["Visual_Grounding_Tool", "Zoom_In_Tool"]
    assert topology["source"] == "manifest.topology"


# ---------------------------------------------------------------------------
# Server, cache, and security


def route_for(app, path: str):
    return next(route for route in app.routes if getattr(route, "path", None) == path)


def test_topology_endpoint_is_authenticated_and_events_carry_activity(
    recorded_runs: Path,
) -> None:
    app = create_app(recorded_runs, viewer_token="token")
    route = route_for(app, "/api/runs/{run_id}/topology")
    authorize = route.dependant.dependencies[0].call
    with pytest.raises(HTTPException) as denied:
        authorize("wrong")
    assert denied.value.status_code == 401
    topology = asyncio.run(route.endpoint("fixture"))
    assert topology["schema_version"] == "studio.topology.v1"
    events = asyncio.run(
        route_for(app, "/api/runs/{run_id}/events").endpoint("fixture", after=-1)
    )["events"]
    assert events and all(
        item["activity"]["schema_version"] == "studio.activity.v1" for item in events
    )
    with pytest.raises(HTTPException) as missing:
        asyncio.run(route.endpoint("../fixture"))
    assert missing.value.status_code == 404


def test_incremental_cache_reads_only_complete_appended_lines(tmp_path: Path) -> None:
    run = tmp_path / "live"
    run.mkdir()
    (run / "run_manifest.json").write_text(json.dumps(manifest_for(1)))
    path = run / "events.jsonl"
    lines = [json.dumps(item) for item in tool_lifecycle("worker_01", 0)]
    path.write_text(lines[0] + "\n" + lines[1][:20])  # second line still in flight
    cache = RunEventCache(run)
    events, _ = cache.snapshot()
    assert [item["event_type"] for item in events] == ["TOOL_CALL_REQUESTED"]
    path.write_text(lines[0] + "\n" + lines[1] + "\n" + lines[2] + "\n")
    events, _ = cache.snapshot()
    assert [item["activity"]["kind"] for item in events] == [
        "tool_request",
        "tool_running",
        "tool_result",
    ]
    assert len({item["activity"]["correlation_id"] for item in events}) == 1


def test_cache_rebuilds_topology_when_a_new_component_is_observed(
    tmp_path: Path,
) -> None:
    run = tmp_path / "legacy"
    run.mkdir()
    path = run / "events.jsonl"
    path.write_text(json.dumps(event(0, "worker_01", "WORKER_STARTED")) + "\n")
    cache = RunEventCache(run)
    _, first = cache.snapshot()
    with path.open("a") as stream:
        stream.write(
            json.dumps(
                event(
                    1,
                    "worker_01",
                    "TOOL_CALL_REQUESTED",
                    {"tool_call_id": "c"},
                    tool="OCR_Tool",
                )
            )
            + "\n"
        )
    events, second = cache.snapshot()
    assert first["fingerprint"] != second["fingerprint"]
    assert "tool:OCR_Tool" in {node["id"] for node in second["nodes"]}
    assert events[-1]["activity"]["tool_node"] == "tool:OCR_Tool"


def test_snapshot_never_exposes_endpoint_credentials(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    manifest = manifest_for(1)
    manifest["actors"] = {
        "worker_01": {"endpoint": SECRET_ENDPOINT, "agent_object_id": 1}
    }
    manifest["pid"] = 42
    (run / "run_manifest.json").write_text(json.dumps(manifest))
    (run / "events.jsonl").write_text("")
    serialized = json.dumps(public_snapshot(tmp_path, "run"))
    for secret in ("hunter2", "sk-SECRET", "alice", '"pid"'):
        assert secret not in serialized


def test_frontend_never_uses_html_injection_or_stores_tokens() -> None:
    static = ROOT / "openvlharness/studio/static"
    for path in static.glob("*.js"):
        source = path.read_text()
        for sink in (
            "innerHTML",
            "outerHTML",
            "insertAdjacentHTML",
            "document.write",
            "eval(",
            "new Function",
        ):
            assert sink not in source, (path.name, sink)
        # The viewer token may be remembered only under an instance-scoped key (a
        # restarted Studio never accepts an old entry); the evaluator token, which
        # releases ground truth, is never written to persistent storage.
        assert 'localStorage.setItem("studio.token' not in source
        for line in source.splitlines():
            if "localStorage.setItem" in line:
                assert "evaluator" not in line.lower(), (path.name, line)
    app = (static / "app.js").read_text()
    assert "window.localStorage.setItem(key, state.token)" in app
    assert "state.backend.instance_id" in app.split("function sessionKey")[1].split("\n")[0]
    html = (static / "index.html").read_text()
    for component in (
        "agent-graph",
        "inspector",
        "timeline",
        "image-stage",
        "step-details",
        "memory-content",
        "replay-slider",
        "final-answer",
        "data-theme-choice",
        "data-graph-mode",
    ):
        assert component in html
    assert (
        "<script>" not in html and "style=" not in html
    )  # CSP: no inline script or style
    theme = (static / "theme.js").read_text()
    code = "\n".join(
        line
        for line in theme.splitlines()
        if not line.lstrip().startswith(("*", "/*", "//"))
    )
    assert "studio.theme" in theme and "token" not in code.lower()


def test_stylesheet_defines_complete_light_and_dark_tokens() -> None:
    css = (ROOT / "openvlharness/studio/static/styles.css").read_text()
    light, dark = css.split(':root[data-theme="dark"]', 1)
    light = light.split(':root[data-theme="light"]', 1)[1].split("}", 1)[0]
    dark = dark.split("}", 1)[0]
    names = lambda block: {
        line.split(":")[0].strip()
        for line in block.splitlines()
        if line.strip().startswith("--")
    }
    assert names(light) == names(dark)
    for token in (
        "--app-background",
        "--panel-background",
        "--text-primary",
        "--graph-edge-idle",
        "--flow-request",
        "--flow-response",
        "--flow-failure",
        "--memory-color",
        "--tool-color",
    ):
        assert token in names(light)
    assert "invert(" not in css
    assert "prefers-reduced-motion" in css


# ---------------------------------------------------------------------------
# Runtime instrumentation (no network)


class Fixed:
    def __init__(self, responses):
        self.responses = list(responses)

    def __call__(self, payload):
        return copy.deepcopy(self.responses.pop(0))


class Probe:
    name = "Probe_Tool"
    backend = "probe_backend"

    def __init__(self):
        self.calls = 0

    def public_schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "probe",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        }

    def invoke(self, call, memory):
        self.calls += 1
        return CapabilityResult(
            ok=True,
            data={"n": 1},
            evidence=[{"type": "text", "text": "one"}],
            payload={
                "ok": True,
                "tool_name": call.name,
                "tool_call_id": call.call_id,
                "result": {"n": 1},
                "error": None,
            },
        )


def tool_turn(call_id: str) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "Probe_Tool",
                                "arguments": '{"query": "x"}',
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"completion_tokens": 3, "prompt_tokens": 10},
    }


def make_observed_agent(responses, tool_limit: int):
    model = ModelAdapter(
        {
            "alias": "qwen3-vl-8b-instruct",
            "base": "http://fixture.invalid/v1",
            "max_tokens": 64,
        },
        requester=Fixed(responses),
    )
    probe = Probe()
    agent = MainAgent(
        model, {probe.name: probe}, MemoryStore, "system", "Question: {user_query}"
    )
    emitted = []

    def sink(event_type, payload, **metadata):
        record = {
            "event_id": f"e{len(emitted)}",
            "event_type": event_type,
            "payload": payload,
            **metadata,
        }
        emitted.append(record)
        return record

    agent.event_sink = sink
    budget = BudgetManager(
        {"tool_calls": tool_limit, "model_requests": 10},
        {"w": {"tool_calls": tool_limit, "model_requests": 10}},
    )
    agent.budget_guard = AgentBudgetGuard(budget, "w")
    return agent, probe, emitted


def test_agent_records_model_boundaries_and_invocation_ids_without_content() -> None:
    final = {
        "choices": [{"message": {"role": "assistant", "content": "<answer>1</answer>"}}]
    }
    agent, probe, emitted = make_observed_agent(
        [tool_turn("same"), final], tool_limit=5
    )
    result = agent.generate("How many?")
    assert result["prediction"] == "1" and probe.calls == 1
    types = [item["event_type"] for item in emitted]
    assert (
        types.count("MODEL_REQUEST_STARTED") == 2
        and types.count("MODEL_RESPONSE_RECEIVED") == 2
    )
    started = [
        item for item in emitted if item["event_type"] == "MODEL_REQUEST_STARTED"
    ]
    responses = [
        item for item in emitted if item["event_type"] == "MODEL_RESPONSE_RECEIVED"
    ]
    assert [r["parent_event_id"] for r in responses] == [s["event_id"] for s in started]
    assert responses[0]["payload"]["usage"] == {
        "completion_tokens": 3,
        "prompt_tokens": 10,
    }
    assert "content" not in json.dumps([s["payload"] for s in started + responses])
    tool_events = [
        item
        for item in emitted
        if item["event_type"].startswith("TOOL_CALL")
        or item["event_type"]
        in {"DECISION_SUMMARY_RECORDED", "EVIDENCE_OBSERVED", "MEMORY_WRITTEN"}
    ]
    invocations = {item["payload"]["invocation_id"] for item in tool_events}
    assert len(invocations) == 1 and next(iter(invocations)).startswith("inv_")
    started_tool = next(
        item for item in emitted if item["event_type"] == "TOOL_CALL_STARTED"
    )
    assert started_tool["payload"]["backend"] == "probe_backend"
    assert "MEMORY_READ" in types
    completed = next(
        item for item in emitted if item["event_type"] == "TOOL_CALL_COMPLETED"
    )
    assert completed["parent_event_id"] == started_tool["event_id"]


def test_budget_denied_tool_call_is_never_reported_as_started() -> None:
    final = {
        "choices": [{"message": {"role": "assistant", "content": "<answer>0</answer>"}}]
    }
    agent, probe, emitted = make_observed_agent([tool_turn("c1"), final], tool_limit=0)
    agent.generate("How many?")
    types = [item["event_type"] for item in emitted]
    assert probe.calls == 0
    assert "TOOL_CALL_STARTED" not in types
    failed = next(item for item in emitted if item["event_type"] == "TOOL_CALL_FAILED")
    requested = next(
        item for item in emitted if item["event_type"] == "TOOL_CALL_REQUESTED"
    )
    assert failed["payload"]["error"]["code"] == "budget_denied"
    assert failed["parent_event_id"] == requested["event_id"]


def test_agent_without_event_sink_is_unchanged() -> None:
    final = {
        "choices": [{"message": {"role": "assistant", "content": "<answer>2</answer>"}}]
    }
    agent, probe, emitted = make_observed_agent([tool_turn("c"), final], tool_limit=5)
    agent.event_sink = None
    assert agent.generate("How many?")["prediction"] == "2"
    assert emitted == [] and probe.calls == 1


def test_orchestrator_manifest_publishes_sanitized_topology(
    recorded_runs: Path,
) -> None:
    manifest = json.loads((recorded_runs / "demo" / "run_manifest.json").read_text())
    topology = manifest["topology"]
    assert topology["schema_version"] == "studio.topology_manifest.v1"
    assert set(topology["actors"]) == {"coordinator", "worker_01", "worker_02"}
    assert topology["actors"]["coordinator"]["tools"] == []
    assert topology["actors"]["worker_02"]["tools"][0]["name"] == "Zoom_In_Tool"
    assert topology["budget"]["tool_calls"] > 0


def test_activity_mapper_ignores_unknown_actor_events() -> None:
    mapper = ActivityMapper()
    activity = mapper.annotate(event(0, "orchestrator", "SOMETHING_NEW"))
    assert activity["path"] == [] and activity["nodes"] == ["orchestrator"]
