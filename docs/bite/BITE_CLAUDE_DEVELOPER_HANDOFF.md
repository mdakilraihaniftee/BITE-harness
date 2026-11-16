# BITE developer handoff (source-of-truth architecture map)

Written during Phase 4C-1E (2026-11-02) from inspected code, not from memory.
When this document and the code disagree, **the code and the phase
`implementation_manifest.json` files are authoritative**. Update this file when
the architecture changes, and keep earlier statements by adding dated sections.

## 1. Ground rules that every phase has followed

- **Output roots.** Each phase writes only under `outputs/bite/<phase>/`.
  Earlier roots are immutable, and checksum inventories and regression tests
  enforce this.
- **Raw before GT.** Raw tool evidence is persisted and finalized before any
  ground truth (GT) is opened. Runtime predictor tables are rejected if they
  contain any GT marker key (`zoom_conditional_protocol.GT_MARKERS`).
- **Partitions.** Partitions are frozen: `calibration_fit` (277 groups),
  `calibration_validation` (72 groups / 78 images), and `internal_test`
  (50, locked). Validation outcomes have never been accessed.
- **Frozen models.** Underlying models are frozen. There is no training, and no
  SAM 3 or Qwen inference without explicit written authorization.
- **No git operations.** No commit, reset or cleanup unless the user authorizes
  it. The working tree carries uncommitted phase work on purpose.
- **Human review.** Optional for annotation-proxy calibration. The 20 genuine
  records under `outputs/bite/phase04b2b4/human_adjudications/completed/` are
  never rewritten.

## 2. Original OpenVLHarness flow, and where BITE attaches

```
run_benchmark.py / evaluation_kit/runner.py
  -> openvlharness/bootstrap.py  build_agent / build_capabilities
       (fixed allowlist PAPER_CAPABILITIES / PAPER_BACKENDS; editing it = production change)
  -> openvlharness/agent/agent.py  Agent.generate -> _run loop
       model: openvlharness/services/models.py ModelAdapter.request (OpenAI-compatible; vLLM Qwen3-VL)
       tools: capability.invoke(VirtualCall, memory)  (openvlharness/capabilities/_base.py)
              -> services/client.py ToolClient.execute -> tool server services/server.py /execute
              grounding: capabilities/grounding.py (Visual_Grounding_Tool; backends sam3_segment, grounding_dino)
              zoom:      capabilities/zoom.py (Zoom_In_Tool; local PIL crop backend)
  BITE passive hook: agent.py:93 create_observer(...)  -> openvlharness/bite/observer.py
       opt-in, capture-only; failures never change agent execution; no decision APIs
```

`openvlharness/bite/` is the **only** BITE code inside the production package.
It handles passive capture and contains `observer`, `state`, `budget`
(recording only), `geometry`, `provenance`, `schemas` and `serialization`.
Nothing in it makes decisions.

## 3. Experiment execution (controlled collection)

`evaluation_kit/bite_collection/` runs tools **through the same public
capability lifecycle** as the agent (`executor.py:97-106`). It never calls the
VLM.

| Concern | Module |
| --- | --- |
| Dataset access (GT-sealed) | `dataset_adapter.py`, `manifest_iterator.py` |
| Prefix (initial SAM 3 grounding) | `state_builder.py` |
| Frozen executable snapshots / branch isolation | `snapshot.py`, `cloning.py`, `branch_runner.py` |
| Action execution and cost | `executor.py`, `budget.py` (logical cost 1 per dispatch) |
| Expansion design | `expansion_protocol.py`, `expansion_runner.py`, `batch_runner.py` |
| Atomic writes / resume | `persistence.atomic_json`, `resume.ResumeLedger` |
| Hash-chained stage events | `integrity.StageEventLedger`, `validate_stage_events` |
| Offline audits | `negative_audit.py`, `focused_analysis.py`, `support_analysis.py` |
| CPU-only fakes | `synthetic.py` |

**Where runtime evidence lives.** Expansion states are stored under
`outputs/bite/phase04b2b3/expansion/aquarium_task_v_expansion_seed418_g30/states/<state>/`:

- `initial_raw_state.json`: the prefix observation, the selected candidate and
  its box. It contains no GT (`offline_gt_used: false`).
- `raw_collection/snapshots/artifacts/<sha256>.jpg`: the source image, with the
  digest as its filename.
- `raw_collection/branches/*`: the Zoom and focused branches.
- `offline_labels/`: **GT is introduced here.** It is written after
  `raw_completion.json` and recorded in `stage_events.jsonl`.

**Identifier caveat.** `candidate_id` and `joint_observation_id` are
state-local. `executor.py:137` derives them from branch, observation and rank.
The 203 expansion candidates share 15 candidate ids. Always key on `state_id`,
or on `(state_id, candidate_id)`.

## 4. Offline analysis (`evaluation_kit/bite_calibration/`)

The package docstring says it is "Offline calibration preparation only. Never
imported by the inference runtime." Main lineage:

| Phase | Modules | Artifacts |
| --- | --- | --- |
| 4B-2B-4 GT-free features | `conditional_features.py`, `evidence_diagnostics.py` | `phase04b2b4/conditional_features/*.jsonl` |
| 4C-1A priors and folds | `prior_model.py`, `grouped_crossfit.py` (label-balanced folds, seed 431), `proxy_calibration.py` | `phase04c1a/crossfit/*_predictions.jsonl` |
| 4C-1B uncertainty and label sensitivity | `grouped_uncertainty.py`, `paired_model_comparison.py`, `label_sensitivity.py`, `grouped_label_sensitivity.py` | `phase04c1b/` |
| 4C-1C-revised frozen fit-only priors | `frozen_prior_export.py`, `annotation_proxy_protocol.py`, `optional_human_review.py`, `sam3_provenance.py` | `phase04c1c_revised/frozen_priors/` (6 models; hashes in its implementation manifest) |
| 4C-1D Zoom feasibility | `zoom_conditional_protocol.py`, `zoom_incremental_model.py`, `paired_zoom_evaluation.py`, `zoom_action_cost_analysis.py`, `sam3_attested_worker.py`, `matched_worker_bridge.py` | `phase04c1d/` |
| **4C-1E** utility screen and semantic action | `action_utility_screen.py`, `semantic_observation_schema.py`, `semantic_region_action.py`, `semantic_feature_extractor.py`, `semantic_pilot_protocol.py`, `semantic_comparison_design.py` | `phase04c1e/` |

Common helpers worth reusing:

- `calibration_metrics.calibration_metrics`
- `zoom_conditional_protocol.read_jsonl` and `file_sha256`
- `paired_zoom_evaluation.align_predictions`
- `action_utility_screen.grouped_utility_bootstrap`, a generic paired group
  bootstrap of per-candidate utilities. `semantic_comparison_design` reuses it
  for Brier differences.

## 5. VLM backend facts (verified)

- **Client.** `ModelAdapter` (`openvlharness/services/models.py:145`). It speaks
  OpenAI-compatible Chat Completions to `<base>/v1/chat/completions`. The alias
  `qwen3-vl-8b-instruct` resolves to `Qwen/Qwen3-VL-8B-Instruct` (in
  `services/model_registry.yaml`). The endpoint comes from `MODEL_BASE_URL` and
  `MODEL_API_KEY`.
- **Requests.** `payload()` and `request(messages, options=..., seed=...)`.
  Passing `requester=fn` replaces HTTP, which is the injection point for tests
  and dry runs. `parse(response, 0)` returns the text.
- **Images.** Images are sent as `image_url` data URLs.
  `media.encode_image_to_base64` resizes according to environment variables, so
  the semantic action encodes PNG itself.
- **No structured output.** There is no `response_format` or guided decoding,
  and the option allowlist rejects unknown options.
- **Usage.** The provider's `usage` is returned in the response. The agent sums
  it, and the semantic action records it per call. Latency is measured
  client-side.
- **Offline test guard.** `tests/conftest.py` removes credentials and refuses
  non-loopback sockets. **Loopback is allowed**, so a vLLM server on localhost
  would be reachable. The pilot runner therefore adds its own gates: a dry run
  requires an injected requester, and a live run requires an authorization bound
  to the manifest digest.

