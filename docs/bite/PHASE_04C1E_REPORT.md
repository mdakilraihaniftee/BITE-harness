# Phase 4C-1E: evidence-utility screening, complementary visual verification and action-space redesign

Report date: **2026-11-02**. Status: **ENGINEERING_SUCCESS /
ZOOM_ONLY_COLLECTION_NOT_JUSTIFIED / SEMANTIC_PILOT_PREPARED_PENDING_AUTHORIZATION**.

This phase was offline. It made no SAM 3 or VLM inference, no download and no
worker start. It did not access validation or internal-test data, did not change
the agent or evaluator, and created no commit. The only model calls were to an
injected local mock requester.

## What was achieved, kept apart by kind

| Kind | Result |
| --- | --- |
| Engineering | Semantic action, GT-free features, a GT-blind 101-case pilot manifest, a gated and resumable runner, and a frozen paired design. Everything mock-validated; 57 new tests; full suite 923 passed / 449 subtests / 0 failures. |
| Development-set prediction (Zoom) | No new fitting. The screen of the 4C-1D predictions shows no reliable benefit. |
| Conditional information | Squared-loss decomposition: the fitted Zoom model moves beliefs by about 0.01 RMS. This describes that fitted model and is not an information ceiling (corrected in 4C-1F). |
| Decision value (offline, fixed policy) | Always-Zoom has negative utility at .50. At .75 the benefit is one avoided error from one group, with break-even penalty 0.0025 per call. |
| Semantic action evidence | **None yet.** Real inference has not been authorized. |
| Held-out / end-to-end / guarantees | None. A theory note shows that distribution-free guarantees are vacuous at Zoom-sized effects. |

## Stage A: Zoom utility screen

Inputs were the 4C-1D OOF predictions for 203 candidates in 30 groups. Their
digests matched the 4C-1D checksum inventory, and nothing was refit. With 406
extra logical calls:

- **IoU .50.** 0 errors avoided and 2 introduced. Gross error utility −0.009852
  [−0.025126, 0]. Gross Brier utility −0.000235 [−0.001262, +0.000760]. There is
  no break-even penalty.
- **IoU .75.** 1 error avoided and 0 introduced. Error utility +0.004926
  [0, +0.015306], with break-even λ = 0.002463 error units per call. Brier
  utility +0.000688 [−0.000188, +0.001732]. Dropping the 3 most favorable
  groups (of 30) removes the entire Brier gain (−0.000007). Dropping the one
  favorable group makes the error gain 0.

The decision is `ZOOM_ONLY_COLLECTION_NOT_JUSTIFIED_FOR_TASK_V_VERIFICATION`,
under a rule fixed before the screen was computed but after 4C-1D was known.
This does not mean Zoom is useless in general, and no action dominance is
claimed. Details: `BITE_ACTION_UTILITY_SCREENING.md`.

## Stage B: existing VLM backend

The backend is `ModelAdapter`, an OpenAI-compatible client (vLLM;
`qwen3-vl-8b-instruct` → `Qwen/Qwen3-VL-8B-Instruct`), with a `requester=`
hook for injection. The repository has no structured-output support, and the
VLM is never called by BITE collection. Adding a capability would mean editing
the production allowlist in `bootstrap.py`. The action is therefore an offline
experiment adapter that reuses `ModelAdapter` unchanged.

## Stages C–E: `semantic_region_inspect_v1`

- **Rendering.** Deterministic: a full frame and a context crop, each with a
  magenta outline drawn outside the box.
- **Prompt.** Neutral and identical for every case. It contains no query, no
  score, no annotation information and asks for no probability. Digest
  `fc0f1b15…`.
- **Ontology.** Frozen (digest `d03ffffc…`). It keeps the dataset categories
  distinct from biological taxa: fish ↔ shark/stingray is recorded as
  `taxonomic_overlap`, never as a match.
- **Parsing.** Strict, with no repair. Statuses are `valid`, `empty_response`,
  `malformed_json`, `schema_violation`, `timeout` and `execution_failure`.
- **Observation records.** Full lineage, a redacted payload, usage and latency,
  `checkpoint_attested: false` and an explicit dependence block. Likelihood
  multiplication with SAM 3 is prohibited.
