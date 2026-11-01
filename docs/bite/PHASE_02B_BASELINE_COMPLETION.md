# Phase 02B — Original baseline completed

**Status: SUCCESS for the one-example execution and evidence-validation task.**
The original paper configuration ran once on `PascalVOC_val_262`, completed in
**3 model iterations with 2 successful SAM3 calls and no tool failures**, saved
valid root-frame JSON, and passed official evaluation and evaluation-only
reproduction. **No BITE implementation or Phase 3 work was started.** This is
an installation/reference check on one validation image, not paper-score reproduction.

Execution date: **2026-10-29, America/New_York**. Attempt began at **21:05:15 UTC /
17:05:15 EDT**; inference/scoring ran at **17:11:10–17:11:17 EDT**; evaluation-only
ran at **17:12:15 EDT**. Source remains `main` at
`c530cdbdc6b7c4f486499eb7e5834ac2bd92692d`.

The [Phase 02 blocked report](PHASE_02_BASELINE_EXECUTION.md) is unchanged.
The previous Phase 02B report is archived
[verbatim](../../outputs/bite/reference_baseline/attempt_20261029T210515Z/previous_phase02b_report.md)
and retained at the end of this file. The new request was handled as a separate
attempt; previous outputs were preserved.

## 1. Current GPU status and original deployment

The new preflight found **no GPU compute processes** and **45,540 MiB free on
each GPU**, removing the earlier independent-workload blocker. No independent
process was stopped, suspended, restarted or moved.

| GPU | Hardware / total MiB | Original allocation | Free before MiB | Used after tests MiB | Free after tests MiB |
| --- | --- | --- | ---: | ---: | ---: |
| 0 | L40S / 46,068 | Qwen TP rank 0 | 45,540 | 41,041 | 4,500 |
| 1 | L40S / 46,068 | Qwen TP rank 1 | 45,540 | 41,041 | 4,500 |
| 2 | L40S / 46,068 | DA3 | 45,540 | 10,071 | 35,470 |
| 3 | L40S / 46,068 | SAM3 + OCR | 45,540 | 26,756 | 18,785 |

Driver: **615.71.10**. The unchanged Qwen launcher used GPUs `0,1`, TP=2,
**0.90 GPU memory utilization**, **168,000-token context**, BF16, eager execution,
Hermes auto tool calling, maximum 4 sequences and 16,384 batched tokens. The
server reported a **426,368-token GPU KV cache** and **2.54× concurrency** for
168,000-token requests. Model-list output confirms `max_model_len: 168000`.
No GPU allocation, precision, context or utilization setting was altered.

Snapshots are `gpu_before.csv` and `gpu_after.csv` in the
[attempt directory](../../outputs/bite/reference_baseline/attempt_20261029T210515Z/).
Final memory is an observed snapshot, not a reservation for additional jobs.

## 2. Services restored and retained

Services were started with the existing `scripts/service.sh`, one at a time,
checking readiness before continuing. All were newly started; none was duplicated
or substituted. They remain running in managed foreground sessions.

| Service | Port | GPU | Verified status / identifier | Log |
| --- | ---: | --- | --- | --- |
| Qwen main + auxiliary | 8222 | 0,1 | Healthy; `Qwen/Qwen3-VL-8B-Instruct` | `services/qwen_foreground.log` |
| SAM3 | 8086 | 3 | Healthy; execution returned `sam3-image` | `services/sam3.log` |
| OCR | 8085 | 3 | Healthy; `PaddlePaddle/PaddleOCR-VL-1.5` | `services/ocr.log` |
| DA3 depth + camera poses | 8087 | 2 | Healthy; `depth-anything/DA3NESTED-GIANT-LARGE`, CUDA | `services/depth.log` |
| Query-image host | 8111 | CPU | Healthy; content-hash images only | `services/image_host.log` |
| Previously authorized image tunnel | Public tunnel to 8111 | CPU | QUIC connected; public-fetch/Lens probe passed | `services/image_tunnel.log` |
| Tool router | 8101 | CPU | Healthy; all 9 original tools and schemas | `services/router.log` |

The first detached Qwen shell exited before server startup and produced an empty
log. The same original launcher was then run in a managed foreground session.
This was a process-supervision correction, **not an inference retry or model
configuration change**. The empty log was preserved.

