# Task-level probe protocol (Phase 4C-1G)

Frozen 2026-11-04, before any final-answer data existed. The code is the source
of truth:
- protocol: `evaluation_kit/bite_calibration/task_level_probe_protocol.py`
- renderer: `branch_evidence_renderer.py`
- runner: `task_level_branch_runner.py`

Frozen digests:

| Item | SHA-256 |
| --- | --- |
| Task manifest | `e97075c488f334cfd0c5d674070e44a9e3c61ecb077dacf0c44a3d8addf8e45a` |
| Prompt template | `47d89da777bb8aa5dc1e543b8b859702d808e8768b4bb76f655ee8df96b8c911` |
| Answer parser | `357446b0b4f2be3226d4449794a9dce8a1fc33b73f6ef69a8d78ddae39bb9438` |
| Renderer contract | `af1389b34e8b53cef4f73c1f20ce1032174420c6736ea4f3ebd56fe8b4f80fb6` |
| Analysis plan | `7a809c11ba049f9e1192d04f1af67e0068bc7cb60653ffbdd9f16e922b3449ab` |

## 1. Which protocol, and why

**Protocol A: controlled fixed-decoder answer probe.** Protocol B (genuine agent
continuation) is not used.

The code audit found the following:

- The 4B-2B-3 Task V states were produced by `evaluation_kit/bite_collection`.
  It runs capabilities through the public capability lifecycle
  (`origin: controlled_collection_action`) and never calls the VLM.
- No agent conversation, model turn or tool-call message exists for these
  states. A genuine `Agent._run` prefix therefore cannot be reconstructed.
- Capturing new prefixes would mean running the production agent with new model
  calls, and re-collecting SAM 3 outputs on a different backend state. That is
  out of scope.

The results therefore describe **how a fixed Qwen3-VL decoder responds to
different recorded evidence presentations**. They do not describe what the
autonomous OpenVLHarness agent would do. The two protocols must never be pooled.

## 2. Population

The population is the Phase 4C-1E frozen semantic pilot (seed 465):

- 15 calibration-fit source groups and 105 initial query states;
- 4 no-candidate states excluded, leaving **101 candidate-present tasks**;
- one source group has 3 tasks, and each of the other 14 has 7.

The manifest is rebuilt from the stored states only (`initial_raw_state.json`,
GT-free branch records and stored image artifacts). It reproduces exactly, and a
test checks this. Paths containing `offline_labels` are refused.

These groups were already used in calibration-fit experiments. This is
**development evaluation, not held-out validation**.

## 3. Task and scoring

The question is: *"How many {query} objects are visible in this image?"*

- The common header adds the frozen ontology definition of the queried class
  and the statement that the 7 dataset categories are mutually exclusive.
- The footer asks for exactly `{"count": <non-negative integer>}`.
- Abstention is **not offered**.

**Reference.** The reference is the number of official Aquarium COCO annotations
of the image whose category name equals the query, case-insensitive, with all
`iscrowd` values counted. It is a benchmark proxy, and COCO-style annotation is
not guaranteed exhaustive.

**Parser** (`parse_count`, strict). It accepts:

- one JSON object with exactly the key `count`, whose value is a non-negative
  JSON integer;
- the same object inside one Markdown fence;
- a bare non-negative integer.

Everything else is invalid. Invalid answers have loss 1 and are reported
separately.

**Metrics.** The primary metric is exact-count accuracy, with loss
`L = 1[ŷ ≠ Y]`. The secondary metric is presence, `1[ŷ > 0] = 1[Y > 0]`,
derived from the same answer; it is not an independent experiment. Results are
reported separately for count-zero and count-positive tasks, and by query class.

## 4. Branches

| Branch | Evidence beyond B0 | Images | Incremental logical cost |
| --- | --- | ---: | ---: |
| B0 | none: original image + recorded initial SAM 3 grounding | 1 | 0 |
| B1 | recorded Zoom crop (Image 2) + focused SAM 3 proposals | 2 | 2 |
| B2 | recorded `semantic_region_inspect_v1` structured output | 1 | 1 |
| B3 | B1 evidence, then B2 evidence (frozen order) | 2 | 3 |

**What every branch shares:**

- the same system prompt, header and footer (checked by test and by digest);
- Image 1, the original image bytes, unmodified;
- the initial grounding block (all proposals in detector-rank order, boxes in
  Image 1 pixels, scores to 3 decimals, masks stated but not shown);
