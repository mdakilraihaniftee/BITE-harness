"""Scheduler engine: policies, real overlap, dependencies, resources, failures, shutdown.

Durations are injected sleeps (deterministic work, real wall clock). Assertions
use interval ordering and generous margins, never exact wall times.
"""

import random
import threading
import time

import pytest

from openvlharness.parsec_vl import BudgetAdapter, Scheduler, Task, TaskOutput, TaskStatus
from openvlharness.parsec_vl.workloads import run_workload


def sleeper(seconds, value=None, calls=None):
    def body(inputs):
        if calls is not None:
            calls.append(threading.get_ident())
        time.sleep(seconds)
        return value if value is not None else sorted(inputs)
    return body


def t(tid, seconds=0.05, deps=(), pool="cpu", cost=None, **kw):
    return Task(task_id=tid, operation=tid.rstrip("0123456789"), body=sleeper(seconds), dependency_ids=deps,
                resource_type=pool, estimated_cost=seconds if cost is None else cost, **kw)


def run(tasks, *, policy="e1", workers=4, capacities=None, budget=None, timeout=20, **kw):
    scheduler = Scheduler(policy=policy, workers=workers, capacities=capacities or {"cpu": 64}, budget=budget, **kw)
    scheduler.submit(tasks)
    assert scheduler.wait(timeout=timeout), "scheduler did not finish (deadlock?)"
    records = {r["task_id"]: r for r in scheduler.records()}
    summary = scheduler.summary()
    scheduler.shutdown()
    return records, summary


def overlap(a, b):
    return a["start_time"] < b["finish_time"] and b["start_time"] < a["finish_time"]


def test_two_independent_operations_really_overlap():
    records, summary = run([t("left", 0.3), t("right", 0.3)], policy="e1", workers=2)
    left, right = records["left"], records["right"]
    assert overlap(left, right), (left, right)
    assert summary["peak_concurrency"] == 2
    # Both ran for ~0.3 s but the whole schedule took clearly less than their sum.
    assert summary["makespan"] < 0.55 < summary["busy_seconds"]
    assert left["worker_id"] != right["worker_id"]
    assert left["start_wall"] and left["finish_wall"]


def test_e0_runs_one_task_at_a_time_in_ready_order():
    tasks = [t(f"a{i}", 0.03) for i in range(5)]
    records, summary = run(tasks, policy="e0", workers=8)
    ordered = sorted(records.values(), key=lambda r: r["start_time"])
    assert [r["task_id"] for r in ordered] == [f"a{i}" for i in range(5)]
    assert summary["peak_concurrency"] == 1 and summary["workers"] == 1
    for first, second in zip(ordered, ordered[1:]):
        assert second["start_time"] >= first["finish_time"]


def test_e1_is_fifo_by_readiness_when_slots_are_scarce():
    records, _ = run([t(f"a{i}", 0.03) for i in range(6)], policy="e1", workers=1)
    assert [r["task_id"] for r in sorted(records.values(), key=lambda r: r["start_time"])] == [f"a{i}" for i in range(6)]


def test_e2_starts_the_critical_path_first():
    def build():
        tasks = [t(f"s{i}", 0.05) for i in range(4)]
        return tasks + [t("c0", 0.05), t("c1", 0.05, ("c0",)), t("c2", 0.05, ("c1",))]
    e1, _ = run(build(), policy="e1", workers=1)
    e2, _ = run(build(), policy="e2", workers=1)
    first_e2 = min(e2.values(), key=lambda r: r["start_time"])["task_id"]
    first_e1 = min(e1.values(), key=lambda r: r["start_time"])["task_id"]
    assert first_e2 == "c0" and first_e1 == "s0"
    assert e2["c0"]["priority"] > e2["s0"]["priority"]


def test_e2_improves_the_mixed_workload_with_two_workers():
    e1 = run_workload("C_mixed", "e1", 2)
    e2 = run_workload("C_mixed", "e2", 2)
    assert e2["makespan"] < e1["makespan"]


def test_dependent_task_waits_for_published_result():
    tasks = [Task(task_id="grounding", operation="g", body=lambda i: (time.sleep(0.1), TaskOutput({"boxes": 3}, ("img_2",)))[1]),
             Task(task_id="crop", operation="crop", body=lambda inputs: inputs["grounding"]["boxes"] * 10, dependency_ids=("grounding",))]
    records, _ = run(tasks)
    assert records["crop"]["start_time"] >= records["grounding"]["finish_time"]
    assert records["grounding"]["result_artifact_refs"] == ["img_2"]
    assert records["crop"]["status"] == "COMPLETED"


