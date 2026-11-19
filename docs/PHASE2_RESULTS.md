# PARSEC-VL Phase 2 results

Parallel planning, declared multi-action plans, selective speculation, and
event-driven replanning (E3–E5). Machine: 2 × Intel Xeon Gold 6544Y (32 cores /
64 hardware threads visible to this session; Phase 1's session saw 8), 4 × NVIDIA
L40S, Python 3.11. Labels: **REAL** (live model and tool services), **FIXTURE**
(real agent loop and capabilities, scripted model, local tool transports with
injected latency), **SYNTHETIC** (declared outcome/duration models; real scheduler,
real processes, real wall clock). Raw data: `outputs/parsec_vl/phase2/`.

## A. Phase 1 findings carried forward — and one correction

* **One tool call per model message** (paper protocol): a single agent never had
  independent tool calls to overlap (0 of 90 recorded real tool turns had more than
  one). Phase 2 keeps that rule and adds a separate, opt-in decision protocol.
* **Scheduler overhead.** Phase 1 measured E1/E2 ≈ 26% slower than the original
  runtime in whole fixture runs. Phase 2 traced most of it to the **event log**:
  `jsonschema.validate()` re-checked the event schema on every event — 4.0 ms per
  event, 97% of `EventLog.emit` — and the scheduler path emits a few more events per
  call, which GIL contention amplified. The validator is now compiled once
  (`openvlharness/studio/schema.py`): **0.096 ms per event**, same checks, invalid
  events still rejected. Re-measured (`parsec.py harness`, FIXTURE, 5 trials):

| Scheduler | Phase 1 (slow validation) | Phase 2 (fixed validation) |
|---|---:|---:|
| off | 3.405 ± 0.081 s | **2.777 ± 0.004 s** |
| E0 | 4.766 ± 0.035 s | 3.950 ± 0.017 s |
| E1 | 4.312 ± 0.210 s | 2.876 ± 0.018 s (+3.6%) |
| E2 | 4.297 ± 0.194 s | 2.871 ± 0.013 s (+3.4%) |

  The fix speeds up every mode, including the original runtime. Request→start per
  call fell from ~50 ms to 2.8 ms. The Phase 2 baseline before the fix reproduced
  Phase 1 (off 3.450 s, E2 4.470 s; `outputs/parsec_vl/phase2_baseline/`).
* CPU-bound Python on threads does not scale (Phase 1: 0.43–0.54×); Phase 2 planning
  therefore uses processes.

## B. How plans enter the system

* **Decision protocol `declared_multi_action_plan`** (E3–E5 only; default stays
  `legacy_single_call`). Workers are offered one extra tool, `Execute_Action_Plan`,
  plus a short system-prompt note. Still one tool call per model message: the plan
  authorizes several actions at once (independent actions, dependencies with
  bindings such as `"$g.boxes_normalized.0"`, and alternative branches). This is a
  different decision protocol, not just a different schedule.
* **Sources** (recorded as `origin_type` on every plan and branch): `model` (the
  worker's own call — real or scripted policy), `controller_heuristic` (one declared
  rule: unreadable OCR → ground text, zoom, OCR the crop; sees only the plan),
  `fixture` (scripted benchmark plans). `coordinator` is reserved: the coordinator has
  no tool access in this runtime. No plan is generated from future results or labels.
* **Validation** (`plans.validate_plan`): unknown/unsupported tools (coding and other
  memory-reading tools are excluded from plans), argument schemas, input images that
  are not in this agent's memory (also blocks cross-run references), geometry,
  unknown dependencies, cycles (Phase 1 DAG validator), bindings that are not declared
  dependencies or name values the producer does not output, nesting, depth/size limits.
  Invalid plans become a tool error; the agent continues.
* **Where real model plans stand: REAL, 2 runs.** Qwen3-VL-8B (FSC-147 row 25, 2
  workers, E5) never called `Execute_Action_Plan`, with or without the prompt note,
  although it was offered (7 tools instead of 6 in every worker request). Plans
  proposed: 0 of 4 worker sessions → valid 0, invalid 0, empty 0. All plan
  executions in this report therefore come from scripted fixtures or synthetic
  scenarios.

## C. Parallel planning implementation

* **Simulation** (`montecarlo.rollout`): per action a resource pool, dependencies, a
  duration model, and a probability of producing usable evidence; per branch a goal
  action. One rollout draws every duration/outcome in a fixed order (common random
  numbers across candidates), then runs a discrete-event list-scheduling simulation
  with worker slots, pool capacities, and the remaining budget. Alternatives become
  necessary when every necessary branch fails; speculative branches run at lower
  priority; started work is charged. Outputs: latency, tool calls, operational
  success, wasted calls/seconds. ~20 µs per rollout (pure Python, CPU-bound).
* **Estimates**: T̂ = mean latency (also sd, p90), Ĉ = mean tool calls, P̂ = probability
  of the *operational* goal (e.g. "a non-empty OCR transcription") — not answer
  correctness. Score = λ·T̂ + μ·Ĉ (λ = 1 per s, μ = 0.25 per call; declared weights).
* **Outcome models** carry their source: `empirical` (`parsec.py outcome-model`:
  durations and evidence rates from earlier recorded real runs only — 19 runs, 70
  grounding / 14 zoom / 6 coding calls, **no OCR calls**, so OCR falls back),
  `declared` (fixtures/scenarios), `heuristic` (probe medians, success 0.5).
* **Processes**: persistent `ProcessPoolExecutor` (spawn start method — safe with the
  runtime's threads), started once per run (or per benchmark), sliding submission
  window of 2 × processes batches, fixed batch layout and per-rollout seeds
  (`seed·1000003 + rollout_index`), aggregation in batch order → **identical
  estimates for any process count**. Planning time budget (default 0.5 s): batches not
  finished in time are dropped and every candidate keeps the same prefix of seeds;
  with no usable estimate the controller falls back to the proposed order / closed-form
  rule. A crashed worker process is replaced once and missing batches are redone.

## D. Multicore benchmark (SYNTHETIC, `parsec.py plan-bench`)

6 candidate plans × 50,000 rollouts = 300,000 rollouts; batch 500; 3 trials. Warm pool
timings exclude pool start-up, which is reported separately (cold start).

| CPU processes | Rollouts | Wall time (mean ± sd) | Speedup vs 1 process | Efficiency | CPU utilization | Cold start |
|---:|---:|---:|---:|---:|---:|---:|
| in-process (sequential) | 300,000 | 7.104 ± 0.150 s | 1.07 | — | 0.99 | — |
| 1 | 300,000 | 7.605 ± 0.378 s | 1.00 | 1.00 | 0.98 | 0.21 s |
| 2 | 300,000 | 3.928 ± 0.216 s | 1.94 | 0.97 | 0.97 | 0.19 s |
| 4 | 300,000 | 2.100 ± 0.063 s | 3.62 | 0.91 | 0.94 | 0.22 s |
| 8 | 300,000 | 1.113 ± 0.022 s | 6.83 | 0.85 | 0.89 | 0.25 s |
| 16 | 300,000 | 0.615 ± 0.010 s | 12.37 | 0.77 | 0.83 | 0.31 s |

All configurations produced bitwise-identical estimates. The one-process pool is 7%
slower than in-process (pickling/IPC); efficiency falls with more processes as the
fixed per-batch overhead (~0.1–0.15 s per evaluation) becomes a larger share.

**Decision quality under a fixed planning time budget** (40 random plan problems,
6 candidates each; reference = 40,000 rollouts per candidate):

| Method | Time budget | Rollouts per candidate | Best choice | Mean regret |
|---|---:|---:|---:|---:|
| closed-form heuristic | 0 | 0 | 0.80 | 0.0167 |
| sequential Monte Carlo | 0.05 s | 240 | 0.97 | 0.0003 |
| parallel Monte Carlo, 8 processes | 0.05 s | 181 | **0.95** | 0.0025 |
| sequential Monte Carlo | 0.2 s | 1,589 | 1.00 | 0 |
| parallel Monte Carlo, 8 processes | 0.2 s | 2,458 | 1.00 | 0 |

**Negative result:** at 50 ms the process pool completes *fewer* rollouts than a plain
loop (IPC latency dominates small batches) and decides slightly worse. At 200 ms it
completes 1.5× more, but both already choose perfectly on these problems. Parallel
planning pays off for large rollout counts (D, 12×), not for the sub-100 ms decisions a
single tool step can afford.

## E. Speculation implementation

Branch lifecycle: planned → necessary | speculative → satisfied / unsatisfied /
adopted / pruned (`controller.py`). Admission: a speculative task needs its inputs,
dependencies, valid arguments, a speculation-safe tool (OCR, grounding, zoom, depth,
camera pose; never coding or web/search), pool and worker capacity, and a budget
reservation in the shared ledger. The scheduler always orders necessary tasks first;
under E5 speculation may use at most capacity−1 units of each shared pool (min 1) and
never the last free worker slot; S2 also refuses speculation that would leave less
budget than the primary branch needs; `speculative_budget_limit` caps speculative
calls per plan. Settlement: pruned queued tasks are cancelled and their reservation
released; running tasks get `SPECULATIVE_TASK_CANCEL_REQUESTED` with
`backend_cancelled: false` — they finish, stay charged, and their result is discarded;
completed-but-unused speculation stays charged; adopted results are replayed into the
agent's memory without re-running the tool. Speculative branches commit only into an
isolated copy of the agent's memory. Replanning only when all necessary branches have
failed; E5 re-evaluates remaining alternatives by Monte Carlo at most `max_replans`
times.

## F. Speculation results (SYNTHETIC, `parsec.py spec-bench`, 30 trials, same per-trial outcomes for every policy)

| Scenario | Policy | Latency (mean ± sd) | Tool calls | Wasted calls | Wasted s | Completion | Necessary queue wait |
|---|---|---:|---:|---:|---:|---:|---:|
| A: alternative usually needed (primary 20%) | S0 | 0.364 ± 0.153 | 3.20 | 0 | 0 | 0.90 | 0.000 |
| | S1 K=1 | **0.291** ± 0.109 | 3.50 | 0.30 | 0.057 | 0.90 | 0.000 |
| | S2 | 0.312 ± 0.109 | 3.50 | 0.30 | 0.057 | 0.90 | 0.001 |
| B: primary usually succeeds (90%) | S0 | 0.143 ± 0.116 | **1.30** | 0 | 0 | 1.00 | 0.001 |
| | S1 K=1 | 0.130 ± 0.080 | 2.27 | 0.97 | 0.186 | 1.00 | 0.001 |
| | S2 | 0.160 ± 0.116 | **1.30** | 0 | 0 | 1.00 | 0.001 |
| C: primary also needs the capacity-1 GPU | S0 | 0.488 ± 0.194 | 4.60 | 0 | 0 | 0.90 | 0.000 |
| | S1 K=1 | 0.480 ± 0.052 | 6.00 | 1.40 | 0.164 | 0.90 | **0.060** |
| | S2 | 0.519 ± 0.194 | 4.60 | 0 | 0 | 0.90 | 0.000 |
| D: planner believes 10%, truth 90% | S0 | 0.143 ± 0.116 | 1.30 | 0 | 0 | 1.00 | 0.001 |
| | S1 K=1 | 0.130 ± 0.080 | 2.27 | 0.97 | 0.186 | 1.00 | 0.001 |
| | S2 | 0.156 ± 0.079 | 2.27 | **0.97** | 0.186 | 1.00 | 0.001 |
| E: budget 4, two alternatives | S0 | 0.325 ± 0.165 | 2.90 | 0 | 0 | 0.60 | 0.000 |
| | S1 K=1 | 0.262 ± 0.117 | 3.30 | 0.40 | 0.080 | 0.60 | 0.000 |
| | S1 K=2 | 0.305 ± 0.152 | 3.33 | 0.43 | 0.085 | **0.37** | 0.001 |
| | S2 | 0.302 ± 0.118 | 3.30 | 0.40 | 0.080 | 0.60 | 0.000 |

(S1 K=2 equals K=1 where only one alternative exists. Full table with p90 and planning
time: `outputs/parsec_vl/phase2/speculation/speculation.md`.)

* Speculation hides latency when the alternative is usually needed (A: −20% with S1).
* When it is rarely needed it wastes ~1 call per decision for ~9% latency (B); S2
  declines and spends no extra calls but pays ~17 ms of planning, so its latency is
  slightly *worse* than S0.
* Under contention (C) S1 delays necessary work (queue wait 0 → 60 ms) and adds 30%
  calls without a latency gain; S2 avoids it.
* With wrong estimates (D) S2 behaves like S1 and adds planning time: **worse than the
  simple policies**.
* With a small budget (E) wide speculation starves later necessary work (completion
  0.60 → 0.37); S2's headroom rule keeps completion at 0.60.

## G. Agent/harness integration

**Same declared plan, three dispatch policies** (FIXTURE, `parsec.py actions-bench`,
one agent, 0.3 s injected tool latency, 5 trials). Plan: OCR(original) ∥
Grounding(original, "sign") → Zoom(box 0) → OCR(crop).

| Dispatch | Tool span (mean ± sd) | Speedup | Overlapping tool pairs | Answer |
|---|---:|---:|---:|---|
| E0 | 1.305 ± 0.007 s | 1.00 | 0 | EXIT 42 |
| E1 | 1.005 ± 0.003 s | 1.30 | 1 | EXIT 42 |
| E2 | 1.000 ± 0.006 s | 1.31 | 1 | EXIT 42 |

E2 trace (seconds from the first tool start; real capability execution intervals):
grounding 0.000–0.382 ∥ OCR(original) 0.001–0.332 → Zoom 0.385–0.694 → OCR(crop)
0.696–0.998. The crop OCR reads `tool_generated_image_2` (the Zoom output), never the
original; observations reach the model in the fixed commit order, identical under E0
and E2 (tested).

**Speculative fallback in a whole run** (FIXTURE, E4, 1 worker; worker_01 events):

```text
event time  event                         detail
0.000  TOOL_CALL_REQUESTED  Execute_Action_Plan   primary: OCR(original); alt1: ground → zoom → OCR(crop)
0.001  PLAN_SELECTED                              speculation S1, chosen [alt1]
0.002  TOOL_CALL_REQUESTED  OCR_Tool              primary OCR (necessary)
0.004  SPECULATIVE_TASK_ADMITTED                  alt1 grounding (speculative; starts at once, overlapping the OCR)
0.223  OCR finished: no readable text → REPLAN_TRIGGERED → REPLAN_COMPLETED next=alt1 (was speculative)
0.226  SPECULATIVE_RESULT_ADOPTED                 grounding still running, continues as necessary work
0.289  TOOL_CALL_COMPLETED  Visual_Grounding_Tool
0.290  TOOL_CALL_REQUESTED  Zoom_In_Tool          coords bound from the grounding box: [62, 100, 314, 278]
0.508  TOOL_CALL_REQUESTED  OCR_Tool              image_id tool_generated_image_2 (the crop)
0.716  TOOL_CALL_COMPLETED  OCR_Tool              "EXIT 42"
0.718  TOOL_CALL_COMPLETED  Execute_Action_Plan
```
Scheduler intervals (scheduler clock): OCR(original) 0.018–0.239 on slot 0, grounding
(speculative) 0.021–0.302 on slot 1 — the two overlap; Zoom 0.307–0.519; OCR(crop)
0.526–0.730.

**Whole multi-agent runs** (FIXTURE, `parsec.py agents-bench`, fallback plan whose
primary always fails on this scene, 0.2 s tool latency, 3 trials; OFF/E2 use the
legacy one-call protocol with the same four tools):

| Workers | OFF | E2 | E3 | E4 | E5 |
|---:|---:|---:|---:|---:|---:|
| 1 | 0.965 | 1.044 | 1.319 | **0.824** | 1.143 |
| 2 | 1.268 | 1.345 | 1.600 | **1.082** | 1.437 |
| 3 | 1.508 | 1.587 | 1.888 | **1.441** | 1.755 |
| 4 | **1.709** | 1.853 | 2.095 | 1.727 | 2.068 |

Run wall time in seconds (sd ≤ 0.16 s). Every run: status COMPLETED, answer "EXIT 42",
4 tool calls per worker, budget respected. E4 speculates one branch per worker (adopted
every time here). E3/E5 include ~0.25 s of planning-pool start-up per run (measured in
`PLANNING_CONFIGURED`) plus 24–541 ms of Monte Carlo per run (growing with N: the
workers share 4 planning processes). **E4 beats the original runtime by 15% for one
worker; the gain disappears at four workers (shared CPU pool and capacity), and E3/E5
are slower than the original in every configuration** — a cold planning pool and
Monte Carlo time cannot be recovered on 0.2 s tool calls.

## H. Real-model validation (REAL)

| Run | Mode | Model requests | Tool calls | Plans proposed | Wall | Answer (reference 38) |
|---|---|---:|---:|---:|---:|---|
| `real_row25_e2` | E2 (legacy protocol) | 15 | 8 | — | 43.0 s | 46 |
| `real_row25_e5` | E5 (plan tool offered) | 13 | 6 | 0 | 19.6 s | 46 |
| `real_row25_e5_prompted` | E5 + plan prompt note | 12 | 5 | 0 | 20.2 s | 46 |

The real model did not use the plan protocol on this task, so E5 executed exactly like
E2 (planning pool started, never used). Wall-time differences come from different
trajectories (the E2 run called the coding tool three times), not from scheduling. Real
plan generation is therefore **not demonstrated**; the deterministic plan path is.

## I. Tests

* New Phase 2 tests (`tests/parsec_vl/`): `test_plans.py` 18, `test_montecarlo.py` 9,
  `test_speculation.py` 15, `test_plan_harness.py` 34 (76 in total) — plan schema/validation/
  provenance/limits/heuristic; identical estimates for 0/1/2/4 processes, real worker
  PIDs, seeds, time budget, crash recovery; S0/S1/S2, adoption without re-execution,
  pending refund vs running cancel-request, non-refundable completed work, unsafe
  tools, speculative/global budget, necessary-first ordering and reserved capacity,
  bounded replanning, backend failure, concurrent agents, process-pool use, planning
  failure fallback, memory isolation and adoption with real capabilities; default
  protocol unchanged, opt-in, real overlap, dependency waits, identical observations
  under E0/E2, invalid plans, N = 1–4 × OFF/E2/E3/E4/E5, memory/peer switches, tight
  budget, worker failure, real planning processes in a run, Studio replay, references
  never reaching planning, request/complete event pairing.
* Phase 1 scheduler tests: unchanged and passing (54).
* Full retained suite: `pytest tests` → **823 passed, 0 failed, 0 errors** (747 at the end of
  Phase 1 + 76 new); lint as in CI (`ruff --select E9,F63,F7,F82`) clean. No new failures;
  no test was removed or weakened.

## J. Changed files

Added: `openvlharness/parsec_vl/{plans,montecarlo,controller,fixture,experiments}.py`,
`tests/parsec_vl/{test_plans,test_montecarlo,test_speculation,test_plan_harness}.py`,
`docs/PHASE2_RESULTS.md`.
Modified: `openvlharness/parsec_vl/scheduler.py` (speculative ordering/limits/reserve,
`on_finish` hook), `openvlharness/parsec_vl/harness.py` (plan runtime/controller, plan
call routing), `openvlharness/agent/agent.py` (decision protocol, plan call),
`openvlharness/multi_agent/{config,orchestrator,run}.py` (e3–e5, planning block, pool
lifecycle), `openvlharness/studio/schema.py` (compiled validator),
`openvlharness/studio/static/story.js` (planning events stay technical),
`scripts/parsec.py` (plan-bench, spec-bench, actions-bench, agents-bench,
outcome-model), `scripts/run_custom_inference.sh` (`-s e3|e4|e5`,
`--planning-processes`), `docs/{ARCHITECTURE,REPRODUCIBILITY,PHASE1_RESULTS}.md`, `README.md`.

## K. Reproduction

See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) §7.

## L. Phase 3 handoff

1. **Configuration.** `execution.scheduler.policy: off|e0|e1|e2|e3|e4|e5`;
   `execution.planning: {candidate_plan_limit, max_plan_depth, beam_width,
   planning_processes, rollouts, planning_time_budget, max_speculative_branches,
   speculative_budget_limit, random_seed, latency_weight, cost_weight, max_replans,
   heuristic_alternatives, outcome_model}`. CLI: `--tool-scheduler e0…e5`,
   `--scheduler-workers`, `--planning-processes` (multi-agent CLI, dataset runner,
   `run_custom_inference.sh -s`). API: `PlanExecutor(scheduler, runtime,
   PlanningConfig.for_mode("e5"), agent_id=…, evaluator=PlanEvaluator(p), model=…,
   budget=…)`.
2. **Plan schema.** `ActionPlan{plan_id, origin_agent_id, origin_type, parent_plan_id,
   objective, rationale, input_artifact_refs, status, estimates, branches[Branch{
   branch_id, name, goal, origin_type, status, pruning_reason, speculation_safe,
   actions[PlanAction{id, tool, arguments, depends_on, expect}]}]}`
   (`ActionPlan.to_dict()`, in `PLAN_CANDIDATES_GENERATED`).
3. **Branch/speculation records.** `PlanExecutor.execute` report: `{plan_id, mode,
   speculation_policy, satisfied, winning_branch, decision_latency_s, planning{wall,
   cpu, evaluations}, decision{selection, speculation terms}, replans, branches,
   tasks[{task_id, branch, action_id, tool, speculative, status, start, finish,
   budget_used}], speculative_tool_calls}`; stored per worker in
   `final_result.json["planning"]`.
4. **Planner metrics.** `PLAN_EVALUATION_COMPLETED{estimates[candidate, rollouts,
   latency_mean/sd/p90, cost_mean, p_operational, wasted_calls_mean,
   wasted_seconds_mean], wall_seconds, cpu_seconds, processes, batches,
   batches_done, outcome_model}`.
5. **Event mapping.** Planned task = `TOOL_CALL_REQUESTED` (with `plan_id`,
   `branch_id`, `action_id`) or `SPECULATIVE_TASK_ADMITTED`; dispatched =
   `SCHEDULER_TASK_STARTED` / `SPECULATIVE_TASK_STARTED` / `TOOL_CALL_STARTED`;
   completed = `SCHEDULER_TASK_FINISHED` + `TOOL_CALL_COMPLETED` (committed) /
   `SPECULATIVE_TASK_COMPLETED`; cancelled = `SPECULATIVE_TASK_PRUNED` (refunded) /
   `SPECULATIVE_TASK_CANCEL_REQUESTED` (`backend_cancelled: false`, charged);
   adopted = `SPECULATIVE_RESULT_ADOPTED` + `adopted_from_speculation: true`.
6. **Resource intervals.** `SCHEDULER_TASK_FINISHED` payload: `task_id, agent_id,
   operation, resource_pool, worker_id, enqueue_time, reserved_time, start_time,
   finish_time, start_wall, finish_wall, status, budget_used,
   metadata{plan_id, branch_id, action_id, logical_request_id, speculative}` — enough
   for a worker-slot/pool Gantt chart, the execution DAG, and speculative overlays.
7. **Benchmark outputs.** `outputs/parsec_vl/phase2/{planning,speculation,actions,agents,
   harness_after_event_fix,real_runs}/` (JSON + Markdown), Phase 1 under
   `outputs/parsec_vl/{bench,scaling,probe,profile,harness}`.
8. **Validated fixtures.** `parsec_vl/fixture.py` (sign task: `PARALLEL_PLAN`,
   `FALLBACK_PLAN`, `run_plan_fixture`), `multi_agent/visual_fixture.py`,
   `parsec_vl/workloads.py`, `experiments.SCENARIOS`.
9. **Real data available.** FSC147_val (counting; 1,286 rows) only. No prepared
   text/OCR dataset, so real OCR outcome rates are unknown.
10. **Limitations.** Real model did not produce plans; outcome model has no real OCR
    data; planning-pool cold start (~0.25 s) is paid per run; E3/E5 lose to the
    original runtime on short tool calls; S2 is only as good as its estimates;
    running GPU calls cannot be cancelled; no in-flight deduplication (side-effect
    and cache-identity guarantees were not established, so it stays off).
11. **Visualization recommendations.** One Gantt chart of `SCHEDULER_TASK_FINISHED`
    intervals per worker slot, coloured by pool, hatched when speculative, greyed when
    discarded; a plan tree from `PLAN_CANDIDATES_GENERATED` with branch status and
    `PLAN_SELECTED` decision terms; budget over time from `BUDGET_UPDATED`; a
    side-by-side OFF/E0–E5 panel from the benchmark JSON; label every number
    REAL/FIXTURE/SYNTHETIC.
