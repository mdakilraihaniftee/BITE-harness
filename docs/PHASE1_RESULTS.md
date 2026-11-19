# PARSEC-VL Phase 1 results

Repository simplification, runtime profiling, and dependency-aware parallel
execution (E0–E2). Every number below was measured on this machine (8 CPU cores,
4× NVIDIA L40S, Python 3.11) and is labelled **REAL** (live model/tool services),
**RECORDED** (earlier real runs, re-analysed from their event logs), **FIXTURE**
(whole multi-agent runs with a scripted model and local tool transports), or
**SYNTHETIC** (scheduler workloads whose tasks sleep for declared durations).
Raw data: `outputs/parsec_vl/` (commands in [REPRODUCIBILITY.md](REPRODUCIBILITY.md)).

## A. Initial state

| | |
|---|---|
| Branch / commit | `proj654` @ `9f571f6` (clean working tree) |
| Tracked files | 785 (440 Python files, 90,991 Python lines; 88 scripts, 233 docs, 82 test files) |
| Capabilities | single-agent `MainAgent`; multi-agent coordinator + 1–4 workers (threads), communication bus, per-actor/global budgets, private memory; Investigation Studio (live/replay); `evaluation_kit`; BITE research pipelines |
| Test baseline | `pytest tests`: **1007 passed, 67 failed, 55 errors**. All 122 failures/errors are in `tests/bite_calibration` and `tests/bite_collection` and are `FileNotFoundError` on frozen artifacts under `outputs/bite/` that do not exist on this machine (pre-existing; nothing fabricated) |

## B. Repository cleanup

Archived (copied with SHA-256 verification to `../BITE-harness-legacy-archive/`,
then removed from the working tree; also in git history). Dependency checks used
`git grep` over imports, scripts, configs, docs, tests, Studio assets, and
`pyproject.toml`; see [LEGACY_ARCHIVE.md](LEGACY_ARCHIVE.md) for the per-path table.

| Original path | Files | Action | Reason | Dependency check |
|---|---:|---|---|---|
| `docs/bite/` | 114 | archive | BITE phase reports, protocols, schemas | referenced only by BITE scripts/tests/README sections |
| `scripts/bite/` | 65 | archive | BITE experiment CLIs | standalone; no importers |
| `evaluation_kit/bite_calibration/` | 71 | archive | calibration research pipeline | imported only by `scripts/bite`, its tests |
| `evaluation_kit/bite_collection/` | 25 | archive | evidence-collection executor | imported only by `scripts/bite`, its tests |
| `tests/bite_calibration/`, `tests/bite_collection/` | 15 | archive with their code | test the archived pipelines; source of all 122 baseline failures | — |
| `visualization/` | 13 | archive | separate demo app from another course | not imported anywhere |
| `docs/STUDIO_STORY_REPORT.md`, `docs/STUDIO_V3_VALIDATION.md`, `docs/images/studio_story*/` | 38 | archive | superseded development reports + their screenshots | links updated |
| `scripts/run_studio_inferences.sh` | 1 | remove (archived copy) | superseded by `run_custom_inference.sh` | references updated |
| `README.md` (BITE) | 1 | archived copy; rewritten | PARSEC-VL README; harness instructions moved to `docs/HARNESS_GUIDE.md` | — |
| `bite-eval` console script | — | removed | duplicate alias of `openvlharness-eval` | no callers except old README |

**Kept on purpose:** `openvlharness/bite/` (opt-in, off-by-default evidence observer
wired into `MainAgent` and `BaseCapability`; removing it means editing the core loop
for no gain) and `tests/bite/`; `evaluation_kit` core; `validation/`; all Studio
assets in use. **Untouched:** `outputs/` (ignored; raw results and run records),
`data/`.