The tunnel received a new hostname. Only operational setting
`IMAGE_UPLOAD_PUBLIC_BASE_URL` in ignored `.env` was refreshed so the original
Serper Lens backend could fetch query images. Credentials were preserved and
not printed. `hosting_change.json` records this change. Public images remain
fetchable while the authorized tunnel runs; the repository itself is not served.

`environment_health.json`, `final_health.json` and their logs retain successful
model-ID, worker, router `/health`, `/tools`, `/llm-schema`, and
`/backend-status` checks. The router retained the unchanged paper preset and
Serper providers; You.com was not substituted.

## 3. Functional tests: actual successful execution

Tests used the existing `outputs/setup/bottles.png`, **separately from the ODinW
benchmark**, before its one inference attempt. All requested smoke tests passed.

| Test | Observed result | Evidence |
| --- | --- | --- |
| A — Qwen multimodal | Intended model described the text and three blue bottle icons | `smokes/qwen_multimodal_response.json` |
| B — SAM3 grounding | `bottle`: 3 boxes, 3 scores, 3 decodable RLE masks, dimensions `[320,600]`, rendered evidence | `smokes/ground_root.json` |
| C — public zoom + memory | `input_image_1` → registered crop `tool_generated_image_2`, 420×304 pixels | `smokes/zoom.json`, `smokes/registered_crop.png` |
| C — ground generated crop | `bottle`: 2 detections, dimensions `[304,420]`, successful resolved crop reference | `smokes/ground_crop.json` |
| D — agent continuation | 2 model iterations; 1 native grounding call/result pair; final answer `3` | `smokes/agent_integration.json` |

Root-image bottle scores were `[0.98046875, 0.984375, 0.98046875]`; these are
retained detector outputs, **not calibrated probabilities**. All root RLE masks
decoded to 320×600 arrays. The agent smoke's declaration and result shared ID
`chatcmpl-tool-a5f1b627cd673dcd`.

The crop request was `coords=[50,100,650,950], padding=50` on the 600×320 input.
The original algorithm implies padded integer crop `(0,16,420,320)`, consistent
with returned 420×304 pixels. This is an **offline source-derived rectangle**;
the tool did not return or persist a transform. Grounding reported coordinates
local to that crop. No new crop-provenance handling was implemented.

The existing `scripts/check_environment.py --probe-tools` also passed **all nine
original capabilities once**: grounding, Serper text/image search and webpage
visit, OCR (`OpenVLHarness 123`), finite depth, two ordered camera matrices,
zoom, and generated Python execution (`391`). Router degradation counts remained
empty. This established full configured-stack readiness; these probes are not
part of the benchmark trajectory. Results: `all_capability_probes.json` and log.

There were no failed functional tests. The offline-focused agent smoke logged
that local tokenizer counting was unavailable and provider context enforcement
was used. A subsequent normal-environment cached tokenizer check loaded
`Qwen2TokenizerFast`; the actual unchanged baseline logged no tokenizer fallback.
The harness's absence of Torch is expected for its tokenizer-only role. DA3
warned about optional 3DGS rendering dependency `gsplat`; depth and camera-pose
probes passed, and no package installation was needed or performed.

## 4. Exact original ODinW execution

Executed **once**, without modified prompts, forced benchmark tool choice,
BITE instructions, alternate tools, extra call budgets, score changes, or
`--ignore-failed`:

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

Exit code: **0**. The evaluator actually selected **`PascalVOC_val_262`**, verified
by its canonical record, compact trajectory and prediction file. Image:
`data/images/ODinW/PascalVOC/2009_003855_jpg.rf.156f9294cb7f0fd32fa0bb3ac55a77ac.jpg`,
500×333 pixels. Sampling seed 42 chooses the row; `paired_sampling_seed: false`
means it is **not** a deterministic model-decoding seed.

Actual evaluator run directory:

```text
outputs/bite/reference_baseline/Qwen3-VL-8B-Instruct/mainagent/
agent_paper_v1_judge_direct_metrics_v1_20261029_171110_bite_reference_preimplementation/
```

The two displayed lines form one path. Under it, dataset artifacts are in
`ODinW13_bbox_val_qwen3/`. Exact machine-readable paths are in `run_directory.txt`
and `baseline_manifest.json` in the attempt directory.

