#!/usr/bin/env bash
# Deterministic Studio demonstration (TEST FIXTURE: scripted policy, no model servers).
# Configure with STUDIO_NUM_AGENTS (1-4), STUDIO_WORKER_MEMORY, STUDIO_PEER_COMMUNICATION,
# STUDIO_ESTIMATE_UPDATES (on|off), STUDIO_EXECUTION_MODE, and STUDIO_DEMO_DELAY (seconds
# per scripted model request).
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$REPO_ROOT"
source scripts/env.sh
# Runners load only the fast Qwen tokenizer (context counting); models run behind HTTP,
# so transformers' "None of PyTorch ... found" advisory does not apply.
export TRANSFORMERS_NO_ADVISORY_WARNINGS="${TRANSFORMERS_NO_ADVISORY_WARNINGS:-1}"

RUN_ID="${1:-studio_demo_$(date -u +%Y%m%d_%H%M%S)}"
exec python scripts/run_with_live_studio.py \
    --run-id "$RUN_ID" \
    --runs-dir outputs/multi_agent \
    -- python scripts/studio_config_matrix.py run \
    --workers "${STUDIO_NUM_AGENTS:-2}" \
    --memory "${STUDIO_WORKER_MEMORY:-on}" \
    --peer "${STUDIO_PEER_COMMUNICATION:-on}" \
    --estimates "${STUDIO_ESTIMATE_UPDATES:-on}" \
    --mode "${STUDIO_EXECUTION_MODE:-cooperative}" \
    --output-dir outputs/multi_agent \
    --run-id "$RUN_ID" \
    --step-delay "${STUDIO_DEMO_DELAY:-0.35}"
