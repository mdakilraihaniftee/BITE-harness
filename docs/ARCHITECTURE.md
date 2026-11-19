# Architecture

PARSEC-VL adds a dependency-aware parallel execution layer to an existing
multi-agent visual-reasoning harness (derived from OpenVLHarness). This page
describes the harness as it actually executes, then the Phase 1 scheduler and
where it plugs in.

## 1. The harness as it executes

```text
MultiAgentOrchestrator.run(task, image)                    openvlharness/multi_agent/orchestrator.py
 ├─ coordinator.plan(...)            one model call (+1 retry)   ── barrier ──
 ├─ workers: ThreadPoolExecutor(max_concurrent_workers)      # concurrent mode; cooperative = one by one
 │    └─ WorkerAgent.run → MainAgent.generate                openvlharness/agent/agent.py
 │          loop (max_iterations):
 │            reserve model_requests ── model request (HTTP, blocking) ── parse
 │            for each tool call in the response:          # the paper protocol allows ONE per message
 │               announce  (DECISION_SUMMARY_RECORDED, TOOL_CALL_REQUESTED)
 │               execute   reserve tool_calls → capability.invoke (HTTP to tool server → GPU service)
 │               publish   result → memory (registry IDs), events, model history
 ├─ peer review round (concurrent; uses peer messages)             ── barrier ──
 ├─ optional coordinator reassessments / follow-up rounds          ── barrier ──
 └─ coordinator.synthesize → FINAL_ANSWER_RECORDED, final_result.json
```

| Question | What the code does |
|---|---|
| Worker start | The orchestrator submits one `WorkerAgent.run` per assignment to a `ThreadPoolExecutor` (`execution.max_concurrent_workers`; the shipped `configs/multi_agent.yaml` sets **2**, so a 4-worker run executes at most 2 workers at a time). `cooperative` mode runs workers one after another. |
| Action choice | The model's response; `ModelAdapter.parse` turns extra calls in one message into `multiple_tool_calls_not_allowed` errors (paper protocol). |
| Tool invocation | `BaseCapability.invoke`: validate + resolve memory references → `execute` (HTTP through the tool server to the backend service) → validate + publish into memory. |
| Synchronous parts | Everything inside one agent: model request, then each tool call, blocking. |
| Existing concurrency | Across workers only (threads). Measured: up to 2 overlapping tool calls and 2 overlapping model requests in recorded real runs (the `max_concurrent_workers: 2` cap). |
| Model serving | All agents share one vLLM endpoint (`MODEL_BASE_URL`); concurrent requests are batched by the server. |
| Evidence | Per-agent `MemoryStore` (image registry `input_image_N` / `tool_generated_image_N`, bindings, URLs); run-scoped content-addressed `ArtifactStore` for images in events. |
| Communication | `CommunicationBus` (assignments, reports, peer messages), budgeted per actor. |
| Budgets | One `BudgetManager` per run: global and per-actor limits for `tool_calls`, `model_requests`, `messages`; atomic reservations under one lock; a reserved unit is spent (no refunds, failed calls are charged). |
| Failures | Tool failures become `CapabilityResult(ok=False)` the model sees; a worker exception becomes a `FAILED` worker result; the run continues. |
| Termination | Model final answer per agent; orchestrator state machine to `COMPLETED`/`FAILED`/`CANCELLED`. |
| Persistence | `events.jsonl` (append-only, thread-safe `EventLog`), `final_result.json`, `budgets.json`, per-worker trajectories. |
| Studio | Reads `events.jsonl` (SSE live or replay), folds events into the story, team view, and evidence viewer. |

## 2. The PARSEC-VL scheduler (Phase 1)

Package `openvlharness/parsec_vl/`:

