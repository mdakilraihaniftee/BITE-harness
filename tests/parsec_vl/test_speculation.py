"""Speculation, cancellation, budget settlement, adoption, isolation, and replanning."""

import threading
import time
from pathlib import Path

import pytest

from openvlharness.parsec_vl import BudgetAdapter, Scheduler, Task, TaskStatus
from openvlharness.parsec_vl.controller import PlanExecutor, PlanningConfig, SyntheticRuntime
from openvlharness.parsec_vl.montecarlo import OutcomeModel, PlanEvaluator
from openvlharness.parsec_vl.plans import ActionPlan, Branch, PlanAction

POOLS = {"OCR_Tool": "ocr", "Visual_Grounding_Tool": "gpu", "Zoom_In_Tool": "cpu", "Unsafe_Tool": "cpu"}
MODEL = OutcomeModel(durations={"OCR_Tool": ("fixed", 0.1), "Visual_Grounding_Tool": ("fixed", 0.2),
                                "Zoom_In_Tool": ("fixed", 0.05)},
                     p_ok={"OCR_Tool": 0.2, "Visual_Grounding_Tool": 0.95, "Zoom_In_Tool": 1.0}, source="declared")


def plan(alternatives=1, unsafe=False, pid="p"):
    branches = [Branch(f"{pid}.primary", "primary", [PlanAction("ocr", "OCR_Tool", {}, (), "text")], "ocr", "fixture")]
    for k in range(1, alternatives + 1):
        tool = "Unsafe_Tool" if unsafe else "Visual_Grounding_Tool"
        branches.append(Branch(f"{pid}.alt{k}", f"alt{k}", [
            PlanAction(f"g{k}", tool, {}), PlanAction(f"z{k}", "Zoom_In_Tool", {}, (f"g{k}",)),
            PlanAction(f"o{k}", "OCR_Tool", {}, (f"z{k}",), "text")], f"o{k}", "fixture"))
    return ActionPlan(pid, "w1", "fixture", branches)


def outcomes(primary_ok, alts=1, alt_ok=True, primary_seconds=0.1):
    result = {"ocr": (primary_seconds, primary_ok)}
    for k in range(1, alts + 1):
        result.update({f"g{k}": (0.2, alt_ok), f"z{k}": (0.05, True), f"o{k}": (0.1, True)})
    return result


def run(mode, outcome, *, alternatives=1, budget=20, workers=4, unsafe=False, evaluator=None, **overrides):
    ledger = BudgetAdapter.with_limit(budget)
    events = []
    scheduler = Scheduler(policy="e2", workers=workers, capacities={"ocr": 1, "gpu": 1, "cpu": 4}, budget=ledger)
    executor = PlanExecutor(scheduler, SyntheticRuntime(outcome, POOLS, MODEL), PlanningConfig.for_mode(mode, plan_selection=False, **overrides),
                            agent_id="w1", emit=lambda kind, payload: events.append((kind, payload)), model=MODEL,
                            budget=ledger.manager, evaluator=evaluator)
    report = executor.execute(plan(alternatives, unsafe))
    settled = executor.settle()
    used = ledger.snapshot()["ledger"]["global"]["tool_calls"]
    scheduler.shutdown()
    return report, settled, used, [k for k, _ in events], events, scheduler


def test_s0_never_speculates_and_falls_back_after_failure():
    report, settled, used, kinds, _, _ = run("e3", outcomes(False))
    assert report["satisfied"] and report["winning_branch"] == "alt1"
    assert "SPECULATIVE_TASK_ADMITTED" not in kinds and settled["wasted_calls"] == 0
    assert used["used"] == 4 and report["decision_latency_s"] > 0.4  # sequential: 0.1 + 0.2 + 0.05 + 0.1


def test_adopted_speculation_hides_latency_without_running_tools_twice():
    report, settled, used, kinds, events, scheduler = run("e4", outcomes(False))
    assert report["winning_branch"] == "alt1" and "SPECULATIVE_RESULT_ADOPTED" in kinds
    assert used["used"] == 4  # each action charged once: adoption reuses the speculative results
    assert report["decision_latency_s"] < 0.42
    assert [a for _, a, _ in report["observations"]] == ["ocr", "g1", "z1", "o1"]
    assert len(scheduler.records()) == 4


def test_unneeded_speculation_is_charged_and_pending_work_is_refunded():
    report, settled, used, kinds, events, scheduler = run("e4", outcomes(True))
    assert report["winning_branch"] == "primary"
    started = [r for r in scheduler.records() if r.get("start_time") is not None]
    # g1 was running when the primary succeeded: cancel requested, physically finished, charged, discarded.
    assert "SPECULATIVE_TASK_CANCEL_REQUESTED" in kinds
    assert any(p.get("backend_cancelled") is False for k, p in events if k == "SPECULATIVE_TASK_CANCEL_REQUESTED")
    assert settled["wasted_calls"] == 1 and settled["wasted_seconds"] >= 0.19
    assert used["used"] == len(started) == 2  # z1/o1 never started: nothing charged for them
    assert [a for _, a, _ in report["observations"]] == ["ocr"]  # no speculative result reaches the agent
    assert report["branches"][1]["status"] == "pruned"