| | Before | After |
|---|---:|---|
| Files (tracked + new) | 785 | 460 |
| Python files / lines | 440 / 90,991 | 271 / 64,290 (includes +2,737 lines of new scheduler code, tests, CLI) |
| `scripts/` | 88 | 23 |
| `docs/` | 233 | 85 (6 Markdown docs + images) |
| Entry points | 6 launch scripts with overlapping roles, `bite-eval`/`openvlharness-eval` aliases | one Phase 1 CLI `scripts/parsec.py` (bench / probe / profile / harness), one task launcher `run_custom_inference.sh`, `openvlharness-eval` |

Tests after cleanup: the suites that remain are unchanged and pass (section G).
The archived suites held about 436 tests (derived: 1129 test outcomes at baseline −
693 tests collected now from the remaining pre-existing suites), 122 of which failed
or errored at baseline. No test of kept code was removed.

## C. Execution architecture (traced)

See [ARCHITECTURE.md](ARCHITECTURE.md) §1. The facts that matter for parallelism:

1. **Workers already run concurrently** (threads, `concurrent` mode), but
   `configs/multi_agent.yaml` caps `max_concurrent_workers` at **2**, so 3–4-worker
   runs execute two workers at a time.
2. **Inside one agent everything is sequential**, and the paper protocol rejects
   more than one tool call per model message (`ModelAdapter.parse`). In 90 recorded
   real tool turns, **0** contained more than one call.
3. Model requests from all agents share one vLLM endpoint; GPU tools are separate
   HTTP services behind one tool server.
4. Budgets: one atomic `BudgetManager`; a reservation is a non-refundable charge.

## D. Profiling

### D1. Recorded real runs (RECORDED, 19 runs, `python scripts/parsec.py profile`)

| Quantity | Value |
|---|---|
| Model request latency (mean of run means) | 2.64 s |
| Tool latency by tool | Visual Grounding (SAM 3) 1.34 s, Zoom 0.07 s, Python coding agent 52.2 s (one run; LLM generation) |
| Model busy time / run wall time (mean) | 0.95 (overlapping requests of different agents count twice) |
| Tool busy time / run wall time (mean) | 0.26 |
| Peak concurrent tool calls / model requests | 2 / 2 (never more, also with 4 workers: the concurrency cap) |
| Multi-call model turns | 0 of 90 |
| Available parallelism T1/T∞ (current structure) | 1.0 (1 worker) to 2.39 (4 workers, row 25) |

T1 = summed model+tool durations; T∞ = longest path when each agent is a chain
(model → tool → model …) and orchestrator phase changes are barriers. These are
fixed-workload numbers for the recorded trajectories, not bounds for adaptive runs.
**Dominant latency: model requests.** Tool scheduling cannot shorten them.

### D2. Real tool-service concurrency (REAL, `python scripts/parsec.py probe`, 8 requests per level)

| Tool (pool) | c=1 median latency | Throughput c=2 / c=4 vs c=1 | Verdict |
|---|---:|---:|---|
| Visual Grounding, SAM 3 (`service:…:8086`) | 0.93 s | 1.08× / 1.08× | serial GPU service: capacity 1 is right |
| Depth (`service:…:8087`) | 0.34 s | 1.22× / 1.26× | little gain |
| OCR (`service:…:8085`) | 0.23 s | 1.69× / 2.79× | scales; capacity 4 would be safe |
| Zoom (`cpu`, in the tool server) | 0.064 s | 1.75× / 2.46× | scales |

No failures at any level. Defaults stay at capacity 1 per GPU service
(`execution.scheduler.service_capacity`, overridable per pool).

### D3. One real multi-agent run through the scheduler (REAL, FSC-147 row 25, 2 workers, E1)

Completed, final answer 46 (reference 38; earlier recorded runs of this row also
answered 46). 11 tool calls, all through the scheduler (6 SAM 3, 3 coding agent,
2 Zoom); 18 model requests; run wall 66.9 s (this trajectory called the coding agent
three times, ~10 s each; wall time is not comparable across stochastic runs).

