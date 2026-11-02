# Task V semantic pilot: execution report

Status: **NOT EXECUTED. AUTHORIZATION ABSENT. Offline preflight PASS.**
Real VLM calls: **0**. SAM 3 calls: **0**.

## 1. Authorization gate

No authorization artifact exists. The search location was
`outputs/bite/phase04c1f/authorization/`, and no newer authorization file was
found anywhere on the filesystem. No authorization file was created by the
coding agent. As specified, the phase stopped after offline preflight.

From Phase 4C-1F on, the runner (`semantic_pilot_protocol.validate_live_binding`)
requires a researcher-written JSON containing all of the following. Missing or
mismatched fields are refused before any request is sent.

| Field | Required value |
| --- | --- |
| `live_semantic_inference_authorized` | `true` |
| `authorized_by` | the researcher's name |
| `manifest_sha256` | `aaa9d61c9749a9ad1995fbbc7bd5c529b67c463a3d2eac4ef3ad8175dc97629f` |
| `prompt_sha256` | `fc0f1b15bf0dd0074ac9586aa4f9c05b2758c3d18a709dea1d0bdd3cb0c035ea` |
| `ontology_sha256` | `d03ffffc3a3df202c0d823d7afbe67a817319b79dba196ebe8530cd093a52d84` |
| `model_alias` / `model_id` | `qwen3-vl-8b-instruct` / `Qwen/Qwen3-VL-8B-Instruct` |
| `endpoint` | `http://127.0.0.1:8222/v1/chat/completions`, which must equal the adapter's endpoint |
| `output_dir` | `outputs/bite/phase04c1f/raw_observations/semantic_pilot_run` |
| `dispatch_cap` | integer 1–101, **cumulative** over canary, main run and every resume |
| `valid_until_utc` (optional) | the runner refuses after this time |
| `non_loopback_endpoint_approved` (optional) | required only for a non-loopback endpoint |

The machine copy is `outputs/bite/phase04c1f/authorization/authorization_requirements.json`.
That file is a requirements list, not an authorization: its placeholder cap is
a string, so the validator rejects it, and a test checks this.

## 2. Frozen pilot integrity: PASS

The check is `scripts/bite/preflight_semantic_pilot.py`, and its output is
`preflight/pilot_integrity.json`. It reads no labels.

- **Every case re-derived.** All 101 cases were rebuilt from their stored
  `initial_raw_state.json` and snapshot image, and each matched the frozen case
  field for field. All 101 rendered-input digests were reproduced
  byte-for-byte.
- **Selection reproduced.** `Random(465).sample(30 groups, 15)` gives exactly
  the 15 frozen groups. Those groups hold 105 states; the 4 no-candidate states
  match the frozen exclusion list, and none of them is a case.
- **Original provenance valid.** Each of the 101 states' original collection
  stage-event chains is valid (`runtime_started → raw_finalized →
  offline_gt_open_authorized → labels_finalized`), and the `raw_completion`
  digests match.
- **Score and query consistent, score never sent.** For every case, the
  initial SAM 3 score in the raw state equals the score in the 4C-1D GT-free
  runtime table, and the query matches. The score is stored in
  `preflight/case_identity.jsonl` and is never sent to the model.
- **Frozen 4C-1E artifacts unchanged.** The file SHA-256 of each matches the
  4C-1E checksum inventory:

  | Artifact | File SHA-256 |
  | --- | --- |
  | manifest | `7aed0c0e8c84d53be2afdb40561290e1d24c4831a6b9e914a8f2ad05ddd6e8fe` |
  | contract | `6a62beebbedc379e0d1174bc4e86dd1a20546075c03149bb5524012a6b0f9a67` |
  | design | `b5038c5ab6bdce086bfd4b0e0f66530db288332218b61160d7eb36dc1925caec` |
  | execution plan | `921b86fb1c69e49b665880bf7f8bb376dc90d17339faa130df2c4fb07d81c592` |

  Two kinds of digest appear in this document. `manifest_sha256` (`aaa9…`) is
  the digest of the manifest's canonical-JSON content. The file digest above is
  the hash of the bytes on disk.
- **Design digest unchanged.** `bd1b2a12b1a344c16a1b87dc4bfc6a69cc0af11b122a61116c4b0f3d31108336`
  equals a fresh `design_record()`.

### Identifier safety

