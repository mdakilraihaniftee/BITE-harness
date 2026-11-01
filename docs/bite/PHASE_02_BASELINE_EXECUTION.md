# Phase 02 — Original baseline execution preflight

**Status: BLOCKED.** The original deployment cannot safely start with the
currently available memory on its configured Qwen GPUs. No model startup,
inference, tool execution, or benchmark scoring was attempted. The Phase 02
runtime acceptance criteria remain unmet. No BITE components were implemented.

Checked on **2026-10-29 at 20:38 UTC / 16:38 America/New_York**. Source:
`main` at `c530cdbdc6b7c4f486499eb7e5834ac2bd92692d` (`v0 updated`).
The Phase 01 report and the supplied Task 2 specification were read first.
Local source is authoritative; no upstream fetch was performed.

Evidence directory:
[`outputs/bite/reference_baseline/preflight_20261029T203800Z/`](../../outputs/bite/reference_baseline/preflight_20261029T203800Z/).
Its [structured manifest](../../outputs/bite/reference_baseline/preflight_20261029T203800Z/phase02_manifest.json)
describes a blocked preflight, **not a completed evaluator run**.

Evidence labels: **fresh** means checked in this phase; **source** means verified
from the local implementation; **pending** means runtime evidence is unavailable.
Historical smoke results from Phase 01 are not substituted for new measurements.

## A — Environment readiness

### GPU blocker

**Fresh:** NVIDIA driver `615.71.10`; four NVIDIA L40S devices. NVIDIA's reported
free memory is used directly, rather than calculating total minus used (reserved
memory makes those quantities differ). Checks ran with host device/socket access.

| GPU | Total MiB | Used MiB | Free MiB | Intended service | Qwen reservation shortfall MiB |
| --- | ---: | ---: | ---: | --- | ---: |
| 0 | 46,068 | 11,961 | 33,580 | Qwen TP rank | 7,881.2 |
| 1 | 46,068 | 4,975 | 40,565 | Qwen TP rank | 896.2 |
| 2 | 46,068 | 4,975 | 40,565 | DA3 | Not a configured Qwen rank |
| 3 | 46,068 | 3,933 | 41,607 | SAM3 + OCR | Not a configured Qwen rank |

