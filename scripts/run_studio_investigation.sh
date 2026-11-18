#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 IMAGE_PATH 'QUESTION' [RUN_ID]" >&2
    exit 2
fi

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$REPO_ROOT"
source scripts/env.sh
# Runners load only the fast Qwen tokenizer (context counting); models run behind HTTP,
# so transformers' "None of PyTorch ... found" advisory does not apply.
export TRANSFORMERS_NO_ADVISORY_WARNINGS="${TRANSFORMERS_NO_ADVISORY_WARNINGS:-1}"

IMAGE_PATH="$1"
QUESTION="$2"
RUN_ID="${3:-investigation_$(date -u +%Y%m%d_%H%M%S)}"

exec python scripts/run_with_live_studio.py \
    --run-id "$RUN_ID" \
    --runs-dir outputs/multi_agent \
    -- python -m openvlharness.multi_agent.run \
    --config configs/multi_agent.yaml \
    --num-agents 2 \
    --mode concurrent \
    --image "$IMAGE_PATH" \
    --task "$QUESTION" \
    --output-dir outputs/multi_agent \
    --run-id "$RUN_ID"
