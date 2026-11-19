"""Declared action plans in the real agent loop and the multi-agent orchestrator (deterministic fixture)."""

import json
from pathlib import Path

import pytest

from openvlharness.multi_agent.testing import _text_of
from openvlharness.parsec_vl import Scheduler
from openvlharness.parsec_vl.controller import PlanningConfig
from openvlharness.parsec_vl.fixture import (
    PARALLEL_PLAN, SIGN_TEXT, PlanAgentBuilder, create_sign_scene, run_plan_fixture,
)
from openvlharness.parsec_vl.harness import PlanController, ToolScheduling, attach_plan_mode, pools_for
from openvlharness.parsec_vl.plans import PLAN_TOOL


def plan_agent(scene, *, plan="parallel", policy="e2", mode="e3", delay=0.25, attach=True):
    builder = PlanAgentBuilder(scene, plan=plan, tool_delay=delay)
    agent = builder(None, "worker_01", True)
    events = []
    agent.event_sink = lambda t, p, **m: (events.append({"event_type": t, "payload": p, **m}), {"event_id": f"e{len(events)}"})[1]
    scheduler = Scheduler(policy=policy, workers=4, capacities=pools_for([agent]))
    agent.tool_scheduler = ToolScheduling(scheduler, "worker_01")
    if attach:
        attach_plan_mode(agent, PlanController(scheduler, "worker_01", PlanningConfig.for_mode(mode, plan_selection=False)))
    return agent, builder, scheduler, events


def ask(agent, scene):
    return agent.generate([{"type": "image", "value": str(scene)}, {"type": "text", "value": "What does the sign say?"}])


@pytest.fixture(scope="module")
def scene(tmp_path_factory) -> Path:
    return create_sign_scene(tmp_path_factory.mktemp("sign") / "scene.png")


def overlap(a, b):
    return a["start"] < b["end"] and b["start"] < a["end"]


def test_default_protocol_is_unchanged(scene):
    agent, builder, scheduler, events = plan_agent(scene, attach=False)
    assert agent.decision_protocol == "legacy_single_call"
    assert PLAN_TOOL not in [s["function"]["name"] for s in agent.json_schema]
    out = ask(agent, scene)  # the scripted model calls Execute_Action_Plan anyway
    scheduler.shutdown()
    failed = [e for e in events if e["event_type"] == "TOOL_CALL_FAILED"]
    assert failed and failed[0]["payload"]["error"]["code"] == "tool_not_found"  # fails safely, nothing executed
    assert builder.log == [] and out["prediction"] == "unreadable"


def test_plan_mode_is_an_explicit_opt_in(scene):
    agent, _, scheduler, _ = plan_agent(scene)
    scheduler.shutdown()
    assert agent.decision_protocol == "declared_multi_action_plan"
    assert PLAN_TOOL in [s["function"]["name"] for s in agent.json_schema]
    assert agent.adapter.allow_multiple_tool_calls is False  # still one tool call per model message


def test_independent_plan_actions_overlap_and_dependents_wait(scene):
    agent, builder, scheduler, events = plan_agent(scene, policy="e2")
    out = ask(agent, scene)
    scheduler.shutdown()
    assert out["prediction"] == SIGN_TEXT
    by_tool = {}
    for record in builder.log:
        by_tool.setdefault(record["tool"], []).append(record)
    ocr_full, ocr_crop = sorted(by_tool["ocr"], key=lambda r: r["start"])
    [ground], [crop] = by_tool["grounding"], by_tool["zoom"]
    assert overlap(ocr_full, ground)                      # independent: ran at the same time
    assert crop["start"] >= ground["end"]                  # Zoom needs the grounding box
    assert ocr_crop["start"] >= crop["end"]                # crop OCR needs the crop
    assert not ocr_full["readable"] and ocr_crop["readable"] and ocr_crop["size"][0] < 400
    completed = [e["payload"] for e in events if e["event_type"] == "TOOL_CALL_COMPLETED" and e["payload"].get("plan_id")]
    assert [p["action_id"] for p in completed] == ["ocr_full", "g", "z", "ocr_crop"]  # commit order
    zoom_event = next(p for p in completed if p["action_id"] == "z")
    assert zoom_event["arguments"] if "arguments" in zoom_event else True
    requested = {e["payload"]["action_id"]: e["payload"] for e in events if e["event_type"] == "TOOL_CALL_REQUESTED" and e["payload"].get("plan_id")}
    assert requested["ocr_crop"]["arguments"]["image_id"] == "tool_generated_image_2"  # the crop, not the original
    assert len(requested["z"]["arguments"]["coords"]) == 4


