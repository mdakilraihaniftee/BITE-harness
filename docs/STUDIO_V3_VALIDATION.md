# Investigation Studio v3 — validation report

Engineering validation of the answer strip (ground truth, coordinator estimate, final
answer), the compact harness-centred team view, the investigation story, and the
runtime switches for worker count, optional worker memory, and peer communication.
These results establish that the software behaves as specified. They are **not** a
research result: no accuracy claim about worker count, memory, or communication
follows from them.

Date: 2026-11-16 (runs recorded 2026-11-17 UTC). Model service: local vLLM serving
`Qwen/Qwen3-VL-8B-Instruct`; tools: the repository tool server, SAM 3, OCR, and depth
services.

## Tier 1 — deterministic configuration matrix (all 16 configurations)

**Test fixture, not model inference.** Every actor is a real `MainAgent` with a real
Qwen-protocol `ModelAdapter`; only the endpoint is a scripted policy that decides from
the actual request, and the tools are deterministic (grounding, zoom, an
always-failing depth tool) over a synthetic five-object scene. Worker 4 has a one-call
tool budget. Each run goes through the real orchestrator, configuration validation,
run manifest, event store, replay snapshot, and the real frontend modules
(`team-view.js`, `answer-state.js`, `story.js`) in Node.

Reproduce: `python scripts/studio_config_matrix.py matrix --output-dir outputs/studio_matrix --report outputs/studio_matrix_report/matrix_report.json`
(the same checks run in `pytest tests/multi_agent/test_estimates_and_policies.py`).

| Workers | Memory | Peer communication | Runtime success | UI success | Memory policy verified | Communication policy verified | Tool calls | Peer msgs | Notebook events | Coordinator estimates | Final |
|---:|---|---|---|---|---|---|---:|---:|---:|---|---|
| 1 | ON | ON (no peers) | ✅ | ✅ | ✅ | ✅ | 2 | 0 | 3 | 4 (initial) → 5 (revised) → 5 (final) | 5 |
| 1 | ON | OFF | ✅ | ✅ | ✅ | ✅ | 2 | 0 | 3 | 4 → 5 (revised) → 5 (final) | 5 |
| 1 | OFF | ON (no peers) | ✅ | ✅ | ✅ | ✅ | 3 | 0 | 0 | 4 → 5 (revised) → 5 (final) | 5 |
| 1 | OFF | OFF | ✅ | ✅ | ✅ | ✅ | 3 | 0 | 0 | 4 → 5 (revised) → 5 (final) | 5 |
| 2 | ON | ON | ✅ | ✅ | ✅ | ✅ | 4 | 2 | 8 | 5 (initial) → 5 (final) | 5 |
| 2 | ON | OFF | ✅ | ✅ | ✅ | ✅ | 4 | 0 | 4 | 5 → 5 (final) | 5 |
| 2 | OFF | ON | ✅ | ✅ | ✅ | ✅ | 7 | 2 | 0 | 5 → 5 (final) | 5 |
| 2 | OFF | OFF | ✅ | ✅ | ✅ | ✅ | 5 | 0 | 0 | 5 → 5 (final) | 5 |
| 3 | ON | ON | ✅ | ✅ | ✅ | ✅ | 7 | 6 | 11 | 5 → 5 (final) | 5 |
| 3 | ON | OFF | ✅ | ✅ | ✅ | ✅ | 6 | 0 | 5 | 5 → 5 (final) | 5 |
| 3 | OFF | ON | ✅ | ✅ | ✅ | ✅ | 12 | 6 | 0 | 5 → 5 (final) | 5 |
| 3 | OFF | OFF | ✅ | ✅ | ✅ | ✅ | 7 | 0 | 0 | 5 → 5 (final) | 5 |
| 4 | ON | ON | ✅ | ✅ | ✅ | ✅ | 8 | 12 | 14 | 5 → 5 (final) | 5 |
| 4 | ON | OFF | ✅ | ✅ | ✅ | ✅ | 7 | 0 | 6 | 5 → 5 (final) | 5 |
| 4 | OFF | ON | ✅ | ✅ | ✅ | ✅ | 13 | 12 | 0 | 5 → 5 (final) | 5 |
| 4 | OFF | OFF | ✅ | ✅ | ✅ | ✅ | 8 | 0 | 0 | 5 → 5 (final) | 5 |

