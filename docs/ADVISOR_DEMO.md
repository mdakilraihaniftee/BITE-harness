# PARSEC-VL advisor demonstration

```bash
cd /home/ai5377/BITE-harness

# 1. Targeted offline verification before a meeting
bash scripts/verify_parsec.sh --quick

# 2. Generate and measure the controlled advisor demo (no GPU/model)
bash scripts/advisor_demo.sh

# 3. Open the last successful demo, already selected in the Studio
bash scripts/advisor_demo.sh --studio

# 4. Full retained tests and broader offline experiments
bash scripts/verify_parsec.sh --full
```

Both shell scripts find the repository and `.venv/bin/python` even when called
from another directory. `PARSEC_PYTHON=/absolute/path/to/python` selects another
prepared environment. They do not download anything or start GPU services.

## Before the meeting

Use `.venv/bin/python`, or activate it with `source .venv/bin/activate`. The offline
demo does not require `.env`, a model API key, a dataset, or internet access.
The full tests include the evaluation dependencies already installed here; on
another machine install the project's `test,server,eval` extras first.

Run quick verification, then the default advisor demonstration. The scripts
print measured results and the exact artifact directory. The quick verification
usually takes a few minutes; full verification takes longer because it repeats
the retained suite and multiple offline experiment trials. A nonzero exit is a
failure to investigate, not a successful presentation check.

The demonstration options are:

| Command | Behavior |
|---|---|
| `bash scripts/advisor_demo.sh` | Bounded demo: two visual-plan trials, 12,000 rollouts per candidate and two planning trials, five speculation trials, one-worker E0–E5 comparison. |
| `bash scripts/advisor_demo.sh --full` | Three visual-plan trials, 50,000 rollouts per candidate and three planning trials, ten speculation trials, two E0–E5 trials. |
| `bash scripts/advisor_demo.sh --studio` | Reopens the last successful demo without rerunning it; starts a demo if none is saved yet. |
| `bash scripts/advisor_demo.sh --quick --studio` | Generates a fresh bounded demo and opens it. |

Verification defaults to **full**. `--quick` runs PARSEC and Studio tests, lint,
JavaScript syntax, historical artifact checks, offline recorded-plan validation,
fixture provenance checks, and smaller scheduler/planning/speculation benchmarks.
It explicitly marks the complete retained suite **NOT VERIFIED**. `--full` also
runs the complete suite, budget sweeps, a four-worker E0–E5 comparison,
the configuration matrix, and figure reproduction.

Run all browser suites separately when Chrome and Node 22+ are available
(tested with Node 24.16.0):

```bash
.venv/bin/python scripts/verify_studio_browser.py
```

This generates fresh fixtures, copies existing real run records, checks all six
browser suites, saves screenshots/counts, and stops only its own temporary Studio.
It never reruns real inference. Missing required stored runs are reported as failures.

Check that the eight historical report figures are available:

```bash
ls docs/figures/fig*.png
```

## During the meeting: a 5–8 minute walkthrough

1. **Problem, 45 seconds.** “A visual agent calls tools to investigate an image.
   Some calls are independent; others consume earlier results. PARSEC-VL asks
   how to overlap useful work while respecting dependencies, shared resources,
   and a fixed budget.”

2. **Dependency DAG, one minute.** “The controlled sign-reading plan runs
   full-image OCR alongside grounding. Zoom consumes the grounding box; crop
   OCR consumes the actual Zoom image. We keep those dependencies intact.”

   ```text
   OCR(original) ------------------------+
   Grounding(original) -> Zoom -> OCR(crop)
   ```

3. **Measured speedup, one minute.** Run the demo and read its sequential and
   parallel tool spans. “This number is measured now, not copied from a report.
   The checker independently inspects execution intervals, crop identity, and
   artifact ownership. This is a scripted-model FIXTURE, not autonomous Qwen.”

4. **CPU planning, one minute.** “One, two, and four CPU processes evaluate the
   same six candidates with the same rollout seeds. The estimates must agree.
   These are CPU simulations, unlike the scheduler's sleeping-task benchmark.
   Warm evaluation time and cold pool startup are reported separately.”

