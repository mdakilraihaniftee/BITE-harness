# Task V semantic verification action: `semantic_region_inspect_v1`

Status: **IMPLEMENTED AND MOCK-TESTED — NO REAL INFERENCE**.

## Why this action

Zoom→focused SAM 3 sends a crop of the original proposal back to the same
detector. Exact repeats were identical in 73 of 73 cases, and Zoom did not
reliably improve correctness prediction (Phase 4C-1D; see
`BITE_ACTION_UTILITY_SCREENING.md`). A *different* visual mechanism, a frozen
VLM inspecting the region, can fail in different ways than the detector does. In
particular, 191 of the 206 annotation negatives at IoU .50 are queries for a
class that has no annotated instance in the image. For a class-naming verifier,
that is exactly the kind of error that could become visible. Whether it actually
helps is an empirical question for the pilot. It is not assumed here.

## Backend: reuse, no production change

This action uses the existing
`openvlharness.services.models.ModelAdapter` (`openvlharness/services/models.py`):

- **Alias:** `qwen3-vl-8b-instruct`, which resolves to
  `Qwen/Qwen3-VL-8B-Instruct` (`openvlharness/services/model_registry.yaml`).
  The protocol is OpenAI-compatible Chat Completions served by vLLM.
- **Construction:** `semantic_region_action.build_adapter` builds the adapter
  with `retry=0`, so one logical dispatch is exactly one physical request. The
  options are `max_tokens=256` and `temperature=0.0`, and the request seed is 0.
- **Test injection:** tests and dry runs inject the adapter's existing
  `requester=` hook. A dry run refuses any adapter that has no injected
  requester.
- **Untouched production code:** the capability allowlist
  (`openvlharness/bootstrap.py`), the tool registry, the agent loop, prompts and
  the evaluator are all unchanged. A regression test checks
  `git status --porcelain` on those paths. Adding a capability would have meant
  editing the production allowlist, so this action stays an offline experiment
  adapter in `evaluation_kit/bite_calibration/`.
- **Image encoding:** images are encoded as PNG directly from the rendered
  pixels. `media.encode_image_to_base64` is deliberately not used, because it
  resizes according to environment variables and would make the input bytes
  depend on the environment.

## Input rendering (`bite.semantic_region_render.v1`)

Rendering is deterministic: the same inputs give byte-identical PNGs, and the
pilot manifest pins each case's render digest.

1. Load the stored source image. Its SHA-256 must match the frozen
   `source_image_sha256`.
2. Draw a magenta outline (255, 0, 255) just outside the candidate box. The
   stroke is max(2 px, 0.4% of the longer image side).
3. Produce image 1, the full outlined frame, and image 2, a context crop. The
   crop adds a margin of max(32 px, 0.5 × the longer box side) on every side,
   clipped to the image.
4. Never upsample. Downsample with LANCZOS only if an edge exceeds 1024 px.

## Observation record and lineage

`inspect_region(case, adapter)` returns `bite.semantic_region_observation.v1`,
which contains:

- **Lineage:** source image digest; `original_candidate_id`; candidate box;
  `initial_observation_id`, `initial_controlled_call_id` and `initial_action_id`
  of the SAM 3 grounding; `parent_snapshot_id`; and the full render metadata
  with per-image digests.
- **Contract identity:** prompt and ontology versions and digests.
- **Backend:** model id, protocol, options, seed, and the model name the server
  reports. `checkpoint_attested: false`, because an OpenAI-compatible endpoint
  exposes no load-time weight identity.
- **Request:** a redacted copy of the payload with images replaced by their
  digests, plus that copy's digest.
- **Execution:** status, latency in ms, the provider's `usage` (tokens), error
  type and detail, and a logical cost of 1.
- **Response:** raw text, response status, parse detail, validated observation,
  and consistency flags.
- **Dependence block:** shares the source image with the initial grounding;
  region derived from the initial proposal; `statistically_independent_...:
  false`; `likelihood_multiplication_permitted: false`.

The case whitelist (`CASE_FIELDS`) admits no GT field and no detector score. Any
other key raises an error. The `query` travels with the case so compatibility
can be computed afterwards, but it is never sent to the model
(`query_sent_to_model: false`).

> **Identifier caveat found in this phase.** Collection candidate IDs and
> `joint_observation_id`s are *state-local*. They are derived from the branch,
> the observation and the rank (`evaluation_kit/bite_collection/executor.py:137`).
> The 203 expansion candidates share only 15 distinct `candidate_id` values and
> one prefix `joint_observation_id`. Earlier analyses keyed on `state_id` and
> are unaffected. Any lineage join must use `(state_id, candidate_id)`. The
> semantic `case_id` and `observation_id` both include `state_id`.

## Runtime features (`bite.semantic_runtime_features.v1`)

`semantic_feature_extractor.extract_features` produces:

- the compatibility category, with one-hot indicators, plus
  `semantic_nonsupport` (dataset-category conflict, other object, or background);
- each categorical field with its own one-hot values and an explicit
  `*_missing` indicator;
- failure indicators: parse, timeout, execution;
- a count of consistency flags.

It never produces a probability or confidence value. The extractor rejects:

- mock records, unless `allow_mock=True` is passed;
- records produced under a different prompt or ontology digest;
- any field name in the GT marker set.

`finalize_feature_table` computes a row digest. `join_offline_labels` will join
labels only to a table whose rows still match that digest, and it checks that
each label refers to the same original candidate hypothesis.

## What this action is not

- It is not a verifier of benchmark correctness. Semantic agreement does not
  establish IoU ≥ τ.
- It is not independent evidence. No likelihood multiplication with SAM 3 is
  allowed.
- It is not a calibrated probability source.
- It is not in production. The agent cannot call it.