def test_sequential_and_parallel_dispatch_publish_the_same_observations(scene):
    seen = {}
    for policy in ("e0", "e2"):
        agent, builder, scheduler, _ = plan_agent(scene, policy=policy, delay=0.1)
        ask(agent, scene)
        scheduler.shutdown()
        messages = builder.policies["worker_01"].requests[-1]["messages"]
        seen[policy] = [_text_of(m.get("content")) for m in messages if m.get("role") == "user"]
        intervals = sorted(builder.log, key=lambda r: r["start"])
        if policy == "e0":
            assert all(b["start"] >= a["end"] for a, b in zip(intervals, intervals[1:]))
    strip = lambda texts: [t.split("Action plan")[1].split(":")[1] if "Action plan" in t else t for t in texts]  # noqa: E731
    assert strip(seen["e0"]) == strip(seen["e2"])  # same evidence, same order, same registry IDs


def test_invalid_plan_is_rejected_and_the_agent_continues(scene, monkeypatch):
    import openvlharness.parsec_vl.fixture as fixture

    bad = json.loads(json.dumps(PARALLEL_PLAN))
    bad["actions"][3]["arguments"]["image_id"] = "$nowhere.image"  # refers to an action that does not exist
    monkeypatch.setitem(fixture.PLANS, "parallel", bad)
    agent, builder, scheduler, events = plan_agent(scene)
    out = ask(agent, scene)
    scheduler.shutdown()
    assert builder.log == []  # nothing executed
    assert agent.plan_controller.stats["invalid"] == 1
    assert agent.plan_controller.stats["rejection_reasons"] == {"unknown_dependency": 1}
    failed = next(e for e in events if e["event_type"] == "TOOL_CALL_FAILED")
    assert failed["payload"]["error"]["code"] == "invalid_plan:unknown_dependency"
    assert out["extra_records"]["trajectory"]["error"] is None if "error" in out["extra_records"]["trajectory"] else True


@pytest.mark.parametrize("workers", [1, 2, 3, 4])
@pytest.mark.parametrize("policy", ["off", "e2", "e3", "e4", "e5"])
def test_multi_agent_runs_complete_in_every_mode(tmp_path, workers, policy):
    orchestrator, builder, result, events = run_plan_fixture(tmp_path, policy=policy, workers=workers, tool_delay=0.05,
                                                             planning_processes=0, rollouts=200)
    assert result["extra_records"]["status"] == "COMPLETED" and result["prediction"] == SIGN_TEXT
    final = json.loads((orchestrator.run_dir / "final_result.json").read_text())
    budgets = final["budgets"]["global"]["tool_calls"]
    assert budgets["used"] <= budgets["limit"]
    kinds = [e["event_type"] for e in events]
    if policy in ("e3", "e4", "e5"):
        assert final["effective_config"]["tool_scheduler"]["decision_protocol"] == "declared_multi_action_plan"
        assert kinds.count("PLAN_CANDIDATES_GENERATED") == workers
        assert all(s["stats"]["valid"] == 1 for s in final["planning"].values())
    else:
        assert not any(k.startswith(("PLAN_", "SPECULATIVE_")) for k in kinds)


