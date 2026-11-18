#!/usr/bin/env bash
# One or two real dataset tasks, each followed live in Investigation Studio.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: bash scripts/run_studio_inferences.sh [--dry-run] [ROW [ROW]]

Run one or two zero-based FSC147_val rows (default: row 0).
Each task opens its live Investigation Story; Technical Trace is available beside it.
Model and tool services must already be running (see README.md).

Examples:
  bash scripts/run_studio_inferences.sh 0
  bash scripts/run_studio_inferences.sh 0 10
  bash scripts/run_studio_inferences.sh --dry-run 0 10

Existing Studio options apply: STUDIO_NUM_AGENTS (default 2 workers plus coordinator),
STUDIO_WORKER_MEMORY, STUDIO_PEER_COMMUNICATION, STUDIO_ESTIMATE_UPDATES,
STUDIO_EXECUTION_MODE, STUDIO_FOLLOW_UP_ROUNDS, STUDIO_PORT, STUDIO_OPEN_BROWSER,
and AGENT_CONFIG. STUDIO_DATASET selects a prepared dataset (default FSC147_val).
--dry-run prints commands without starting the UI, loading data, or running inference.
EOF
}

dry_run=false
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then usage; exit 0; fi
if [[ "${1:-}" == "--dry-run" ]]; then dry_run=true; shift; fi
if (( $# > 2 )); then usage >&2; exit 2; fi
if (( $# == 0 )); then set -- 0; fi
rows=("$@")
# Validate every row before starting any inference.
for row in "${rows[@]}"; do
    if [[ ! "$row" =~ ^[0-9]+$ ]]; then
        echo "Invalid row: '$row'. Use one or two nonnegative row positions." >&2
        exit 2
    fi
done

task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$task_root"
dataset="${STUDIO_DATASET:-FSC147_val}"
batch_id="$(date -u +%Y%m%d_%H%M%S)_$$_${RANDOM}"
ordinal=0
for row in "${rows[@]}"; do
    ordinal=$((ordinal + 1))
    run_id="studio_inference_${batch_id}_${ordinal}_row_${row}"
    command=(bash scripts/run_studio_dataset_task.sh "$dataset" "$row" "$run_id")
    printf 'Task %s/%s — dataset %s, row %s\n' "$ordinal" "${#rows[@]}" "$dataset" "$row"
    if "$dry_run"; then
        printf '%q ' "${command[@]}"
        printf '\n'
    else
        "${command[@]}"
    fi
done
