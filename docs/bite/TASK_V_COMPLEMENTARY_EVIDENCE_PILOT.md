# Task V complementary-evidence pilot (semantic verification)

Status: **FROZEN — LIVE INFERENCE NOT AUTHORIZED, NOT EXECUTED**.

## Purpose

The pilot has five purposes:

1. Show that the semantic action can run against the real backend.
2. Measure how often responses satisfy the structured contract.
3. Measure the rates of failure, ambiguity, background and unclear responses.
4. Record the action's provenance and cost.
5. Get an early indication of whether semantic evidence complements the SAM 3
   score.

It is **not** large enough to establish a calibrated probability model, and it
is not a held-out validation.

## Frozen manifest

`outputs/bite/phase04c1e/semantic_pilot_manifest/manifest.json`, digest
`aaa9d61c9749a9ad1995fbbc7bd5c529b67c463a3d2eac4ef3ad8175dc97629f`.

| Item | Value |
| --- | --- |
| Source cohort | Phase 4B-2B-3 expansion `bite.task_v_expansion.seed418.g30.v1` (calibration_fit) |
| Group selection | `random.Random(465).sample(sorted 30 group ids, 15)` |
| Inputs to selection | group ids only: no labels, model performance, or label-balanced 4C-1A folds |
| Initial states in selected groups | 105 (15 × 7 queries) |
| Excluded no-candidate states | 4 |
| Semantic cases (= logical dispatches) | **101** |
| Cap / cap rule | 105; above the cap, keep the lowest sha256(seed:state_id). Not triggered. |
| Cases per query | starfish 15, jellyfish 15, penguin 15, fish 14, stingray 14, shark 14, puffin 14 |
| Validation / internal-test cases | 0 |
| New SAM 3 calls | 0 (stored candidates and stored source images reused) |

Cases are built only from each state's `initial_raw_state.json` and its stored
snapshot image. The image digest is checked against `source_image_sha256`. The
reader refuses any path containing `offline_labels`, `human_adjudications`,
`crossfit` or `internal_test`. **The number of annotation positives among the
pilot cases was deliberately not computed.** It will first be seen during the
offline analysis, after all raw observations are finalized.

## Resource estimate (manifest)

| Item | Estimate |
| --- | ---: |
| Physical requests | 101 |
| Visual input tokens (ceil(w/32)·ceil(h/32) per image) | ≈ 101,885 |
| Text input tokens | ≈ 70,700 (≈ 700 per case) |
| Output tokens (upper bound) | 25,856 |

Measured GPU time and monetary cost are unavailable. The runner records the
provider's `usage` and the wall-clock latency of every request.

## Execution (requires separate authorization)

- **Dry run (mock; safe):**
  `.venv/bin/python scripts/bite/run_semantic_verification_pilot.py --mode mock_dry_run --output <scratch>`
- **Live run (requires an authorization JSON):**
  `MODEL_BASE_URL=<vLLM base> .venv/bin/python scripts/bite/run_semantic_verification_pilot.py --mode live --authorization <file> --output outputs/bite/phase04c1f/semantic_pilot_run`
- **Authorization template:**
  `outputs/bite/phase04c1e/execution_readiness/semantic_pilot_execution_plan.json`.
  The JSON must contain `live_semantic_inference_authorized: true`, a named
  `authorized_by`, and the exact manifest digest, prompt digest and model alias.
  It must also give a `dispatch_cap` of at most 105.
- **Resume:** rerun with `--resume` using the same output, manifest and
  configuration. Completed cases are skipped after a digest check. If any case
  is partial or corrupt, the run stops for inspection. Each case directory keeps
  `semantic_observation.json`, `raw_response.json`, `raw_completion.json` and a
  hash-chained `stage_events.jsonl` (`runtime_started` → `raw_finalized`).
- **Failure handling:** one physical request per case and no automatic retry.
  Timeouts, execution failures and malformed or schema-violating responses are
  recorded as such, never imputed.

