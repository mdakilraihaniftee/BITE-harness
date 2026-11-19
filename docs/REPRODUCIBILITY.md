# Reproducing PARSEC-VL (Phases 1–3)

All commands run from the repository root after `source scripts/env.sh`.
Measurements are written to `outputs/parsec_vl/` (ignored by git). Results:
[PHASE1_RESULTS.md](PHASE1_RESULTS.md), [PHASE2_RESULTS.md](PHASE2_RESULTS.md), and the
course report [CISC654_REPORT.md](CISC654_REPORT.md) (Phase 3). §8 is the Phase 3 set.

For current independent checks and a bounded presentation workflow:

```bash
bash scripts/verify_parsec.sh --quick    # targeted tests + offline smoke; fresh output directory
bash scripts/verify_parsec.sh --full     # full retained suite + broader controlled experiments
bash scripts/advisor_demo.sh            # measured fixture / CPU planning / speculation
bash scripts/advisor_demo.sh --studio   # reopen the saved demo, automatic browser sign-in
.venv/bin/python scripts/verify_studio_browser.py  # all six browser suites, no inference
```

See [ADVISOR_DEMO.md](ADVISOR_DEMO.md) and [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md).
The commands below record the historical Phase 1–3 experiment procedure; use new
output directories when rerunning them to preserve those measurements.

## 1. Install

```bash
python -m pip install -e '.[test,server]'      # add ,eval for dataset runs and tests/evaluation
```

Model/tool services, checkpoints, and datasets: [HARNESS_GUIDE.md](HARNESS_GUIDE.md).
Nothing below needs a GPU except §4 and §5.

## 2. Tests

```bash
python -m pytest tests/parsec_vl -q                      # scheduler, budget, harness integration (~1 min)
python -m pytest tests/parsec_vl tests/multi_agent tests/studio tests/test_agent.py -q
python -m pytest tests -q                                 # everything
```

## 3. Controlled scheduler benchmarks (synthetic, CPU only)

```bash
python scripts/parsec.py bench --trials 5                 # workloads A,B,C,D,M,V,X × E0/E1/E2 × 1,2,4,8 workers
python scripts/parsec.py bench --workloads S_scaling --policies e0,e1 --workers 1,2,4,8 \
    --trials 5 --out outputs/parsec_vl/scaling            # worker scaling, 32 equal tasks
```

Outputs: `bench_raw.json` (every trial with per-task intervals), `bench_summary.json`,
`bench_summary.md`. Task bodies sleep for declared durations, so these measure
overlap of waiting work, dependency handling, and capacity limits; they are not GPU
throughput. Speedup is relative to E0 of the same workload; efficiency = speedup /
workers. T1, T∞ and T_LB use the task durations measured in the E0 runs.

## 4. Real tool-service probe (GPU services, no model calls)

```bash
python scripts/parsec.py probe --requests 8 --concurrency 1,2,4
```

Calls the real Visual Grounding (SAM 3), OCR, Depth, and Zoom capabilities on
`data/images/FSC147/234.jpg` at 1, 2, and 4 concurrent clients and records
latency and throughput (`outputs/parsec_vl/probe/`).

## 5. Profiling runs

```bash
python scripts/parsec.py profile                          # every recorded real run in outputs/multi_agent
python scripts/parsec.py profile outputs/multi_agent/<run_id>
```

Real runs are those whose model responses report token usage; scripted fixture runs
are skipped unless `--include-fixtures` is given.

A real multi-agent run through the scheduler (one FSC-147 task; uses the model):

```bash
python scripts/run_studio_dataset_task.py --dataset FSC147_val --row 25 --num-agents 2 \
    --agent-config examples/local_grounding_tools.yaml --tool-scheduler e1 --no-estimate-updates \
    --output-dir outputs/parsec_vl/real_runs --run-id real_row25_e1
python scripts/parsec.py profile outputs/parsec_vl/real_runs/real_row25_e1 --out outputs/parsec_vl/real_runs/profile
```

## 6. Scheduler inside a deterministic multi-agent run (no models)