* Real contention handled: at t = 4.5 s both workers requested SAM 3; worker 1
  queued **0.87 s** behind worker 2 (pool capacity 1). Per D2, running them together
  would have given ~1.08× throughput while doubling each call's latency.
* Overhead: median request→start **44.6 ms** with the scheduler vs **12.2 ms** mean in
  the 19 recorded runs without it (+~30 ms per call, ~3% of a SAM 3 call). Ready→start
  inside the scheduler: 19.5 ms median, of which ~4 ms is the budget event write
  (measured: `BudgetManager.reserve` with the event log costs 3.9 ms).

### D4. Whole multi-agent runs, scheduler off vs E0–E2 (FIXTURE, `python scripts/parsec.py harness`, 5 trials)

> **Phase 2 correction.** Most of the E1/E2 overhead below came from the event log, not
> the scheduler: `jsonschema.validate()` re-checked the event schema on every event
> (~4 ms each, 97% of `EventLog.emit`), and the scheduler path emits a few more events
> per call, under GIL contention. Phase 2 compiles the validator once (0.1 ms per event).
> Re-measured numbers: [PHASE2_RESULTS.md](PHASE2_RESULTS.md) §A.

Two workers, deterministic visual fixture (scripted model, real Zoom/grounding
capabilities on local transports with a 0.5 s injected delay; the grounding detector
is CPU-bound Python).

| Scheduler | Run wall s (mean ± sd) | Answer | Peak concurrent tool calls | Request→start mean |
|---|---:|---|---:|---:|
| off (original runtime) | 3.405 ± 0.081 | 6 | 2 | 12.2 ms |
| E0 | 4.766 ± 0.035 | 6 | 1 | 299.2 ms |
| E1 | 4.312 ± 0.210 | 6 | 2 | 50.4 ms |
| E2 | 4.297 ± 0.194 | 6 | 2 | 48.0 ms |

**Negative result.** With one call per turn there is nothing to overlap that the
worker threads were not already overlapping, so E1/E2 cannot beat the original
runtime here. They are **~26% slower** in this fixture: ~40 ms of extra hand-off per
call, plus slower CPU-bound fixture tools (grounding 0.67 s vs 0.57 s) because the
scheduler's threads and event writes compete for the GIL. E0 serializes the two
workers (the sequential reference). Logical results were identical in every trial.
What the scheduler does add in real runs is resource protection (D3), budget-safe
admission, and per-task telemetry. Speedups must come from more independent work per
decision (Phase 2 planning/speculation, several calls per turn).

## E. Scheduler implementation

See [ARCHITECTURE.md](ARCHITECTURE.md) §2: task model and validated lifecycle, DAG
validation (duplicates, missing dependencies, cycles), ready queue ordered by
policy, worker slots (threads), typed resource pools, budget reservation through
the existing ledger (`BudgetManager.reserve`/`release`), failure/timeout/cancel
propagation, inline admission plus a dispatcher thread for deadlines, and harness
integration that preserves call order and memory semantics. E0/E1/E2 differ only
in slot count and ready-queue order.

## F. Controlled benchmarks (SYNTHETIC, `python scripts/parsec.py bench`, 5 trials each)

Speedup = E0 makespan / makespan; efficiency = speedup / workers; T_LB = max(critical
path, Σ work per pool / capacity, T1 / workers) from durations measured in the E0
runs. Standard deviations are ≤ 0.001 s unless shown. E0 rows: A 1.606 s, B 0.806 s,
C 2.008 s, D 1.508 s, M 2.008 s, V 1.798 s, X 0.113 s (1 worker; E1/E2 with 1 worker
are within 0.005 s of E0 except X).

