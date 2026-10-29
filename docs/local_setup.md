# Local research environment

All nine capabilities are configured and passed live probes on this checkout.
The active `.env` selects the unchanged
`configs/agent/qwen3_8b_paper.yaml`. Qwen, SAM3, OCR, depth/pose, the router,
the image host, and the approved image tunnel are running.

## Start working

Run from the repository root:

```bash
source scripts/env.sh
python scripts/check_environment.py
python scripts/infer.py outputs/setup/bottles.png \
  --question 'How many bottles are visible?' \
  --output outputs/bottles-inference.json
```

`source scripts/env.sh` activates the editable harness environment and reads the
ignored `.env` as data. It loads model endpoints, provider credentials, GPU
assignments, dataset/cache locations, and `AGENT_CONFIG`. Both the router and
Python API need these variables. The evaluator also reads `.env` itself.
Credentials are not stored in tracked configuration files.

`python scripts/check_environment.py --probe-tools` executes actual backends,
including provider calls that use search credits. It validates decoded depth,
ordered camera matrices, image crops, OCR, generated Python, search, page visits,
and reverse image search, then checks provider/auxiliary degradation counters.
The repeated-frame camera probe checks the output contract, not motion accuracy.
The report is `outputs/setup/environment.json`; failed checks exit nonzero.

## Services and restart commands

Services are already running. After a reboot or shutdown, use one terminal per
foreground command. Stop an existing service before starting another on its port.

| Service | Command | Port | GPU |
| --- | --- | --- | --- |
| Qwen main + auxiliary | `bash scripts/service.sh qwen` | 8222 | 0,1 |
| SAM3 grounding | `bash scripts/service.sh sam3` | 8086 | 3 |
| PaddleOCR-VL | `bash scripts/service.sh ocr` | 8085 | 3 |
| DA3 depth + camera poses | `bash scripts/service.sh depth` | 8087 | 2 |
| Tool router | `bash scripts/service.sh router` | 8101 | CPU |
| Query-image host | `bash scripts/service.sh image-host` | 8111 | CPU |
| Approved image tunnel | `bash scripts/service.sh image-tunnel` | public URL | CPU |

