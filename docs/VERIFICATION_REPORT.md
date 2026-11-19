# Independent PARSEC-VL verification — 19 November 2026

**Offline implementation checks pass. Historical numerical verification is
partial because some original per-trial records were not retained. The advisor
demonstration is ready with the limitations below. After explicit user approval,
a real two-worker Qwen example also completed in a subsequent follow-up; its
answer was incorrect against the official annotation.**

This audit inspected source, reproduced failures before fixing them, reran the
retained tests and controlled benchmarks, recomputed stored measurements, and
used actual Chrome sessions. Historical tables were not treated as new results.
The initial audit performed no commits, pushes, resets, archived-code restoration,
model downloads, new real inference, or GPU stress tests. The authorized real-run
follow-up is recorded below. Existing unrelated edits were preserved.

## Authorized real-run follow-up — 15:00 UTC

The user explicitly approved starting missing GPU services and executing one real
example. The previously selected row-7 run was a historical failed recording,
with no worker activity because Qwen had refused its first model request. A new
saved Qwen startup log showed successful startup in about 32 seconds, followed by
an unrecorded stop; its exit cause cannot be established from that log.

The new `--start-services` option starts missing local services in detached
processes, reuses healthy instances, waits for readiness, and only then starts a
fresh task and selects it in Studio. Occupied ports are not replaced. Logs and
timeouts make service startup failures visible. Newly started Qwen uses a 32k
demo context. `--ui-only` remains available without GPU/model use. The Studio now
labels completed/failed recordings accurately instead of calling them live streams.

Verified run: `outputs/multi_agent/verified_fsc147_val_row25_w2_memon_peeroff_schede2_20261119_145759/`.
It completed at 14:58:14 UTC with **95 events, two completed workers, two completed
Visual Grounding calls, nine model requests, four messages, and no failed events**.
The final answer was **46**, while the official FSC147 annotation is **38**
(absolute error **8**). E2 recorded both tool tasks, but grounding capacity one
serialized their execution; peak tool concurrency was one. This run establishes
working real execution and visualization, not improved counting accuracy or
parallel tool speedup.

All required services passed readiness and remained running after the startup
helper exited. The Studio suite passed **100 tests in 17.72 seconds**, including
new startup/reuse/timeout/failed-process checks and six Node terminal-label cases.
Bash syntax, JavaScript syntax and fatal Python lint checks passed. The complete
retained suite and six-suite browser matrix were not repeated for this follow-up.
Actual headless Chrome verified the new real run, both worker answers, evidence,
the scheduler timeline, the old failed-run guidance, and zero browser exceptions.
Evidence: `outputs/services/verified_example25_20261119.log`, service logs with
stamp `20261119T145704Z_1288102`, and
`outputs/setup/verified_example25/{browser_check.json,completed.png}`. Earlier
verification sections below describe the initial offline audit at their original
timestamps; the service-unavailable observations there are historical.

## A. Environment and evidence locations

| Item | Observed state |
|---|---|
| Repository | `/home/ai5377/BITE-harness` |
| Branch / HEAD | `proj654` / `9f571f6e87ca1347c2badd81de68e9a96b5f3a8c` |
| Working tree | Substantially modified before the audit, including the course simplification and previous Studio changes; not reset |
| Python | `.venv/bin/python`, CPython 3.11.2 |
| CPU | 64 logical CPUs visible and 64 in process affinity |
| GPU inventory | Four NVIDIA L40S, 46,068 MiB each; inventory and health queries only |
| Relevant packages | pytest 9.2.0, FastAPI 0.163.1, httpx 0.28.1, NumPy 2.4.6, Pillow 13.0.0, PyYAML 6.0.3, Ruff 0.16.10, Matplotlib 3.11.2, pandas 2.3.3 |
| Dataset input | FSC147 row 0 resolves to `data/images/FSC147/190.jpg`; image exists; label excluded from runtime input |
| Real service readiness | Router, SAM3, OCR, depth healthy; Qwen on port 8222 refuses connections |

All paths below are relative to `outputs/parsec_vl/` and contain ignored local
artifacts that should be preserved separately when sharing the project:

| Evidence | Directory |
|---|---|
| Baseline, reproduced failures, health check, input-only real-task preflight | `verification/audit_20261119_QPtnrU/` |
| Comprehensive independent measurements (set A), historical audit, figures | `verification/20261119T140501Z_hobny8uw/` |
| Successful quick verification | `verification/20261119T141538Z_cn4mjgb1/` |
| Final full verification | `verification/20261119T142036Z_agurvd_n/` |
| Final six-suite browser check and screenshots | `verification/20261119T141700Z_l5nv6uvs/` |
| Bounded advisor demo | `advisor_demo/20261119T140606Z_kbhl8a46/` |
| Fuller advisor demo | `advisor_demo/20261119T142257Z_p_77ft1j/` |