| Workload | Policy | Workers | Makespan s | Speedup | Efficiency | Peak conc. | T_LB s | Obs/T_LB | Budget used |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A independent (8 × 0.2 s) | E1 | 2 | 0.803 | 2.00 | 1.00 | 2 | 0.801 | 1.003 | 8 |
| | E1 | 4 | 0.404 | 3.97 | 0.99 | 4 | 0.400 | 1.008 | 8 |
| | E1 | 8 | 0.205 | 7.83 | 0.98 | 8 | 0.200 | 1.024 | 8 |
| | E2 | 8 | 0.205 | 7.82 | 0.98 | 8 | 0.200 | 1.025 | 8 |
| B chain (8 × 0.1 s) | E1 | 8 | 0.804 | 1.00 | 0.12 | 1 | 0.801 | 1.004 | 8 |
| | E2 | 8 | 0.805 | 1.00 | 0.12 | 1 | 0.801 | 1.004 | 8 |
| C mixed (6 short + 4-chain) | E1 | 2 | 1.403 | 1.43 | 0.71 | 2 | 1.001 | 1.402 | 10 |
| | E2 | 2 | **1.003** | **2.00** | 1.00 | 2 | 1.001 | 1.003 | 10 |
| | E1 | 4 | 1.004 | 2.00 | 0.50 | 4 | 0.801 | 1.254 | 10 |
| | E2 | 4 | **0.802** | **2.50** | 0.62 | 4 | 0.801 | 1.002 | 10 |
| | E1 | 8 | 0.806 | 2.49 | 0.31 | 7 | 0.801 | 1.006 | 10 |
| D contention (6 GPU cap-1 + 4 CPU) | E1 | 2 | 0.903 | 1.67 | 0.83 | 2 | 0.901 | 1.002 | 10 |
| | E1 | 8 | 0.904 | 1.67 | 0.21 | 5 | 0.901 | 1.003 | 10 |
| M wrong estimates | E1 | 2 | **1.204** | 1.67 | 0.83 | 2 | 1.001 | 1.203 | 10 |
| | E2 | 2 | 1.404 | 1.43 | 0.71 | 2 | 1.001 | 1.402 | 10 |
| | E1 | 4 | **0.805** | 2.49 | 0.62 | 4 | 0.801 | 1.005 | 10 |
| | E2 | 4 | 1.004 | 2.00 | 0.50 | 4 | 0.801 | 1.254 | 10 |
| V visual pipeline (measured latencies) | E1 | 2 | 1.226 | 1.47 | 0.73 | 2 | 1.225 | 1.001 | 5 |
| | E2 | 4 | 1.226 | 1.47 | 0.37 | 3 | 1.225 | 1.001 | 5 |
| X CPU-bound Python | E1 | 2 | 0.206 ± 0.019 | **0.53** | 0.26 | 2 | 0.054 | 3.80 | 8 |
| | E1 | 8 | 0.254 ± 0.015 | **0.43** | 0.05 | 6 | 0.018 | 14.0 | 8 |

Full table (all policies × 1/2/4/8 workers): `outputs/parsec_vl/bench/bench_summary.md`.

Worker scaling, 32 independent 0.1 s waits (S, E1): p = 1, 2, 4, 8 → makespan
3.215, 1.609, 0.807, 0.407 s; **S(p) = 1.00, 2.00, 3.99, 7.89; E(p) = 1.00, 1.00,
1.00, 0.99** (sd ≤ 0.001 s).

**Interpretation.**
* Independent waiting work scales almost linearly; the gap to T_LB is 2–4 ms of
  dispatch per wave (dispatch latency 0.2–0.8 ms per task, total policy decision
  time < 1 ms per run).
* A serial chain gets no speedup at any width (efficiency falls as 1/p).
* **E2 beats E1 only when the queue order matters:** on C it reaches the bound
  (1.003 s vs 1.403 s at 2 workers). With enough workers (8) both reach it.
* **E2 is worse than E1 when its estimates are wrong** (M: 1.404 vs 1.204 s at 2
  workers, 1.004 vs 0.805 s at 4). Kept as a negative result.
* A capacity-1 pool bounds the speedup (D: 1.67× = 1.5 / 0.9) regardless of workers;
  the GPU pool runs at 99.9% saturation.
