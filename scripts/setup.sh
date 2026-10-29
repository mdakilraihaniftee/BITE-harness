#!/usr/bin/env bash
# Recreate the source-checkout environments without changing system Python.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$PWD/.cache/pip}"
mkdir -p "$PIP_CACHE_DIR" outputs/setup

bootstrap_env() {
    local target_env="$1"
    # --without-pip also works on Debian installations missing ensurepip.
    python3 -m venv --without-pip "$target_env"
    if ! "$target_env/bin/python" -m pip --version >/dev/null 2>&1; then
        python3 -m pip --python "$target_env/bin/python" install pip
    fi
}

bootstrap_env .venv
.venv/bin/python -m pip install -e '.[qwen,server,eval,test]' \
    'transformers==4.57.3' 'huggingface_hub==0.35.3' 'ruff==0.16.10'
if [[ ! -f .env ]]; then cp .env.example .env; fi
for component in "$@"; do
    case "$component" in
      vllm)
        bootstrap_env .venvs/vllm
        .venvs/vllm/bin/python -m pip install 'vllm==0.18.1' 'transformers==4.57.3' 'huggingface_hub==0.35.3'
        ;;
      sam3)
        bootstrap_env .venvs/sam3
        (source .venvs/sam3/bin/activate; bash openvlharness/services/tools/sam3_segment/install.sh)
        ;;
      depth)
        bootstrap_env .venvs/da3
        (source .venvs/da3/bin/activate; bash openvlharness/services/tools/depth_estimation/install.sh)
        ;;
      *) echo "Unknown component: $component (choose vllm, sam3, depth)" >&2; exit 2 ;;
    esac
done
echo 'Environment ready. Run: source scripts/env.sh'
echo 'Cache checkpoints: python scripts/download_models.py qwen ocr depth [sam3]'