Each verifier execution saves environment/git state, logs, JUnit reports, raw
benchmark JSON, a machine-readable summary, and `SUMMARY.md` in a fresh directory.
No Phase 1–3 measurement files were overwritten.

## B. Automated tests and checks

The final test commands executed inside the verification script were:

| Command | Collected | Passed | Failed / errors | Skipped | Wall duration |
|---|---:|---:|---:|---:|---:|
| `.venv/bin/python -m pytest tests/parsec_vl -q --junitxml=…/parsec_tests.xml` | 141 | 141 | 0 / 0 | 0 | 67.61 s |
| `.venv/bin/python -m pytest tests/studio -q --junitxml=…/studio_tests.xml` | 92 | 92 | 0 / 0 | 0 | 18.87 s |
| `.venv/bin/python -m pytest tests -q --junitxml=…/retained_tests.xml` | 844 | 844 | 0 / 0 | 0 | 111.06 s |

The complete suite additionally passed **451 subtests**, reported separately
from collected tests. The three retained warnings are pandas future warnings in
counting evaluators, not failures. Required evaluation dependencies were present;
no missing-dependency skips explain these numbers.

The untouched pre-audit baseline was **840 passed**, with 451 subtests, in
202.78 s. The earlier reported 834 is not the current baseline: that difference
already existed before this audit. The old report has no per-case collection
manifest from which to reconstruct all six net differences. This audit added
four narrowly scoped pytest cases: two Monte Carlo deadline cases, one rejected
budget-release case, and one offline plan-revalidation case. Two additional Node
story regressions run inside an existing pytest frontend test.

The first verification attempt also found a test-order dependency:
`test_resource_pools_follow_the_backend_server` failed when the PARSEC suite ran
alone, although the full suite passed. The test relied on another test importing
`.env`. It now supplies explicit offline deployment values with `monkeypatch`;
the resource-pool assertions were retained. That first failed verifier summary
was preserved; subsequent targeted and full runs use the correction.

Other required checks:

- Python: `python -m ruff check --select E9,F63,F7,F82 openvlharness evaluation_kit scripts tests` — PASS.
- JavaScript: `node --check` for Studio modules and script `.mjs`/`.cjs` files — PASS.
- Shell entry points: `bash -n` and execution from outside the repository — PASS.
- Quick verification: PASS, with the full retained suite explicitly NOT VERIFIED in that tier.
- Final full verifier: **PASS**, exit 0, all 17 required checks completed successfully.
  The complete retained suite and fresh raw interval/budget/numerical checks ran;
  no required check was silently omitted. The failed first attempt remains in
  its original directory alongside the successful final run.

## C. Scheduler, plan execution, and budget correctness

| Area | Status | Evidence and scope |
|---|---|---|
| DAG validation and readiness | PASS | Cycle/missing/duplicate rejection, ordered publication, ready-queue policies, and measured interval checks |
| Concurrent execution | PASS | Independent OCR/grounding intervals overlap; E0 intervals do not |
| Dependencies | PASS | Zoom begins after grounding finishes; crop OCR begins after Zoom finishes |
| Resource capacities | PASS | Unit tests plus sweeps of raw interval endpoints across every stored/new scheduler trial; capacity-1 pools never exceed one |
| Failure/timeout/cancellation | PASS | Failure propagation, skipped dependents, discarded late results, bounded randomized DAG completion, shutdown and pre-dispatch refunds |
| Atomic reservation and actor limits | PASS | Contending threads, global/per-actor limits, nonnegative remaining budget, and the new rejected-release regression |
| Plan validation | PASS | Unknown tools/images, unsafe tools, schemas, dependency inference, and malformed plans rejected |
| Image provenance and ownership | PASS | Persisted Zoom output registry ID equals crop OCR input ID; image scopes, actual dimensions, run IDs and artifact owner agree |
| Memory publication/isolation | PASS | Sequential and parallel canonical observations match; stable ordered history; speculative branch evidence stays isolated until adoption |

