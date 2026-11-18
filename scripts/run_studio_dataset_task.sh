#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$REPO_ROOT"
source scripts/env.sh
# Runners load only the fast Qwen tokenizer (context counting); models run behind HTTP,
# so transformers' "None of PyTorch ... found" advisory does not apply.
export TRANSFORMERS_NO_ADVISORY_WARNINGS="${TRANSFORMERS_NO_ADVISORY_WARNINGS:-1}"

DATASET="${1:-FSC147_val}"
ROW="${2:-0}"
RUN_ID="${3:-${DATASET,,}_row_${ROW}_$(date -u +%Y%m%d_%H%M%S)}"

# on/off environment switches -> --flag / --no-flag (anything else is an error).
flag() {
    case "$2" in
        on|true|1) printf -- "--%s" "$1" ;;
        off|false|0) printf -- "--no-%s" "$1" ;;
        *) echo "Invalid value for $1: '$2' (use on or off)" >&2; exit 2 ;;
    esac
}

exec python scripts/run_with_live_studio.py \
    --run-id "$RUN_ID" \
    --runs-dir outputs/multi_agent \
    -- python scripts/run_studio_dataset_task.py \
    --dataset "$DATASET" \
    --row "$ROW" \
    --num-agents "${STUDIO_NUM_AGENTS:-2}" \
    --mode "${STUDIO_EXECUTION_MODE:-concurrent}" \
    "$(flag worker-memory "${STUDIO_WORKER_MEMORY:-on}")" \
    "$(flag peer-communication "${STUDIO_PEER_COMMUNICATION:-on}")" \
    "$(flag estimate-updates "${STUDIO_ESTIMATE_UPDATES:-on}")" \
    --follow-up-rounds "${STUDIO_FOLLOW_UP_ROUNDS:-0}" \
    --agent-config "${AGENT_CONFIG:-examples/local_grounding_tools.yaml}" \
    --output-dir outputs/multi_agent \
    --run-id "$RUN_ID"
