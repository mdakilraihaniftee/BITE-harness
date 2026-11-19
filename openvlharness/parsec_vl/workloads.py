"""Controlled, synthetic benchmark workloads for the scheduler (Phase 1: E0-E2).

SYNTHETIC: task bodies sleep for a declared duration. Sleeping releases the
GIL exactly like waiting on an HTTP tool or model service, so these workloads
measure the scheduler's ability to overlap *waiting* work and to respect
dependencies, worker slots, resource capacities, and the budget. They say
nothing about GPU throughput; real backend concurrency is measured separately
(``probe_services`` in ``scripts/parsec.py``). Makespans in results are real
wall-clock measurements of the executor running these declared waits.

The ``visual_pipeline`` workload replays durations measured on this machine's
real tool services (see docs/REPORT.md); it is still a synthetic
replay, not a real tool execution.

``cpu_bound`` is a negative control: pure-Python arithmetic holds the GIL, so
thread workers cannot speed it up. CPU-parallel computation is Phase 2.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .dag import Task
from .resources import BudgetAdapter
from .scheduler import Scheduler


def _sleep(seconds: float) -> Callable[[dict[str, Any]], Any]:
    def body(inputs: dict[str, Any]) -> dict[str, Any]:
        time.sleep(seconds)
        return {"slept": seconds, "inputs": sorted(inputs)}
    return body


def _spin(iterations: int) -> Callable[[dict[str, Any]], Any]:
    def body(inputs: dict[str, Any]) -> int:
        total = 0
        for i in range(iterations):
            total += i * i % 7
        return total
    return body


def _t(task_id: str, op: str, seconds: float, deps: tuple[str, ...] = (), pool: str = "io", declared: bool = True) -> Task:
    return Task(task_id=task_id, operation=op, body=_sleep(seconds), dependency_ids=deps, resource_type=pool,
                estimated_cost=seconds if declared else None, agent_id="benchmark")


def independent(n: int = 8, seconds: float = 0.2) -> tuple[list[Task], dict[str, int]]:
    """A: n independent tool-like waits."""
    return [_t(f"a{i:02d}", "tool", seconds) for i in range(n)], {"io": 64}


def chain(n: int = 8, seconds: float = 0.1) -> tuple[list[Task], dict[str, int]]:
    """B: a serial chain; no task-level parallelism exists."""
    return [_t(f"b{i:02d}", "tool", seconds, (f"b{i - 1:02d}",) if i else ()) for i in range(n)], {"io": 64}


def mixed(short: int = 6, short_seconds: float = 0.2, chain_len: int = 4, chain_seconds: float = 0.2) -> tuple[list[Task], dict[str, int]]:
    """C: short independent tasks submitted first, then a longer dependent chain.

    With few workers, FIFO starts the short tasks first and delays the chain,
    which is the critical path; critical-path priority starts the chain at once.
    """
    tasks = [_t(f"s{i:02d}", "short", short_seconds) for i in range(short)]
    tasks += [_t(f"c{i:02d}", "chain", chain_seconds, (f"c{i - 1:02d}",) if i else ()) for i in range(chain_len)]
    return tasks, {"io": 64}


def contention(gpu_tasks: int = 6, gpu_seconds: float = 0.15, cpu_tasks: int = 4, cpu_seconds: float = 0.15) -> tuple[list[Task], dict[str, int]]:
    """D: several tasks need one capacity-1 GPU service; a few independent CPU tasks."""
    tasks = [_t(f"g{i:02d}", "gpu_tool", gpu_seconds, pool="gpu") for i in range(gpu_tasks)]
    tasks += [_t(f"p{i:02d}", "cpu_tool", cpu_seconds, pool="cpu") for i in range(cpu_tasks)]
    return tasks, {"gpu": 1, "cpu": 8}


def misestimated(short: int = 6, short_seconds: float = 0.2, chain_len: int = 4, chain_seconds: float = 0.2) -> tuple[list[Task], dict[str, int]]:
    """M: like C, but the chain is submitted first and the declared estimates are wrong.

    The short tasks claim 1.0 s and the chain tasks 0.05 s. FIFO happens to
    start the chain first; critical-path priority trusts the bad estimates and
    delays it. Shows that E2 is only as good as its duration estimates.
    """
    tasks = [Task(task_id=f"c{i:02d}", operation="chain", body=_sleep(chain_seconds),
                  dependency_ids=(f"c{i - 1:02d}",) if i else (), resource_type="io", estimated_cost=0.05,
                  agent_id="benchmark") for i in range(chain_len)]
    tasks += [Task(task_id=f"s{i:02d}", operation="short", body=_sleep(short_seconds), resource_type="io",
                   estimated_cost=1.0, agent_id="benchmark") for i in range(short)]
    return tasks, {"io": 64}


# Median single-request latencies measured on this machine's real services with
# ``scripts/parsec.py probe`` (outputs/parsec_vl/probe/probe.json, concurrency 1):
# SAM3 grounding 0.93 s, OCR 0.23 s, depth 0.34 s, Zoom 0.064 s. OCR on a crop is
# assumed to cost the same as OCR on the original (not measured separately).
VISUAL_SECONDS = {"grounding": 0.93, "ocr": 0.23, "depth": 0.34, "crop": 0.064, "crop_ocr": 0.23}


def visual_pipeline(scale: float = 1.0, durations: dict[str, float] | None = None) -> tuple[list[Task], dict[str, int]]:
    """The spec's example DAG: grounding, OCR, depth on the original; crop after grounding; OCR on the crop."""
    d = {k: v * scale for k, v in (durations or VISUAL_SECONDS).items()}
    tasks = [
        _t("grounding", "Visual_Grounding_Tool", d["grounding"], pool="service:sam3"),
        _t("ocr", "OCR_Tool", d["ocr"], pool="service:ocr"),
        _t("depth", "Depth_Estimation_Tool", d["depth"], pool="service:depth"),
        _t("crop", "Zoom_In_Tool", d["crop"], ("grounding",), pool="cpu"),
        _t("crop_ocr", "OCR_Tool", d["crop_ocr"], ("crop",), pool="service:ocr"),
    ]
    return tasks, {"service:sam3": 1, "service:ocr": 1, "service:depth": 1, "cpu": 4}