The image host serves content-hash-named images only from `.cache/image-host`.
Public query-image hosting was explicitly approved and has passed the router's
public-fetch and Serper Lens checks. The tunnel's hostname changes when restarted:
copy its new URL from the log into `IMAGE_UPLOAD_PUBLIC_BASE_URL` in `.env`,
then restart the router. Images published there are fetchable by URL while the
tunnel runs. See [Cloudflare's Quick Tunnel documentation](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).
For a stable hosting address, use the README's S3/GCS or named-tunnel deployment.

`.venv` contains the harness, router, tokenizer, evaluator, and tests.
`.venvs/vllm` serves Qwen and OCR in separate processes; `.venvs/sam3` and
`.venvs/da3` isolate perception dependencies. System Python is unchanged.
GPU services require NVIDIA device access. Checkpoints are pinned in the local
Hugging Face cache, and launchers use offline resolution after downloads.

## Optional You.com backends

The two new backends are `youcom_text_search` and `youcom_webpage_visit`.
They reuse the existing summarizer, page extractor, URL memory, content limits,
and challenge detection. Serper remains the default in the paper presets and
is the reverse-image-search provider in both configurations.

`configs/local_qwen_youcom.yaml` is a complete nine-capability alternative.
To select it, change `AGENT_CONFIG` in `.env` to that path and restart the router.
Use the same config for agent inference and evaluation. General You.com web
search works without a key; Contents requires `YDC_API_KEY` or
`YDC_API_KEY_FILE`. The supplied key has passed both APIs live. For keyless use,
remove the You.com page-visit capability/service or select Serper page visits.
You.com advertises only `search_type: search`; other Serper search modes remain
available when the Serper backend is selected.

The [You.com backend guide](../openvlharness/services/tools/youcom_text_search/README.md)
covers request contracts, retry/Retry-After handling, errors, credentials, and
configuration fragments. Provider choice changes retrieved evidence and should
be recorded when comparing experiments.

Other retained local profiles provide smaller tool sets:

| Configuration | Capabilities |
| --- | --- |
| `configs/local_qwen.yaml` | OCR, depth, camera poses, zoom, coding |
| `configs/local_qwen_web.yaml` | Above + Serper text search and page visits |
| `configs/local_qwen_search.yaml` | Above + Serper reverse image search |
| `configs/local_qwen_grounding.yaml` | Local perception/coding + SAM3, text search, page visits |

## Evaluation

`LMUData` points at `data/`; runs go under `outputs/`. FSC147 and ODinW validation
TSVs/images and ODinW ground-truth annotations are prepared locally.

```bash
source scripts/env.sh
openvlharness-eval \
  --config configs/agent/qwen3_8b_paper.yaml \
  --judge-config configs/judge_no_judge.yaml \
  --data FSC147_val ODinW13_bbox_val_qwen3 \
  --num-examples 12 --shuffle --seed 42 \
  --num-proc 1 --save-html all --work-dir outputs/evaluations
```

The completed counting-plus-grounding run is under
`outputs/grounding-evaluations/Qwen3-VL-8B-Instruct/mainagent/`. It sampled 12
questions per dataset, used constant-confidence direct metrics, and saved
predictions, HTML, trajectories, detection sidecars, and configuration identity.
It used `configs/local_qwen_grounding.yaml` before reverse image search was
added to the active router. Results are installation checks, not paper reproduction.

| Split | Recorded result |
| --- | --- |
| FSC147_val, 12 questions | MAE 18.08; RMSE 42.77; exact-count accuracy 50.00% |
| ODinW validation, 12 questions | AP 72.79; AP50 87.56; AP75 77.16 (sampled-domain mean) |

One ODinW question, `PascalVOC_val_1178`, exhausted `agent.max_iterations: 15`
while making category-by-category grounding calls. Its saved failure and partial
trajectory are retained. No perception/provider service error caused that limit.
For experiments requiring more tool turns, copy the config, increase the budget,
and assign a new `agent_config_version`; use a fresh run to preserve identity.
The paper presets retain their original settings.

The earlier five-capability counting smoke run remains in `outputs/evaluations/`.
Evaluation-only re-scoring passed. A separate one-question run under
`outputs/raw-trace-validation/` exported one Qwen token trace with zero export
failures. The README describes resume, failed-row retries, evaluation-only mode,
judge settings, and raw-trace requirements.

## Verified inference artifacts

| Artifact | Live result |
| --- | --- |
| `outputs/bottles-inference.json` | Qwen answered `3` |
| `outputs/grounding-inference.json` | Agent called SAM3 grounding and answered `3` |
| `outputs/ocr-coding-inference.json` | OCR result retained in memory; Python computed `861` |
| `outputs/reverse-image-inference.json` | Agent consumed reverse-image evidence and answered `3` |
| `outputs/youcom-search-visit-inference.json` | You.com search then page visit returned `https://docs.python.org/3/` |
| `outputs/setup/image-search-live.json` | Public benchmark image returned reverse-search image evidence; no degradations |
| `outputs/setup/youcom-environment.json` | Live You.com-backed router and tool probes passed |

## Recreate and verify

```bash
bash scripts/setup.sh                 # harness, router, evaluation, tests
bash scripts/setup.sh vllm depth sam3 # also install GPU service environments
source scripts/env.sh
python scripts/download_models.py qwen ocr depth sam3
python -m pip check
python -m pytest tests -q
ruff check --isolated --select E9,F63,F7,F82 .
```

The bootstrap handles this host's missing `ensurepip` using system
`pip --python`; it requires Python 3.10+ and pip 22.3+. The serving environment
uses vLLM 0.18.1 and Transformers 4.57.3. The harness tokenizer uses Transformers
4.57.3 and huggingface-hub 0.35.3. Checkpoints/source revisions match the
repository deployment guides. Caches, data, environments, and run outputs are
ignored by Git. Do not remove caches while services are using them.

The final regression run passed **531 tests and 449 subtests**, including 25 new
You.com tests. All nine live capability probes passed with zero degradations.
All paper presets and local configurations resolve to registered backends.
The README's 32 documented dataset names resolve to loaders; full dataset
benchmarks and hosted GPT/Kimi endpoints have not all been run.

Depth setup fixes install the pinned upstream model's undeclared `addict`
dependency and use the supported Matplotlib colormap registry. New CPU-only
regressions cover rendering and its missing-Matplotlib fallback. The You.com
coverage checks wire formats, key precedence, no key downgrade, bounded retries,
Retry-After, errors, empty results, challenge handling, router wiring, and schema
isolation from the Serper defaults.

Records: `outputs/setup/pytest.log`, `pytest.xml`, `*-requirements.txt`, live
preflight JSON files, and `outputs/services/*.log`. Credentials stay in `.env`.