The visual fixture uses the real harness and capabilities, a scripted model,
local pixel detection, the actual image crop implementation, and a declared OCR
rule. It does not use SAM3 or a real OCR model. The artifact/provenance checker
reads persisted events; it does not infer correctness from a printed speedup.
Some dependent plan tasks are submitted only after prerequisites finish, so
their scheduler `dependency_ids` can be empty: the declared plan and actual
tool intervals are checked together rather than fabricating scheduler edges.

## D. Monte Carlo correctness and measured CPU parallelism

**PASS for fixed-workload reproducibility and process execution.** The evaluator
uses `ProcessPoolExecutor` with spawn, CPU-bound discrete-event simulations and
random draws, deterministic rollout-index seeds, fixed batch partitions, and
ordered aggregation. Fresh records include actual worker PIDs, CPU time,
completed batch counts, estimates, warm wall time, cold startup, and total trial
wall time including shutdown. Different process counts use the same six
candidates and 50,000 rollouts each: **300,000 rollouts per trial**.

Existing tests exercise time budgets, process crash recovery, shared/lazy pool
start, and concurrent first use. New regressions proved that the old timeout
aggregation could combine noncontiguous seed batches or give one candidate
samples while another had none. Aggregation now uses only the contiguous
completed prefix shared by every candidate, including a zero-length prefix.
Full-workload estimates remain identical across process counts.

Set A, three trials per process count, seed 654, batch size 500:

| CPU processes | New warm wall s | New speedup vs one process | Historical speedup |
|---:|---:|---:|---:|
| 1 | 8.139 | 1.00× | 1.00× |
| 2 | 4.103 | 1.98× | 1.94× |
| 4 | 2.150 | 3.79× | 3.72× |
| 8 | 1.151 | 7.07× | 6.83× |
| 16 | 0.639 | 12.73× | 12.48× |

The final full verification repeated the same workload and measured
**1.86× / 3.61× / 6.71× / 11.65×** at 2/4/8/16 processes. Both independent
measurement sets are retained; the faster first result is not presented as a
guarantee. Numerical estimates remained identical in the repeat.

These are newly measured **SYNTHETIC CPU computations**, not model speedups.
Every fresh fixed-rollout estimate matches. Startup is excluded from warm time
and stored separately for every trial; total wall time is also retained. The
bounded advisor demo measured 1.94× and 3.70× at two/four processes; its fuller
repeat measured 1.86× and 3.61×. Different load/rollout counts change timing;
the demonstration prints its current result rather than hardcoding a gain.

## E. Speculation, contention, and small budgets

**PASS for admission, branch isolation, pruning, adoption, cancellation,
non-refundable dispatched work and budget protection.** New experiment files
retain each trial's outcome draws, physical scheduler records, ledger snapshot,
latency, calls, waste, and completion. Means were recomputed from those records.
The same draws are checked across policies; calls must equal dispatches and
the ledger charge. No new trial exceeded its configured budget.

Representative set A results, ten paired trials per policy (SYNTHETIC):

| Scenario | No speculation | Fixed speculation K=1 | Observation |
|---|---|---|---|
| Alternative frequently needed | 0.392 s, 3.4 calls | 0.297 s, 3.6 calls | About 24% lower decision latency |
| Alternative rarely needed | 0.121 s, 1.0 call | 0.121 s, 2.1 calls | 110% more calls without meaningful latency improvement |
| Capacity-1 simulated GPU pool | 0.483 s, 4.5 calls | 0.473 s, 6.0 calls | Small latency difference, 1.5 unused calls per decision |
| Small budget, B=4 | 40% completion | 40% completion | K=2 fell to 30%; unused dispatched work remained charged |

These samples differ from the historical 30-trial sample, so the original 20%
latency reduction and 75% extra calls were not copied as new measurements.
Completion here is a declared operational goal, not answer accuracy. Selective
S2 avoided waste in the rarely-needed case but paid planning overhead. The full
budget sweep covered B=3,4,5,8,12. The overhead and contention variants were also
independently rerun under set A; no new GPU workload was launched.

## F. Investigation Studio and browser verification

| Browser suite | Previous reported | New result |
|---|---:|---:|
| PARSEC | 55/55 | **55/55** |
| Simple team | 59/59 | **59/59** |
| Story | 29/29 | **29/29** |
| Visual evidence | 36/36 | **36/36** |
| Matrix | 88/88 | **92/92** |
| Original Studio | 62/62 | **64/64** |

Counts depend on optional legacy/server inputs and added automatic-session
coverage; the current checks and exact inputs are saved with every report.
No assertions were removed simply to reproduce the earlier totals.