## 5. Complete model/tool trajectory

The full recorded assistant text and raw argument strings are retained in
`trajectory_review.json` and the canonical record. This table summarizes every
model iteration; there was no extra finalization request.

| Iteration | Recorded response / decision | Tool and exact arguments | Native call ID | Backend / input frame | Observation and new memory |
| --- | --- | --- | --- | --- | --- |
| 1 | Identifies a person and two horses; proposes person then horse grounding | `Visual_Grounding_Tool`, `{"query":"person","image_id":"input_image_1"}` | `chatcmpl-tool-8b54482ffc57154f` | `sam3_segment`, root 500×333 | Success: 1 box/mask, score `0.984375`; `tool_generated_image_1`; `segment_person` binding; continue |
| 2 | Uses the person result, proposes grounding the two horses | `Visual_Grounding_Tool`, `{"query":"horse","image_id":"input_image_1"}` | `chatcmpl-tool-836284f7de74a3c5` | `sam3_segment`, root 500×333 | Success: 2 boxes/masks, scores `0.9765625`, `0.96484375`; `tool_generated_image_2`; `segment_horse` binding; continue |
| 3 | Compiles one person and two horses into the requested JSON | No call | None | Root image | Final answer; stops before the 15-iteration maximum |

Each ID appears exactly once in an assistant native declaration and once in its
later native `role: tool` result. Both tool acknowledgments contain `ok`; actual
visual/JSON evidence follows as user messages. Image-resolution metadata confirms
that both requested `input_image_1` references resolved to that same root image.
Memory output records map the observations to native result/evidence message
indexes `(4,5)` and `(8,9)` (zero-based). All three saved masks decoded to 333×500
arrays, with aligned finite boxes and scores.

| Query | Raw pixel xyxy (rounded here only for readability) | Saved normalized xyxy | Score |
| --- | --- | --- | ---: |
| person | `[201.7684,131.7963,285.5702,332.9205]` | `[404,396,571,1000]` | 0.984375 |
| horse, left | `[-0.8233,29.3160,197.3323,331.7884]` | `[0,88,395,996]` | 0.9765625 |
| horse, right | `[311.8002,46.7826,500.0980,329.0599]` | `[624,140,1000,988]` | 0.96484375 |

Full-precision raw values remain unchanged in the canonical record and detection
sidecar. Two raw horse boxes slightly exceed image bounds; canonical normalized
evidence clamps them to 0–1000. This existing behavior was preserved, not repaired
or substituted during evaluation.

No repeated grounding query, empty result, invalid proposal, unknown tool, tool
failure or baseline zoom call occurred. The three detections are spatially
separate in the root frame; this trace does not exercise cross-call duplicate
association. Registered images 1/2 are grounding visualizations, **not crops**.
Post-zoom grounding was tested only in the separate smoke test.

Baseline window HTTP log deltas: **3 Qwen POSTs, 2 router POSTs, 2 SAM3 POSTs**;
OCR/depth counts did not increase. This is consistent with the recorded calls
and no additional attempts reaching those services. Complete client physical
attempt telemetry does not exist, so the manifest keeps that field `null` with
an explanation rather than asserting a measured attempt count. Model usage:
**13,965 prompt + 332 completion = 14,297 total tokens**, accumulated across the
three main-agent requests. Smoke-test and auxiliary-probe usage is excluded.

## 6. Actual evidence persistence and availability

The canonical file was retained by `--keep-file-db`:

```text
ODinW13_bbox_val_qwen3/results/0d/PascalVOC_val_262/record.json
```

Within it, `extra_records.trajectory.chat_history[0]` and `[1]` each retain
`assistant.tool_calls`, raw `tool_responses`, and `memory_outputs`. The raw result
keys include `model`, `prompt`, `pred_boxes`, `pred_scores`, `pred_masks`,
`orig_img_h`, `orig_img_w`, `num_masks`, and `rendered_image_b64`. Canonical memory
results include pixel/normalized boxes, scores, labels, RLE masks, dimensions
and rendered-image IDs. Environment messages expose `segment_person` and
`segment_horse` binding descriptors; no full live memory checkpoint is saved.

