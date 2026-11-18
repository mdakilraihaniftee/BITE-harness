#!/usr/bin/env bash
# Run chosen dataset tasks with a custom team configuration, each followed live in
# Investigation Studio. Thin front end over scripts/run_studio_dataset_task.py.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: bash scripts/run_custom_inference.sh [options] TASKS

TASKS   zero-based row index(es) in the dataset: 25 | 3,7,12 | 10-13 | 0 5-6 9
        Tasks run one after another; each gets its own run and Studio view.

Team
  -w, --workers N          number of workers, 1-4 (plus one coordinator)    [2]
  -m, --memory on|off      private worker notebook across phases            [on]
  -p, --peer on|off        worker-to-worker messages                        [on]
  -c, --comm on|off        message bus for reports and peer messages        [on]
                           (off also disables peer messages; assignments
                           are always delivered)
  -e, --estimates on|off   coordinator provisional estimates (each costs    [on]
                           one extra model request)
      --mode MODE          concurrent | cooperative                         [concurrent]
      --follow-ups N       extra coordinator follow-up rounds               [0]
      --reassess N         max coordinator reassessments                    [runtime default]

Task source
  -d, --dataset NAME       prepared dataset                                 [FSC147_val]
      --agent-config FILE  agent/tool profile          [examples/local_grounding_tools.yaml]

Output and UI
      --runs-dir DIR       where runs are written                           [outputs/multi_agent]
      --tag TEXT           label added to each run id                       [custom]
      --port N             first Studio port to try                         [8787]
      --no-browser         do not open a browser (the link is printed)
      --check              only resolve each task's input (question + image, label sealed);
                           no model calls, no Studio
      --dry-run            print the commands and exit
  -h, --help

Model and tool services must already be running (see README.md).

Examples
  bash scripts/run_custom_inference.sh 25
  bash scripts/run_custom_inference.sh -w 4 --memory off --peer on 10
  bash scripts/run_custom_inference.sh -w 1 -m off -p off -e off 0-2
  bash scripts/run_custom_inference.sh -w 3 --comm off --mode cooperative 3,7
  bash scripts/run_custom_inference.sh --check 0-4          # look before running
  bash scripts/run_custom_inference.sh --dry-run -w 2 5 9   # print commands only
EOF
}

die() { echo "error: $*" >&2; echo "Run with --help for usage." >&2; exit 2; }
onoff() {  # name value -> --name | --no-name
    case "${2,,}" in
        on|true|yes|1) printf -- "--%s" "$1" ;;
        off|false|no|0) printf -- "--no-%s" "$1" ;;
        *) die "$1 must be on or off (got '$2')" ;;
    esac
}
need() { [[ $# -ge 2 && -n "$2" ]] || die "$1 needs a value"; }

workers=2 memory=on peer=on comm=on estimates=on mode=concurrent follow_ups=0 reassess=""
dataset=FSC147_val agent_config=examples/local_grounding_tools.yaml
runs_dir=outputs/multi_agent tag=custom port="${STUDIO_PORT:-8787}" browser=true
check=false dry_run=false
task_args=()

while (( $# )); do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        -w|--workers) need "$@"; workers="$2"; shift 2 ;;
        -m|--memory) need "$@"; memory="$2"; shift 2 ;;
        -p|--peer) need "$@"; peer="$2"; shift 2 ;;
        -c|--comm) need "$@"; comm="$2"; shift 2 ;;
        -e|--estimates) need "$@"; estimates="$2"; shift 2 ;;
        --mode) need "$@"; mode="$2"; shift 2 ;;
        --follow-ups) need "$@"; follow_ups="$2"; shift 2 ;;
        --reassess) need "$@"; reassess="$2"; shift 2 ;;
        -d|--dataset) need "$@"; dataset="$2"; shift 2 ;;
        --agent-config) need "$@"; agent_config="$2"; shift 2 ;;
        --runs-dir) need "$@"; runs_dir="$2"; shift 2 ;;
        --tag) need "$@"; tag="$2"; shift 2 ;;
        --port) need "$@"; port="$2"; shift 2 ;;
        --no-browser) browser=false; shift ;;
        --check) check=true; shift ;;
        --dry-run) dry_run=true; shift ;;
        --) shift; task_args+=("$@"); break ;;
        -*) die "unknown option '$1'" ;;
        *) task_args+=("$1"); shift ;;
    esac
done