*Runtime success* means all of the following passed: event schema and contiguous
sequence; COMPLETED lifecycle; manifest worker count and IDs; exactly one coordinator;
distinct agent and adapter objects per actor and tool calls only by workers; no
worker's requests naming another worker (no state contamination); memory policy;
communication policy; global and per-actor budgets never exceeded; estimate revisions
numbered 1..n, first estimate after the first worker report, last state final; replay
snapshot fully annotated with N+1 agents. *UI success*: one card per agent, correct
memory/peer indicators and tool chips, the estimate and final answer correct at
**every** replay prefix (no early reveal), story tool and estimate steps matching the
events, and at least one estimate linked to recorded evidence.

Observations (fixture behavior, not research findings):

* **Memory OFF** produced zero notebook events and no `private_memory.json`; working
  context (image registry) events continued. Without the notebook, workers had to
  re-derive the uncertain region, costing more tool calls (e.g. 2 → 3 for one worker;
  4 → 7 for two workers with peers; 8 → 13 for four workers with peers). Final
  answers were unchanged in this fixture.
* **Peer communication OFF** produced zero worker-to-worker messages and no peer review;
  assignments and reports still flowed in every configuration. With peers ON and one
  worker, no peer message was sent.
* **Worker count** increased tool calls, model requests (8 → 30), and events; the
  fixture's two disagreeing workers (4 vs 5) appear from N = 2.
* **Coordinator estimates** changed during execution for N = 1 (4 → 5 after a
  follow-up); for N ≥ 2 the first estimate already matched the final value and later
  reassessments were recorded as *retained* without new revisions. Budget stops and an
  execution failure (depth tool) appear from N = 3/4 and are labelled distinctly.
* Withdrawal (`provisional → unresolved`) is exercised by the `withdrawal` scenario
  (`initial → withdrawn → finalized`).

## Tier 2 — real model and tool smoke tests (bounded)

Task: FSC-147 `val` row position 10 (dataset index 10), “How many grape are there in
the image? Your final answer should be a single integer.” Same task for all four runs,
executed sequentially with `scripts/run_studio_dataset_task.py` (concurrent mode,
coordinator estimates ON, no follow-up rounds). The reference was resolved only after
each run was terminal, through the evaluator path (`openvlharness/studio/reference.py`),
and scored with the benchmark's `parse_count` exact-match rule.

| Run ID | Workers | Memory | Peer comm. | Model | Tool calls | Model requests (coordinator) | Messages (peer) | Notebook events | Coordinator answer states | Final | Reference | Correct | Time | Generated tokens | Events | UI/replay |
|---|---:|---|---|---|---|---:|---:|---:|---|---:|---:|---|---:|---:|---:|---|
| `real_fsc147_row10_w1_memoff_peeroff` | 1 | OFF | OFF | Qwen3-VL-8B-Instruct | 1 (grounding 1) | 7 (5) | 2 (0) | 0 | 1 reassessment: unresolved → final 40 | 40 | 46 | No (|err| 6) | 16.8 s | 465 | 63 | ✅ |
| `real_fsc147_row10_w2_memon_peeron` | 2 | ON | ON | Qwen3-VL-8B-Instruct | 6 (grounding 4, zoom 2) | 17 (7) | 10 (2) | 6 | 2 reassessments: unresolved → final 2 | 2 | 46 | No (|err| 44) | 39.3 s | 1,714 | 185 | ✅ |
| `real_fsc147_row10_w3_memon_peeroff` | 3 | ON | OFF | Qwen3-VL-8B-Instruct | 4 (grounding 2, zoom 1, Python 1) | 12 (5) | 6 (0) | 3 | 1 reassessment: unresolved → final 2 | 2 | 46 | No (|err| 44) | 67.5 s | 1,423 | 127 | ✅ |
| `real_fsc147_row10_w4_memoff_peeron` | 4 | OFF | ON | Qwen3-VL-8B-Instruct | 7 (grounding 5, zoom 2) | 22 (7) | 28 (12) | 0 | 2 reassessments: unresolved → final 39 | 39 | 46 | No (|err| 7) | 54.2 s | 2,306 | 278 | ✅ |

Time is first-to-last event; generated tokens are measured from responses. Cost was
local GPU time on an already-running vLLM server (no paid API). *UI/replay* = 21/21
browser checks on these runs (worker cards, released reference and evaluation,
estimate history, replay start with no estimate and no final answer, no console
errors).