| Module | Responsibility |
|---|---|
| `dag.py` | `Task` (validated unit of work), `TaskStatus` + validated transitions, DAG validation (duplicates, missing dependencies, cycles), bottom levels, `graph_metrics` (T1, T∞, T1/T∞), `lower_bound`. |
| `resources.py` | `ResourcePools` (typed integer capacities, busy-time accounting) and `BudgetAdapter` (reserve/settle/release through the run's existing `BudgetManager`; no second ledger). |
| `scheduler.py` | `Scheduler`: one engine, three policies, worker slots, timeouts, failure propagation, cancellation, shutdown, telemetry. |
| `harness.py` | `ToolScheduling`: runs an agent's tool calls through a shared scheduler; resource-pool mapping per backend server. |
| `profiling.py` | Profiles recorded runs from `events.jsonl` (no extra instrumentation or model calls). |
| `workloads.py` | Synthetic benchmark DAGs A–D, M, V, X, S. |

Phase 2 modules are described in §3.

### Task lifecycle

```text
CREATED ─┬─> BLOCKED ──> READY ──> RESERVED ──> RUNNING ──> COMPLETED
         │                 │          │            └──────> FAILED   (exception or timeout)
         └─> READY         ├─> FAILED (budget denied at admission; nothing charged)
                           └─> CANCELLED / SKIPPED            RESERVED ─> CANCELLED (reservation released)
```

`SKIPPED` = a prerequisite did not complete (propagated transitively). A running
task is never cancelled; on timeout it is marked `FAILED`, its dependents are
skipped, and its late result is discarded when the thread returns.

### Dispatch rule

A ready task starts only when **all four** hold: prerequisites `COMPLETED` (their
results published), a worker slot is free, its resource pool has capacity, and its
budget cost was reserved. Ready tasks are ordered by policy:

| Policy | Slots | Order |
|---|---|---|
| E0 sequential FIFO | 1 | ready order; never overtakes the queue head |
| E1 parallel FIFO | `workers` | ready order; a task whose pool is full is passed over (work-conserving) |
| E2 critical path | `workers` | highest bottom level (estimated remaining downstream work) first, then ready order |

E2 estimates come from `Task.estimated_cost`; inside the harness that is the mean
latency of the agent's *previous* calls of the same tool (online, never future
outcomes). With no estimate a task counts 1 (longest downstream chain).

### Resources and budget

Pools: `cpu`, `remote_io`, `model_service`, and one `service:<host:port>` pool per
backend server (depth and camera pose share a server, so they share a pool).
Unverified GPU services get capacity **1** (`execution.scheduler.service_capacity`);
the Phase 1 probe measured which services gain from concurrency (see
PHASE1_RESULTS.md). Budget: the scheduler reserves `tool_calls` for the task's
agent through the run's `BudgetManager` (same units and limits as before);
`spent + reserved ≤ total` holds because the manager counts both, atomically.
`BudgetManager.release` exists only for tasks cancelled before dispatch.

### Harness integration

```text
MainAgent turn with calls [c1, c2, c3]
  agent thread:  prepare(ci)  validate + resolve references (reads memory only)
                 announce(ci) DECISION_SUMMARY_RECORDED, TOOL_CALL_REQUESTED
  scheduler:     run_backend(ci) on a worker slot  ─ TOOL_CALL_STARTED at the real start
  agent thread:  finish(ci) in call order          ─ memory write, TOOL_CALL_COMPLETED, history
```

`BaseCapability.invoke` is now `prepare` → `run_backend` → `finish` (same code,
same results). Memory has one writer, the agent thread, so registry IDs and the
model-visible history are identical to sequential execution (tested). Within a
turn, a call waits for the earlier calls when one of its references does not
resolve exactly yet (including the single-image fallback), when its tool reads
memory in the backend (`parallel_safe = False`, e.g. coding), or when the BITE
observer is on. Across agents, every worker's calls share the scheduler, its pools,
and the run budget.

Enable it per run: `execution.scheduler.policy: e0|e1|e2` (or `e3|e4|e5`, §3) in the multi-agent
config, or `--tool-scheduler e1 [--scheduler-workers N]` on
`python -m openvlharness.multi_agent.run`, `scripts/run_studio_dataset_task.py`,
`scripts/studio_config_matrix.py run`, and `-s e1` on
`scripts/run_custom_inference.sh`. `off` (default) leaves the original path
untouched. Because the paper protocol forbids several calls per model message,
intra-agent concurrency needs `ModelAdapter.allow_multiple_tool_calls = True`, an
explicit protocol change that is off everywhere by default (used only in tests).

### Telemetry

Each task produces `SCHEDULER_TASK_STARTED` and `SCHEDULER_TASK_FINISHED` events in
the run's existing `events.jsonl` (no second store) with: `run_id`, `task_id`,
`agent_id`, `operation` (tool), `dependency_ids`, `resource_pool`, `worker_id`,
`created_time`, `enqueue_time`, `reserved_time`, `start_time`, `finish_time`
(monotonic seconds from scheduler start), `start_wall`/`finish_wall` (UTC),
`status`, `failure_reason`, `budget_used`, and `metadata.invocation_id` /
`request_event_id` correlating with the Studio's tool events. The Investigation
Story keeps them in the Technical Trace only. `final_result.json["scheduler"]` holds
the run summary (makespan, peak concurrency, waits, pool saturation, budget).