5. **Speculation, one minute.** “Starting the fallback while the primary runs
   can hide latency if it is needed. The wasteful case shows extra charged calls
   when it is not. The small-budget case can lose completions when speculation
   consumes the fallback's budget.” Read the current table, including negative results.

6. **Visualization, two minutes.** Open the saved demo with `--studio`.
   The parallel run is selected automatically. In **Timeline**, show full-image
   OCR overlapping grounding and the subsequent Zoom/crop OCR bars. Click a bar
   for its recorded interval and evidence. Open **Plan & DAG**, then **Budget &
   resources**. Select `advisor_adopted_0` for speculative adoption and
   `advisor_pruned_0` for unused/cancelled work. Select `advisor_four_workers_0`
   for the coordinator and four workers. Expand **Technical details** for the
   full architecture; drag replay to the beginning, then use **Go live**.
   Switch light/dark themes. In **Compare**, point out the evidence badge and
   source path: those are stored historical measurements, not the current
   demo's table. The current E0–E5 comparison is saved under the demo directory.

7. **Limitations, 45 seconds.** “Recorded natural Qwen prompts proposed zero
   plans out of twenty. The two executed explicitly requested real plans were
   serial. All overlapping action-plan results shown here use scripted fixtures.
   Scheduling overhead, model latency, estimate error, and service contention
   can remove the benefit.”

The 4/3 work/span ratio assumes equal tool durations. The real local detector and
image-processing costs are unequal; do not describe 4/3 as an exact measured bound.
Operational completion in synthetic speculation is not model answer accuracy.

## Browser access

`--studio` starts or safely reuses a compatible Studio and opens the selected run.
The launcher performs authentication automatically: no token field or Connect
button. Reloads use a browser session cookie. Existing servers on other ports or
with older API versions are left alone.

On an SSH machine, forward the **printed port** using VS Code's Ports tab or:

```bash
ssh -N -L PORT:127.0.0.1:PORT USER@SERVER
```

Replace the placeholders, then open the complete printed visualization link once.
If its ticket has expired or the server restarted, run `--studio` again for a fresh
automatic sign-in link. Authentication protects run data, artifacts, and memory.

## If something fails

Open the normal Studio independently of model startup:

```bash
bash scripts/run_custom_inference.sh --ui-only
```

This shows saved runs; it does not execute a dataset row. A normal custom command
also opens this viewer if its required-service check fails, then exits with status
3 without starting the requested task. HTTP errors from readiness endpoints count
as failures. On SSH, forward the printed port and open the full launch link.

If Qwen seems stuck loading, check whether it is actually running:

```bash
curl --fail --max-time 5 http://127.0.0.1:8222/v1/models
nvidia-smi
```

A refused connection alone cannot distinguish loading from a stopped process.
When starting the GPU service yourself, keep its terminal open and capture logs:

```bash
mkdir -p outputs/services
set -o pipefail
bash scripts/service.sh qwen 2>&1 | tee "outputs/services/qwen_$(date -u +%Y%m%dT%H%M%S).log"
```

Wait for the models endpoint to return JSON before rerunning the custom command.
For a smaller demo context, pass `--max-model-len 32768` after `qwen`; this overrides
the configured 168,000-token context for that launch. It changes the available
context, and is not a verified remedy for an unidentified startup failure.

Open the saved run without inference:

```bash
bash scripts/advisor_demo.sh --studio
```

Each demo keeps `fixture_checks.json` with its run IDs, persisted runs and assets,
`planning/multicore.json`, `speculation/speculation.json`,
`comparisons/whole/variants.json`, logs, and `SUMMARY.md` under
`outputs/parsec_vl/advisor_demo/<unique-id>/`. `latest.json` points to the last
successful demo; failed demos do not replace it. Browser checks preserve their
own unique output directory and screenshots under `outputs/parsec_vl/verification/`.

For a standalone scheduler experiment, use a fresh output path:

```bash
source .venv/bin/activate
python scripts/parsec.py bench --workloads B_chain,C_mixed,S_scaling \
  --policies e0,e1,e2 --workers 1,2,8 --trials 2 \
  --out "outputs/parsec_vl/manual_$(date -u +%Y%m%dT%H%M%S)/scheduler"
```

