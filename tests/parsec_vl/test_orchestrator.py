"""The scheduler inside a full multi-agent run (deterministic visual fixture, no models)."""

import json

import pytest

from openvlharness.multi_agent import MultiAgentOrchestrator
from openvlharness.multi_agent.config import apply_run_options, effective_run_config
from openvlharness.multi_agent.testing import fixture_config
from openvlharness.multi_agent.visual_fixture import VisualAgentBuilder, create_visual_scene


def run(tmp_path, policy, tool_delay=0.15):
    image = create_visual_scene(tmp_path / "scene.png")
    config = fixture_config(tmp_path, workers=2, memory=True, peer=False, mode="concurrent", estimate_updates=True,
                            follow_up_rounds=0)
    config["workers"]["overrides"] = {}
    config["workers"]["default"]["tool_calls"] = 8
    config = apply_run_options(config, tool_scheduler=policy, scheduler_workers=4)
    builder = VisualAgentBuilder(image, tool_delay=tool_delay)
    orchestrator = MultiAgentOrchestrator(config, factory=builder.factory(), run_id=f"run_{policy}",
                                          output_directory=tmp_path / "runs")
    result = orchestrator.run("How many marked objects are in the image?", [
        {"type": "image", "value": str(image)}, {"type": "text", "value": "How many marked objects are in the image?"}])
    events = [json.loads(line) for line in (orchestrator.run_dir / "events.jsonl").read_text().splitlines()]
    return orchestrator, result, events


def logical(events):
    per_agent = {}
    requests = {e["payload"]["invocation_id"]: e["payload"]["arguments"] for e in events if e["event_type"] == "TOOL_CALL_REQUESTED"}
    for e in events:
        if e["event_type"] in ("TOOL_CALL_COMPLETED", "TOOL_CALL_FAILED"):
            p = e["payload"]
            per_agent.setdefault(e["agent_id"], []).append(
                (e["tool_name"], json.dumps(requests[p["invocation_id"]], sort_keys=True), p["ok"],
                 [(o.get("registry_id"), o.get("width"), o.get("height")) for o in (p.get("visual") or {}).get("outputs", [])]))
    return per_agent


@pytest.mark.parametrize("policy", ["e0", "e1", "e2"])
def test_scheduled_run_matches_the_original_runtime(tmp_path, policy):
    _, base_result, base_events = run(tmp_path / "off", "off")
    orchestrator, result, events = run(tmp_path / policy, policy)
    assert result["extra_records"]["status"] == base_result["extra_records"]["status"] == "COMPLETED"
    assert result["prediction"] == base_result["prediction"]
    assert logical(events) == logical(base_events)
    kinds = [e["event_type"] for e in events]
    assert kinds.count("SCHEDULER_CONFIGURED") == 1
    tool_calls = kinds.count("TOOL_CALL_STARTED")
    assert kinds.count("SCHEDULER_TASK_STARTED") == kinds.count("SCHEDULER_TASK_FINISHED") == tool_calls > 0
    assert not [e for e in base_events if e["event_type"].startswith("SCHEDULER")]  # off: original event stream
    final = json.loads((orchestrator.run_dir / "final_result.json").read_text())
    summary = final["scheduler"]
    assert summary["policy"] == policy and summary["status"] == {"COMPLETED": tool_calls}
    budgets = json.loads((orchestrator.run_dir / "budgets.json").read_text())
    assert budgets["global"]["tool_calls"]["used"] == summary["budget_used"] == tool_calls
    assert budgets["global"]["tool_calls"]["used"] <= budgets["global"]["tool_calls"]["limit"]
    assert final["effective_config"]["tool_scheduler"]["policy"] == policy
    if policy == "e0":
        assert summary["peak_concurrency"] == 1
    else:
        assert summary["peak_concurrency"] == 2  # the two workers' tool calls overlap


def test_scheduler_records_correlate_with_studio_tool_events(tmp_path):
    _, _, events = run(tmp_path, "e1")
    started = {e["payload"]["scheduler_task_id"]: e for e in events if e["event_type"] == "TOOL_CALL_STARTED"}
    finished = [e for e in events if e["event_type"] == "SCHEDULER_TASK_FINISHED"]
    for record in finished:
        p = record["payload"]
        tool_event = started[p["task_id"]]
        assert tool_event["agent_id"] == record["agent_id"] == p["agent_id"]
        assert p["metadata"]["invocation_id"] == tool_event["payload"]["invocation_id"]
        assert p["resource_pool"] == "cpu" and p["worker_id"] in range(4)
        assert p["finish_time"] >= p["start_time"] >= p["enqueue_time"]


def test_studio_replays_a_scheduled_run(tmp_path):
    from openvlharness.studio.replay import run_cache

    orchestrator, _, events = run(tmp_path, "e1")
    replayed, _ = run_cache(orchestrator.run_dir.parent, orchestrator.run_id).snapshot()
    assert [e["event_id"] for e in replayed] == [e["event_id"] for e in events]
    scheduler_events = [e for e in replayed if e["event_type"].startswith("SCHEDULER_TASK")]
    assert scheduler_events and all((e.get("activity") or {}).get("kind", "lifecycle") == "lifecycle" for e in scheduler_events)


def test_scheduler_is_off_by_default_and_options_are_validated(tmp_path):
    config = fixture_config(tmp_path, workers=1, memory=False, peer=False)
    assert config["execution"]["scheduler"]["policy"] == "off"
    assert effective_run_config(config)["tool_scheduler"]["policy"] == "off"
    with pytest.raises(ValueError):
        apply_run_options(config, tool_scheduler="fast")
    with pytest.raises(ValueError):
        apply_run_options(config, tool_scheduler="e1", scheduler_workers=0)