## 6. Where to change things next

| Goal | Where | Notes |
| --- | --- | --- |
| Run the live semantic pilot | `scripts/bite/run_semantic_verification_pilot.py --mode live` | Needs the authorization JSON; output goes to `outputs/bite/phase04c1f/` |
| Analyze the pilot | new script: `collect_observations` → `finalize_feature_table` → join labels (`phase04b2b3/offline_labels/initial_candidate_labels.jsonl`) and 4C-1D runtime Zoom features by `state_id` → `semantic_comparison_design.logo_crossfit` + `evaluate_comparisons` → `classify_pilot` | Do not edit the frozen design; any change is a new version |
| A new action contract | copy the `semantic_observation_schema` pattern: versioned prompt/ontology digests, strict parser, whitelist case fields | Never pass GT or detector score to a verifier |
| A matched SAM 3 worker | `sam3_attested_worker.py`, `matched_worker_bridge.py` | Prepared; not authorized |
| Held-out validation | `validation_protocol.py`, `validation_model_contract.py` | Frozen; not authorized |
| Agent integration | requires editing `bootstrap.py` allowlists and config validation | Production change; out of scope so far |

## 7. Practical commands

```bash
cd /home/ai5377/OpenVLHarness
# targeted BITE tests
.venv/bin/python -m pytest tests/bite tests/bite_calibration tests/bite_collection -q
# full suite (offline; loopback-only network)
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check <changed files>
# Phase 4C-1E reproduction (no model calls)
.venv/bin/python scripts/bite/evaluate_zoom_action_utility.py
.venv/bin/python scripts/bite/prepare_semantic_verification_pilot.py
.venv/bin/python scripts/bite/assess_phase04c1e_readiness.py
.venv/bin/python scripts/bite/build_phase04c1e_manifest.py
```

Each phase ends with a `build_phase<id>_manifest.py`. It records source,
script, doc, test and artifact SHA-256 values, along with the git commit, branch
and working-tree status.

## 8. Discrepancies against the original handoff prompt

- The handoff message was cut off by its own size limit at "Generate a final
  artifact manifest containing: - File identities". Nothing after that point was
  seen.
- `docs/bite/PHASE_04C1C_REVISED_REPORT.md` and every other document the
  handoff named exist. No substitutes were needed.
- The handoff's "TASK_V_PRIOR_RESULTS.md" exists alongside
  `TASK_V_PRIOR_CALIBRATION_EXPERIMENT.md`. Both describe Phase 4C-1A.
- The 4C-1D readiness record states
  `ZOOM_INCONCLUSIVE_MORE_FIT_EVIDENCE_NEEDED`. The researcher's later
  instruction redirected work toward complementary evidence. Phase 4C-1E's
  utility screen documents why another Zoom-only collection is not justified for
  this endpoint.

## 9. Phase 4C-1F update (2026-11-02)

Status: offline preflight PASS. Authorization is absent, and no VLM call was
made.

**New modules**

| Module | Purpose |
| --- | --- |
| `semantic_pilot_preflight.py` | Re-derives every frozen case from its stored state, reproduces render digests and group selection, validates original raw-before-GT chains, builds the scoped identity table, applies the smart-resize token rule, and extracts measured Zoom latencies from GT-free branch records |
| `semantic_pilot_analysis.py` | Post-collection pipeline written before data: lineage validation, finalize-then-join, frozen LOGO models, paired bootstrap (seed 467), decision and cost screens, stratified failure analysis, frozen rule plus guard overlay |
| `action_utility_screen.sample_size_sensitivity` | Hoeffding vs empirical-Bernstein vs normal-approximation group counts |

**Runner changes** (`semantic_pilot_protocol.py`)

- `validate_live_binding` checks the ontology, model id, endpoint, loopback,
  run directory, cap ≤ case count, and the optional `valid_until_utc`.