def test_completed_but_unused_speculation_stays_charged():
    # The primary is slow and succeeds: the speculative branch completes first, then is discarded.
    report, settled, used, kinds, _, scheduler = run("e4", outcomes(True, primary_seconds=0.6))
    assert report["winning_branch"] == "primary" and settled["wasted_calls"] == 3
    assert used["used"] == 4 and "SPECULATIVE_RESULT_ADOPTED" not in kinds


def test_queued_speculation_is_cancelled_with_its_reservation_released():
    ledger = BudgetAdapter.with_limit(10)
    scheduler = Scheduler(policy="e2", workers=1, capacities={"cpu": 1})
    scheduler.budget = ledger
    blocker = Task(task_id="busy", operation="x", body=lambda i: time.sleep(0.2))
    spec = Task(task_id="spec", operation="x", body=lambda i: None, metadata={"speculative": True})
    scheduler.submit([blocker, spec])
    time.sleep(0.05)
    assert scheduler.cancel(["spec"]) == ["spec"] and scheduler.task("spec").status is TaskStatus.CANCELLED
    scheduler.wait()
    scheduler.shutdown()
    assert ledger.snapshot()["ledger"]["global"]["tool_calls"]["used"] == 1


def test_unsafe_alternatives_are_never_speculated():
    report, settled, used, kinds, _, _ = run("e4", outcomes(True), unsafe=True)
    assert "SPECULATIVE_TASK_ADMITTED" not in kinds and used["used"] == 1


def test_speculative_budget_limit_and_global_budget_are_never_exceeded():
    report, settled, used, _, _, _ = run("e4", outcomes(False, alts=2), alternatives=2, max_speculative_branches=2,
                                         speculative_budget_limit=3)
    assert report["speculative_tool_calls"] <= 3
    for budget in (1, 2, 3, 5):
        _, _, used, _, _, _ = run("e4", outcomes(False, alts=2, alt_ok=False), alternatives=2, budget=budget,
                                  max_speculative_branches=2)
        assert used["used"] <= budget


def test_s2_keeps_headroom_for_necessary_work_in_a_small_budget():
    # Budget 4 = primary (1) + one alternative (3). S2 must not spend it on speculation it cannot afford.
    report, _, used, kinds, _, _ = run("e5", outcomes(False, alts=2), alternatives=2, budget=4, max_speculative_branches=2)
    assert report["satisfied"] and used["used"] <= 4


def test_necessary_work_is_ordered_before_speculation_and_keeps_reserved_capacity():
    order = []
    scheduler = Scheduler(policy="e2", workers=1, capacities={"gpu": 1}, necessary_slot_reserve=0)
    blocker = Task(task_id="busy", operation="x", body=lambda i: time.sleep(0.1), resource_type="gpu")
    scheduler.submit([blocker])
    scheduler.submit([Task(task_id="spec", operation="x", body=lambda i: order.append("spec"), resource_type="gpu",
                           metadata={"speculative": True}, estimated_cost=5.0)])
    scheduler.submit([Task(task_id="need", operation="x", body=lambda i: order.append("need"), resource_type="gpu",
                           estimated_cost=0.1)])
    scheduler.wait()
    scheduler.shutdown()
    assert order == ["need", "spec"]  # submitted later, higher E2 priority on the speculative task, still second
    limited = Scheduler(policy="e2", workers=4, capacities={"gpu": 2}, speculative_limits={"gpu": 1}, necessary_slot_reserve=1)
    limited.submit([Task(task_id=f"s{i}", operation="x", body=lambda i: time.sleep(0.05), resource_type="gpu",
                         metadata={"speculative": True}) for i in range(3)])
    limited.wait()
    summary = limited.summary()
    limited.shutdown()
    assert summary["peak_concurrency"] == 1  # at most one speculative unit of the gpu pool


def test_replanning_only_on_meaningful_events_and_bounded():
    _, _, _, kinds, _, _ = run("e5", outcomes(True))
    assert "REPLAN_TRIGGERED" not in kinds  # primary succeeded: nothing to reconsider
    report, _, _, kinds, _, _ = run("e5", outcomes(False, alts=3, alt_ok=False), alternatives=3, max_replans=1,
                                    max_speculative_branches=0)
    assert not report["satisfied"] and report["replans"] <= 1
    assert kinds.count("REPLAN_TRIGGERED") == 3  # one per exhausted branch, Monte Carlo at most once