[`scripts/service.sh`](../../scripts/service.sh#L11) requests **0.90 of total
memory per Qwen GPU**, approximately **41,461.2 MiB each**, with TP=2 on GPUs
`0,1`, bfloat16, and context length **168,000**. Both configured ranks fail this
necessary resource check. Aggregate free memory across GPUs does not fix it.
Passing this check later would still require successful model loading and KV
cache validation; it is not a guarantee that the context will fit.

The observed GPU processes all belong to account `ai5377`, but use independent
Conda environments, not this repository's service environments:

| GPU | PIDs | Environment | Reported process memory |
| --- | --- | --- | --- |
| 0 | 1542705 | `tooldf` | 11,952 MiB |
| 1 | 1542697, 1542700, 1542703 | `aasist` | 1,652 MiB each |
| 2 | 1542698, 1542701, 1542704 | `aasist` | 1,652 MiB each |
| 3 | 1542696 | `demucs` | 610 MiB |
| 3 | 1542699, 1542702 | `aasist` | 1,652 MiB each |

Their command arguments and unrelated private paths were not saved. None was
killed, suspended, restarted, or otherwise modified. Full sanitized evidence is
in `gpu_preflight.json`. Memory availability is a snapshot, not a reservation.

**Minimum user action:** arrange for the independent workloads on GPUs **0 and
1** to finish or obtain an allocation with at least approximately **41,462 MiB
free on each**, preferably with headroom, then repeat the preflight. The measured
shortfalls are approximately **7.70 GiB on GPU 0** and **0.88 GiB on GPU 1**.
Safe options are waiting for normal completion or coordinating a scheduled
allocation with the workload owner. No termination command is proposed.
Changing GPU assignment, memory utilization, context, or precision would require
an explicitly approved, separately identified deployment; it would not complete
this unchanged-baseline task.

### Python and dependencies

**Fresh:** activated with `source scripts/env.sh`; active Python is
`.venv/bin/python`, version **3.11.2**, and the editable project is
`openvlharness 0.1.0` at this repository. `python -m pip show openvlharness`
confirmed the installation location.

| Environment | Python | Relevant installed distributions | `pip check` |
| --- | --- | --- | --- |
| `.venv` | 3.11.2 | OpenAI 3.37.0; Transformers 4.57.3; huggingface-hub 0.35.3; pandas 2.3.3; pycocotools 2.0.11; LVIS 0.5.3 | Passed |
| `.venvs/vllm` | 3.11.2 | vLLM 0.18.1; Torch 2.10.0; Transformers 4.57.3; FastAPI 0.162.0; python-multipart 0.0.32 | Passed |
| `.venvs/sam3` | 3.11.2 | SAM3 0.1.0; Torch 2.10.0+cu128; pycocotools 2.0.11; FastAPI 0.162.0; python-multipart 0.0.32 | Passed |
| `.venvs/da3` | 3.11.2 | depth-anything-3 0.0.0; Torch 2.10.0+cu128; addict 2.4.0; FastAPI 0.162.0; python-multipart 0.0.32 | Passed |

`environments.json` retains package metadata, interpreter paths, and all four
successful `pip check` outputs. These are dependency checks, not fresh CUDA
inference tests. No missing declared dependency was discovered; no installation
or upgrade was performed. The regression suite was not rerun for this report-only
phase, and the historical test count is not presented as a fresh result.

### Cached checkpoints

**Fresh:** all `refs/main` revisions match the pins in
[`scripts/download_models.py`](../../scripts/download_models.py#L10), and all
located weights resolve to existing, nonempty targets. The Qwen weight index
also references existing shards. Small configuration-file inventories were saved;
enormous weight files were not hashed or loaded.

| Model | Cached revision | Weight files |
| --- | --- | ---: |
| Qwen/Qwen3-VL-8B-Instruct | `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b` | 4 |
| facebook/sam3 | `3c879f39826c281e95690f02c7821c4de09afae7` | 2 |
| PaddlePaddle/PaddleOCR-VL-1.5 | `2a4195faa5e7914c12f2fc601d72c81caf8d2da5` | 1 |
| depth-anything/DA3NESTED-GIANT-LARGE | `8615eefb62f2db4f8d6ebaa59160086981672829` | 1 |

These identify cached sources, not a currently served model. Runtime model IDs
are `null` because no model server responded. Launchers set `HF_HUB_OFFLINE=1`;
this phase also used offline settings for local configuration/CLI checks. No
checkpoint or dataset was downloaded.

## B — Service restoration

**Fresh:** no listener appeared on the configured service ports. All ten HTTP
GET probes failed with `ConnectionError` / connection refused. They used direct
loopback connections, disabled environment proxies, and performed no retries.
See `service_health.json` and `listening_ports.txt`.

| Service | Port | Checked paths | Started / reused | Result |
| --- | ---: | --- | --- | --- |
| Qwen main and auxiliary | 8222 | `/v1/models`, `/health` | Neither | Unreachable |
| Tool router | 8101 | `/health`, `/tools`, `/backend-status` | Neither | Unreachable |
| SAM3 | 8086 | `/health` | Neither | Unreachable |
| OCR | 8085 | `/health`, `/v1/models` | Neither | Unreachable |
| DA3 depth / camera pose | 8087 | `/health` | Neither | Unreachable |
| Query-image host | 8111 | `/health` | Neither | Unreachable |

The inspected launch order, **pending a successful resource preflight**, is:

1. `bash scripts/service.sh qwen`; wait for health and the intended model ID.
2. `bash scripts/service.sh sam3`; verify health and a permitted grounding probe.
3. `bash scripts/service.sh ocr`, then `bash scripts/service.sh depth`, checking
   readiness after each. OCR requests 0.45 GPU memory utilization on GPU 3;
   SAM3 shares that GPU. Their joint loading must be checked rather than assumed.
4. Restore the query-image host and previously authorized tunnel if required for
   the paper preset's Serper Lens readiness. Its old URL is not a current health
   check. Verify the new public image URL before router startup.
5. `bash scripts/service.sh router` with the effective paper `AGENT_CONFIG`;
   check health, backend status, schemas, then minimal live capability probes.

The scripts run services in the foreground and contain no process-killing or log
overwrite commands. The SAM3 and DA3 worker modules load models at import, so
they were read as source and were **not imported** in this phase. The resource
blocker was established before the first launch; the startup procedure stopped
there, as Task 2 requires. No partial service stack or duplicate model was started.

**Fresh / CPU only:** `load_agent_config` and `build_capabilities` accepted the
unchanged paper preset and produced all **nine public schemas**, saved in
`public_schemas.json`. This confirms local construction, not retrieval from a
running router. The selection remains SAM3, Serper search/Lens/page visit, OCR,
DA3 depth/pose, zoom, and Python coding. You.com was not substituted.

**Pending:** ordinary multimodal Qwen inference, native tool calling, SAM3
boxes/scores/RLE masks, public zoom and image registration, grounding a generated
crop, router dispatch, and continuation through model-visible evidence. None
was simulated or declared live-verified.

## C — Original baseline run

**Not executed.** CLI help succeeded and confirms every requested flag. The exact
pending command remains:

```bash
source scripts/env.sh
openvlharness-eval \
  --config configs/agent/qwen3_8b_paper.yaml \
  --judge-config configs/judge_no_judge.yaml \
  --data ODinW13_bbox_val_qwen3 \
  --num-examples 1 \
  --shuffle \
  --seed 42 \
  --num-proc 1 \
  --save-html all \
  --keep-file-db \
  --run-tag bite_reference_preimplementation \
  --work-dir outputs/bite/reference_baseline
```

**Fresh:** independently applying the actual CLI sampling algorithm,
`sorted(random.Random(42).sample(range(4938), 1))`, selects zero-based row **912**,
sample **`PascalVOC_val_262`**. This verifies the local input selection; the
evaluator has not executed it. The TSV and image are local:

| Identity | Verified value |
| --- | --- |
| Dataset | `ODinW13_bbox_val_qwen3` |
| TSV rows | 4,938 |
| TSV MD5 | `55ae98c3e4ffa1c3292f4939f1b52012` |
| TSV SHA-256 | `6d82b735b3fe0032aaa661f5d7451efaa646e44e151a3d98d2ebea381ae67509` |
| Image | `data/images/ODinW/PascalVOC/2009_003855_jpg.rf.156f9294cb7f0fd32fa0bb3ac55a77ac.jpg` |
| Image dimensions | 500 × 333 pixels |
| Image SHA-256 | `a18039d3edc2c8ae46fb2b8347318c79f91f5643c3811181d366ed4a4403e1b5` |
| Question SHA-256 | `e2d57cbf29a593345c38f8e015e0076c044b58ed737de95331877969f4bfdfc2` |

Image resolution was checked against `ImageBaseDataset.img_root` and
`img_root_map`, including the `data/images/ODinW` prefix. The question and
annotations were not modified. No policy or inference process received GT.

There is **no evaluator run directory** yet. The timestamped `preflight_...`
directory holds checks only; no prediction, canonical `record.json`, detection
sidecar, HTML trace, or official diagnostic CSV has been created for this phase.
There were **zero inference attempts**, including infrastructure retries.

## D — Full execution trace

| Iteration | Tool / call ID / arguments | Input image | Observation / artifacts | Status |
| --- | --- | --- | --- | --- |
| Not started | No model proposal or dispatch | No model input submitted | None | Blocked by GPU preflight |

Phase counters are **0 model iterations, 0 logical tool calls, 0 successful calls,
0 tool failures** because no execution occurred. Token usage and final response
are unavailable, not measured as zero. No tool failure rate is inferred.

There is no trace from which to judge repeated queries, duplicate detections,
post-zoom usefulness, early stopping, empty results, native ID pairing, or backend
retries. These checks remain mandatory when the baseline can run. No historical
trace is relabeled as this sample's execution.

## E — Data availability for BITE

**No new runtime evidence is available.** The following field-availability matrix
is **source-verified expected persistence**, conditional on the relevant calls
actually occurring. It is not an inspection of newly generated Phase 02 files.

Legend: **Y** = structured retained field; **P** = partial/presentation only;
**N** = no dedicated retained field. HTML displays can be truncated and are not
a machine-readable observation store.

| Field | Canonical record / rich trajectory | Compact `full_trajectories` | Detection sidecar | HTML | Prediction file | Per-row CSV |
| --- | --- | --- | --- | --- | --- | --- |
| Raw backend envelope | Y | N | N | P | N | N |
| Native call IDs / original normalized arguments | Y | Y, retained native messages | N | P | N | N |
| Canonical numerical memory outputs | Y | N | P, detection subset | P | N | N |
| Grounding boxes | Y, pixel and normalized representations | P, rounded normalized evidence | Y, pixel boxes | P | Final normalized boxes | Counts / matches only |
| Retained numeric detector scores | Y | N in normal grounding evidence | Y | P, may be truncated | N with constant scoring | N |
| SAM3 RLE masks and source dimensions | Y | N, not full numerical payload | Dimensions only; no masks | P | N | N |
| Generated image pixels / references | Y, response images and message evidence | Y, message images saved to files by default | N | P | N | N |
| Complete live image/binding registry snapshot | N | N | N | N | N | N |
| Exact crop rectangle / child-to-root transform | N | N | N | N | N | N |
| Tool failures | Y, structured payload where emitted | Y, model-facing feedback | N | P | Final failure sentinel only | Parsed outcome only |
| Ground truth | N, original agent result | Y, evaluator adds it offline | N | Y, evaluator display | Y, dataset columns | GT counts and matching diagnostics |
| Per-tool latency / physical retry counts | N | N | N | N | N | N |

Source anchors:

- [`agent.py`](../../openvlharness/agent/agent.py#L99):
  `extra_records.trajectory.chat_history[*].assistant.tool_calls` keeps ID, name,
  raw arguments, parsed args and parse errors. `tool_responses` retains execute
  envelopes. `memory_outputs` retains call ID, image refs, canonical results,
  processor metadata and message indexes. `messages` retains native history.
- [`sam3_segment/server.py`](../../openvlharness/services/tools/sam3_segment/server.py#L285):
  successful raw results include `model`, `prompt`, `pred_boxes`, `pred_scores`,
  `pred_masks`, `orig_img_h`, `orig_img_w`, `num_masks`, and rendered image base64.
  RLE counts need the dimensions to reconstruct masks. Scores are retained,
  filtered detector outputs, **not calibrated correctness probabilities**.
- [`grounding.py`](../../openvlharness/capabilities/grounding.py#L355):
  agent canonical keys are `boxes`, `scores`, `masks`, `size`, etc.; Python
  bindings use `pred_*` keys. Detection sidecars retain selected geometry and
  scores, not masks or a source-image provenance graph.
- [`runner.py`](../../evaluation_kit/runner.py#L50): canonical
  `results/<shard>/<sample>/record.json` retains the original generated result;
  compact trajectory JSON is built separately from messages and selected fields.
  GT is attached to evaluator reporting records after generation, rather than
  supplied to the agent. HTML renders rich fields with text limits.
- [`zoom_in_image_by_bbox/tool.py`](../../openvlharness/services/tools/zoom_in_image_by_bbox/tool.py#L98):
  requested normalized coordinates are padded, clamped and rounded to integer
  pixel extents before cropping. Only crop pixels are returned. The actual
  integer rectangle and ancestry transform are absent. A follow-up grounding
  call would report boxes in the crop frame, not automatically the root frame.

**Fresh persistence settings:** `FULL_TRAJECTORIES_LIMIT` is unset, so the image
runner's default is unlimited (`-1`). `MVTK_KEEP_FILE_DB` is unset, but the pending
command's `--keep-file-db` prevents cleanup. `--save-html all` requests all HTML;
default `--save-images files` saves message images beside compact trajectories.
Raw token-trace export is not enabled; turning it on would change effective
`return_token_ids`, so it was not added to the reference command. `WORLD_SIZE`
is unset. Effective settings and public schemas were saved without credentials.

## F — Evaluation

**Pending:** final JSON parsing, label membership, normalized 0–1000 coordinates,
root-image geometry, COCO scoring, AP/AP50/AP75/area metrics, and per-row TP/FP/FN
diagnostics. There is no prediction to validate or score. The manifest records
final validity, official results and evaluation-only results as `null` with the
resource-blocker reason. No overall paper-score reproduction is claimed.

The judge remains `direct_metrics_v1`, `model_name: null`, `score_mode: constant`.
No scorer, threshold, score, or official metric was changed.

**Source / CLI verified:** evaluation-only mode requires **`--data`** in addition
to the saved run directory. After a real run exists, its supported form is:

```bash
source scripts/env.sh
openvlharness-eval \
  --mode eval \
  --data ODinW13_bbox_val_qwen3 \
  --run-dir <actual_saved_run_directory>
```

This is a template and was **not run**. The current preflight directory must not
be passed as an evaluator run. The local eval branch loads saved identity and
predictions without building an inference agent, but fresh verification that no
model/tool calls occur and that metrics agree requires the missing baseline
artifacts. Historical saved predictions were not evaluated as a substitute.

## G — Scientific reproducibility

Before checks, `git status --short` showed only untracked `docs/bite/`; tracked
files matched HEAD. The existing Phase 01 report was preserved. The branch and
commit were unchanged. Only this report and new ignored preflight artifacts were
created in the repository. Runtime code, configs, `.env`, checkpoint refs,
datasets and existing experiment outputs were not modified. No services,
drivers, CUDA installations, global configuration or independent processes were
changed.

The evidence directory contains:

- `phase02_manifest.json`: blocked status, source identity, sample identity,
  zero-attempt counters, null results and reasons.
- `source_identity.json`: Git state and SHA-256 hashes of configs, launchers,
  workers, model registry, evaluator CLI and runner.
- Unexpanded `qwen3_8b_paper.yaml` and `judge_no_judge.yaml` snapshots; no secrets.
- `gpu_preflight.json`, `listening_ports.txt`, `service_health.json`.
- `environments.json`, `checkpoint_inventory.json`, `effective_settings.json`.
- `sample_identity.json`, `public_schemas.json`, `cli_help.txt`,
  `cli_verification.json`.
- `SHA256SUMS`: file-integrity inventory for the saved preflight evidence.

Configuration SHA-256 values:

```text
agent: 19f737475b048a8a025002ba3642a70d6611b9c97c4b67e45d9630e0700a4431
judge: ecdf99927811800757d3702fe25ae2f82d43e22295253857cf3b2d8884bb6323
```

The phase manifest also hashes the supplied Task 2 specification and Phase 01
report. Credentials were checked only for presence, not printed, saved, hashed,
or authenticated. The public tunnel URL was not probed or saved. Provider access
and query-image hosting remain runtime prerequisites to verify after resources
are available. This is an integrity inventory, not signed or write-protected
storage; preserve this timestamped directory and create a new one for later
attempts.

Known scientific limits remain: this selected validation sample is a development
sanity case; PascalVOC val/test aliases are not disjoint calibration partitions;
retained detector scores are censored outputs; crops lack explicit transforms;
and current records do not provide full physical-attempt or cost accounting.

## H — Phase 3 implementation requirements

**Phase 3 has not started.** There is no actual Phase 02 trace on which to base
new empirical conclusions. The following minimum requirements are inherited
from source inspection and must be confirmed against the first real trace:

1. **Observation ledger:** per-question run/sample/action/observation IDs; native
   proposal versus executed backend; resolved image ID; raw and canonical output;
   empty versus failed outcomes; no inference-time access to GT.
2. **Crop transforms:** actual integer crop rectangle, parent and child IDs and
   hashes, dimensions and composed child-to-root transform. Requested padding
   alone is insufficient.
3. **Candidate provenance:** frame-aware detection records with rank, label,
   retained score and mask references; explicit cross-call association distinct
   from artifact deduplication and official score-sidecar matching.
4. **Logical budget:** count dispatched public capability calls, including
   dispatched failures; distinguish invalid proposals and transport attempts.
   Record model iterations, finalization and physical retry costs separately.
5. **Evidence dependencies:** source image/crop ancestry, checkpoint, query,
   preprocessing and prior evidence parents; do not multiply repeated detector
   scores as if the calls were independent observations.
6. **Offline calibration:** retained canonical observations, frozen disjoint
   image-group manifests, separately stored GT labels, declared matching rules
   and action-selection probabilities. Existing default compact traces alone
   are insufficient.

**Smallest next step:** obtain the original GPU allocation and finish Phase 02:
start each unchanged service with health checks, perform minimal functionality
probes, run the prescribed sample once, retain its canonical artifacts, inspect
call/result pairing and re-score saved predictions. Only then review a separate
observer-only Phase 3 proposal with disabled-mode equivalence tests. No planner,
belief estimator, provenance instrumentation or budget controller was added here.