- The cap is cumulative across invocations, so canary and resumes are included.
- `--canary N` allows N ≤ 5.
- The run halts after 3 consecutive failures, or when the served model differs.
- Each observation gains `execution_context`: authorization digest, timestamps
  and scoped identity.
- `validate_authorization` itself is unchanged.

**New scripts**

- `preflight_semantic_pilot.py`
- `analyze_semantic_pilot.py`
- `assess_phase04c1f_readiness.py`
- `build_phase04c1f_manifest.py`

**Live run location:**
`outputs/bite/phase04c1f/raw_observations/semantic_pilot_run`. This replaces
the 4C-1E plan's `outputs/bite/phase04c1f/semantic_pilot_run`, so that the run
sits under the `raw_observations/` folder the phase layout specifies.

**Label source for the pilot analysis:** the 4C-1D OOF M0 rows
(`label`, `annotation_scope_audit`), checksum-verified against the 4C-1D
inventory.

**Environment facts**

- vLLM 0.18.1 lives in `.venvs/vllm`, launched by `scripts/service.sh qwen` on
  `127.0.0.1:8222`.
- Qwen3-VL-8B is cached at revision `0c351dd…` under
  `.cache/huggingface/hub`, and its weights are verified against their blob
  names.
- `tests/conftest.py` allows loopback connections, so tests must always inject
  a `requester`.

## 10. Phase 4C-1G update (2026-11-04, code-verified)

Status: ENGINEERING_SUCCESS_WITH_BLOCKERS. 0 real model calls; neither the 4C-1F
semantic authorization nor the new 4C-1G final-answer authorization exists.

**Protocol.** Protocol A (controlled fixed-decoder counting probe) only. Task V
states have no agent conversation prefix (controlled capability execution), so
genuine agent continuation (Protocol B) is not reconstructible without new agent
and SAM 3 runs.

**New modules** (`evaluation_kit/bite_calibration/`)

| Module | Purpose |
| --- | --- |
| `task_level_probe_protocol.py` | Counting task, frozen prompt/parser digests, GT-blind task manifest from the 4C-1E semantic manifest plus stored states, pre-call features, `validate_branch_authorization` |
| `branch_evidence_renderer.py` | B0–B3 message rendering from stored evidence; original JPEG and stored crop PNG are sent unmodified; semantic lineage check |
| `task_level_branch_runner.py` | `run_branches` (cumulative cap plus phase-total cap that counts semantic dispatches), `finalize_outcomes` (immutable), `build_count_labels` (only after verified finalization), `join_outcomes` |
| `oracle_headroom.py` | Hindsight best-fixed/oracle/gaps, `group_bootstrap` (generic, paired, seed 467), LOGO influence, strata |
| `learnable_headroom.py` | P0–P3 LOGO selectors, recovery fraction |
| `task_level_decision_analysis.py` | Transitions, combined-evidence counts, costs, predeclared `classify` |

**Scripts:** `prepare_oracle_headroom_pilot.py`, `preflight_oracle_headroom.py`,
`run_oracle_headroom_branches.py`, `analyze_oracle_headroom.py`,
`assess_phase04c1g_readiness.py`, `build_phase04c1g_manifest.py`.

**Facts worth knowing**

- `selected_detector_rank` is non-zero for 46 of the 101 tasks. Always name the
  anchored proposal by rank, never assume P1.
- Each Zoom branch record holds the crop PNG at
  `raw_collection/observations/artifacts/<focused.source_image.sha256>.png`;
  focused boxes are in crop pixels, mapped by `source_frame.child_to_root_transform`.
- Count labels are the official Aquarium COCO annotations whose category name
  equals the query (casefold). `matching.load_coco` drops invalid boxes, and the
  dropped count is recorded.
- Branch-run unit ids are `<task_id>:<branch>`, and the directory names replace
  `:` with `_`.
- The run configuration includes the authorization digest. Canary and resume
  must therefore use the same authorization file, and a new authorization needs a
  new run directory.
- When the semantic pilot runs, the historical test
  `test_no_semantic_run_or_results_exist_without_authorization` will fail by
  design and needs a dated replacement (see `PHASE_04C1G_REPORT.md`).