def test_backend_failure_moves_to_the_next_branch():
    class Failing(SyntheticRuntime):
        def backend(self, action, prepared, ctx):
            if action.action_id == "ocr":
                raise RuntimeError("service down")
            return super().backend(action, prepared, ctx)
    ledger = BudgetAdapter.with_limit(10)
    scheduler = Scheduler(policy="e2", workers=4, capacities={"ocr": 1, "gpu": 1, "cpu": 4}, budget=ledger)
    executor = PlanExecutor(scheduler, Failing(outcomes(True), POOLS, MODEL), PlanningConfig.for_mode("e3", plan_selection=False),
                            agent_id="w1", model=MODEL, budget=ledger.manager)
    report = executor.execute(plan())
    scheduler.shutdown()
    assert report["winning_branch"] == "alt1"
    assert ledger.snapshot()["ledger"]["global"]["tool_calls"]["used"] == 4  # the failed call is charged


def test_two_agents_progress_independently_on_one_scheduler():
    ledger = BudgetAdapter.with_limit(40)
    scheduler = Scheduler(policy="e2", workers=6, capacities={"ocr": 2, "gpu": 2, "cpu": 4}, budget=ledger)
    reports = {}

    def agent(name, ok):
        executor = PlanExecutor(scheduler, SyntheticRuntime(outcomes(ok), POOLS, MODEL), PlanningConfig.for_mode("e4", plan_selection=False),
                                agent_id=name, model=MODEL, budget=ledger.manager)
        reports[name] = executor.execute(plan(pid=name))
    threads = [threading.Thread(target=agent, args=(f"w{i}", i % 2 == 0)) for i in range(4)]
    began = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    scheduler.shutdown()
    assert len(reports) == 4 and all(r["satisfied"] for r in reports.values())
    assert time.monotonic() - began < 1.5  # no global round: the fast agents did not wait for the slow ones


def test_monte_carlo_s2_uses_the_process_pool():
    with PlanEvaluator(processes=2, batch_size=100) as evaluator:
        report, _, _, kinds, events, _ = run("e5", outcomes(False), evaluator=evaluator, rollouts=400, planning_time_budget=5.0,
                                             planning_gate="off")
    completed = [p for k, p in events if k == "PLAN_EVALUATION_COMPLETED"]
    assert completed and completed[0]["processes"] == 2 and completed[0]["outcome_model"] == "declared"
    assert report["decision"]["speculation"]["method"] == "monte_carlo"
    assert report["planning"]["cpu_seconds"] > 0


def test_planning_failure_falls_back_safely():
    class Broken:
        processes = 2

        def evaluate(self, *a, **k):
            raise RuntimeError("pool crashed")
    report, _, _, kinds, events, _ = run("e5", outcomes(False), evaluator=Broken(), planning_gate="off")
    assert report["satisfied"]
    assert any(p.get("fallback") for k, p in events if k == "PLAN_EVALUATION_COMPLETED")
    assert report["decision"]["speculation"]["method"] == "closed_form"


def test_harness_branch_isolation_and_adoption(tmp_path: Path):
    """Real capabilities: speculative crops stay out of the agent's memory unless adopted."""
    from openvlharness.parsec_vl.fixture import FALLBACK_PLAN, PlanAgentBuilder, create_sign_scene
    from openvlharness.parsec_vl.harness import PlanController, ToolScheduling, attach_plan_mode, pools_for

    for readable, expect_adopted in ((True, False), (False, True)):
        scene = create_sign_scene(tmp_path / f"scene_{readable}.png", readable=readable)
        builder = PlanAgentBuilder(scene, plan="fallback", tool_delay=0.15, ocr_delay=0.4)
        agent = builder(None, "worker_01", True)
        events = []
        agent.event_sink = lambda t, p, **m: (events.append((t, p)), {"event_id": f"e{len(events)}"})[1]
        scheduler = Scheduler(policy="e2", workers=4, capacities=pools_for([agent]))
        agent.tool_scheduler = ToolScheduling(scheduler, "worker_01")
        attach_plan_mode(agent, PlanController(scheduler, "worker_01", PlanningConfig.for_mode("e4", plan_selection=False)))
        out = agent.generate([{"type": "image", "value": str(scene)}, {"type": "text", "value": "What does the sign say?"}])
        scheduler.shutdown()
        assert out["prediction"] == "EXIT 42"
        adopted = any(t == "SPECULATIVE_RESULT_ADOPTED" for t, _ in events)
        assert adopted is expect_adopted
        published = [p for t, p in events if t == "TOOL_CALL_COMPLETED" and p.get("plan_id")]
        assert {p["action_id"] for p in published} == ({"ocr_full", "g", "z", "ocr_crop"} if expect_adopted else {"ocr_full"})
        # What the model actually received on its next request (the scripted policy records every request).
        from openvlharness.multi_agent.testing import _text_of
        seen = "\n".join(_text_of(m.get("content")) for m in builder.policies["worker_01"].requests[-1]["messages"])
        assert ("[alt1/z]" in seen) is expect_adopted  # speculative evidence reaches the model only when adopted
        assert ("[primary/ocr_full]" in seen) is True