```bash
python scripts/studio_config_matrix.py run --scenario visual --workers 2 --mode concurrent \
    --tool-scheduler e1 --tool-delay 0.5 --output-dir outputs/parsec_vl/fixture_runs --run-id visual_e1
python scripts/studio_ctl.py --runs-dir outputs/parsec_vl/fixture_runs ensure   # open it in the Studio
```

The scheduler events are in the Studio's Technical Trace; the summary is in
`final_result.json["scheduler"]`.

## 7. Phase 2 (planning, speculation, E3–E5)

```bash
python -m pytest tests/parsec_vl -q                                 # Phase 1 + Phase 2 tests (~2 min)
python scripts/parsec.py plan-bench                                  # multicore Monte Carlo (in-process vs 1/2/4/8/16 processes)
                                                                     #   + decision quality under 0.05/0.2 s planning budgets
python scripts/parsec.py plan-bench --processes 1 --quality-instances 0   # sequential Monte Carlo only
python scripts/parsec.py actions-bench                               # one declared parallel plan in the harness, E0/E1/E2
python scripts/parsec.py spec-bench                                  # speculation scenarios A–E under S0/S1/S2
python scripts/parsec.py agents-bench                                # coordinator + 1–4 workers, OFF/E2/E3/E4/E5
python scripts/parsec.py harness --trials 5                          # Phase 1 comparison, re-measured
python scripts/parsec.py outcome-model                               # empirical outcome model from earlier real runs
```

Single runs (deterministic fixture, no model):

```bash
python -c "from pathlib import Path; from openvlharness.parsec_vl.fixture import run_plan_fixture as r; \
o,_,res,_ = r(Path('outputs/parsec_vl/phase2/demo'), policy='e5', workers=2, planning_processes=2); \
print(res['extra_records']['status'], res['prediction'], o.run_dir)"
```

Replace `policy='e5'` with `e3` (Monte Carlo plan selection), `e4` (fixed-width
speculation), or `off`/`e2` (original one-call protocol). Open the run directory's
parent in the Studio with `python scripts/studio_ctl.py --runs-dir outputs/parsec_vl/phase2/demo ensure`.

Real model (needs services; uses the model):

```bash
python scripts/run_studio_dataset_task.py --dataset FSC147_val --row 25 --num-agents 2 \
    --agent-config examples/local_grounding_tools.yaml --tool-scheduler e5 --planning-processes 4 \
    --no-estimate-updates --output-dir outputs/parsec_vl/phase2/real_runs --run-id real_row25_e5
bash scripts/run_custom_inference.sh -w 2 -s e5 25                  # same, live in the Studio
```

Outputs go to `outputs/parsec_vl/phase2/<experiment>/` as JSON plus a Markdown table.

## 8. Phase 3 (course delivery)

Three tiers. Evidence labels: **SYNTHETIC** = declared sleeps or CPU work in the
scheduler, **FIXTURE** = the real harness and multi-agent runtime with a scripted
model and local tool transports, **REAL** = the Qwen model and/or the GPU tool services.

### 8.1 Fast (≈1 minute, no GPU, no model)

```bash
python scripts/parsec.py demo                      # OFF vs E3 (sequential and parallel dispatch) vs E4, printed table
python scripts/parsec.py demo --studio             # same, then opens the runs in the Investigation Studio
python scripts/parsec.py figures                   # docs/figures/fig1..fig8 from the recorded results (no execution)
python scripts/plan_probe.py --revalidate          # re-checks the recorded real-model plan proposals (no inference)
python -m pytest tests/parsec_vl tests/studio -q
```

### 8.2 Full experiment set (≈25 minutes, CPU only; the probe line needs the tool services)

Exactly the commands that produced `outputs/parsec_vl/phase3/`:

```bash
P3=outputs/parsec_vl/phase3
python scripts/parsec.py bench --trials 5 --out $P3/bench                                   # Exp. 1: workloads A–X, E0/E1/E2, 1–8 workers
python scripts/parsec.py bench --workloads S_scaling --policies e0,e1 --workers 1,2,4,8 \
    --trials 5 --out $P3/scaling                                                            # Exp. 1: speedup and efficiency
python scripts/parsec.py plan-bench --out $P3/planning                                      # Exp. 2 + 3: multicore Monte Carlo, decision quality
python scripts/parsec.py spec-bench --trials 30 --out $P3/speculation                       # Exp. 4: speculation scenarios A–E
python scripts/parsec.py spec-bench --trials 30 --scenarios E_small_budget \
    --budgets 3,4,5,8,12 --out $P3/budget                                                   # Exp. 5: budget sensitivity
python scripts/parsec.py spec-bench --trials 30 --scenarios C_limited_resources \
    --capacities gpu=2 --out $P3/speculation_gpu2                                           # Exp. 6: GPU pool capacity 2
python scripts/parsec.py compare --set whole --workers 1,2,4 --trials 5                     # Exp. 7: OFF, E0–E5 whole runs
python scripts/parsec.py compare --set overhead --workers 1,4 --trials 5                    # planning overhead: eager/lazy/warm/sequential/heuristic/gate
python scripts/parsec.py compare --set contention --workers 4 --trials 5                    # Exp. 6: slots and pool capacity
python scripts/parsec.py matrix                                                             # Exp. 8: 1–4 workers × memory × peer (16 runs)
python scripts/parsec.py harness --trials 5 --out $P3/harness                               # Phase 1 comparison, re-measured
python scripts/parsec.py actions-bench --out $P3/actions                                    # one declared plan, E0/E1/E2
python scripts/parsec.py probe --requests 8 --concurrency 1,2,4 --out $P3/probe             # REAL tool services, no model
python scripts/parsec.py figures                                                            # regenerate docs/figures
```

Each command writes JSON (every trial) and a Markdown table. `compare` writes to
`outputs/parsec_vl/phase3/<set>/variants.{json,md}` and keeps every run directory under
`runs/`, so any row can be opened in the Studio:
`python scripts/studio_ctl.py --runs-dir outputs/parsec_vl/phase3/whole/runs ensure`.

### 8.3 Real model (needs the model and tool services; small, bounded)

```bash
python scripts/plan_probe.py --samples 5                  # 3 questions × 2 plan schemas × 5 first decisions (30 model calls, nothing executed)
python scripts/plan_probe.py --execute 2                  # 2 complete single-agent investigations of the explicit sign question
python -m openvlharness.multi_agent.run --config configs/multi_agent.yaml --num-agents 1 --mode concurrent \
    --no-estimate-updates --tool-scheduler e3 --planning-processes 2 \
    --image outputs/parsec_vl/phase3/plan_probe/sign_scene.png \
    --task "What does the sign say? Answer with the exact text. Use Execute_Action_Plan: read the whole image with OCR and, in parallel, ground the sign, zoom into it, and read the zoomed crop." \
    --output-dir outputs/parsec_vl/phase3/real_runs --run-id real_sign_e3_explicit
```

Model sampling is stochastic: counts can differ between repetitions. The recorded
responses are in `outputs/parsec_vl/phase3/plan_probe/plan_probe.json`; the re-validation
with the current parser is `plan_probe_revalidated.json`.

### 8.4 Studio browser checks (needs Node and Chrome; see INVESTIGATION_STUDIO.md)

The current repeatable browser procedure prepares fresh fixtures, copies the
required existing real recordings, starts an authenticated temporary Studio, and
runs the PARSEC, simple, story, visual, matrix, and original suites:

```bash
.venv/bin/python scripts/verify_studio_browser.py
```

The script prints a unique directory under `outputs/parsec_vl/verification/`.
It contains per-suite logs, assertion counts, screenshots, fixture run IDs, and
recorded-run provenance. It uses owner session records internally; there is no
manual token paste step. Live producers use scripted fixtures only. It stops
only the temporary Studio that it started. Missing recorded inputs cause a
nonzero exit, rather than silently dropping checks.

Historical PARSEC browser checks asserted 55 properties: bars matching recorded
intervals, permitted overlap and dependency order, resource capacities, replay
prefixes, evidence links, comparison labels, and both themes. Current counts
for all suites are recorded in `docs/VERIFICATION_REPORT.md`.