| Field | Canonical / rich trajectory | Compact trajectory | Detection sidecar | HTML | Prediction / diagnostics |
| --- | --- | --- | --- | --- | --- |
| Tool names, full args, native IDs | Both calls, raw args and parsed args | Both native declarations/results | Queries and tool name, no native IDs | Display; may truncate | Absent |
| Raw pixel boxes | All 3, full precision | Rounded normalized evidence only | All 3, full precision | Display may truncate | Final normalized boxes / counts |
| Numeric retained SAM3 scores | All 3 | Absent from normal grounding evidence | All 3 | Display may truncate | Constant-score evaluation does not recover these |
| Numerical masks + dimensions | 3 RLE strings + `[333,500]`, all decoded successfully | Annotated pixels, not numerical masks | Dimensions, no masks | Display/visualization, not complete numerical storage | Absent |
| Images and IDs | Input, 2 rendered images, canonical refs and evidence | 3 files under `full_trajectories/images/` plus message refs | No source-image ID | Embedded visual evidence | Absent |
| Raw tool output / canonical output | Both retained | `ok` acknowledgments plus model-facing evidence; no rich `memory_outputs` | Selected boxes/scores only | Raw display limited to 2,000 characters | Absent |
| Crop metadata | No baseline crop; smoke has requested args and generated ref only | No baseline crop | No transforms | No baseline crop | No transforms |
| Failures | None occurred; structured field locations available | No failure messages | No failure records | No failures shown | Successful prediction |
| Offline GT | No evaluator-added GT in original agent result | `ground_truth` present | Absent | GT displayed | XLSX metadata, filtered COCO GT, CSV GT counts/matches |
| Per-tool latency / physical retry telemetry | No standard field | Absent | Absent | Absent | Absent |

The rich native history has **11 messages**. The compact file has **12**:
reporting appends the final assistant response reconstructed from the final
turn. The compact file has no `chat_history` or raw numerical `memory_outputs`;
it cannot replace the canonical record for calibration. Both formats retain the
same two native call/result IDs. No per-instance evaluation block appeared in
the compact JSON; per-row diagnostics remain in the CSV.

`FULL_TRAJECTORIES_LIMIT` was unset, so all image trajectories were eligible;
`--save-html all` retained HTML, and default `--save-images files` retained the
three image files. Raw token-trace export was not added, preserving the original
`return_token_ids: false` configuration. Labeled evaluator/HTML/prediction
artifacts must remain offline from future inference policy inputs.

## 7. Prediction validity and official evaluation

Saved prediction, unchanged:

```json
[
  {"bbox_2d": [404, 396, 571, 1000], "label": "person"},
  {"bbox_2d": [0, 88, 395, 996], "label": "horse"},
  {"bbox_2d": [624, 140, 1000, 988], "label": "horse"}
]
```

Validation passed: JSON parses; all labels belong to the 20 prompted classes;
each box is ordered and within 0–1000. Root-frame identity is established by the
resolved input IDs and 500×333 source dimensions, with no crop path in this run.
The final boxes exactly match the clamped normalized grounding observations.
`<answer>` extraction succeeded.

The unchanged `pycocotools.COCOeval` evaluator ran with
`judge_no_judge.yaml`, `score_mode: constant`, Qwen3 multilabel/norm1k semantics,
and the official detection cap. Only **PascalVOC/val, one image** was evaluated.

| Metric | Result, 0–100 scale |
| --- | ---: |
| AP (IoU 0.50:0.95) | 92.52 |
| AP50 | 100.00 |
| AP75 | 100.00 |
| APl | 92.52 |
| APs / APm | Unavailable (`-1` sentinel; displayed N/A) |

The saved per-row CSV has two rows: `(num_pred,num_gt,tp,fp,fn,mean_match_iou)`
equals `(2,2,2,0,0,95.53)` and `(1,1,1,0,0,91.18)`. Mean matched IoU is a
**percentage** at IoU 0.5. Aggregate diagnostic counts are TP=3, FP=0, FN=0.
This CSV does not retain candidate-level matched IDs or explicit category IDs;
future calibration needs a separate offline export.

## 8. Evaluation-only reproduction

Executed once with the actual saved run directory:

```bash
source scripts/env.sh
openvlharness-eval \
  --mode eval \
  --data ODinW13_bbox_val_qwen3 \
  --run-dir outputs/bite/reference_baseline/Qwen3-VL-8B-Instruct/mainagent/agent_paper_v1_judge_direct_metrics_v1_20261029_171110_bite_reference_preimplementation
```

Exit code **0**. The log states it evaluated saved outputs without an inference
agent and shows fresh COCO matching/accumulation. All six official AP values
agree exactly with the original run, and the prediction XLSX hash is unchanged.

Before/after counts remained **Qwen 10, SAM3 6, OCR 1, depth 2, router 15 POSTs**
across the whole restored-session history. Qwen and OCR request-success and
prompt/generation token counters also remained unchanged. No model or tool
execution was repeated. Evidence: `before_eval_only.json`, `after_eval_only.json`,
`eval_only.log`, and `trajectory_review.json`.

**Coverage metadata differs, not the AP values:** inference-mode evaluation had
one sampled loader row (`images_total=1`, completed=1, dropped=0). Evaluation-only
loads the full validation loader and its coverage filter sees 3,422 PascalVOC
images, keeps the one saved image and drops 3,421 incomplete images. Its warning
and these metadata differences are preserved. Do not interpret the re-score as
evaluation on 3,422 predicted images or expect byte-identical whole metric JSON.

Before re-scoring, original predictions and scoring/GT/diagnostic files were
copied to `original_scoring/`. Thus original coverage metadata is preserved even
though the CLI normally refreshes scoring files in the actual run directory.

## 9. Reproducibility manifests and limits

The [supplemental baseline manifest](../../outputs/bite/reference_baseline/attempt_20261029T210515Z/baseline_manifest.json)
records Git and working-tree identity, exact config hashes, fresh package
metadata, cached revisions, server identities, GPU snapshots/allocation, dataset
and sample hashes, seed semantics, actual counts, token usage, final prediction,
both evaluations, exact artifact paths and unsupported telemetry as `null`.
The evaluator's own `run_manifest.json` remains in the real run directory.

| Checkpoint | Resolved cached revision, verified again before execution |
| --- | --- |
| Qwen/Qwen3-VL-8B-Instruct | `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b` |
| facebook/sam3 | `3c879f39826c281e95690f02c7821c4de09afae7` |
| PaddlePaddle/PaddleOCR-VL-1.5 | `2a4195faa5e7914c12f2fc601d72c81caf8d2da5` |
| depth-anything/DA3NESTED-GIANT-LARGE | `8615eefb62f2db4f8d6ebaa59160086981672829` |

Workers used offline cache resolution. A runtime SAM3 name alone does not certify
a checkpoint hash; provenance here combines the offline launcher, pinned cache
ref, worker source identity and preserved process logs. Huge weight files were
not hashed or copied, and no checkpoint download was requested.

All interpreters are Python 3.11.2. Fresh distribution metadata includes harness
0.1.0, Transformers 4.57.3, vLLM 0.18.1, serving Torch 2.10.0, SAM3/DA3 Torch
2.10.0+cu128, pycocotools 2.0.11 and evaluator pandas 2.3.3. The preceding four
successful `pip check` records are preserved as explicitly historical files;
no packages were reinstalled or changed in this attempt.

Agent YAML SHA-256:
`19f737475b048a8a025002ba3642a70d6611b9c97c4b67e45d9630e0700a4431`.
Judge YAML SHA-256:
`ecdf99927811800757d3702fe25ae2f82d43e22295253857cf3b2d8884bb6323`.
TSV MD5: `55ae98c3e4ffa1c3292f4939f1b52012`;
TSV SHA-256: `6d82b735b3fe0032aaa661f5d7451efaa646e44e151a3d98d2ebea381ae67509`.
Image SHA-256: `a18039d3edc2c8ae46fb2b8347318c79f91f5643c3811181d366ed4a4403e1b5`.

Runtime code, agent/judge configs, scorer, dataset and earlier reports remain
unchanged. New files are this updated report and ignored attempt/evaluator
artifacts. The only operational settings edit is the tunnel URL described above.
Services were started as requested and left healthy. No secrets were saved in
the manifests or reports; file-integrity inventories exclude growing live logs
and instead cover frozen log snapshots.