The mock contract validation ran the full path over all 101 real cases with
scripted responses covering every response class:

- valid (dataset category, other dataset category, background, unclear, other
  object with multiple objects, fenced JSON);
- prose-wrapped malformed JSON;
- an extra `confidence` field (schema violation);
- an empty response;
- a timeout;
- an HTTP failure.

Resume after completion dispatched 0 requests. The payload text was the same for
every case, the redacted payloads never mention "score", and no network request
was made (`semantic_observation_contract/mock_contract_report.json`).

## Frozen paired comparison (to run after the live pilot)

Design: `outputs/bite/phase04c1e/semantic_pilot_manifest/paired_comparison_design.json`
(`semantic_comparison_design.py`).

| Model | Features |
| --- | --- |
| M0 `m0_initial_score` | z(initial score) |
| MZ `mz_zoom` | z(score), z(focused−initial score; mean-imputed), score_change_observed, association ambiguous, no-alignment |
| **MS `ms_semantic`** | z(score), semantic match, semantic non-support, semantic unavailable (reference: unclear or taxonomic overlap) |
| MZS `mzs_zoom_semantic` | union of MZ and MS (secondary complementarity) |
| MS-loc (secondary) | MS plus localization = adequate |

- **Primary estimand:** *D_semantic = Brier(MS) − Brier(M0)*. Negative values
  favor semantic evidence. It is computed separately at IoU .50 and .75.
- **Folds:** every model is **refit** with the same leave-one-source-group-out
  folds on the same pilot rows. Neither the frozen full-fit prior nor the 4C-1A
  OOF predictions serve as the primary baseline.
- **Fitting:** L2 penalty λ = 1 with an unpenalized intercept, and fold-local
  standardization and imputation. If a training fold lacks either class, that
  endpoint is NON_ESTIMABLE; folds are never changed to fix it.
- **Uncertainty:** paired source-group bootstrap with seed 467.
- **Cost:** the semantic action costs 1 logical dispatch and Zoom costs 2. Tokens
  and latency are recorded. A SAM 3 call and a VLM call are **not** treated as
  equal resource cost.
- **Prespecified pilot decision:**
  - valid-response rate < 0.90 → `REVISE_CONTRACT_AS_NEW_VERSION`
  - D < 0 at both endpoints → `PROCEED_TO_LARGER_FIT_COLLECTION`
  - D ≥ 0 at both endpoints → `STOP_SEMANTIC_ACTION_FOR_TASK_V`
  - otherwise → `INCONCLUSIVE`

  None of these outcomes establishes significance or calibration.
- **Implementation check:** with a synthetic injected signal, the procedure
  detects MS < M0 with an interval excluding zero. A null signal is not
  rewarded.

## Threats to validity

- 15 groups is very small. Intervals will be wide, and positives will be few:
  the expansion as a whole had 31 positives at .50.
- The semantic action may mostly recognize *class absence*. Because the query
  design asks for all seven classes in every image, absence dominates the
  negatives. A benefit found here may not carry over to naturally selected agent
  queries (see `TASK_V_AGENT_TASK_EXTENSION_PROPOSAL.md`).
- The VLM's checkpoint is not attested, and the SAM 3 historical checkpoint
  identity is still `CACHE_CONFIG_VERIFIED_ONLY`.
- The prompt and ontology were frozen without any pilot data. If they are
  ill-suited, the correct remedy is a new version, never tuning on labels.

> **Update (Phase 4C-1F, 2026-11-02).** The live authorization must now also
> name the ontology digest, the model id, the exact endpoint and the run
> directory. The cap counts across all invocations, including the canary. The
> run directory is
> `outputs/bite/phase04c1f/raw_observations/semantic_pilot_run`. See
> `TASK_V_SEMANTIC_PILOT_EXECUTION_REPORT.md`. The frozen manifest, prompt,
> ontology and design are unchanged.
