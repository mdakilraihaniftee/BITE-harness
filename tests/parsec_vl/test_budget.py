"""Budget safety under concurrency: one ledger (BudgetManager), atomic reservations."""

import threading
import time

import pytest

from openvlharness.multi_agent.budget import BudgetManager
from openvlharness.parsec_vl import BudgetAdapter, Scheduler, Task


def test_concurrent_requests_for_the_final_unit_grant_exactly_one():
    for _ in range(20):
        manager = BudgetManager({"tool_calls": 5}, {})
        for _ in range(4):
            assert manager.reserve("w", "tool_calls").granted
        barrier = threading.Barrier(16)
        granted = []

        def contend():
            barrier.wait()
            granted.append(manager.reserve("w", "tool_calls").granted)

        threads = [threading.Thread(target=contend) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert granted.count(True) == 1
        snapshot = manager.snapshot()
        assert snapshot["global"]["tool_calls"]["remaining"] == 0
        assert snapshot["counters"]["rejected"]["tool_calls"] == 15


def test_actor_and_global_limits_both_hold_under_stress():
    manager = BudgetManager({"tool_calls": 30}, {f"w{i}": {"tool_calls": 10} for i in range(4)})
    results = {f"w{i}": 0 for i in range(4)}
    lock = threading.Lock()

    def actor(name):
        for _ in range(25):
            if manager.reserve(name, "tool_calls").granted:
                with lock:
                    results[name] += 1

    threads = [threading.Thread(target=actor, args=(f"w{i}",)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(results.values()) == 30
    assert all(count <= 10 for count in results.values())


def test_release_returns_only_what_was_reserved():
    manager = BudgetManager({"tool_calls": 2}, {"w": {"tool_calls": 2}})
    assert manager.reserve("w", "tool_calls").granted
    manager.release("w", "tool_calls")
    assert manager.remaining("w", "tool_calls") == 2
    with pytest.raises(RuntimeError, match="exceeds"):
        manager.release("w", "tool_calls")
    with pytest.raises(ValueError):
        manager.release("w", "tool_calls", 0)
    assert manager.snapshot()["counters"]["released"] == {"tool_calls": 1}


def test_rejected_actor_release_does_not_change_global_accounting():
    manager = BudgetManager({"tool_calls": 2}, {"a": {"tool_calls": 1}, "b": {"tool_calls": 1}})
    assert manager.reserve("a", "tool_calls").granted
    before = manager.snapshot()
    with pytest.raises(RuntimeError, match="exceeds"):
        manager.release("b", "tool_calls")
    assert manager.snapshot() == before
    assert manager.remaining("a", "tool_calls") == 0


def sleeper(seconds):
    return lambda inputs: time.sleep(seconds)


def test_scheduler_never_overspends_and_reports_denials():
    ledger = BudgetAdapter.with_limit(3)
    scheduler = Scheduler(policy="e1", workers=8, capacities={"cpu": 8}, budget=ledger)
    scheduler.submit([Task(task_id=f"t{i}", operation="op", body=sleeper(0.05)) for i in range(10)])
    assert scheduler.wait(timeout=5)
    records = scheduler.records()
    scheduler.shutdown()
    ran = [r for r in records if r.get("start_time") is not None]
    denied = [r for r in records if (r["failure_reason"] or "").startswith("budget_denied")]
    assert len(ran) == 3 and len(denied) == 7
    snapshot = ledger.snapshot()
    assert snapshot["ledger"]["global"]["tool_calls"] == {"limit": 3, "used": 3, "remaining": 0}
    assert snapshot["scheduler"]["denied_tasks"] == 7 and snapshot["scheduler"]["in_flight"] == 0


def test_spent_plus_reserved_never_exceeds_total_while_running():
    ledger = BudgetAdapter.with_limit(6)
    scheduler = Scheduler(policy="e1", workers=3, capacities={"cpu": 3}, budget=ledger)
    scheduler.submit([Task(task_id=f"t{i}", operation="op", body=sleeper(0.03)) for i in range(12)])
    peak = 0
    while not scheduler.wait(timeout=0.005):
        snapshot = ledger.snapshot()
        spent_and_reserved = snapshot["ledger"]["global"]["tool_calls"]["used"]
        assert spent_and_reserved <= 6
        assert sum(snapshot["scheduler"]["pending"].values()) + sum(snapshot["scheduler"]["charged"].values()) == spent_and_reserved
        peak = max(peak, snapshot["scheduler"]["in_flight"])
    scheduler.shutdown()
    assert peak <= 3


def test_failed_operation_is_charged_not_free():
    ledger = BudgetAdapter.with_limit(5)
    scheduler = Scheduler(policy="e1", workers=1, capacities={"cpu": 1}, budget=ledger)
    scheduler.submit([Task(task_id="bad", operation="op", body=lambda i: 1 / 0)])
    scheduler.wait()
    scheduler.shutdown()
    assert ledger.snapshot()["ledger"]["global"]["tool_calls"]["used"] == 1
    assert scheduler.task("bad").record()["budget_used"] == 1


def test_tasks_without_a_budget_resource_are_not_charged():
    ledger = BudgetAdapter.with_limit(1)
    scheduler = Scheduler(policy="e1", workers=2, capacities={"cpu": 2}, budget=ledger)
    scheduler.submit([Task(task_id=f"free{i}", operation="bookkeeping", body=sleeper(0.01), budget_resource=None) for i in range(3)])
    scheduler.wait()
    scheduler.shutdown()
    assert ledger.snapshot()["ledger"]["global"]["tool_calls"]["used"] == 0