## 10. Minimum Phase 3 requirements; stop here

The reference baseline is now available for reviewing a **separate observer-only
Phase 3 task**. No observer, belief model, planner, controller, calibration fitting
or fine-tuning was implemented. The actual trace establishes these requirements:

1. Capture immutable action/observation identity alongside raw and canonical
   outputs, requested/resolved image ID, backend and native call ID. Both current
   calls resolve correctly, but grounding output alone does not identify its frame.
2. Preserve exact crop rectangles and composed child-to-root transforms. This
   baseline did not zoom; the smoke confirms crop grounding works but the transform
   is absent from returned data. Require nested-crop round-trip tests.
3. Associate persistent candidates across calls using frame-aware geometry and
   provenance. This run has no repeated query or duplicates and cannot validate
   association behavior; the official score-sidecar matcher is not a substitute.
4. Count public dispatches (2 here), including dispatched failures; separately
   record invalid proposals, model turns, finalization, latency and physical
   attempts. Standard retry/latency fields are still absent.
5. Record shared root pixels, crops, checkpoint, query and prior evidence parents.
   The person/horse calls share the same image and SAM3 checkpoint; do not assume
   independent evidence or use retained detector scores as calibrated posteriors.
6. Retain canonical numerical evidence and export candidate-level GT matches
   **offline**, with explicit ignore/matching semantics. Keep GT-bearing compact
   traces/HTML/XLSX out of runtime policy inputs; freeze disjoint calibration
   manifests and handle PascalVOC val/test aliases before collecting training data.

Start with a reviewed schema and default-off observer equivalence tests preserving
native requests/results and predictions, including concurrent questions, empty
results, failures and nested crops. This single successful image does not supply
those missing calibration or protocol edge cases. **Phase 3 is not started.**

---

# Earlier Phase 02B attempt — preserved verbatim

The following is the earlier blocked check at 20:45 UTC. Its status is historical;
the successful retry above is the current result.

# Phase 02B — Baseline completion: still blocked

**Status: BLOCKED.** Fresh checks at **2026-10-29 20:45:50 UTC / 16:45:50
America/New_York** confirm that the original Qwen allocation still cannot start
safely. No inference, tool execution or evaluation was attempted. Phase 3 has
not started.

This continues the [Phase 02 report](PHASE_02_BASELINE_EXECUTION.md), preserving
it and the [Phase 01 audit](PHASE_01_REPOSITORY_AUDIT.md). Task 2B explicitly
requires stopping GPU-dependent work when resources remain insufficient.
Previously completed dependency, dataset and capability audits were not rerun.

New evidence: [preflight directory](../../outputs/bite/reference_baseline/preflight_2b_20261029T204550Z/)
and [Phase 02B manifest](../../outputs/bite/reference_baseline/preflight_2b_20261029T204550Z/phase02b_manifest.json).
This directory is a resource preflight, not an evaluator run.

## 1. Current GPU status

**Fresh host checks:** four NVIDIA L40S GPUs; driver `615.71.10`.

| GPU | Total MiB | Used MiB | Reported free MiB | Intended allocation | Qwen reservation shortfall MiB |
| --- | ---: | ---: | ---: | --- | ---: |
| 0 | 46,068 | 11,961 | 33,580 | Qwen TP rank 0 | 7,881.2 |
| 1 | 46,068 | 4,975 | 40,565 | Qwen TP rank 1 | 896.2 |
| 2 | 46,068 | 4,975 | 40,565 | DA3 | Not a configured Qwen rank |
| 3 | 46,068 | 3,933 | 41,607 | SAM3 + OCR | Not a configured Qwen rank |

The unchanged launcher requests `0.90 × 46,068 = 41,461.2 MiB` on **each** Qwen
rank, TP=2 on GPUs `0,1`, context 168,000, BF16. Both configured ranks fail this
necessary preflight. GPU utilization of 0% does not mean allocated memory is
available. Free memory was queried directly, accounting for NVIDIA's reserved
memory rather than subtracting used memory from total.

All **10 previously observed GPU PIDs are still active**. The owner is `ai5377`;
they are independent workloads using `tooldf` (GPU 0), `aasist` (GPUs 1–3) and
`demucs` (GPU 3). Their PIDs, owners, elapsed times and allocations are saved in
`gpu_preflight.json`. They were not killed, suspended, restarted or modified.

