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

from ..studio.artifacts import ArtifactStore
from ..studio.topology import display_endpoint
from .actors import AgentFactory, CoordinatorAgent, WorkerAgent
from .budget import BudgetManager
from .communication import CommunicationBus
from .config import effective_run_config, worker_config
from .estimate import EstimateTracker
from .events import EventLog
from .schemas import Assignment, RunStatus, WorkerResult, WorkerStatus, utc_now

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


def _actor_topology(
    agent: Any, *, role: str, tool_access: bool, optional_memory: bool | None = None
) -> dict[str, Any]:
    """Describe one actor's logical components without secrets or inference.

    Only attributes that already exist on the constructed agent are read; no
    model or tool request is made. Endpoints keep scheme/host/port/path only.
    """
    adapter = getattr(agent, "adapter", None)
    declared = getattr(agent, "studio_topology", None)
    declared = declared if isinstance(declared, dict) else {}
    tools = []
    capabilities = getattr(agent, "capabilities", None)
    if isinstance(capabilities, dict):
        for name, capability in sorted(capabilities.items()):
            client = getattr(capability, "client", None)
            service_config = getattr(capability, "service_config", None) or {}
            service = service_config.get("server_url") or getattr(client, "base_url", None)
            tools.append(
                {
                    "name": str(name),
                    "backend": getattr(capability, "backend", None),
                    "service": display_endpoint(service),
                }
            )
    tools.extend(
        tool
        for tool in declared.get("tools", [])
        if isinstance(tool, dict) and not any(t["name"] == tool.get("name") for t in tools)
    )
    modules: list[str] = []
    factory = getattr(agent, "memory_factory", None)
    if callable(factory):
        try:
            modules = [str(item) for item in getattr(factory(), "modules", [])]
        except Exception:  # noqa: BLE001 - topology description is best effort
            modules = []
    model_client = {
        "model_id": getattr(adapter, "model", None) or getattr(agent, "model", None),
        "protocol": getattr(adapter, "protocol", None),
        "endpoint": display_endpoint(getattr(adapter, "endpoint", None)),
        "kind": "remote" if adapter is not None else None,
    }
    model_client.update(declared.get("model_client") or {})
    return {
        "role": role,
        "tool_access": bool(tool_access),
        "harness": {
            "implementation": type(agent).__name__,
            "max_iterations": getattr(agent, "max_iterations", None),
        },
        "model_client": model_client,
        "memory": {
            # Working context (conversation + per-question registry) is always on.
            "modules": modules or declared.get("memory_modules", []),
            "scope": "private",
            "working_context": True,
            "optional_notebook": optional_memory,
        },
        "tools": tools if tool_access else [],
    }


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
        self.artifacts = ArtifactStore(self.run_dir)
        self.events = EventLog(
            self.run_id,
            self.task_id,
            self.run_dir / "events.jsonl",
            self.artifacts,
        )
        self.status = RunStatus.CREATED
        self._created_at = utc_now()
        self.factory = factory or AgentFactory()
        self._cancelled = threading.Event()
        self.effective_config = effective_run_config(self.config)
        self.estimates = EstimateTracker(
            self.events.emit, self.run_dir / "coordinator" / "estimate_history.json"
        )
        self.reassessments = 0
        self._coordinator_call_cost = 1
        self._follow_up_rounds = 0
        self.round = 0
        self._consumed_reports: set[tuple[str, int]] = set()
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
        self.scheduler: Any = None  # parsec_vl.Scheduler when execution.scheduler.policy != "off"
        self.planning_pool: Any = None  # parsec_vl.PlanEvaluator for e3/e5
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
        _write_json(
            self.run_dir / "run_state.json",
            {
                "run_id": self.run_id,
                "task_id": self.task_id,
                "status": target.value,
                "updated_at": utc_now(),
            },
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
        coordinator_agent.event_sink = self._event_sink("coordinator")
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
                memory_enabled=self.config["memory"]["optional_worker_memory"],
            )
            agent.event_sink = self._event_sink(worker_id)
            (self.run_dir / "workers" / worker_id).mkdir(parents=True)
        (self.run_dir / "coordinator").mkdir(parents=True)
        self._start_scheduler(coordinator_agent)

    def _start_scheduler(self, coordinator_agent: Any) -> None:
        """PARSEC-VL: one shared tool scheduler for every agent with tools (if enabled)."""
        settings = self.config["execution"]["scheduler"]
        if settings["policy"] == "off":
            return
        from ..parsec_vl.harness import ToolScheduling, pools_for
        from ..parsec_vl.resources import BudgetAdapter
        from ..parsec_vl.scheduler import Scheduler

        agents = {worker_id: worker.agent for worker_id, worker in self.workers.items()}
        if self.config["coordinator"]["tool_access"]:
            agents["coordinator"] = coordinator_agent
        capacities = pools_for(agents.values(), service_capacity=settings["service_capacity"],
                               capacities=settings["capacities"])

        def sink(event_type: str, record: dict[str, Any]) -> None:
            status = record["status"]
            self.events.emit(
                record.get("agent_id") or "orchestrator",
                event_type,
                record,
                summary=(f"Scheduler started {record['operation']} on worker slot {record.get('worker_id')}."
                         if event_type == "SCHEDULER_TASK_STARTED"
                         else f"Scheduler task {record['operation']} {status.lower()}."),
                status=("running" if event_type == "SCHEDULER_TASK_STARTED" else
                        "completed" if status == "COMPLETED" else "failed" if status == "FAILED" else "cancelled"),
                tool_name=record.get("operation"),
            )

        planned = settings["policy"] in ("e3", "e4", "e5")
        selective = settings["policy"] == "e5"
        self.scheduler = Scheduler(
            policy=settings.get("plan_dispatch", "e2") if planned else settings["policy"], workers=settings["workers"],
            capacities=capacities,
            budget=BudgetAdapter(self.budget), run_id=self.run_id, event_sink=sink,
            task_timeout=settings["task_timeout_seconds"],
            # E5 keeps one worker slot and one unit of every shared pool for necessary work.
            speculative_limits={p: max(1, c - 1) for p, c in capacities.items()} if selective else None,
            necessary_slot_reserve=1 if selective and settings["workers"] > 1 else 0,
        )
        for agent_id, agent in agents.items():
            agent.tool_scheduler = ToolScheduling(self.scheduler, agent_id)
        if planned:
            self._start_planning(settings["policy"], agents)
        self.events.emit(
            "orchestrator", "SCHEDULER_CONFIGURED",
            {"policy": self.scheduler.policy, "workers": self.scheduler.workers, "capacities": capacities},
            summary=f"Tool calls run through the PARSEC-VL scheduler ({self.scheduler.policy}, "
                    f"{self.scheduler.workers} worker slot(s)).",
        )

    def _start_planning(self, policy: str, agents: dict[str, Any]) -> None:
        """E3-E5: declared action plans for every tool-using agent; one shared planning process pool."""
        from ..parsec_vl.controller import PlanningConfig
        from ..parsec_vl.harness import PlanController, attach_plan_mode
        from ..parsec_vl.montecarlo import PROBE_PRIORS, OutcomeModel, PlanEvaluator

        planning = dict(self.config["execution"]["planning"])
        path = planning.pop("outcome_model", None)
        schema = planning.pop("plan_schema", "current")
        model = OutcomeModel.load(path) if path else PROBE_PRIORS
        config = PlanningConfig.for_mode(policy, **planning)
        startup, warning = 0.0, None
        if config.plan_selection or config.speculation == "S2":
            def started(seconds: float) -> None:
                self.events.emit("orchestrator", "PLANNING_POOL_STARTED",
                                 {"processes": config.planning_processes, "startup_seconds": round(seconds, 4),
                                  "pool_mode": config.planning_pool},
                                 summary=f"Started {config.planning_processes} planning processes ({seconds:.2f} s).")
            if config.planning_pool == "shared":
                self.planning_pool = PlanEvaluator.shared(config.planning_processes)
                self.planning_pool.on_start = started
            else:
                self.planning_pool = PlanEvaluator(processes=config.planning_processes, on_start=started)
            if config.planning_pool == "eager":
                try:
                    startup = self.planning_pool.start()
                except Exception as exc:  # noqa: BLE001 - planning must never stop the run
                    warning = f"planning process pool unavailable ({type(exc).__name__}: {exc}); evaluating in-process"
                    self.planning_pool.shutdown()
                    self.planning_pool = PlanEvaluator(processes=0)
        for agent_id, agent in agents.items():
            attach_plan_mode(agent, PlanController(self.scheduler, agent_id, config, evaluator=self.planning_pool,
                                                   model=model, budget=self.budget, run_id=self.run_id), schema=schema)
        self.events.emit("orchestrator", "PLANNING_CONFIGURED", {
            "mode": policy, "speculation": config.speculation, "decision_protocol": "declared_multi_action_plan",
            "planning_processes": config.planning_processes if self.planning_pool else 0,
            "pool_mode": config.planning_pool, "planning_gate": config.planning_gate,
            "pool_startup_seconds": round(startup, 4), "outcome_model": model.to_dict(), "warning": warning},
            summary=f"Workers may submit declared action plans ({policy.upper()}, speculation {config.speculation}).")

    def _event_sink(self, agent_id: str):
        def emit(event_type: str, payload: dict[str, Any], **metadata: Any):
            return self.events.emit(agent_id, event_type, payload, **metadata)

        return emit

    def _record_initial_inputs(
        self, original_task: str, original_input: list[dict[str, Any]]
    ) -> None:
        started = self.events.emit(
            "orchestrator",
            "RUN_STARTED",
            {"worker_count": len(self.worker_ids)},
            status="running",
        )
        self.events.emit(
            "orchestrator",
            "RUN_CONFIGURATION_RECORDED",
            {"effective_config": self.effective_config},
            summary=(
                f"Run configured with {self.effective_config['num_workers']} worker(s); optional memory "
                f"{'on' if self.effective_config['optional_worker_memory_enabled'] else 'off'}; peer communication "
                f"{'on' if self.effective_config['peer_communication_enabled'] else 'off'}."
            ),
            parent_event_id=started["event_id"],
        )
        task_event_id = f"evt_{uuid4().hex}"
        refs = []
        image_index = 0
        for item in original_input:
            if item.get("type") == "image" and isinstance(item.get("value"), str):
                value = item["value"]
                if not value.startswith(("http://", "https://", "data:image/")):
                    image_index += 1
                    try:
                        refs.append(
                            self.artifacts.register_file(
                                value,
                                source_event_id=task_event_id,
                                alias=f"input_image_{image_index}",
                            )
                        )
                    except (OSError, ValueError):
                        pass
        self.events.emit(
            "orchestrator",
            "TASK_RECEIVED",
            {"original_task": original_task},
            summary="Received the immutable original task and authorized visual inputs.",
            parent_event_id=started["event_id"],
            artifact_refs=refs,
            event_id=task_event_id,
        )
        _write_json(self.run_dir / "run_manifest.json", self._manifest(original_task))

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
        topology_actors = {}
        if self.coordinator is not None:
            topology_actors["coordinator"] = _actor_topology(
                self.coordinator.agent,
                role="coordinator",
                tool_access=self.config["coordinator"]["tool_access"],
            )
        for worker_id, worker in self.workers.items():
            topology_actors[worker_id] = _actor_topology(
                worker.agent,
                role=worker.role,
                tool_access=True,
                optional_memory=worker.memory_enabled,
            )
        communication = self.config["communication"]
        topology = {
            "schema_version": "studio.topology_manifest.v1",
            "worker_ids": list(self.worker_ids),
            "communication": {
                "enabled": communication["enabled"],
                "peer_to_peer": communication["peer_to_peer"],
                "peer_communication_enabled": self.effective_config[
                    "peer_communication_enabled"
                ],
                "max_inbox_per_actor": communication["max_inbox_per_actor"],
                "max_messages_per_actor": communication["max_messages_per_actor"],
            },
            "budget": {
                "tool_calls": self.config["budget"]["global_tool_calls"],
                "model_requests": self.config["budget"]["global_model_requests"],
                "messages": self.config["budget"]["global_messages"],
            },
            "actors": topology_actors,
        }
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "created_at": self._created_at,
            "original_task": original_task,
            "worker_count": len(self.worker_ids),
            "coordinator_count": 1,
            "execution_mode": self.config["execution"]["mode"],
            "effective_config": self.effective_config,
            "git_commit": commit,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pid": os.getpid(),
            "actors": actors,
            "topology": topology,
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
            if worker is not None and worker.memory_enabled:
                # Optional notebook records exist only when the policy is on.
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
        final["estimate_history"] = self.estimates.history
        final["effective_config"] = self.effective_config
        final["run_id"] = self.run_id
        final["task_id"] = self.task_id
        final["run_status"] = self.status.value
        _write_json(self.run_dir / "budgets.json", self.budget.snapshot())
        _write_json(self.run_dir / "final_result.json", final)

    # ---- investigation rounds, evidence provenance, and answer state --------
    def _round_event(
        self,
        phase: str,
        kind: str,
        workers: list[str],
        evidence: list[dict[str, Any]] | None = None,
    ) -> None:
        if phase == "STARTED":
            self.round += 1
        payload: dict[str, Any] = {"round": self.round, "kind": kind, "workers": list(workers)}
        if evidence is not None:
            payload["reports"] = len(evidence)
        label = {"initial": "initial investigation", "follow_up": "follow-up", "peer_review": "peer review"}[kind]
        self.events.emit(
            "orchestrator",
            f"INVESTIGATION_ROUND_{phase}",
            payload,
            summary=(
                f"Round {self.round} ({label}) started for {len(workers)} worker(s)."
                if phase == "STARTED"
                else f"Round {self.round} ({label}) finished with {len(evidence or [])} new report(s)."
            ),
            status="running" if phase == "STARTED" else "completed",
        )

    def _collect_evidence(self) -> list[dict[str, Any]]:
        """Reports produced since the last collection, with recorded event IDs.

        A report reaches the coordinator through the message bus when
        communication is enabled (its delivery event is linked) and otherwise
        through the orchestrator's direct result handoff.
        """
        assert self.coordinator is not None
        delivered = {}
        for record in self.coordinator.drain_inbox():
            metadata = record.get("metadata") or {}
            if record.get("message_type") == "CANDIDATE_ANSWER":
                delivered[(record["sender_id"], metadata.get("report_index"))] = record.get(
                    "delivered_event_id"
                )
        evidence = []
        for worker_id in self.worker_ids:
            report = self.workers[worker_id].last_report
            if not report:
                continue
            key = (worker_id, report["report_index"])
            if key in self._consumed_reports:
                continue
            self._consumed_reports.add(key)
            item = dict(report)
            item["delivered_event_id"] = delivered.get(key)
            item["channel"] = "message_bus" if item["delivered_event_id"] else "direct_result_handoff"
            evidence.append(item)
        return evidence

    def _latest_reports(self) -> list[dict[str, Any]]:
        return [
            dict(self.workers[worker_id].last_report)
            for worker_id in self.worker_ids
            if self.workers[worker_id].last_report
        ]

    def _maybe_reassess(
        self,
        original_task: str,
        results: list[WorkerResult],
        evidence: list[dict[str, Any]],
        *,
        allow_follow_up: bool,
    ) -> list[dict[str, Any]]:
        policy = self.config["coordinator"]["estimate_updates"]
        if not policy["enabled"]:
            return []
        if policy["trigger"] == "meaningful_evidence" and not evidence:
            return []
        if self.reassessments >= policy["max_reassessments"]:
            self.events.emit(
                "coordinator",
                "COORDINATOR_REASSESSMENT_RECORDED",
                {"outcome": "skipped_limit", "round": self.round,
                 "max_reassessments": policy["max_reassessments"]},
                summary="Coordinator reassessment skipped: the configured reassessment limit was reached.",
            )
            return []
        # Keep enough model requests in reserve for synthesis. A coordinator
        # call can need several requests (e.g. a retry for a missing answer
        # tag), so the reserve uses the largest per-call cost observed so far.
        per_call = self._coordinator_call_cost
        remaining = [
            self.budget.remaining("coordinator", "model_requests"),
            self.budget.remaining("orchestrator", "model_requests"),
        ]
        available = min(value for value in remaining if value is not None) if any(v is not None for v in remaining) else None
        if available is not None and available < 2 * per_call:
            self.events.emit(
                "coordinator",
                "COORDINATOR_REASSESSMENT_RECORDED",
                {"outcome": "skipped_budget", "round": self.round,
                 "coordinator_model_requests_remaining": remaining[0],
                 "reserved_for_synthesis": per_call},
                summary="Coordinator reassessment skipped to preserve the model-request budget for synthesis.",
            )
            return []
        assert self.coordinator is not None
        follow_up_workers = []
        if allow_follow_up and self._follow_up_rounds < self.config["coordinator"]["max_follow_up_rounds"]:
            follow_up_workers = [
                worker_id
                for worker_id, result in zip(self.worker_ids, results)
                if result.status == WorkerStatus.COMPLETED.value
            ]
        before = self.budget.used("coordinator", "model_requests")
        self.reassessments += 1
        cap = (available - per_call) if available is not None else 2 * per_call
        guard = getattr(self.coordinator.agent, "budget_guard", None)
        if guard is not None and hasattr(guard, "capped"):
            with guard.capped(cap):
                assessment = self.coordinator.reassess(
                    original_task, results, evidence, self.estimates.current(),
                    round_index=self.round, follow_up_workers=follow_up_workers,
                )
        else:
            assessment = self.coordinator.reassess(
                original_task, results, evidence, self.estimates.current(),
                round_index=self.round, follow_up_workers=follow_up_workers,
            )
        cost = self.budget.used("coordinator", "model_requests") - before
        self._coordinator_call_cost = max(self._coordinator_call_cost, cost)
        if assessment is None:
            return []
        self.estimates.assess(
            estimate=assessment["estimate"],
            status=assessment["status"],
            summary=assessment["summary"],
            reason=assessment["reason"],
            evidence=evidence,
            round_index=self.round,
            model_requests=cost,
        )
        return assessment["follow_up"]

    def _run_follow_ups(
        self,
        original_task: str,
        results: list[WorkerResult],
        follow_ups: list[dict[str, Any]],
        original_input: list[dict[str, Any]],
    ) -> list[WorkerResult]:
        assert self.coordinator is not None
        by_id = {result.agent_id: result for result in results}
        limit = self.config["coordinator"]["max_follow_up_rounds"]
        while follow_ups and self._follow_up_rounds < limit and not self._cancelled.is_set():
            self._follow_up_rounds += 1
            assignments = []
            for index, item in enumerate(follow_ups, start=1):
                worker_id = item["worker_id"]
                assignment = Assignment(
                    assignment_id=f"follow_up_{self._follow_up_rounds:02d}_{index:02d}",
                    task_id=self.task_id,
                    worker_id=worker_id,
                    scope=item["scope"],
                    required_output="updated candidate answer, evidence references, and limitations",
                    tool_budget=worker_config(self.config, worker_id)["tool_calls"],
                    deadline_seconds=self.config["execution"]["task_timeout_seconds"],
                )
                if self.coordinator.send_follow_up(assignment, index) == "delivered":
                    assignments.append(assignment)
            if not assignments:
                break
            workers = [a.worker_id for a in assignments]
            self._round_event("STARTED", "follow_up", workers)
            round_index = self.round

            def execute(assignment: Assignment) -> WorkerResult:
                return self.workers[assignment.worker_id].follow_up(
                    by_id[assignment.worker_id], assignment, original_input, round_index
                )

            if self.config["execution"]["mode"] == "cooperative" or len(assignments) == 1:
                updated = [execute(a) for a in assignments]
            else:
                with ThreadPoolExecutor(
                    max_workers=min(self.config["execution"]["max_concurrent_workers"], len(assignments)),
                    thread_name_prefix="multi-agent-follow-up",
                ) as executor:
                    updated = list(executor.map(execute, assignments))
            for result in updated:
                by_id[result.agent_id] = result
            results = [by_id[worker_id] for worker_id in self.worker_ids]
            evidence = self._collect_evidence()
            self._round_event("COMPLETED", "follow_up", workers, evidence)
            follow_ups = self._maybe_reassess(
                original_task, results, evidence, allow_follow_up=True
            )
        return results

    def run(
        self, original_task: str, original_input: list[dict[str, Any]]
    ) -> dict[str, Any]:
        results: list[WorkerResult] = []
        final: dict[str, Any] = {"final_answer": None, "final_status": "FAILED"}
        failure: str | None = None
        try:
            self._record_initial_inputs(original_task, original_input)
            self._transition(RunStatus.INITIALIZING)
            self._initialize()
            # Publish the constructed actor topology before any inference so a
            # live Studio can draw harnesses, model clients, memory, and tools.
            _write_json(
                self.run_dir / "run_manifest.json", self._manifest(original_task)
            )
            self._transition(RunStatus.PLANNING)
            assert self.coordinator is not None
            specs = [
                (worker_id, self.workers[worker_id].role)
                for worker_id in self.worker_ids
            ]
            plan_before = self.budget.used("coordinator", "model_requests")
            assignments = self.coordinator.plan(
                original_task,
                specs,
                self.config["execution"]["task_timeout_seconds"],
                {
                    worker_id: worker_config(self.config, worker_id)["tool_calls"]
                    for worker_id in self.worker_ids
                },
            )
            self._coordinator_call_cost = max(
                1, self.budget.used("coordinator", "model_requests") - plan_before
            )
            self._transition(RunStatus.ASSIGNING)
            self.coordinator.send_assignments(assignments)
            self._transition(RunStatus.RUNNING)
            self._round_event("STARTED", "initial", self.worker_ids)
            results = self._execute_workers(assignments, original_input)
            evidence = self._collect_evidence()
            self._round_event("COMPLETED", "initial", self.worker_ids, evidence)
            if self._cancelled.is_set():
                self._transition(RunStatus.CANCELLED)
                final = {"final_answer": None, "final_status": "CANCELLED"}
                self.events.emit(
                    "orchestrator",
                    "RUN_CANCELLED",
                    {"reason": "Cancellation was requested at an orchestration boundary."},
                    summary="Investigation stopped after a cancellation request.",
                    status="cancelled",
                )
            else:
                follow_ups = self._maybe_reassess(
                    original_task, results, evidence, allow_follow_up=True
                )
                results = self._run_follow_ups(
                    original_task, results, follow_ups, original_input
                )
                if (
                    self.bus.enabled
                    and self.bus.peer_to_peer
                    and len(self.worker_ids) > 1
                    and self.config["execution"]["peer_review_rounds"] > 0
                ):
                    self.coordinator.request_verification(self.worker_ids)
                    reports_before = {
                        worker_id: self.workers[worker_id].reports
                        for worker_id in self.worker_ids
                    }
                    self._round_event("STARTED", "peer_review", self.worker_ids)
                    results = self._review_workers(results, original_input)
                    reviewed = [
                        worker_id
                        for worker_id in self.worker_ids
                        if self.workers[worker_id].reports > reports_before[worker_id]
                    ]
                    evidence = self._collect_evidence()
                    self._round_event("COMPLETED", "peer_review", reviewed, evidence)
                    self._maybe_reassess(
                        original_task, results, evidence, allow_follow_up=False
                    )
                self._transition(RunStatus.SYNTHESIZING)
                final = self.coordinator.synthesize(original_task, results)
                self.estimates.finalize(
                    final.get("final_answer"),
                    evidence=self._latest_reports(),
                    summary="Final answer from coordinator synthesis.",
                )
                self.coordinator.record_final(final)
                self._transition(RunStatus.COMPLETED)
                self.events.emit(
                    "orchestrator",
                    "RUN_COMPLETED",
                    {"final_answer": final.get("final_answer")},
                    summary="Investigation completed and the final answer was persisted.",
                )
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
            self.events.emit(
                "orchestrator",
                "RUN_FAILED",
                {"error": failure},
                summary=f"Investigation failed: {failure}",
                status="failed",
            )
            final = {
                "final_answer": None,
                "final_status": self.status.value,
                "failure_reason": failure,
            }
        finally:
            if self.scheduler is not None:
                self.scheduler.shutdown(cancel_pending=True, wait=True)
                final["scheduler"] = self.scheduler.summary()
                plans = {aid: {"stats": w.agent.plan_controller.stats, "plans": w.agent.plan_controller.reports}
                         for aid, w in self.workers.items() if getattr(w.agent, "plan_controller", None) is not None}
                if plans:
                    final["planning"] = plans
            if self.planning_pool is not None:
                final.setdefault("planning_pool", {
                    "mode": self.config["execution"]["planning"]["planning_pool"],
                    "started": self.planning_pool.starts > 0 or self.planning_pool.started,
                    "startup_seconds": round(self.planning_pool.startup_seconds, 4)})
                if self.config["execution"]["planning"]["planning_pool"] != "shared":
                    self.planning_pool.shutdown()
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
