"""Deterministic lifecycle, scheduling, failure isolation, and persistence."""

from __future__ import annotations

import copy
import json
import os
import platform
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from .actors import AgentFactory, CoordinatorAgent, WorkerAgent
from .budget import BudgetManager
from .communication import CommunicationBus
from .config import worker_config
from .events import EventLog
from .schemas import RunStatus, WorkerResult, WorkerStatus, utc_now

TRANSITIONS = {
    RunStatus.CREATED: {RunStatus.INITIALIZING},
    RunStatus.INITIALIZING: {RunStatus.PLANNING, RunStatus.FAILED},
    RunStatus.PLANNING: {
        RunStatus.ASSIGNING,
        RunStatus.FAILED,
        RunStatus.BUDGET_EXHAUSTED,
    },
    RunStatus.ASSIGNING: {RunStatus.RUNNING, RunStatus.FAILED},
    RunStatus.RUNNING: {
        RunStatus.SYNTHESIZING,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.BUDGET_EXHAUSTED,
    },
    RunStatus.SYNTHESIZING: {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.BUDGET_EXHAUSTED,
    },
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
    RunStatus.BUDGET_EXHAUSTED: set(),
}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "<redacted>"
                if any(
                    word in key.lower()
                    for word in ("key", "token", "secret", "password")
                )
                else _redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class MultiAgentOrchestrator:
    def __init__(
        self,
        config: dict[str, Any],
        *,
        factory: AgentFactory | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
        output_directory: str | Path | None = None,
    ) -> None:
        self.config = copy.deepcopy(config)
        self.run_id = run_id or f"run_{uuid4().hex[:12]}"
        self.task_id = task_id or "task_001"
        root = Path(output_directory or config["output"]["directory"])
        self.run_dir = root / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.events = EventLog(self.run_id, self.task_id, self.run_dir / "events.jsonl")
        self.status = RunStatus.CREATED
        self.factory = factory or AgentFactory()
        self._cancelled = threading.Event()
        worker_ids = [
            f"worker_{index:02d}" for index in range(1, config["num_agents"] + 1)
        ]
        actor_ids = ["coordinator", *worker_ids]
        communication = config["communication"]
        actor_limits: dict[str, dict[str, int]] = {
            "coordinator": {
                "tool_calls": 0
                if not config["coordinator"]["tool_access"]
                else config["budget"]["global_tool_calls"],
                "model_requests": config["coordinator"]["model_requests"],
                "messages": communication["max_messages_per_actor"],
            }
        }
        for worker_id in worker_ids:
            settings = worker_config(config, worker_id)
            actor_limits[worker_id] = {
                "tool_calls": settings["tool_calls"],
                "model_requests": settings["model_requests"],
                "messages": communication["max_messages_per_actor"],
            }
        self.budget = BudgetManager(
            {
                "tool_calls": config["budget"]["global_tool_calls"],
                "model_requests": config["budget"]["global_model_requests"],
                "messages": config["budget"]["global_messages"],
            },
            actor_limits,
            self.events.emit,
        )
        self.bus = CommunicationBus(
            actors=set(actor_ids),
            coordinator_id="coordinator",
            enabled=communication["enabled"],
            peer_to_peer=communication["peer_to_peer"],
            max_inbox=communication["max_inbox_per_actor"],
            budget=self.budget,
            events=self.events,
            message_path=self.run_dir / "messages.jsonl",
        )
        self.worker_ids = worker_ids
        self.workers: dict[str, WorkerAgent] = {}
        self.coordinator: CoordinatorAgent | None = None

    def _transition(self, target: RunStatus) -> None:
        if target not in TRANSITIONS[self.status]:
            raise RuntimeError(
                f"Invalid run-state transition: {self.status.value} -> {target.value}"
            )
        previous = self.status
        self.status = target
        self.events.emit(
            "orchestrator",
            "RUN_STATE_CHANGED",
            {"from": previous.value, "to": target.value},
        )

    def cancel(self) -> None:
        self._cancelled.set()

    def _initialize(self) -> None:
        coordinator_settings = self.config["coordinator"]
        coordinator_agent = self.factory.create(
            "coordinator",
            coordinator_settings["agent_config"],
            tool_access=coordinator_settings["tool_access"],
            budget=self.budget,
        )
        self.coordinator = CoordinatorAgent(
            coordinator_agent, self.bus, self.events, self.run_id, self.task_id
        )
        for worker_id in self.worker_ids:
            settings = worker_config(self.config, worker_id)
            agent = self.factory.create(
                worker_id,
                settings["agent_config"],
                tool_access=True,
                budget=self.budget,
            )
            peers = tuple(item for item in self.worker_ids if item != worker_id)
            self.workers[worker_id] = WorkerAgent(
                worker_id,
                settings["role"],
                agent,
                self.bus,
                self.events,
                self.run_id,
                self.task_id,
                peers,
            )
            (self.run_dir / "workers" / worker_id).mkdir(parents=True)
        (self.run_dir / "coordinator").mkdir(parents=True)

    def _execute_workers(
        self, assignments: list[Any], original_input: list[dict[str, Any]]
    ) -> list[WorkerResult]:
        timeout = self.config["execution"]["task_timeout_seconds"]
        if self.config["execution"]["mode"] == "cooperative":
            results = []
            for assignment in assignments:
                if self._cancelled.is_set():
                    break
                results.append(
                    self.workers[assignment.worker_id].run(assignment, original_input)
                )
            return results
        concurrency = min(
            self.config["execution"]["max_concurrent_workers"], len(assignments)
        )
        results: dict[str, WorkerResult] = {}
        with ThreadPoolExecutor(
            max_workers=concurrency, thread_name_prefix="multi-agent-worker"
        ) as executor:
            futures = {
                executor.submit(self.workers[a.worker_id].run, a, original_input): a
                for a in assignments
            }
            try:
                for future in as_completed(futures, timeout=timeout):
                    assignment = futures[future]
                    try:
                        results[assignment.worker_id] = future.result()
                    except Exception as exc:  # noqa: BLE001 - isolate arbitrary actor failures
                        results[assignment.worker_id] = WorkerResult(
                            agent_id=assignment.worker_id,
                            task_id=self.task_id,
                            assigned_scope=assignment.scope,
                            status=WorkerStatus.FAILED.value,
                            failure_reason=f"{type(exc).__name__}: {exc}",
                        )
            except TimeoutError:
                for future, assignment in futures.items():
                    if assignment.worker_id not in results:
                        future.cancel()
                        results[assignment.worker_id] = WorkerResult(
                            agent_id=assignment.worker_id,
                            task_id=self.task_id,
                            assigned_scope=assignment.scope,
                            status=WorkerStatus.FAILED.value,
                            failure_reason=f"Worker exceeded {timeout} seconds",
                        )
        return [results[worker_id] for worker_id in self.worker_ids]

    def _review_workers(
        self, results: list[WorkerResult], original_input: list[dict[str, Any]]
    ) -> list[WorkerResult]:
        rounds = min(
            self.config["execution"]["peer_review_rounds"],
            max(0, self.config["coordinator"]["max_rounds"] - 1),
        )
        if not self.bus.peer_to_peer or not self.bus.enabled or rounds == 0:
            return results
        by_id = {result.agent_id: result for result in results}
        for _ in range(rounds):
            concurrency = min(
                self.config["execution"]["max_concurrent_workers"], len(results)
            )
            if self.config["execution"]["mode"] == "cooperative":
                for worker_id in self.worker_ids:
                    by_id[worker_id] = self.workers[worker_id].review(
                        by_id[worker_id], original_input
                    )
            else:
                with ThreadPoolExecutor(
                    max_workers=concurrency, thread_name_prefix="multi-agent-review"
                ) as executor:
                    futures = {
                        worker_id: executor.submit(
                            self.workers[worker_id].review,
                            by_id[worker_id],
                            original_input,
                        )
                        for worker_id in self.worker_ids
                    }
                    for worker_id, future in futures.items():
                        try:
                            by_id[worker_id] = future.result(
                                timeout=self.config["execution"]["task_timeout_seconds"]
                            )
                        except Exception as exc:  # noqa: BLE001 - review failure is non-fatal
                            by_id[
                                worker_id
                            ].uncertainty_or_limitations = (
                                f"Review failed: {type(exc).__name__}: {exc}"
                            )
        return [by_id[worker_id] for worker_id in self.worker_ids]

    def _manifest(self, original_task: str) -> dict[str, Any]:
        try:
            commit = (
                subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    check=False,
                    cwd=Path(__file__).resolve().parents[2],
                    timeout=5,
                ).stdout.strip()
                or None
            )
        except (OSError, subprocess.SubprocessError):
            commit = None
        actors = {}
        candidates = (
            {"coordinator": self.coordinator.agent} if self.coordinator else {}
        ) | {worker_id: worker.agent for worker_id, worker in self.workers.items()}
        for actor_id, agent in candidates.items():
            adapter = getattr(agent, "adapter", None)
            actors[actor_id] = {
                "model_id": getattr(agent, "model", None),
                "endpoint": getattr(adapter, "endpoint", None),
                "generation_options": _redact(getattr(adapter, "options", {})),
                "agent_object_id": id(agent),
                "adapter_object_id": id(adapter) if adapter is not None else None,
            }
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "created_at": utc_now(),
            "original_task": original_task,
            "worker_count": len(self.worker_ids),
            "coordinator_count": 1,
            "execution_mode": self.config["execution"]["mode"],
            "git_commit": commit,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pid": os.getpid(),
            "actors": actors,
        }

    def _persist(
        self,
        original_task: str,
        original_input: list[dict[str, Any]],
        results: list[WorkerResult],
        final: dict[str, Any],
    ) -> None:
        safe_input = []
        for item in original_input:
            value = dict(item)
            if isinstance(value.get("value"), str) and value["value"].startswith(
                "data:image/"
            ):
                value["value"] = f"<embedded image: {len(value['value'])} characters>"
            safe_input.append(value)
        _write_json(self.run_dir / "run_manifest.json", self._manifest(original_task))
        _write_json(
            self.run_dir / "inputs" / "original_task.json",
            {"task": original_task, "input": safe_input},
        )
        (self.run_dir / "config.resolved.yaml").write_text(
            yaml.safe_dump(_redact({"multi_agent": self.config}), sort_keys=False),
            encoding="utf-8",
        )
        for result in results:
            worker_dir = self.run_dir / "workers" / result.agent_id
            _write_json(
                worker_dir / "result.json",
                {
                    key: value
                    for key, value in result.to_dict().items()
                    if key != "trajectory"
                },
            )
            _write_json(worker_dir / "trajectory.json", result.trajectory)
            worker = self.workers.get(result.agent_id)
            if worker is not None:
                _write_json(worker_dir / "private_memory.json", worker.private_memory)
        if self.coordinator is not None:
            _write_json(
                self.run_dir / "coordinator" / "trajectory.json",
                self.coordinator.trajectories,
            )
            _write_json(
                self.run_dir / "coordinator" / "memory.json",
                self.coordinator.private_memory,
            )
        final["budgets"] = self.budget.snapshot()
        final["cost_summary"] = self.budget.snapshot()["measured"]
        final["run_id"] = self.run_id
        final["task_id"] = self.task_id
        final["run_status"] = self.status.value
        _write_json(self.run_dir / "budgets.json", self.budget.snapshot())
        _write_json(self.run_dir / "final_result.json", final)

    def run(
        self, original_task: str, original_input: list[dict[str, Any]]
    ) -> dict[str, Any]:
        results: list[WorkerResult] = []
        final: dict[str, Any] = {"final_answer": None, "final_status": "FAILED"}
        failure: str | None = None
        try:
            self._transition(RunStatus.INITIALIZING)
            self._initialize()
            self._transition(RunStatus.PLANNING)
            assert self.coordinator is not None
            specs = [
                (worker_id, self.workers[worker_id].role)
                for worker_id in self.worker_ids
            ]
            assignments = self.coordinator.plan(
                original_task,
                specs,
                self.config["execution"]["task_timeout_seconds"],
                {
                    worker_id: worker_config(self.config, worker_id)["tool_calls"]
                    for worker_id in self.worker_ids
                },
            )
            self._transition(RunStatus.ASSIGNING)
            self.coordinator.send_assignments(assignments)
            self._transition(RunStatus.RUNNING)
            results = self._execute_workers(assignments, original_input)
            if self._cancelled.is_set():
                self._transition(RunStatus.CANCELLED)
                final = {"final_answer": None, "final_status": "CANCELLED"}
            else:
                if (
                    self.bus.enabled
                    and self.bus.peer_to_peer
                    and len(self.worker_ids) > 1
                    and self.config["execution"]["peer_review_rounds"] > 0
                ):
                    self.coordinator.request_verification(self.worker_ids)
                results = self._review_workers(results, original_input)
                self._transition(RunStatus.SYNTHESIZING)
                final = self.coordinator.synthesize(original_task, results)
                self._transition(RunStatus.COMPLETED)
        except Exception as exc:  # noqa: BLE001 - persist every orchestration failure
            failure = f"{type(exc).__name__}: {exc}"
            if self.status not in {
                RunStatus.FAILED,
                RunStatus.CANCELLED,
                RunStatus.BUDGET_EXHAUSTED,
            }:
                target = (
                    RunStatus.BUDGET_EXHAUSTED
                    if "budget exhausted" in str(exc).lower()
                    else RunStatus.FAILED
                )
                if target in TRANSITIONS[self.status]:
                    self._transition(target)
                else:
                    self.status = target
            self.events.emit("orchestrator", "RUN_FAILED", {"error": failure})
            final = {
                "final_answer": None,
                "final_status": self.status.value,
                "failure_reason": failure,
            }
        finally:
            final["worker_results"] = [
                {
                    key: value
                    for key, value in result.to_dict().items()
                    if key != "trajectory"
                }
                for result in results
            ]
            self._persist(original_task, original_input, results, final)
        return {
            "prediction": final.get("final_answer"),
            "extra_records": {
                "multi_agent": final,
                "run_directory": str(self.run_dir.resolve()),
                "status": self.status.value,
                "error": failure,
            },
        }