**Required action:** coordinate normal completion or a scheduled allocation
providing at least approximately **41,462 MiB free on both GPUs 0 and 1**, with
headroom preferred. Current shortfalls are approximately **7.70 GiB** and
**0.88 GiB**, respectively. Then repeat the preflight. Passing the reservation
check still requires successful model loading and context/KV-cache validation.
Moving GPUs or changing utilization, TP, context or precision would be a separate
deployment and is not authorized by this task. Reclaiming unrelated processes is
also prohibited. No model startup was attempted expecting an OOM.

## 2. Services restored or reused

**Fresh:** no listeners on the configured ports; ten direct loopback HTTP probes
failed with connection refused. The probes disabled environment proxies and
used no transport retries. Evidence: `service_health.json`, `listening_ports.txt`.

| Service | Port | Probe paths | Result | Started / reused |
| --- | ---: | --- | --- | --- |
| Qwen main + auxiliary | 8222 | `/v1/models`, `/health` | Unreachable | Neither |
| SAM3 | 8086 | `/health` | Unreachable | Neither |
| OCR | 8085 | `/health`, `/v1/models` | Unreachable | Neither |
| Depth / camera pose | 8087 | `/health` | Unreachable | Neither |
| Router | 8101 | `/health`, `/tools`, `/backend-status` | Unreachable | Neither |
| Query-image host | 8111 | `/health` | Unreachable | Neither |

The GPU-dependent startup procedure stopped at Task 2B Step 2. No duplicate or
partial service stack was started. Public query-image hosting and provider
authentication were not probed; no search provider was substituted. The paper
configuration and its Serper selection remain unchanged.

## 3. Functional tests

| Requested check | Phase 02B outcome |
| --- | --- |
| A: real multimodal Qwen request | Not attempted; GPU preflight blocked |
| B: SAM3 boxes, retained scores, masks and dimensions | Not attempted; no SAM3 service |
| C: public zoom, memory registration, grounding a crop | Not attempted; original service stack unavailable |
| D: agent tool-result continuation and native ID pairing | Not attempted; no inference |

No functional success or model/tool execution failure is claimed. Endpoint
connection failures are readiness failures, not dispatched tool failures. Prior
dependency checks and cached checkpoint inventories remain historical evidence
at **20:38 UTC**, explicitly dated in the new manifest; they are not relabeled as
fresh inference tests. Fifteen previous preflight artifacts passed SHA-256
integrity verification. All previously hashed source/config files also match.

## 4. Original ODinW command

**Not executed.** The prescribed unchanged command remains:

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

Previously verified selection: row **912**, question/image ID
**`PascalVOC_val_262`**, dataset **`ODinW13_bbox_val_qwen3`**. The local image is
`data/images/ODinW/PascalVOC/2009_003855_jpg.rf.156f9294cb7f0fd32fa0bb3ac55a77ac.jpg`
(500 × 333). This is the pending sample, **not an actually evaluated sample**.
Its checksums and the original sampler evidence are retained from Phase 02 in
the new manifest; sampling was not unnecessarily repeated. No question or GT
was modified, and no agent received GT.

## 5. Per-iteration trajectory

| Iteration | Tool / arguments / native ID | Input image / backend | Output / artifacts | Status |
| --- | --- | --- | --- | --- |
| None | No proposal or dispatch | None submitted | None | Resource preflight blocked |

This task made **0 inference attempts, 0 model iterations, 0 logical tool calls,
0 successful calls and 0 tool failures**. There are no malformed proposals or
transport retries from an agent run. Token usage is unknown, not measured as
zero. Native call/result pairing, detection counts, scores, masks, artifact IDs,
repeated calls, crop-frame behavior and stopping decisions have no fresh trace
to inspect.

## 6. Raw-evidence availability