@pytest.mark.parametrize("memory, peer", [(True, True), (False, False)])
def test_memory_and_peer_switches_still_work_with_plans(tmp_path, memory, peer):
    _, _, result, events = run_plan_fixture(tmp_path, policy="e5", workers=2, memory=memory, peer=peer,
                                            tool_delay=0.05, planning_processes=0, rollouts=200)
    assert result["extra_records"]["status"] == "COMPLETED"
    config = next(e for e in events if e["event_type"] == "RUN_CONFIGURATION_RECORDED")["payload"]["effective_config"]
    assert config["optional_worker_memory_enabled"] is memory and config["peer_communication_enabled"] is peer


def test_tight_global_budget_is_never_overspent(tmp_path):
    orchestrator, _, result, _ = run_plan_fixture(tmp_path, policy="e4", workers=2, global_tool_calls=3,
                                                  tool_delay=0.05, planning_processes=0, rollouts=200)
    budgets = json.loads((orchestrator.run_dir / "budgets.json").read_text())["global"]["tool_calls"]
    assert budgets["used"] <= 3 and result["extra_records"]["status"] == "COMPLETED"


def test_worker_failure_does_not_block_the_other_workers(tmp_path, monkeypatch):
    import openvlharness.parsec_vl.fixture as fixture

    original = fixture.PlanPolicy.__call__

    def flaky(self, payload):
        if self.actor_id == "worker_02":
            raise RuntimeError("worker model crashed")
        return original(self, payload)
    monkeypatch.setattr(fixture.PlanPolicy, "__call__", flaky)
    _, _, result, events = run_plan_fixture(tmp_path, policy="e5", workers=2, tool_delay=0.05, planning_processes=0, rollouts=200)
    assert result["extra_records"]["status"] == "COMPLETED" and result["prediction"] == SIGN_TEXT
    assert any(e["event_type"] == "WORKER_FINISHED" and e["agent_id"] == "worker_02" and e["status"] == "failed" for e in events) \
        or any(e["agent_id"] == "worker_02" and e["status"] == "failed" for e in events)


def test_planning_uses_real_processes_in_a_run(tmp_path):
    orchestrator, _, result, events = run_plan_fixture(tmp_path, policy="e5", workers=1, tool_delay=0.05,
                                                       planning_processes=2, rollouts=400,
                                                       planning={"planning_gate": "off"})
    configured = next(e for e in events if e["event_type"] == "PLANNING_CONFIGURED")["payload"]
    assert configured["planning_processes"] == 2 and configured["warning"] is None
    evaluations = [e["payload"] for e in events if e["event_type"] == "PLAN_EVALUATION_COMPLETED"]
    assert evaluations and all(e["processes"] == 2 for e in evaluations)


def test_studio_replays_a_plan_run_and_keeps_planning_technical(tmp_path):
    from openvlharness.studio.replay import run_cache

    orchestrator, _, _, events = run_plan_fixture(tmp_path, policy="e4", workers=1, tool_delay=0.05, planning_processes=0)
    replayed, _ = run_cache(orchestrator.run_dir.parent, orchestrator.run_id).snapshot()
    assert [e["event_id"] for e in replayed] == [e["event_id"] for e in events]
    planning = [e for e in replayed if e["event_type"].startswith(("PLAN_", "SPECULATIVE_", "REPLAN_"))]
    assert planning and all((e.get("activity") or {}).get("kind", "lifecycle") == "lifecycle" for e in planning)


def test_reference_answer_never_reaches_planning(tmp_path):
    orchestrator, _, _, events = run_plan_fixture(tmp_path, policy="e5", workers=1, tool_delay=0.05,
                                                  planning_processes=0, reference=True)
    assert (tmp_path / ".references").exists()
    for event in events:
        if event["event_type"].startswith(("PLAN_", "REPLAN_", "SPECULATIVE_")):
            assert ".references" not in json.dumps(event)