- decoding: `temperature 0.0`, `max_tokens 128`, `seed 0`.

**How the extra evidence is rendered:**

- **Zoom.** The executed arguments, the crop rectangle, the pixel offset and the
  stored crop artifact as Image 2. Focused proposals are given in Image 2
  coordinates and mapped to Image 1 with the recorded transform.
- **Semantic.** The six contract fields. A failed observation is rendered as
  `Status: failed (<status>)` with no fields. B2 and B3 refuse to render when
  the semantic observation is absent or its lineage does not match
  (case, state, candidate, image and render digests).
- **Never rendered:** a reference count, a correctness hint, a branch-quality
  hint or any GT.

**Caveats:**

- B1 and B3 add an image and roughly 2× the text (median 1,127 versus 419
  evidence characters for B1 versus B0). Branch effects are effects of the whole
  **evidence-presentation intervention**, not pure information gain.
- The semantic verifier and the decoder are the same Qwen3-VL-8B weights, with
  different prompts and images. The semantic observation is **not an independent
  model oracle**.
- B3 is a **combined-evidence** branch. Semantic inspection uses the original
  candidate box, not the Zoom output, so neither action enables the other.

## 5. Execution ordering (raw before GT)

For each `(task, branch)` unit the runner:

1. verifies the frozen task;
2. renders the branch input;
3. persists `branch_input.json` (redacted payload and digests);
4. appends a stage event;
5. sends exactly one request (no transport retry);
6. persists `raw_response.json` and `final_answer.json`;
7. seals the unit with content digests and a second stage event.

`finalize_outcomes` then requires all 404 live units, writes and hashes
`finalized_outputs/raw_outcome_table.jsonl`, and logs the event. It is immutable.

Only `build_count_labels` opens annotations, through
`AquariumDatasetAdapter.load_offline_ground_truth`. It refuses unless the
finalized table digest and its event verify, and it logs the table digest it
was joined to.

## 6. Authorization and budget

Two independent researcher-written gates exist. Neither has been written.

1. **Phase 4C-1F semantic pilot** (unchanged): runner
   `run_semantic_verification_pilot.py`, cap ≤ 101, requirements in
   `outputs/bite/phase04c1f/authorization/`.
2. **Phase 4C-1G final answers**: runner `run_oracle_headroom_branches.py`.
   Requirements are in
   `outputs/bite/phase04c1g/authorization/authorization_requirements.json`. The
   authorization must bind:
   - the task manifest, prompt, parser and renderer digests, and the semantic
     manifest digest;
   - the model alias and id, and the exact endpoint (loopback unless separately
     approved);
   - the branch set, the output directory and the semantic-run directory;
   - a cumulative final-answer cap (≤ 404) and a **cumulative phase-total cap
     (semantic + final answers ≤ 505)**;
   - the researcher's name (an agent name is rejected) and a timezone-aware
     expiry.

Canary and resume both count toward the caps. A canary is all authorized
branches for ≤ 5 pending tasks. The run halts after 3 consecutive transport
failures or a served-model mismatch, and partial or corrupt units block further
dispatch.

## 7. Commands

All commands run from the repository root.

```bash
bash scripts/service.sh qwen                                                 # researcher-operated
MODEL_BASE_URL=http://127.0.0.1:8222/v1 .venv/bin/python scripts/bite/run_semantic_verification_pilot.py \
  --mode live --authorization <4c1f_auth.json> --output outputs/bite/phase04c1f/raw_observations/semantic_pilot_run --canary 5
#   ... inspect engineering fields only, then the same command with --resume instead of --canary 5
MODEL_BASE_URL=http://127.0.0.1:8222/v1 .venv/bin/python scripts/bite/run_oracle_headroom_branches.py \
  --mode live --authorization <4c1g_auth.json> --output outputs/bite/phase04c1g/raw_continuations/branch_run --canary 5
#   ... inspect engineering fields only (no answers vs labels), then --resume
.venv/bin/python scripts/bite/analyze_oracle_headroom.py
.venv/bin/python scripts/bite/assess_phase04c1g_readiness.py
.venv/bin/python scripts/bite/build_phase04c1g_manifest.py
```

A canary check may inspect only these engineering fields:

- `final_answer.json` `response_status`;
- `served_model_reported`;
- `latency_ms`;
- `token_usage`;
- the presence of `raw_text`.

It must not compare counts with anything.