The existing figures and report work offline if live presentation is unavailable.
Do not substitute an old speedup for a failed new measurement: identify it as a
historical result. If a process-parallel benchmark is slower under current load,
show that result and its cold-start cost.

## Optional real-service demonstration — only when GPU/model use is authorized

The initial independent check on 19 November 2026 found Qwen on port 8222 unavailable;
the router, SAM3, OCR, and depth workers answered health checks. Recent real-task
failures contain connection-refused errors from Qwen, not scheduler errors.
Recheck availability before a real run. The initial audit ran no real inference.
In a subsequent explicitly authorized follow-up, all missing services were started
and example 25 completed with two workers, memory on, communication on, peer off,
and E2. Both workers completed one grounding call and returned 46; the official
count is 38 (absolute error 8). Execution completion does not imply answer accuracy.

To start missing local services and run a new example with its live visualization
using a single command:

```bash
bash scripts/run_custom_inference.sh --start-services \
  --workers 2 --memory on --comm on --peer off --scheduler e2 25
```

`--start-services` explicitly uses GPU resources. It checks the selected profile,
reuses healthy services, starts missing local services in detached processes,
prints logs under `outputs/services/`, and waits up to ten minutes for readiness
before starting inference. It never replaces a listener on an occupied port;
if startup fails, it reports the log path and starts no task. Started services
stay running after the task or terminal exits. Newly started Qwen uses a 32,768
token demo context; an existing Qwen instance keeps its own context setting.
The helper can be invoked separately after `source scripts/env.sh` with
`python scripts/ensure_local_services.py --qwen-context-length 168000` when the
larger research context is required. Custom/remote service endpoints must be
started manually. `--check` continues to inspect inputs without starting services.

Reopen the verified completed real run without running inference again:

```bash
.venv/bin/python scripts/studio_ctl.py url \
  --run verified_fsc147_val_row25_w2_memon_peeroff_schede2_20261119_145759 --open
```

Completed and failed recordings are labeled as recorded rather than live streams.
The failed-run notice explains that opening a recording does not restart it.

```bash
source scripts/env.sh

# Health/configuration checks only: do not add --probe-tools.
python scripts/check_environment.py \
  --config examples/local_grounding_tools.yaml \
  --output "outputs/setup/advisor_readiness_$(date -u +%Y%m%dT%H%M%S).json"

# Inspect the exact zero-based dataset row and actual image; no inference.
bash scripts/run_custom_inference.sh --check \
  --workers 1 --memory off --peer off --estimates off --scheduler e2 0
```

If Qwen is absent, an authorized operator can start it in a separate terminal
with `bash scripts/service.sh qwen`, using the configured GPU allocation, and wait
for `/v1/models` to answer. Do not restart healthy workers or kill existing services.
Keep the health check green before running the following **one** task:

```bash
# REAL inference; execute only with permission to use the model/GPU resources.
bash scripts/run_custom_inference.sh \
  --workers 1 --memory off --comm on --peer off \
  --estimates off --follow-ups 0 --scheduler e2 0
```

This uses the existing global/per-agent budgets. Change the last number to choose
another row; check it first. `--workers` accepts 1–4 **workers plus a coordinator**.
`--memory` controls the optional notebook; required working context stays on.
`--peer off` stops worker-to-worker traffic. `--comm off` disables the message bus
and peer traffic; coordinator assignment/result handoff still works. The shipped
runtime caps concurrent workers at two, independently of tool scheduler slots.

A real E2 run may be entirely sequential inside each agent. Show actual events;
do not claim an autonomously generated parallel Qwen plan.

## After the meeting

- Source: `openvlharness/parsec_vl/`, `openvlharness/multi_agent/`, `openvlharness/studio/`.
- Tests: `tests/parsec_vl/`, `tests/studio/`, and the retained `tests/` suite.
- New measurements, test logs, JUnit counts, environment and git state:
  `outputs/parsec_vl/verification/<unique-id>/`.
- Historical benchmark data: `outputs/parsec_vl/phase3/`; it was not overwritten.
- Independent conclusions: [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md).
- Technical report: [CISC654_REPORT.md](CISC654_REPORT.md).
- Reproduction: [REPRODUCIBILITY.md](REPRODUCIBILITY.md).