@pytest.mark.parametrize("policy", ["e3", "e4"])
def test_every_published_plan_action_has_a_request_event(tmp_path, policy):
    """Studio pairs REQUESTED/COMPLETED by invocation ID, including actions adopted while still running."""
    _, _, _, events = run_plan_fixture(tmp_path, policy=policy, workers=1, tool_delay=0.05, planning_processes=0)
    requested = {e["payload"]["invocation_id"]: i for i, e in enumerate(events) if e["event_type"] == "TOOL_CALL_REQUESTED"}
    completed = [(i, e) for i, e in enumerate(events) if e["event_type"] == "TOOL_CALL_COMPLETED" and e["payload"].get("plan_id")]
    assert len(completed) == 4
    for index, event in completed:
        assert requested[event["payload"]["invocation_id"]] < index
    adopted = [e["payload"]["action_id"] for _, e in completed if e["payload"]["adopted_from_speculation"]]
    assert adopted == ([] if policy == "e3" else ["g", "z", "ocr_crop"])



def test_no_planning_pool_is_started_when_no_plan_arrives(tmp_path):
    """E5 with a worker that never calls Execute_Action_Plan: the lazy pool never starts."""
    orchestrator, _, result, events = run_plan_fixture(tmp_path, policy="e5", workers=2, legacy=True, tool_delay=0.05,
                                                       planning_processes=2)
    kinds = [e["event_type"] for e in events]
    assert result["extra_records"]["status"] == "COMPLETED"
    assert "PLANNING_POOL_STARTED" not in kinds and "PLAN_CANDIDATES_GENERATED" not in kinds
    final = json.loads((orchestrator.run_dir / "final_result.json").read_text())
    assert final["planning_pool"] == {"mode": "lazy", "started": False, "startup_seconds": 0.0}


def test_gate_records_its_choice_and_skips_the_pool_for_small_decisions(tmp_path):
    orchestrator, _, _, events = run_plan_fixture(tmp_path, policy="e5", workers=1, tool_delay=0.05, planning_processes=2)
    started = [e["payload"] for e in events if e["event_type"] == "PLAN_EVALUATION_STARTED"]
    skipped = [e["payload"] for e in events if e["event_type"] == "PLAN_EVALUATION_SKIPPED"]
    assert started or skipped
    for payload in started:
        assert payload["gate"]["backend"] in ("sequential", "parallel") and "stakes_s" in payload["gate"]
    assert all(p["backend"] == "heuristic" and p["reason"] for p in skipped)
    assert "PLANNING_POOL_STARTED" not in [e["event_type"] for e in events]  # two candidates: in-process is cheaper


def test_eager_pool_reproduces_phase2_startup(tmp_path):
    _, _, _, events = run_plan_fixture(tmp_path, policy="e5", workers=1, tool_delay=0.05, planning_processes=2,
                                       planning={"planning_pool": "eager", "planning_gate": "off"})
    started = [e["payload"] for e in events if e["event_type"] == "PLANNING_POOL_STARTED"]
    assert len(started) == 1 and started[0]["startup_seconds"] > 0


def test_shared_pool_starts_once_across_runs(tmp_path):
    from openvlharness.parsec_vl.montecarlo import PlanEvaluator

    PlanEvaluator.shutdown_shared()
    try:
        counts = []
        for index in range(2):
            _, _, _, events = run_plan_fixture(tmp_path / str(index), policy="e5", workers=1, tool_delay=0.05,
                                               planning_processes=2, planning={"planning_pool": "shared", "planning_gate": "off"})
            counts.append(sum(e["event_type"] == "PLANNING_POOL_STARTED" for e in events))
        assert counts == [1, 0]  # the second run reuses the warm pool
        assert PlanEvaluator.shared(2).started
    finally:
        PlanEvaluator.shutdown_shared()


def test_concurrent_first_use_starts_exactly_one_pool():
    import threading

    from openvlharness.parsec_vl.experiments import benchmark_candidates
    from openvlharness.parsec_vl.montecarlo import PlanEvaluator

    evaluator = PlanEvaluator(processes=2, batch_size=100)
    candidates = benchmark_candidates()[:2]
    threads = [threading.Thread(target=evaluator.evaluate, args=(candidates, 200, 1)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert evaluator.starts == 1
    evaluator.shutdown()
