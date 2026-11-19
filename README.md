# PARSEC-VL

**Parallel Adaptive Reasoning with Speculative Execution and Constrained Tool Budgets**
— budget-aware parallel planning and speculative execution for multi-agent visual
reasoning. CISC 654 (Parallel Computing) course project.

## What problem does it solve?

A visual-reasoning agent answers an image question by alternating model reasoning
with tool calls (grounding, OCR, depth, zoom, ...). Several agents (a coordinator and
1–4 workers) can investigate the same image. The work forms a dependency graph:
some operations are independent (grounding, OCR, and depth on the original image),
others must wait (OCR on a crop needs the crop, which needs grounding). The tools
run on shared GPU services with limited capacity, and every run has a fixed tool
and model budget.

PARSEC-VL asks: **how can parallel computation shorten this work without violating
tool dependencies, overloading shared services, or overspending the budget?**

## Architecture

```text
                 Coordinator agent ── plans, assigns, synthesizes
                  │            ▲
        assigns   ▼            │ reports
  Worker 1 … Worker N   (threads; each: model request → tool calls → model request …)
        │ proposes validated tool calls (arguments unchanged)
        ▼
  PARSEC-VL scheduler  ── dependencies · worker slots · typed resource pools · run budget
        │ dispatches when all four allow
        ▼
  Tool services (SAM 3 grounding, OCR, depth, zoom, …) ── results published to each
  agent's private memory, in call order ── Investigation Studio (live / replay)
```

The runtime is the OpenVLHarness-derived multi-agent harness in `openvlharness/`
(agents, capabilities, services, memory, multi-agent orchestrator, Studio). Phase 1
adds `openvlharness/parsec_vl/`. Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Parallel scheduler (Phase 1)

One engine, three policies, the same task model:

| Policy | Behaviour |
|---|---|
| **E0** sequential FIFO | one task at a time, in ready order (fixed-workload reference) |
| **E1** parallel FIFO | independent ready tasks run concurrently within worker, resource, and budget limits |
| **E2** critical path | like E1, but the ready task with the most estimated remaining downstream work goes first |
| **E3** | E2 + declared action plans (`Execute_Action_Plan`): Monte Carlo selects which branch leads |
| **E4** | E2 + declared action plans + fixed-width speculation (start K alternatives early) |
| **E5** | E2 + plans + Monte Carlo plan selection + budget-aware selective speculation + event-driven replanning |

E3–E5 are a different decision protocol (the agent may authorize several actions at
once), not just a different schedule; the original one-call-per-message protocol stays
the default. Monte Carlo plan evaluation runs on a persistent pool of CPU processes and
gives identical estimates for any process count.

A task runs only after its prerequisites completed and published their results,
a worker slot is free, its resource pool (`cpu`, `remote_io`, `model_service`, one
pool per GPU service) has capacity, and its budget cost is reserved in the run's
existing ledger. Failures skip only dependent tasks; timeouts, cancellation, and
shutdown release what they hold. Each task is recorded (enqueue, start, finish,
worker slot, pool, budget) in the run's event log for a later Gantt view.

## Installation

```bash
git clone <this repository> && cd BITE-harness
python -m pip install -e '.[test,server]'      # add ,eval for dataset runs
source scripts/env.sh
```

GPU model/tool services, checkpoints, and datasets: [docs/HARNESS_GUIDE.md](docs/HARNESS_GUIDE.md).
Agent configurations: [examples/local_grounding_tools.yaml](examples/local_grounding_tools.yaml)
(Qwen plus grounding, OCR, depth, zoom, coding; used by the multi-agent runs) and
[examples/local_tools.yaml](examples/local_tools.yaml) (Zoom and coding with a hosted GPT model; no GPU tool workers).

## Quick start

For the checked advisor workflow, use [docs/ADVISOR_DEMO.md](docs/ADVISOR_DEMO.md):
`bash scripts/verify_parsec.sh --quick`, `bash scripts/advisor_demo.sh`, then
`bash scripts/advisor_demo.sh --studio`. Independent findings and restrictions
are recorded in [docs/VERIFICATION_REPORT.md](docs/VERIFICATION_REPORT.md).

```bash
# 1. The course demonstration (no model, ~10 s): the same visual-tool plan,
#    sequential vs parallel, plus speculation; then open the runs in the Studio.
python scripts/parsec.py demo --studio

# 2. Tests (CPU only, ~2 min for the PARSEC suites)
python -m pytest tests/parsec_vl tests/studio -q

# 3. Controlled experiments (CPU only; SYNTHETIC or FIXTURE, see docs/REPRODUCIBILITY.md)
python scripts/parsec.py bench          # scheduler: independent / chain / mixed / contention / visual pipeline
python scripts/parsec.py plan-bench     # multicore Monte Carlo planning, 1-16 processes
python scripts/parsec.py spec-bench     # speculation: helps / wastes / contention / wrong estimates / small budget
python scripts/parsec.py compare --set whole   # whole multi-agent runs, OFF and E0-E5
python scripts/parsec.py figures        # course figures from the recorded results (docs/figures)

# 4. Real model and tool services (needs the services and authorization)
bash scripts/run_custom_inference.sh -w 2 25               # original runtime
bash scripts/run_custom_inference.sh -w 2 --scheduler e5 25   # PARSEC-VL E5
python scripts/plan_probe.py --samples 5                   # does the model propose plans? (first decisions only)
```