Verified in actual Chrome: coordinator/worker cards, Gantt bars matching recorded
intervals, independent overlap and later dependencies, pool capacity lanes,
declared plan DAG, actual crop evidence, adoption/pruning, budget/resources,
labelled historical comparisons, live incremental events, prefix-safe replay,
both themes, responsive layout, and no unexpected browser exceptions.

The visual chain suite measures overlays in the displayed image's natural pixel
coordinates: the crop is 202×170 rather than 640×400; crop-local boxes and their
transformed original-image boxes are checked separately. Metadata-poor counting
mocks intentionally lack an input image/transform record. The viewer must show
their actual 150×150 crop and explicitly mark geometry unverified, with no
invented overlay. An old matrix assertion read a hidden legacy panel; it was
replaced with those stronger checks of the visible evidence workspace.

Viewer authentication remains enabled on run, artifact, memory and stream APIs.
The UI has no token controls: launch links sign in automatically using HttpOnly,
SameSite cookies. Tests verify reloads without browser-storage credentials,
rejection of unauthenticated API calls, viewer-only evaluator scope, server
restart isolation, and single-use tickets in fresh browsers. No viewer tokens
are placed in this report or screenshot filenames.

## G. Historical arithmetic and presentation audit

- **Scheduler:** means/trial counts, dependency intervals, capacity, budget,
  speedup and efficiency recomputed from Phase 1/3 raw trials. The historical
  eight-worker scaling result is **7.902540777×**, efficiency **0.987817597**.
  Set A reran at **7.888×**; serial chains stayed approximately 1.00×. On the
  two-worker mixed DAG, E2 was 1.004 s versus FIFO's 1.404 s.
- **Same visual plan:** historical E0/E1 aggregate ratio is consistent with
  1.31×. The one stored trace per policy shows the expected overlap/dependencies,
  but five-trial means cannot be reconstructed from only those traces. New set A
  retained three full provenance traces per dispatch: **1.325 s sequential,
  1.011 s parallel, 1.31×**. Canonical tool observations agree.
  The final verification repeat measured **1.351 s / 1.008 s, 1.34×**, with
  three trials each; raw spans retain the timing variability rather than
  treating the equal-delay idealisation as an exact limit on these measurements.
- **Whole harness:** historical whole/overhead/contention row means were
  independently reconstructed from persisted event timestamps and trial counts.
  Four-worker set A, 0.2 s injected tool delay, three trials:

  | Mode | Historical wall s (five trials) | New wall s |
  |---|---:|---:|
  | OFF | 1.777 | 1.801 |
  | E0 | 4.048 | 3.980 |
  | E1 | 1.862 | 1.797 |
  | E2 | 1.852 | 1.839 |
  | E3 | 1.855 | 1.793 |
  | E4 | 1.737 | 1.739 |
  | E5 | 2.008 | 1.927 |

  OFF–E2 and E3–E5 use different decision protocols. This is a whole-run fixture
  comparison, not an identical-work real-model speedup claim.
- **Historical Monte Carlo:** ratios recompute to 1.942/3.722/6.827/12.480×.
  Original individual timings, worker PIDs and estimates per process count were
  not saved, so the old means/identity assertions are **NOT INDEPENDENTLY
  VERIFIABLE from the stored aggregate file alone**. The one historical reference
  estimate vector exactly matches the new independent fixed-workload result.
  New raw trials provide process-by-process evidence.
- **Historical speculation:** aggregate consistency and stated parameters can be
  checked, but original per-trial means/outcomes are **NOT INDEPENDENTLY
  VERIFIABLE**. New runs preserve them. The planning gate's known calibration
  problems were retained, not hidden or tuned away.
- **Recorded real-service probe:** request counts / wall totals reproduce c=4
  versus c=1 throughput: grounding **0.905×**, OCR **3.124×**, depth **1.158×**,
  Zoom **2.560×**. No new service stress test was run; original individual
  latency samples are not stored.
- **Recorded Qwen plans:** offline schema revalidation confirms **0/20** natural
  first decisions proposed plans, and **10/10** explicitly requested proposals
  validate. Both stored real executions have three raw tool intervals and
  **zero overlapping pairs**. Proposals with independent actions are not proof
  of executed parallel work. No new inference was attempted.
- **Figures:** all eight figures regenerated into a fresh output folder from
  the recorded sources are byte-identical to `docs/figures/`. Axes, units,
  legends and SYNTHETIC/FIXTURE labels were inspected; source selection was
  traced in `parsec_vl/report.py`. This verifies source-to-figure reproduction,
  not missing historical raw means.