# ---- validate everything before anything runs -------------------------------------------
[[ "$workers" =~ ^[1-4]$ ]] || die "--workers must be 1-4 (got '$workers')"
[[ "$mode" == concurrent || "$mode" == cooperative ]] || die "--mode must be concurrent or cooperative"
[[ "$follow_ups" =~ ^[0-9]+$ ]] || die "--follow-ups must be a nonnegative integer"
[[ -z "$reassess" || "$reassess" =~ ^[0-9]+$ ]] || die "--reassess must be a nonnegative integer"
[[ "$port" =~ ^[0-9]+$ ]] || die "--port must be a number"
[[ "$tag" =~ ^[A-Za-z0-9_-]+$ ]] || die "--tag may contain only letters, digits, _ and -"
flags=("$(onoff worker-memory "$memory")" "$(onoff peer-communication "$peer")"
       "$(onoff communication "$comm")" "$(onoff estimate-updates "$estimates")")
if [[ "${comm,,}" =~ ^(off|false|no|0)$ && "${peer,,}" =~ ^(on|true|yes|1)$ ]]; then
    echo "note: --comm off turns off the message bus, so peer messages are off too." >&2
fi
(( workers == 1 )) && [[ "${peer,,}" =~ ^(on|true|yes|1)$ ]] && echo "note: one worker has no peers; --peer on has no effect." >&2

(( ${#task_args[@]} )) || die "give at least one task index, e.g. 25 or 3,7 or 10-13"
rows=()
for arg in "${task_args[@]}"; do
    IFS=',' read -ra parts <<< "$arg"
    for part in "${parts[@]}"; do
        [[ -z "$part" ]] && continue
        if [[ "$part" =~ ^([0-9]+)-([0-9]+)$ ]]; then
            lo=$((10#${BASH_REMATCH[1]})); hi=$((10#${BASH_REMATCH[2]}))
            (( lo <= hi )) || die "range '$part' goes backwards"
            (( hi - lo < 200 )) || die "range '$part' is too large (max 200 tasks)"
            for ((r = lo; r <= hi; r++)); do rows+=("$r"); done
        elif [[ "$part" =~ ^[0-9]+$ ]]; then
            rows+=("$((10#$part))")
        else
            die "invalid task index '$part' (use 25, 3,7 or 10-13)"
        fi
    done
done

repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repo"
[[ -f "$agent_config" ]] || die "agent config not found: $agent_config"
if ! "$dry_run"; then
    # shellcheck disable=SC1091
    source scripts/env.sh
    export TRANSFORMERS_NO_ADVISORY_WARNINGS="${TRANSFORMERS_NO_ADVISORY_WARNINGS:-1}"
fi

on() { [[ "${1,,}" =~ ^(on|true|yes|1)$ ]] && echo on || echo off; }
effective_peer="$(on "$peer")"
[[ "$(on "$comm")" == off ]] && effective_peer=off   # no message bus, no peer messages
cfg_tag="w${workers}_mem$(on "$memory")_peer${effective_peer}"
[[ "$(on "$comm")" == off ]] && cfg_tag+="_commoff"
[[ "$(on "$estimates")" == off ]] && cfg_tag+="_estoff"
stamp="$(date -u +%Y%m%d_%H%M%S)"

printf 'Dataset %s · tasks: %s\n' "$dataset" "${rows[*]}"
printf 'Team: coordinator + %s worker(s) · memory %s · peer %s · message bus %s · estimates %s · %s · follow-ups %s\n' \
    "$workers" "$(on "$memory")" "$effective_peer" "$(on "$comm")" "$(on "$estimates")" "$mode" "$follow_ups"

status=0
for i in "${!rows[@]}"; do
    row="${rows[$i]}"
    run_id="${tag}_${dataset,,}_row${row}_${cfg_tag}_${stamp}"
    task=(python scripts/run_studio_dataset_task.py --dataset "$dataset" --row "$row"
          --agent-config "$agent_config" --num-agents "$workers" --mode "$mode" "${flags[@]}"
          --follow-up-rounds "$follow_ups" --output-dir "$runs_dir" --run-id "$run_id")
    [[ -n "$reassess" ]] && task+=(--max-reassessments "$reassess")
    if "$check"; then
        command=("${task[@]}" --inspect-only)
    else
        command=(python scripts/run_with_live_studio.py --run-id "$run_id" --runs-dir "$runs_dir" --port "$port")
        "$browser" || command+=(--no-browser)
        command+=(-- "${task[@]}")
    fi
    printf '\n== Task %s/%s · row %s · run %s\n' "$((i + 1))" "${#rows[@]}" "$row" "$run_id"
    if "$dry_run"; then printf '%q ' "${command[@]}"; printf '\n'; continue; fi
    rc=0; "${command[@]}" || rc=$?
    if (( rc )); then
        echo "Task row $row failed (exit $rc); continuing with the next task." >&2
        status=1
    fi
done
"$dry_run" || "$check" || printf '\nRuns are in %s. Reopen one later with:\n  python scripts/studio_ctl.py --runs-dir %s url --run <run_id> --open\n' "$runs_dir" "$runs_dir"
exit "$status"