def cpu_bound(n: int = 8, iterations: int = 300_000) -> tuple[list[Task], dict[str, int]]:
    """Negative control: GIL-bound Python work does not speed up on thread workers."""
    return [Task(task_id=f"x{i:02d}", operation="python_loop", body=_spin(iterations), resource_type="cpu",
                 agent_id="benchmark") for i in range(n)], {"cpu": 64}


def scaling(n: int = 32, seconds: float = 0.1) -> tuple[list[Task], dict[str, int]]:
    """Worker scaling: many equal independent waits (remote-I/O-like)."""
    return [_t(f"w{i:02d}", "tool", seconds) for i in range(n)], {"io": 256}


WORKLOADS: dict[str, Callable[[], tuple[list[Task], dict[str, int]]]] = {
    "A_independent": independent,
    "B_chain": chain,
    "C_mixed": mixed,
    "D_contention": contention,
    "M_misestimated": misestimated,
    "V_visual_pipeline": visual_pipeline,
    "X_cpu_bound": cpu_bound,
    "S_scaling": scaling,
}


def run_workload(name: str, policy: str, workers: int, *, budget: int | None = None) -> dict[str, Any]:
    """Build a fresh copy of the workload, run it to completion, return the measured summary."""
    tasks, capacities = WORKLOADS[name]()
    ledger = BudgetAdapter.with_limit(budget if budget is not None else len(tasks))
    with Scheduler(policy=policy, workers=workers, capacities=capacities, budget=ledger, run_id=f"bench_{name}") as scheduler:
        scheduler.submit(tasks)
        if not scheduler.wait(timeout=300):
            raise TimeoutError(f"workload {name} did not finish")
        summary = scheduler.summary()
        records = scheduler.records()
    summary["workload"] = name
    summary["records"] = records
    summary["results"] = {r["task_id"]: r["status"] for r in records}
    return summary