## Sequential vs parallel benchmark

`scripts/parsec.py bench` runs workloads **A** independent tasks, **B** a serial
chain, **C** a mixed DAG with a long critical path, **D** contention for a
capacity-1 GPU pool, **M** wrong duration estimates, **V** the visual pipeline
(grounding → crop → crop OCR alongside OCR and depth, replaying measured service
latencies), and **X** CPU-bound Python (negative control), under E0/E1/E2 with 1, 2,
4, and 8 workers, 5 trials each. Results, including the cases where parallelism
or E2 does not help: [docs/PHASE1_RESULTS.md](docs/PHASE1_RESULTS.md).

## Investigation Studio

Run `bash scripts/run_studio_demo.sh` to open the visualization directly. Local
viewing signs in automatically, selects the run, and works across reloads with
no token entry. `python scripts/parsec.py demo --studio` also
opens the course demo. On a remote machine, forward the printed port and open
the printed URL. The browser remembers the session; API access stays authenticated.

The browser Studio (live view and replay: investigation story,
technical trace, compact agent/harness overview, tool evidence with ROIs and crops,
coordinator answer tracking, sealed ground truth) has a **Parallel execution** panel:
a Gantt chart of the real scheduler intervals (by slot, resource pool, or agent; queue
wait, speculation, adoption, critical path, model and planning lanes), the plan
dependency DAG with branch outcomes and the recorded speculation decision, a budget and
resource monitor, and a comparison of recorded benchmarks labelled REAL, FIXTURE, or
SYNTHETIC. Screenshots: [docs/images/parsec/](docs/images/parsec/). Guide:
[docs/INVESTIGATION_STUDIO.md](docs/INVESTIGATION_STUDIO.md).

## Reproducing measurements

Every command and output location: [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md).
Measurements are labelled real (live services), recorded (earlier real runs), or
synthetic (sleep-based scheduler workloads).

## Project phases and status

| Phase | Scope | Status |
|---|---|---|
| 1 | Repository simplification, runtime profiling, DAG scheduler (E0/E1/E2), budget-safe resource control, harness integration, benchmarks | **done** — [results](docs/PHASE1_RESULTS.md) |
| 2 | Declared action plans, CPU-parallel Monte Carlo plan evaluation, fixed-width and selective speculation, event-driven replanning (E3–E5) | **done** — [results](docs/PHASE2_RESULTS.md) |
| 3 | Lazy planning pool and overhead gate, real-model plan probe, Studio Gantt/DAG/budget/compare views, full experiments, figures, course report | **done** — [report](docs/CISC654_REPORT.md) |

## Limitations

- The harness protocol allows **one tool call per model message**, so a single
  agent never has independent tool calls to overlap. E3–E5 add an opt-in plan tool
  that authorizes several actions per decision. In a bounded probe, Qwen3-VL-8B never
  chose it on its own (0 of 20 first decisions); when explicitly asked it wrote valid
  plans (10 of 10), and two such real plans executed on the real tool services as
  serial chains (no overlap). All parallel plan execution in the results therefore
  comes from scripted fixtures or synthetic workloads.
- Planning has a cost: a cold planning pool (~0.25 s) and Monte Carlo time made E3/E5
  slower than the original runtime on short tool calls; speculation helps only when
  the alternative is likely to be needed and estimates are right.
- Model requests dominate wall time in recorded real runs; tool scheduling cannot
  shorten them.
- Worker slots are threads: good for waiting on HTTP services, useless for
  CPU-bound Python (measured slowdown); Monte Carlo planning therefore uses processes.
- Synthetic benchmarks measure scheduling, not GPU throughput.

## Repository layout

```text
openvlharness/        agent loop, capabilities, services, memory, multi_agent/, studio/
openvlharness/parsec_vl/   scheduler, resources/budget, harness integration, profiling, workloads (Phase 1);
                           plans, montecarlo, controller, fixture, experiments (Phase 2)
evaluation_kit/       datasets, runner, scoring (openvlharness-eval)
scripts/              parsec.py (bench/probe/profile), run_custom_inference.sh, Studio tools, setup
configs/, examples/   agent and multi-agent configurations
tests/                parsec_vl/, multi_agent/, studio/, evaluation/, agent and capability tests
docs/                 CISC654_REPORT (final report), CISC654_SLIDES (talk outline), ARCHITECTURE, REPRODUCIBILITY,
                      PHASE1_RESULTS, PHASE2_RESULTS, HARNESS_GUIDE, INVESTIGATION_STUDIO, figures/, images/parsec/
```

Earlier BITE research material was archived, not deleted: [docs/LEGACY_ARCHIVE.md](docs/LEGACY_ARCHIVE.md).

## License and acknowledgement

MIT ([LICENSE](LICENSE)); third-party components and model/data licenses in
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md). Built on
[OpenVLHarness](https://github.com/uclanlp/OpenVLHarness) ([paper](https://arxiv.org/abs/2610.26860)):
the agent loop, capability layer, memory, model adapters, tool services, and
evaluation kit originate there and keep their original attribution.