**No new runtime formats exist for this attempt.** The matrix below summarizes
the unchanged source contracts already inspected in Phase 02, conditional on a
future real execution. It does not claim that these files were generated here.
The [detailed source-based matrix](PHASE_02_BASELINE_EXECUTION.md#e--data-availability-for-bite)
remains the reference.

| Required evidence | Canonical record / rich trajectory | Compact trajectory | Detection sidecar | Other outputs |
| --- | --- | --- | --- | --- |
| Full arguments and native call IDs | Structured call records and native messages | Retained native messages | No native IDs / arguments | HTML display may truncate |
| Raw grounding boxes and numeric scores | Raw payload and canonical result | Rounded normalized boxes in normal grounding evidence; numeric scores absent | Pixel boxes and retained scores | Prediction retains final boxes, not source scores in constant mode |
| SAM3 segmentation masks | RLE counts and source dimensions | No full numerical mask payload | No masks | Rendered HTML/image is not the numerical mask record |
| Image IDs and generated image pixels | Call args, memory outputs, payload images and native evidence | Message refs and saved images | No source-image provenance | No complete live registry snapshot in these formats |
| Tool outputs and failures | Raw envelopes plus canonical outputs | Model-facing evidence/errors | Detection subset only | HTML is presentation; final prediction can carry a failure sentinel |
| Offline GT | Original agent result has no evaluator-added GT | Evaluator adds GT after inference | No | Prediction input columns, HTML and diagnostics can include GT information |
| Crop metadata | Requested coordinates and image refs; no actual integer crop transform | Call args and image refs only | No transform | Exact parent-to-child/root transform is not stored |

Current preflight files contain none of these runtime observations. A fresh
canonical `record.json`, rich/compact trajectory, detection sidecar, HTML,
prediction and per-row CSV remain acceptance requirements after restoration.
SAM3 scores must not be treated as calibrated probabilities. Evaluator-added
GT must remain offline and excluded from future controller inputs.

## 7. Official evaluation

No prediction exists to parse, validate or score. JSON validity, labels,
root-image geometry, 0–1000 coordinates and official metrics are **unverified**.
The new manifest stores the prediction, validity and official metrics as `null`
with the resource-blocker reason. No metric, threshold or evaluation code changed.
No paper-level score reproduction is claimed.

## 8. Evaluation-only reproduction

Not attempted: this task created no evaluator run or saved prediction.
The supported CLI form was already verified in Phase 02:

```bash
openvlharness-eval \
  --mode eval \
  --data ODinW13_bbox_val_qwen3 \
  --run-dir <actual_saved_run_directory>
```

The preflight directory is not a valid replacement for that run directory.
Agreement between metrics and absence of Qwen/tool calls during re-scoring remain
pending. Historical predictions were not substituted.

## 9. Reproducibility manifest and preserved files

Git remains `main` at `c530cdbdc6b7c4f486499eb7e5834ac2bd92692d`; tracked source
and configurations are unchanged. The original reports and previous outputs
were preserved. New repository files are this report and ignored preflight
artifacts only; no `.env`, runtime, package, checkpoint, dataset or global system
changes were made.

The new evidence directory contains `phase02b_manifest.json`, `gpu_preflight.json`,
`service_health.json`, `listening_ports.txt`, `source_identity.json`,
`validation.json` and `SHA256SUMS`. The manifest includes fresh source/GPU/service
identity, unchanged config hashes, zero-attempt counts, null results with reasons,
and explicitly dated inherited environment/checkpoint/sample evidence. No
credential values or unrelated command arguments were saved. File hashes provide
an integrity inventory, not write-protected or signed storage.

There is **no evaluator results directory or prediction artifact for Phase 02B**.
Preserve this timestamped attempt and use a new directory for later preflights.

## 10. Next-phase engineering requirements

**Phase 3 cannot begin on a verified baseline yet.** The next technical step is
resource coordination, followed by unchanged service restoration and the single
prescribed baseline run. Retain its canonical record, inspect every native
call/result pairing and numerical output, then verify evaluation-only reproduction.

No new trace exists to revise the prior instrumentation requirements. After
baseline review, the minimum separate observer proposal still needs: question-local
action/observation IDs; resolved image/frame identity; exact integer crop geometry
and composed transforms; cross-call detection provenance and explicit association;
logical-dispatch accounting distinct from malformed proposals and physical
attempts; shared image/checkpoint/query dependency records; and disjoint offline
calibration manifests and labels. Default-off equivalence checks must preserve
native payloads and predictions. None of this instrumentation, planning, fitting
or fine-tuning was implemented in Phase 02B.
