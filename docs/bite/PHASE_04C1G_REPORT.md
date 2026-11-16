# Phase 4C-1G: oracle headroom, learnable headroom and controlled branch evaluation

Report date: **2026-11-04**.

| | |
| --- | --- |
| Status | **ENGINEERING_SUCCESS_WITH_BLOCKERS** |
| Research outcome | **EXPERIMENT_INSUFFICIENT_OR_INVALID** (execution not authorized) |
| Real model calls | **0** (Qwen 0, SAM 3 0) |

Constraints observed:

- no services were started;
- no labels were opened;
- no validation or internal-test access;
- no change to the agent, evaluator, models or serving parameters;
- no git operations.

## 1. Protocol actually used

**Protocol A, a controlled fixed-decoder answer probe.** Protocol B (genuine
agent continuation) is not reconstructible. The 4B-2B-3 states come from
controlled capability execution: no agent conversation, model turn or tool-call
message was recorded. Rebuilding prefixes would mean new agent and SAM 3 runs.
See `TASK_LEVEL_PROBE_PROTOCOL.md` §1. No Protocol B result exists, and the two
protocols must never be pooled.

## 2. Data integrity (GT-free)

| Item | Value |
| --- | --- |
| Source groups | 15 (calibration-fit; seed-465 frozen pilot); 14 with 7 tasks, 1 with 3 |
| Initial query states / no-candidate | 105 / 4 |
| Tasks (candidate-present) | 101; the frozen manifest reproduces exactly |
| Queries | starfish 15, jellyfish 15, penguin 15, fish 14, stingray 14, shark 14, puffin 14 |
| Zoom branches / crops / focused success | 101 / 101 / 101 (all `complete`) |
| Semantic observations | **0 / 101 (pilot never run)** |
| Count-zero vs count-positive tasks | **not computed**: labels stay sealed until the outcome table is finalized |
| Selected detector rank ≠ 0 | 46 tasks; the renderer names the anchored proposal by rank |
| Input identities | the 4C-1E semantic manifest matches its inventory; 4C-1F preflight PASS; 4C-1D, 4C-1E and 4C-1F artifact checksums unchanged |
| Model | `Qwen/Qwen3-VL-8B-Instruct` (alias `qwen3-vl-8b-instruct`), cache revision `0c351dd…`; shard hashes verified in 4C-1F |
| Backend | vLLM launch script `scripts/service.sh qwen`, loopback `127.0.0.1:8222`, **not running**; 4 × L40S idle; about 716 GB free |
| Unrelated process | `cloudflared` → `127.0.0.1:8112` is still present. It is neither used nor touched, and images go inline to loopback only |

## 3. What was built

**Modules** (in `evaluation_kit/bite_calibration/`):

| Module | Purpose |
| --- | --- |
| `task_level_probe_protocol.py` | task, prompt, strict parser, GT-blind manifest, pre-call features, authorization binding (both caps, expiry, researcher-only) |
| `branch_evidence_renderer.py` | deterministic B0–B3 rendering from stored records; failure-preserving; lineage-checked semantic evidence |
| `task_level_branch_runner.py` | gated, resumable runner; cumulative final-answer cap and phase-total cap (semantic + final ≤ 505); canary ≤ 5 tasks; halts on failures or model mismatch; immutable finalization; labels after finalization only |
| `oracle_headroom.py` | Stage A statistics, generic paired group bootstrap, LOGO influence, strata |
| `learnable_headroom.py` | P0–P3 under LOGO, recovery fraction, influence |
| `task_level_decision_analysis.py` | transitions, combined-evidence diagnostics, measured costs, predeclared go/no-go |

**Scripts** (in `scripts/bite/`):

- `prepare_oracle_headroom_pilot.py`
- `preflight_oracle_headroom.py`
- `run_oracle_headroom_branches.py`
- `analyze_oracle_headroom.py`
- `assess_phase04c1g_readiness.py`
- `build_phase04c1g_manifest.py`

**Existing code reused:**

- the semantic pilot runner and its authorization (unchanged);
- `ModelAdapter`;
- `ResumeLedger` and `StageEventLedger`;
- `atomic_json`;
- `AquariumDatasetAdapter.load_offline_ground_truth`;
- the 4C-1F backend probes;
- the ontology definitions;
- the λ grid.

Nothing in `openvlharness/` was modified.

**Offline evidence produced** (under `outputs/bite/phase04c1g/`):

- the protocol contracts and analysis plan;
- the task manifest and pre-call feature table;
- B0/B1 render digests, with identical common prompt parts checked on all 101
  pairs;
- input identity, backend readiness, request estimate (largest request about
  3.6k tokens) and dispatch budget;
- authorization status and requirements;
- a mock B0/B1 contract run (202 units, local requester, finalized without
  labels);
- readiness.

## 4–7. Branch results, oracle headroom, learnable headroom and decision transitions

**None exist.** These sections stay empty until a live run completes. The
result documents (`ORACLE_HEADROOM_RESULTS.md`, `LEARNABLE_HEADROOM_RESULTS.md`,
`COMBINED_EVIDENCE_ANALYSIS.md`) describe only the frozen plan.

## 8. Scientific limitations (apply to any future result)

- Only 15 independent groups, already used in calibration-fit work. This is
  development evaluation, not held-out validation.
- Class-absent queries on which SAM 3 still returned a candidate may dominate.
  Counting results could reduce to presence and false-positive rejection.
- A fixed-decoder probe is not autonomous agent behaviour.
- The same Qwen3-VL weights produce the semantic observation and the final
  answer.
- Evidence is dependent: shared pixels, a shared candidate box, and Zoom built
  from the initial proposal.
- The action set is fixed, so the oracle bounds headroom within that set only,
  and it is optimistic by construction.
- B1 and B3 are longer presentations (one more image and about 2× the text), and
  no length-matched control exists.
- Logical, latency and token costs are not comparable to each other. Zoom
  latencies come from another date and service state.
- The COCO-style counts are not human-verified as exhaustive.

## 9. Research go/no-go

**`EXPERIMENT_INSUFFICIENT_OR_INVALID`**. See `PHASE_04C1G_RESEARCH_DECISION.md`.

## 10. Remaining steps (researcher)

1. `bash scripts/service.sh qwen`.
2. Write the 4C-1F semantic authorization
   (`outputs/bite/phase04c1f/authorization/authorization_requirements.json`).
   Run the canary (5), then resume.
3. Write the 4C-1G authorization
   (`outputs/bite/phase04c1g/authorization/authorization_requirements.json`;
   cap ≤ 404, phase total ≤ 505). Run the canary (≤ 5 tasks × 4 branches), then
   resume.
4. Run `analyze_oracle_headroom.py`, then the readiness script and the manifest
   builder.

Expected real calls: 101 semantic + 404 final answers = 505, with no retries
beyond that.

**Note.** The historical test
`test_phase04c1f.py::test_no_semantic_run_or_results_exist_without_authorization`
asserts that `outputs/bite/phase04c1f/raw_observations` does not exist. An
authorized semantic run will make it fail by design. It should then be replaced,
in a dated change, by a test asserting that the run carries a valid
authorization digest. It must not simply be deleted.

## Verification

See `outputs/bite/phase04c1g/implementation_manifest.json` (tests, checksums,
git state).