What the real runs show:

* All policy switches behaved as configured: no peer messages with peers OFF, no
  notebook events with memory OFF, notebook writes and reads with memory ON.
* The real coordinator **never formed a provisional estimate**: each reassessment
  returned `unresolved` because worker counts conflicted (e.g. 2 vs 35 vs 39) without
  verification it considered sufficient, so the UI correctly showed *No estimate yet*
  until the final answer, marked “no provisional estimate preceded it”.
* Some workers answered “2” with zero tool calls; in two runs the coordinator
  synthesized “2”. This is model behavior, recorded as-is.
* None of the four answers matched the reference (46). Four single-row runs cannot
  support any comparison between configurations.

A first attempt of the same four runs (kept in `outputs/multi_agent_budget_bug_runs/`)
ended `BUDGET_EXHAUSTED`: real coordinator calls cost two requests each (answer-tag
retry), and the first reassessment budget check assumed one, starving synthesis. The
orchestrator now reserves the observed per-call cost for synthesis and caps each
reassessment (regression test:
`test_multi_request_coordinator_calls_never_starve_synthesis`), and
`configs/multi_agent.yaml` raises `coordinator.model_requests` from 4 to 8.

## Browser validation

`scripts/studio_browser_matrix.mjs` (headless Chrome, CDP): **90/90** checks on the
fixture runs, and **21/21** with `--real-runs` on the four real runs; the existing
`scripts/studio_browser_check.mjs`: **62/62**. The checks verify content, not just
files: card and agent counts, duplicate blocks, indicator text, tool chips, worker
card height (≤ 300 px desktop, ≤ 320 px laptop), card overlap, rows (all four workers in
one row at 1600 px and 1280 px), horizontal page overflow (desktop, laptop 1280×800,
phone 390 px), sticky strip, theme colors, expanded details, SVG node count in the full
view, sealed/withheld/released reference states, estimate and final values at
specific replay positions, linked evidence with ROI and crop, legacy-run behavior,
and console errors. Screenshots (`docs/images/studio_v3/`):

| # | Screenshot |
|---|---|
| 1 | `01-w1-memory-off-peer-off.png` — one worker, memory OFF, peer OFF |
| 2 | `02-w2-memory-on-peer-on.png` — two workers, memory ON, peer ON |
| 3 | `03-w3-memory-on-peer-off.png` — three workers, memory ON, peer OFF |
| 4 | `04-w4-memory-off-peer-on.png` — four workers, memory OFF, peer ON |
| 5 | `05-ground-truth-sealed-during-inference.png` |
| 6 | `06-ground-truth-released-after-completion.png` (with provenance popover) |
| 7 | `07-before-first-estimate.png` |
| 8 | `08-first-provisional-estimate.png` |
| 9 | `09-revised-estimate.png` |
| 10 | `10-final-answer.png` (estimate history) |
| 11 | `11-compact-architecture-light.png` |
| 12 | `12-compact-architecture-dark.png` |
| 13 | `13-expanded-harness-detail.png` |
| 14 | `14-roi-synchronized-with-estimate-revision.png` |
| 15 | `15-laptop-w4.png` — 1280×800 |
| — | `real_fsc147_row10_w{1,2,3,4}_*.png` — the real runs |

Reports: `docs/images/studio_v3/browser-matrix-report.json`,
`docs/images/studio_v3/browser-real-runs-report.json`.

## Regression results

| Suite | Result |
|---|---|
| `pytest tests/multi_agent tests/studio` | 112 passed (all multi-agent and Studio tests, including 16 matrix configurations, estimate tests A–G, leakage, authorization, and Node frontend-model tests) |
| `pytest tests` (full) | 994 passed, 68 failed, 55 errors; before this change: 957 passed, 68 failed, 55 errors. The 123 failing/erroring tests are **identical** before and after and are all in `tests/bite_calibration/` and `tests/bite_collection/`, which need historical research artifacts under `outputs/bite/` that are absent from this checkout (e.g. `outputs/bite/phase04b2b4/diagnostics/conditional_evidence_summary.json`). |
| Browser (`studio_browser_matrix.mjs`) | 90/90 fixture checks; 21/21 real-run checks |
| Browser (`studio_browser_check.mjs`, pre-existing) | 62/62 |
