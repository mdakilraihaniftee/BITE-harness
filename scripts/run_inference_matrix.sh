#!/usr/bin/env bash
# One real dataset example, varied across workers, notebook memory and messages.
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repo"

usage() {
    cat <<'EOF'
Usage: bash scripts/run_inference_matrix.sh [ROW] [options]

Runs the same example sequentially in 16 configurations:
  1,2,3,4 workers x memory on/off x communication on/off.
Worker counts exclude the coordinator. Peer messages follow communication.
Coordinator assignments and result handoff still work with communication off.

Options:
  ROW                   Zero-based dataset row (default: 25)
  --dataset NAME        Prepared dataset (default: FSC147_val)
  --scheduler MODE      off or e0-e5 (default: e2, fixed across the matrix)
  --runs-dir DIR        Output directory (default: new outputs/inference_matrix/ run)
  --start-services      Start missing local services before the first variant
  --studio              Open the first variant in the live visualization
  --dry-run             Preview commands; no inference or output files
  --help                Show this help

Estimates and follow-up rounds are disabled in every variant. Studio links are
printed for every variant; --studio opens the first one. Select other runs in
Studio's run menu. Individual runs retain normal events,
trajectories and final results; matrix_status.tsv records exit status and logs.

Examples:
  bash scripts/run_inference_matrix.sh 25 --dry-run
  bash scripts/run_inference_matrix.sh 25 --start-services --studio
  bash scripts/run_inference_matrix.sh 7 --scheduler e5
EOF
}
die() { echo "error: $*" >&2; exit 2; }
need() { [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || die "$1 needs a value"; }

row=25 dataset=FSC147_val scheduler=e2 runs_dir="" row_given=false
dry_run=false start_services=false studio=false
while (( $# )); do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --dataset) need "$@"; dataset="$2"; shift 2 ;;
        --scheduler) need "$@"; scheduler="$2"; shift 2 ;;
        --runs-dir) need "$@"; runs_dir="$2"; shift 2 ;;
        --start-services) start_services=true; shift ;;
        --studio) studio=true; shift ;;
        --dry-run) dry_run=true; shift ;;
        -*) die "unknown option '$1' (see --help)" ;;
        *) "$row_given" && die "supply exactly one example row";
           row="$1"; row_given=true; shift ;;
    esac
done
[[ "$row" =~ ^[0-9]+$ ]] || die "ROW must be a nonnegative integer"
[[ "$scheduler" =~ ^(off|e[0-5])$ ]] || die "--scheduler must be off or e0-e5"
if [[ -z "$runs_dir" ]]; then
    runs_dir="outputs/inference_matrix/$(date -u +%Y%m%dT%H%M%SZ)_$$"
fi
if ! "$dry_run"; then
    mkdir -p -- "$runs_dir/logs"
    printf 'workers\tmemory\tcommunication\tpeer\tscheduler\texit_code\tseconds\tlog\n' > "$runs_dir/matrix_status.tsv"
fi
printf 'Same example: %s row %s; 16 variants; scheduler %s\n' "$dataset" "$row" "$scheduler"
printf 'Runs directory: %s\n' "$runs_dir"

status=0 index=0
for workers in 1 2 3 4; do
    for memory in on off; do
        for comm in on off; do
            index=$((index + 1))
            peer="$comm"
            # A single worker cannot send peer messages.
            (( workers == 1 )) && peer=off
            variant="w${workers}_mem_${memory}_comm_${comm}"
            command=(bash scripts/run_custom_inference.sh
                --dataset "$dataset" --workers "$workers" --memory "$memory"
                --comm "$comm" --peer "$peer" --scheduler "$scheduler"
                --estimates off --follow-ups 0 --mode concurrent
                --runs-dir "$runs_dir/runs" --tag "matrix_${variant}")
            if ! "$studio" || (( index != 1 )); then command+=(--no-browser); fi
            "$start_services" && command+=(--start-services)
            "$dry_run" && command+=(--dry-run)
            command+=("$row")
            printf '\nVariant %s/16: %s (peer %s)\n' "$index" "$variant" "$peer"
            if "$dry_run"; then
                "${command[@]}"
            else
                began=$SECONDS
                code=0
                "${command[@]}" 2>&1 | tee "$runs_dir/logs/$variant.log" || code=$?
                printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
                    "$workers" "$memory" "$comm" "$peer" "$scheduler" "$code" \
                    "$((SECONDS - began))" "logs/$variant.log" >> "$runs_dir/matrix_status.tsv"
                (( code == 0 )) || status=1
            fi
            start_services=false
        done
    done
done
if ! "$dry_run"; then
    printf '\nMatrix exit statuses: %s/matrix_status.tsv\n' "$runs_dir"
    printf 'Open recorded runs:\n  bash scripts/run_custom_inference.sh --ui-only --runs-dir %q\n' "$runs_dir/runs"
fi
exit "$status"