* The visual pipeline is bounded by its critical path (grounding 0.93 → crop 0.06 →
  crop OCR 0.23 = 1.225 s); E1 and E2 both hit it (1.47×), and more than 3 workers
  are idle.
* **Threads do not speed up CPU-bound Python**: 0.41–0.54× (slower), up to 14× above
  the ideal bound. CPU-parallel planning (Phase 2) needs processes.

## G. Correctness verification

`pytest tests/parsec_vl` (54 tests): DAG validity, cycles, missing/duplicate IDs,
transitions; E0 order and no overlap; **measured overlap** of two independent
operations (intervals intersect, peak 2, makespan < 0.55 s for two 0.3 s tasks,
different worker slots); E2 critical-path order; dependent tasks start after the
prerequisite's finish and see only its published result; resource capacity (no two
capacity-1 tasks overlap); each body runs exactly once (40 tasks, 6 workers);
failure isolation and skip propagation; timeout (waiters released at the deadline,
late result discarded); shutdown and cancel-before-dispatch release reservations;
15 random DAGs × 3 policies with injected failures and budget limits always
terminate, respect dependencies, and never overspend; concurrent submissions from
four agent threads; telemetry fields. Budget: 16 threads racing for the last unit →
exactly one grant (20 repetitions); actor and global limits under stress; release
accounting; spent + reserved ≤ total sampled during execution; failed calls charged.
Harness: real `MainAgent` + real Zoom capability, three same-turn calls overlap
(peak 3) and produce **identical** registry IDs, consumed images, canonical results,
and model history to the sequential path; a call that uses an earlier call's output
waits for it (complete-before-consume, including the single-image fallback);
memory-reading tools run alone; budget denial uses the run's ledger; two agents
sharing one scheduler get exactly their own outputs. Orchestrator: E0/E1/E2 runs
match the original runtime's logical outputs and answer; budgets.json consistent;
scheduler telemetry correlates with Studio tool events; the Studio replays a
scheduled run; the default stays `off`.

Overlap evidence (SYNTHETIC visual pipeline, E1, 4 workers, one trial; seconds
from scheduler start):

| Task | Pool | Slot | Ready | Start | Finish | Depends on |
|---|---|---:|---:|---:|---:|---|
| grounding | service:sam3 | 0 | 0.001 | 0.001 | 0.932 | — |
| ocr | service:ocr | 1 | 0.001 | 0.002 | 0.232 | — |
| depth | service:depth | 2 | 0.001 | 0.003 | 0.343 | — |
| crop | cpu | 0 | 0.932 | 0.932 | 0.996 | grounding |
| crop_ocr | service:ocr | 0 | 0.996 | 0.996 | 1.226 | crop |

Full suite after Phase 1: `pytest tests` → **747 passed, 0 failed, 0 errors**
(451 subtests; 693 pre-existing tests in the kept suites + 54 new). Lint as in CI
(`ruff --select E9,F63,F7,F82`): clean. One test needed a fix during the work
(`tests/test_examples.py` requires the README to link the example configs; the new
README links them).

## H. Limitations

* The protocol's one-call-per-message rule leaves no intra-agent parallelism in real
  runs; the opt-in `allow_multiple_tool_calls` changes the agent protocol and was used
  only in tests.
* The scheduler adds ~30–50 ms per tool call and, in CPU-heavy fixtures, GIL
  contention; it did not shorten whole multi-agent runs (D4).
* Only one real scheduled run was made (authorization scope); real makespan effects
  are not established.
* The `max_concurrent_workers: 2` cap in `configs/multi_agent.yaml` limits existing
  cross-agent concurrency; it was reported, not changed.
* E2 depends on duration estimates (online per-tool means in the harness); wrong
  estimates hurt (M).
* No deduplication of identical calls: logical requests and physical invocations are
  counted separately, but in-flight sharing is deferred (no safe side-effect metadata
  yet).