def test_results_are_passed_only_from_completed_prerequisites():
    seen = {}
    tasks = [t("a", 0.01), Task(task_id="b", operation="b", body=lambda inputs: seen.setdefault("b", dict(inputs)), dependency_ids=("a",))]
    run(tasks)
    assert seen["b"] == {"a": []}


def test_resource_capacity_is_enforced():
    tasks = [t(f"g{i}", 0.08, pool="gpu") for i in range(4)] + [t(f"c{i}", 0.08) for i in range(4)]
    records, summary = run(tasks, workers=8, capacities={"gpu": 1, "cpu": 8})
    gpu = sorted((r for r in records.values() if r["resource_pool"] == "gpu"), key=lambda r: r["start_time"])
    for first, second in zip(gpu, gpu[1:]):
        assert not overlap(first, second)
    assert summary["resources"]["gpu"]["peak_in_use"] == 1
    assert summary["resources"]["cpu"]["peak_in_use"] > 1  # other pools still overlap


def test_unknown_resource_pool_is_rejected():
    scheduler = Scheduler(policy="e1", workers=1, capacities={"cpu": 1})
    with pytest.raises(ValueError, match="unknown resource pool"):
        scheduler.submit([t("a", pool="gpu")])
    scheduler.shutdown()


def test_each_task_body_runs_exactly_once():
    counts = {}
    lock = threading.Lock()

    def body(tid):
        def run_once(inputs):
            with lock:
                counts[tid] = counts.get(tid, 0) + 1
            time.sleep(0.005)
        return run_once

    tasks = [Task(task_id=f"x{i}", operation="x", body=body(f"x{i}"), dependency_ids=(f"x{i - 3}",) if i >= 3 else ())
             for i in range(40)]
    _, summary = run(tasks, workers=6)
    assert counts == {f"x{i}": 1 for i in range(40)}
    assert summary["physical_invocations"] == summary["logical_requests"] == 40


def test_failure_is_contained_and_dependents_are_skipped():
    def boom(inputs):
        raise RuntimeError("backend exploded")

    tasks = [Task(task_id="grounding", operation="g", body=boom), t("crop", 0.01, ("grounding",)),
             t("crop_ocr", 0.01, ("crop",)), t("ocr", 0.05), t("depth", 0.05)]
    records, summary = run(tasks, budget=BudgetAdapter.with_limit(10))
    assert records["grounding"]["status"] == "FAILED" and "backend exploded" in records["grounding"]["failure_reason"]
    assert records["crop"]["status"] == records["crop_ocr"]["status"] == "SKIPPED"
    assert records["crop"]["failure_reason"] == "dependency grounding failed"
    assert records["ocr"]["status"] == records["depth"]["status"] == "COMPLETED"
    assert "start_time" not in records["crop"]  # never ran
    # The failed call was dispatched, so it is charged (non-refundable); skipped tasks are not.
    assert summary["budget_used"] == 3


def test_task_submitted_after_its_dependency_failed_is_skipped_immediately():
    scheduler = Scheduler(policy="e1", workers=2, capacities={"cpu": 2})
    scheduler.submit([Task(task_id="g", operation="g", body=lambda i: 1 / 0)])
    scheduler.wait()
    scheduler.submit([t("crop", 0.01, ("g",))])
    assert scheduler.wait(timeout=5)
    assert scheduler.task("crop").status is TaskStatus.SKIPPED
    scheduler.shutdown()


def test_worker_timeout_fails_the_task_and_discards_its_late_result():
    tasks = [t("slow", 0.6, metadata={"timeout_seconds": 0.1}), t("after", 0.01, ("slow",)), t("other", 0.05)]
    scheduler = Scheduler(policy="e1", workers=2, capacities={"cpu": 4})
    began = time.monotonic()
    scheduler.submit(tasks)
    assert scheduler.wait(timeout=5)
    assert time.monotonic() - began < 0.5  # waiters are released at the deadline, not at the late return
    slow = scheduler.task("slow")
    assert slow.status is TaskStatus.FAILED and slow.failure_reason == "timeout"
    assert scheduler.task("after").status is TaskStatus.SKIPPED
    assert scheduler.task("other").status is TaskStatus.COMPLETED
    scheduler.shutdown()  # joins the abandoned worker
    assert slow.result is None and slow.timing.get("returned_time") is not None