The 101 cases use only **12 distinct local `candidate_id` values**, and 95 cases
share an id with at least one other case. Candidate id alone is therefore
**not** a safe key. Every record now carries a scoped identity
`(source_run_id, state_id, candidate_id, action_version)`, and all 101 are
unique. Labels join on `state_id`, with an equality check on `candidate_id`.
Dispatch and resume key on `case_id`, which is derived from `state_id` and
`candidate_id`.

## 3. Backend readiness and provenance

| Item | Finding |
| --- | --- |
| Client | existing `ModelAdapter`, alias `qwen3-vl-8b-instruct` → `Qwen/Qwen3-VL-8B-Instruct`, Chat Completions |
| Endpoint (from `.env`, host only) | `127.0.0.1:8222`, loopback. An API key is configured; its value was never read into outputs. |
| Service | **not running**: nothing listens on 8222 and there is no vLLM process |
| Launch command | `bash scripts/service.sh qwen` (researcher-operated). vLLM 0.18.1, `--served-model-name Qwen/Qwen3-VL-8B-Instruct`, bf16, `--max-model-len ${QWEN_CONTEXT_LENGTH:-168000}`, `--max-num-batched-tokens 16384`, `--max-num-seqs 4`, `HF_HUB_OFFLINE=1` |
| GPUs | 4 × NVIDIA L40S (46 GB), all idle at preflight |
| Weights cache | `refs/main` = pinned `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b`. All 4 safetensors shards (17.5 GB) re-hashed and matched their LFS SHA-256 blob names: `CACHE_CONTENT_VERIFIED_ONLY`. |
| Load-time identity | **UNVERIFIED.** An OpenAI-compatible endpoint exposes only the served model *name*. The runner records it per response and halts if it differs from the authorized model id. |
| Decoding | `temperature 0` (greedy), `max_tokens 256`, `seed 0`. The model's generation defaults (top_k 20, top_p 0.8, temperature 0.7) have no effect under greedy decoding, and repetition penalty is 1.0. |
| Timeout / retries | 120 s per request; transport retries 0. A failure is recorded, counted against the cap, and never retried. The run halts after 3 consecutive timeouts or execution failures. |
| Disk | about 716 GB free |

### Privacy

Images go only as inline base64 in the request body to the authorized endpoint.
A loopback endpoint is required by default. The action never uses the image
host or upload utilities. **Observation:** an unrelated process launched from
another project (`cloudflared tunnel --url http://127.0.0.1:8112`) is running
on this machine. It exposes an image host serving
`/home/ai5377/ARGUS/.cache/logo-validation-host`. The semantic pilot does not
use it. It was left untouched, but the researcher should confirm it is
intended.

## 4. Request estimate (supersedes the 4C-1E estimate)

This estimate uses the cached processor's own limits (`min_pixels` 65,536 and
`max_pixels` 16,777,216, with a resize factor of 32) and token counts from the
pinned `tokenizer.json`. File: `preflight/request_estimate.json`.

| Item | Estimate |
| --- | ---: |
| Requests | 101 |
| Visual input tokens | ≈ 102,160 (832–1,536 per request) |
| Text input tokens | ≈ 51,409 (509 per request, including about 32 for ChatML) |
| Output tokens (cap) | 25,856 |
| Largest request | ≈ 2,301 tokens; fits the 168,000-token context |
| Image payload | 3.2 MB maximum per request; 185 MB in total over loopback |

The 4C-1E estimate of about 70.7k text tokens used a character heuristic, and
its visual rule ignored the processor's minimum pixel count. Runtime and GPU
time cannot be promised from these figures.

## 5. Execution procedure once authorized (unchanged prompt, ontology and manifest)

1. The researcher starts the service (`bash scripts/service.sh qwen`) and
   writes the authorization JSON.
2. **Canary.** Run
   `run_semantic_verification_pilot.py --mode live --authorization <file> --output outputs/bite/phase04c1f/raw_observations/semantic_pilot_run --canary 5`.
   This runs the first 5 frozen cases in manifest order, and they count toward
   the cumulative cap. Inspect the parse status, served model, persisted raw
   output and usage. **Do not look at labels.**
3. **Main run.** Rerun the same command with `--resume` instead of `--canary`.
   Completed cases are skipped after a digest check, and partial or corrupt
   cases stop the run.
4. **Analysis.** Run `analyze_semantic_pilot.py`. It refuses an incomplete,
   mock or lineage-mismatched run. It writes the GT-free table and digest
   before opening labels, and it hash-chains the stage events.

If real responses show the frozen contract cannot be interpreted, the
response must be: keep every response under v1, create a new contract version,
and ask for a new execution decision. **Never edit the v1 prompt.**