- **Features.** GT-free and categorical, with explicit missingness. Mock records
  are rejected, and a digest-bound finalize-then-join step protects the labels.

Found in passing: collection `candidate_id` and `joint_observation_id` values
are state-local. The 203 candidates share 15 candidate ids. Earlier analyses
were unaffected because they keyed on `state_id`. The new lineage keys
include `state_id`.

## Stage F: frozen pilot

- 15 of the 30 expansion groups, chosen with `Random(465)` and no labels, no
  performance and no label-balanced folds.
- 105 states, of which 4 have no candidate, leaving **101 semantic cases** (cap
  105, not triggered).
- 0 validation or internal-test cases, and 0 new SAM 3 calls.
- Manifest digest `aaa9d61c…`. Estimated 101 requests, about 102k visual and
  about 71k text input tokens, and at most 25.9k output tokens.
- A mock run over all 101 real cases passed contract, invariance and resume
  checks.

Live execution requires an authorization JSON bound to the manifest digest, the
prompt digest, the model alias and a dispatch cap. Its output must go to
`outputs/bite/phase04c1f/`.

## Stage G: frozen paired comparison

M0, MZ, MS and MZS (plus a secondary MS-loc) are all refit with the same
leave-one-group-out folds on the pilot rows. The primary estimand is
*Brier(MS) − Brier(M0)*, with a group bootstrap using seed 467. The pilot
decision rule is prespecified:

- `REVISE_CONTRACT_AS_NEW_VERSION`
- `PROCEED_TO_LARGER_FIT_COLLECTION`
- `STOP_SEMANTIC_ACTION_FOR_TASK_V`
- `INCONCLUSIVE`

None of these outcomes establishes significance or calibration. A synthetic
injected-signal control is detected, and a null signal is not rewarded. Design
digest `bd1b2a12…`.

## Stages H–I: theory and task extension

`BITE_DEPENDENT_EVIDENCE_VALUE_THEORY.md` restates the classical identities:

- Brier gain = E[(pa−p0)²] under correct specification;
- the 0–1 VOI is zero unless an observation can cross the threshold;
- chain-rule conditioning for dependent observations.

It adds an empirical cross-term diagnostic, and a sample-size calculation
showing that Hoeffding-type guarantees would need about 240k groups at Zoom-sized
effects, compared with about 600 at effects of ±0.1. No new theorem or novelty
is claimed.

`TASK_V_AGENT_TASK_EXTENSION_PROPOSAL.md` defines T1, presence verification.
T1 reuses the stored seven-query expansion SAM 3 outputs. Only policies whose
actions and observations are all represented in the recorded branches can be
replayed exactly offline. Adaptive policies cannot (corrected in 4C-1F).

> **Phase 4C-1F corrections (2026-11-02).** Two statements in this report were
> narrowed:
>
> - The fitted-model probability displacement is not an information ceiling.
> - Exact offline evaluation requires coverage of the policy's actions and
>   observations.
>
> The Hoeffding sample sizes are worst-case and distribution-free. They are not
> a universal requirement. See `BITE_DEPENDENT_EVIDENCE_VALUE_THEORY.md`. No
> measurement was changed.

## Limitations and open risks

- The semantic pilot is small (15 groups) and dominated by class absence. Any
  benefit may reflect absence detection under a design-imposed query
  distribution.
- The pilot reuses fit data whose labels earlier phases already used for
  development. It is a feasibility pilot, not an independent test.
- Neither the VLM nor the historical SAM 3 checkpoint is attested.
- Structured output is not enforced, so contract validity must be measured.

## Artifacts

- Root: `outputs/bite/phase04c1e/`. Subfolders: `integrity/`,
  `utility_screening/`, `semantic_action/`, `semantic_pilot_manifest/`,
  `semantic_observation_contract/`, `theory/`, `execution_readiness/`,
  `tests/`, `readiness/`.
- Inventory files: `manifest_checksums.json` and `implementation_manifest.json`.

Aquarium Combined (Roboflow), obtained through the GLIP-curated archive, is
attributed under CC BY 4.0. Images and derived visual artifacts remain internal.
No rendered images are stored in the outputs; only their digests are kept.