def test_graceful_shutdown_cancels_pending_work_and_releases_reservations():
    ledger = BudgetAdapter.with_limit(10)
    scheduler = Scheduler(policy="e1", workers=1, capacities={"cpu": 1}, budget=ledger)
    scheduler.submit([t("running", 0.3), t("queued1", 0.1), t("queued2", 0.1), t("child", 0.1, ("queued1",))])
    time.sleep(0.1)
    scheduler.shutdown(cancel_pending=True, wait=True)
    states = {tid: scheduler.task(tid).status for tid in ("running", "queued1", "queued2", "child")}
    assert states["running"] is TaskStatus.COMPLETED  # in-flight work finishes
    assert states["queued1"] is states["queued2"] is TaskStatus.CANCELLED
    assert states["child"] is TaskStatus.SKIPPED  # its prerequisite was withdrawn
    assert scheduler.task("child").failure_reason == "dependency queued1 cancelled"
    snapshot = ledger.snapshot()
    assert snapshot["ledger"]["global"]["tool_calls"]["used"] == 1  # only the task that ran
    assert all(v == 0 for v in snapshot["scheduler"]["pending"].values())
    with pytest.raises(RuntimeError):
        scheduler.submit([t("late")])


def test_cancel_before_dispatch_releases_budget_and_skips_dependents():
    ledger = BudgetAdapter.with_limit(5)
    scheduler = Scheduler(policy="e1", workers=1, capacities={"cpu": 1}, budget=ledger)
    scheduler.submit([t("busy", 0.2), t("victim", 0.05), t("child", 0.05, ("victim",))])
    time.sleep(0.05)
    assert set(scheduler.cancel(["victim"])) == {"victim", "child"}
    assert scheduler.wait(timeout=5)
    assert scheduler.task("child").status is TaskStatus.SKIPPED
    scheduler.shutdown()
    assert ledger.snapshot()["ledger"]["global"]["tool_calls"]["used"] == 1


@pytest.mark.parametrize("policy", ["e0", "e1", "e2"])
def test_random_dags_with_failures_always_terminate(policy):
    rng = random.Random(654)
    for trial in range(15):
        n = rng.randint(5, 25)
        tasks = []
        for i in range(n):
            deps = tuple(f"n{j}" for j in rng.sample(range(i), k=min(i, rng.randint(0, 3))))
            fail = rng.random() < 0.15

            def body(inputs, fail=fail):
                time.sleep(rng.random() * 0.004)
                if fail:
                    raise ValueError("injected")
                return 1
            tasks.append(Task(task_id=f"n{i}", operation="op", body=body, dependency_ids=deps,
                              resource_type=rng.choice(["cpu", "gpu"])))
        ledger = BudgetAdapter.with_limit(rng.randint(n // 2, n))
        records, summary = run(tasks, policy=policy, workers=rng.randint(1, 5), capacities={"cpu": 3, "gpu": 1},
                               budget=ledger, timeout=30)
        assert all(r["status"] in {"COMPLETED", "FAILED", "SKIPPED"} for r in records.values())
        for r in records.values():  # nothing ran before its prerequisites completed
            if r.get("start_time") is not None:
                for dep in r["dependency_ids"]:
                    assert records[dep]["status"] == "COMPLETED"
                    assert r["start_time"] >= records[dep]["finish_time"]
        used = ledger.snapshot()["ledger"]["global"]["tool_calls"]
        assert 0 <= used["used"] <= used["limit"]
        assert used["used"] == sum(1 for r in records.values() if r.get("start_time") is not None)


def test_concurrent_submissions_from_several_agents_share_one_engine():
    scheduler = Scheduler(policy="e1", workers=4, capacities={"cpu": 4, "gpu": 1})
    errors = []

    def agent(name):
        try:
            for turn in range(3):
                ids = scheduler.submit([t(f"{name}.t{turn}.{k}", 0.02, pool="gpu" if k == 0 else "cpu") for k in range(2)])
                scheduler.wait(ids)
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=agent, args=(f"worker_0{i}",)) for i in range(1, 5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert not errors
    summary = scheduler.summary()
    scheduler.shutdown()
    assert summary["status"] == {"COMPLETED": 24}
    assert summary["resources"]["gpu"]["peak_in_use"] == 1


def test_telemetry_records_have_gantt_fields():
    events = []
    records, _ = run([t("a", 0.01), t("b", 0.01, ("a",))], run_id="run_x", event_sink=lambda kind, rec: events.append((kind, rec)))
    for field in ("run_id", "task_id", "agent_id", "operation", "dependency_ids", "resource_pool", "worker_id",
                  "enqueue_time", "start_time", "finish_time", "status", "budget_used", "start_wall", "finish_wall"):
        assert field in records["b"], field
    assert records["b"]["run_id"] == "run_x"
    assert [k for k, _ in events].count("SCHEDULER_TASK_STARTED") == 2
    assert [k for k, _ in events].count("SCHEDULER_TASK_FINISHED") == 2


def test_unknown_policy_is_rejected():
    with pytest.raises(ValueError):
        Scheduler(policy="e9")