## 3. Phase 2: declared action plans, Monte Carlo planning, speculation (E3–E5)

| Module | Responsibility |
|---|---|
| `plans.py` | `ActionPlan` → `Branch` (primary + alternatives) → `PlanAction` (existing tool name + arguments, explicit `depends_on`, optional `expect` goal). Bindings `"$<id>.<value>"` pass an ancestor's output (grounding box, crop image). `validate_plan` checks tools, argument schemas, input images in this agent's memory, geometry, dependencies/cycles (Phase 1 DAG validator), bindings, depth and size limits. `heuristic_alternatives`: the one declared controller rule. `PLAN_TOOL_SCHEMA`. |
| `montecarlo.py` | Plan → compact simulation spec; `rollout` = discrete-event list scheduling with pools, worker slots, budget, outcome draws, speculation option; `PlanEvaluator` = persistent spawn `ProcessPoolExecutor`, fixed batches, seeds by rollout index, ordered aggregation (identical results for any process count), sliding submission window, time budget, crash recovery. `OutcomeModel` with provenance (`empirical`/`declared`/`heuristic`). |
| `controller.py` | `PlanExecutor`: runs one plan through the existing `Scheduler`; branch lifecycle; S0/S1/S2; adoption; pruning/cancellation; event-driven replanning; `PlanningConfig` (E3/E4/E5 presets); `SyntheticRuntime`. |
| `harness.py` | `HarnessRuntime` (real capabilities, agent memory, isolated branch memories, Studio tool events), `PlanController` (handles `Execute_Action_Plan`, validation stats), `attach_plan_mode`. |
| `fixture.py`, `experiments.py` | Deterministic sign-reading fixture (real OCR/grounding/Zoom capabilities, scripted model); Phase 2 experiment drivers. |

**Decision protocols.** `legacy_single_call` (default): unchanged. `declared_multi_action_plan`
(E3–E5 only, explicit opt-in): the model is additionally offered `Execute_Action_Plan`.
It is still one tool call per model message; the plan authorizes several actions at
once, so it is a different decision protocol, not just a different schedule.

```text
model ── Execute_Action_Plan(actions, alternatives) ── validate (plans.py) ── reject → tool error, agent continues
   │                                                         │ valid
   │                         E3/E5: Monte Carlo picks the leading branch (process pool, time budget)
   │                         S0/S1/S2: which alternatives start speculatively
   ▼                                                         ▼
 agent thread  <── commit in fixed topological order ── Scheduler (E2 order; necessary before speculative)
   │  primary branch → agent memory; alternatives → isolated memory copy until adopted
   └─ one tool result: every committed action's evidence, in commit order
```

**Identity.** `plan_id = <run>.<agent>.planNNNN`; `branch_id = <plan_id>.<branch>`;
logical request / Studio invocation ID = `<plan_id>.<branch>.<action>`; scheduler
`task_id = <agent>.<branch>.<action>.tNNNNN` (the physical execution).

**Branch lifecycle and budget.** planned → necessary | speculative → satisfied /
unsatisfied / adopted / pruned. Every task reserves `tool_calls` in the run's one
`BudgetManager` when admitted. Queued work that is pruned is cancelled and its
reservation released. Running work cannot be stopped (`backend_cancelled: false`): it
finishes, stays charged, and its result is discarded. Completed but unused
speculation stays charged. Adoption replays stored payloads into the agent's memory
(`finish`), so no tool runs twice. E5 additionally limits speculation to `capacity−1`
units of each shared pool (at least 1) and keeps one worker slot for necessary
work; S2 also refuses speculation that would leave less budget than the primary
branch needs. `speculative_budget_limit` caps speculative calls per plan (a counter,
not a second ledger).

**Replanning.** Triggered only when every necessary branch has failed; E5 re-evaluates
the remaining alternatives by Monte Carlo at most `max_replans` times; otherwise the
proposed order is used.

**Events (technical trace).** `PLANNING_CONFIGURED`, `PLAN_CANDIDATES_GENERATED`,
`PLAN_REJECTED`, `PLAN_EVALUATION_STARTED/COMPLETED` (estimates, wall, CPU, processes,
outcome-model source), `PLAN_SELECTED` (decision terms), `SPECULATIVE_TASK_ADMITTED/
STARTED/COMPLETED/CANCEL_REQUESTED/PRUNED`, `SPECULATIVE_RESULT_ADOPTED`,
`REPLAN_TRIGGERED/COMPLETED`, `PLAN_EXECUTION_COMPLETED`. Committed actions also emit
normal `TOOL_CALL_REQUESTED/STARTED/COMPLETED` events (with `plan_id`, `branch_id`,
`executed_interval`, `adopted_from_speculation`), so the Studio shows their evidence.

