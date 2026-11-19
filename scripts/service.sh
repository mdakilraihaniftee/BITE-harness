#!/usr/bin/env bash
# Run a service in the foreground; process supervision stays with the caller.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
# download_models.py prepares model-ID refs at the documented revisions.
# Serving must not silently update those refs to a newer Hub main revision.
export HF_HUB_OFFLINE=1
service="${1:-}"
if [[ $# -gt 0 ]]; then shift; fi
case "$service" in
  qwen)
    export CUDA_VISIBLE_DEVICES="${QWEN_GPUS:-0,1}"
    export VLLM_WORKER_MULTIPROC_METHOD=spawn
    IFS=, read -ra devices <<< "$CUDA_VISIBLE_DEVICES"
    exec .venvs/vllm/bin/python -m vllm.entrypoints.openai.api_server \
      --model Qwen/Qwen3-VL-8B-Instruct \
      --served-model-name Qwen/Qwen3-VL-8B-Instruct \
      --host 127.0.0.1 --port 8222 --tensor-parallel-size "${#devices[@]}" \
      --dtype bfloat16 --max-model-len "${QWEN_CONTEXT_LENGTH:-168000}" \
      --gpu-memory-utilization 0.90 --enable-auto-tool-choice --tool-call-parser hermes \
      --max-num-seqs 4 --max-num-batched-tokens 16384 --enforce-eager \
      --limit-mm-per-prompt '{"video":0}' "$@"
    ;;
  ocr)
    export CUDA_VISIBLE_DEVICES="${OCR_GPUS:-3}"
    export PATH="$OPENVLHARNESS_ROOT/.venvs/vllm/bin:$PATH"
    exec bash openvlharness/services/tools/ocr/run_ocr_server.sh "$@"
    ;;
  depth)
    export CUDA_VISIBLE_DEVICES="${DEPTH_GPUS:-2}"
    exec .venvs/da3/bin/python -m uvicorn openvlharness.services.tools.depth_estimation.server:app \
      --host 127.0.0.1 --port 8087 "$@"
    ;;
  sam3)
    export CUDA_VISIBLE_DEVICES="${SAM3_GPUS:-3}"
    exec .venvs/sam3/bin/python -m uvicorn openvlharness.services.tools.sam3_segment.server:app \
      --host 127.0.0.1 --port 8086 "$@"
    ;;
  router)
    # Listen where the agents look for the router (TOOL_SERVER_URL in .env), e.g. 18101
    # when another project's router already holds the config's default port 8101.
    router_port="$(python -c 'import os,urllib.parse as u;print(u.urlsplit(os.environ.get("TOOL_SERVER_URL","")).port or "")')"
    exec python -m openvlharness.services.server --config "${AGENT_CONFIG:-configs/local_qwen.yaml}" \
      ${router_port:+--port "$router_port"} "$@"
    ;;
  image-host)
    exec python -m openvlharness.services.image_host --port 8111 "$@"
    ;;
  image-tunnel)
    exec .cache/bin/cloudflared tunnel --url http://127.0.0.1:8111 --no-autoupdate "$@"
    ;;
  *)
    echo 'Usage: bash scripts/service.sh {qwen|ocr|depth|sam3|router|image-host|image-tunnel} [extra arguments]' >&2
    exit 2
    ;;
esac