## H. Defects and discrepancies found

1. Scheduler events fell through into action-plan story rendering, producing
   fabricated “0 actions / unknown” cards. The scheduler records now remain
   in Technical Trace. Genuine empty plan attempts stay visible.
2. Deadline-limited Monte Carlo aggregated mismatched/noncontiguous seed batches
   and mishandled a zero-common-sample result. Corrected and regression-tested.
3. A failed actor refund could reduce the global ledger before raising an
   exception. Both balances are now validated before either is modified.
4. `plan_probe.py --revalidate` built a complete model agent/tokenizer and
   required deployment variables despite being offline. It now constructs
   capability schemas only; `--recorded` separates read-only input from new output.
5. One PARSEC test depended on `.env` side effects from another suite. Its
   explicit offline fixture makes targeted and complete execution agree.
6. Original browser checks expected removed token fields; matrix evidence checks
   read hidden legacy DOM. Assertions now verify automatic sessions and the
   actual visible crop/provenance. Authentication assertions remain enforced.
7. Recent real-task failures are connection refusals at Qwen's endpoint. Healthy
   tool workers do not make a missing model service usable. Interrupted runs
   can also retain nonterminal persisted states; they were not relabelled or
   used as successful evidence.

## I. Changes made for reliability

- Added `scripts/verify_parsec.sh` and `scripts/advisor_demo.sh`, backed by the
  existing scheduler, fixture, Monte Carlo and experiment implementations through
  `scripts/parsec_audit.py`; no replacement benchmark engine or agent architecture.
- Added `scripts/verify_studio_browser.py` to prepare fresh inputs, run all browser
  suites, preserve provenance/screenshots, and stop its own temporary Studio.
- New Monte Carlo/speculation results retain raw trials, process IDs, timings,
  outcome draws and budget records needed for subsequent independent audits.
- Added the regressions and small fixes listed above; no assertions weakened,
  retained tests deleted, or archived research reintroduced.
- Corrected report seed/batch pseudocode, qualified the equal-delay work/span
  idealisation, corrected the speculation cost headline, and narrowed the blanket
  “GPU services do not scale” statement to the measured SAM3 result. Existing
  historical benchmark numbers were not silently replaced.
- Added [ADVISOR_DEMO.md](ADVISOR_DEMO.md) and linked the current procedures from
  the README and reproduction guide.

## J. Remaining limitations

- No recorded real-Qwen parallel tool-plan execution. The real sample is small;
  the advisor's central parallel plan is scripted.
- Qwen was unavailable during the initial audit. The explicitly authorized
  follow-up above started it and completed one real run; availability is temporal.
- Threaded waiting-task scaling is not CPU-bound multicore speedup; the separate
  process-based Monte Carlo experiment supplies that evidence.
- The planning gate uses fixed, imperfect cost estimates and can be slower than
  a warm pool or simple heuristic. Shared GPU capacity and model-turn latency
  can dominate end-to-end behavior.
- Old action/Monte Carlo/speculation summaries lack some original raw samples.
  The new outputs cannot retroactively prove those original means.
- Missing image-transform metadata remains explicitly unverified, rather than
  inferred from the desired display. A passing finite test set is not a proof
  against every possible concurrency schedule.

## K. Advisor readiness

Follow-up on 19 November, approximately 14:46 UTC: Qwen had no running process,
port 8222 refused connections, and all four host GPUs reported zero memory usage.
The installed serving packages and four cached weight shards were present. There
was no saved Qwen startup log, so the cause of its exit remains unverified. The
custom launcher now opens the saved-run Studio even on a failed service check;
`--ui-only` opens it without requiring a task or model. Readiness checks now reject
HTTP errors. Bash syntax and isolated launcher checks passed for UI-only, failed
services, healthy services, and input-only inspection. An actual UI-only invocation
successfully reused the authenticated Studio on port 8793. No GPU service was
started and no real inference was executed for this follow-up.

**Verification: PARTIAL** for all historical/scientific claims; the missing
original raw samples and unexecuted new real-service experiments are explicitly
identified. Required offline implementation tests pass.

**Advisor demo: READY WITH LIMITATIONS.** The deterministic fixture, real crop
provenance, actual CPU multiprocessing, speculation benefit/waste, and
authenticated live/replay UI work without GPU inference. The optional real-model
demonstration completed once in the authorized follow-up above. Recheck service
health before another run. Follow
[ADVISOR_DEMO.md](ADVISOR_DEMO.md); do not present fixture speedup as real-model speedup.