## 4. Phase 3: overhead-aware planning and the PARSEC-VL Studio view

**Planning pool lifecycle** (`execution.planning.planning_pool`). `lazy` (default): the
process pool is created by the first evaluation that needs it, exactly once per run
even when several workers ask concurrently (`PlanEvaluator.start` is guarded by a
lock), reused for every later decision, and shut down at run end; a run in which no
plan is proposed starts no processes. `eager` starts it at run start (Phase 2
behaviour). `shared` keeps one process-wide warm pool across runs in the same Python
process (explicit opt-in; closed at interpreter exit). Every start emits
`PLANNING_POOL_STARTED` with its measured cost.

**Planning gate** (`execution.planning.planning_gate: auto|off`). Before each
evaluation, `controller.choose_planning_backend` compares:

```text
stakes      = spread of closed-form scores (latency + μ·tool calls) across candidates
sequential  = candidates × rollouts × 24 µs            (capped by the planning time budget)
parallel    = sequential / processes + 0.12 s (+ 0.25 s if the pool is cold)
backend     = heuristic   if 1 candidate, or stakes < 0.05 s, or min(sequential, parallel) > stakes
            = sequential  if sequential ≤ parallel
            = parallel    otherwise
```

The constants are the Phase 2 measurements on this machine (in-process rollout cost,
pool overhead per evaluation, cold start); they are declared in `PlanningConfig`, not
tuned on evaluation answers. Skipped simulations emit `PLAN_EVALUATION_SKIPPED` with the
reason; when no simulation runs, plan selection uses the same closed form
(`montecarlo.heuristic_estimate`). `off` reproduces Phase 2 (always the pool).

**Model-facing plan schema** (`execution.planning.plan_schema: current|simple`). The
Phase 3 probe (`scripts/plan_probe.py`) showed the real model only proposes plans when
explicitly asked. Two parser rules were fixed from what it actually produced: a
`"$id.value"` argument is an explicit data dependency, so a missing `depends_on`
entry is added and recorded (`estimates.inferred_dependencies`) instead of rejecting
the plan; and the flat `simple` schema (`steps`, `after`, `$id.box`, `$id.image`,
`fallback`) is translated into the canonical plan before validation. Both schemas are
accepted; `current` stays the default (no measured difference).

**Studio: PARSEC-VL panel** (`static/parsec-view.js`, one panel under the team
overview, four tabs). Everything is a pure fold over the visible event prefix
(`buildModel(events)`), so replay never shows future data and live runs update as
events arrive.

| Tab | Shows | Source |
|---|---|---|
| Timeline | Gantt of real execution intervals; lanes by scheduler slot, resource pool (rows ≤ capacity), or agent; queue wait drawn separately; speculative (hatched), adopted (outlined), unused/cancelled (faded), running (open to "now"); planning lane (pool start-up, evaluations); critical path; zoom/pan; click → details + tool evidence | `SCHEDULER_TASK_STARTED/FINISHED` (one scheduler clock), `PLAN_EVALUATION_*`, `PLANNING_POOL_STARTED` placed via the recorded wall anchor |
| Plan & DAG | Plan graph from declared `depends_on` only; branch status, origin label (model-generated / scripted policy / controller heuristic / fixture); decision explained from recorded terms; predicted (Monte Carlo) vs observed | `PLAN_CANDIDATES_GENERATED`, `PLAN_SELECTED`, `REPLAN_*`, `PLAN_EXECUTION_COMPLETED` |
| Budget & resources | Limit, spent, reserved-not-started, available, speculative charged/unused, cancelled before start, logical vs physical, denials; budget over time; pool occupancy (a proxy, not GPU utilization) | `BUDGET_UPDATED`, scheduler records, run configuration |
| Compare | Recorded benchmark tables (REAL / FIXTURE / SYNTHETIC), one paired workload per table, baseline deltas | `GET /api/parsec/experiments` → `parsec_vl/report.load_comparisons` (read-only; nothing runs) |

Runs without PARSEC metadata show "No PARSEC-VL planning or scheduler data was
recorded for this run." The Investigation Story gains three concise step types
(plan proposed, speculative result adopted, plan outcome as facts); queue, budget, and
evaluation bookkeeping stay in the Technical Trace.
