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

PARSEC-VL tool scheduler
  -s, --scheduler P        off | e0 (sequential FIFO) | e1 (parallel FIFO)   [off]
                           | e2 (critical-path priority); routes every tool
                           call through one shared scheduler.
                           e3 | e4 | e5 also let workers submit declared
                           action plans (Execute_Action_Plan): e3 Monte Carlo
                           plan selection, e4 fixed-width speculation, e5
                           selective speculation + replanning. e3-e5 change
                           the agents' decision protocol.
      --planning-processes N  CPU processes for Monte Carlo planning      [4]
      --scheduler-workers N  concurrent tool executions for e1/e2           [4]

Task source
  -d, --dataset NAME       prepared dataset                                 [FSC147_val]
      --agent-config FILE  agent/tool profile          [examples/local_grounding_tools.yaml]

Output and UI
      --runs-dir DIR       where runs are written                           [outputs/multi_agent]
      --tag TEXT           label added to each run id                       [custom]
      --port N             first Studio port to try                         [8787]
      --no-browser         do not open a browser (the link is printed)
      --ui-only            open Studio with saved runs; no task or model needed
      --start-services     start missing local GPU services, wait up to 10 minutes,
                           then run the task (new Qwen uses a 32k demo context)
      --check              only resolve each task's input (question + image, label sealed);
                           no model calls, no Studio
      --dry-run            print the commands and exit
  -h, --help

Model and tool services must already be running unless --start-services is used
(see README.md). If a
required service is down, Studio still opens for saved runs, but no task starts.

Examples
  bash scripts/run_custom_inference.sh 25
  bash scripts/run_custom_inference.sh -w 4 --memory off --peer on 10
  bash scripts/run_custom_inference.sh -w 1 -m off -p off -e off 0-2
  bash scripts/run_custom_inference.sh -w 3 --comm off --mode cooperative 3,7
  bash scripts/run_custom_inference.sh -w 2 --scheduler e1 25
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
scheduler=off scheduler_workers=4 planning_processes=4
dataset=FSC147_val agent_config=examples/local_grounding_tools.yaml
runs_dir=outputs/multi_agent tag=custom port="${STUDIO_PORT:-8787}" browser=true
check=false dry_run=false ui_only=false start_services=false
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
        -s|--scheduler) need "$@"; scheduler="$2"; shift 2 ;;
        --scheduler-workers) need "$@"; scheduler_workers="$2"; shift 2 ;;
        --planning-processes) need "$@"; planning_processes="$2"; shift 2 ;;
        -d|--dataset) need "$@"; dataset="$2"; shift 2 ;;
        --agent-config) need "$@"; agent_config="$2"; shift 2 ;;
        --runs-dir) need "$@"; runs_dir="$2"; shift 2 ;;
        --tag) need "$@"; tag="$2"; shift 2 ;;
        --port) need "$@"; port="$2"; shift 2 ;;
        --no-browser) browser=false; shift ;;
        --ui-only) ui_only=true; shift ;;
        --start-services) start_services=true; shift ;;
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
[[ "$scheduler" =~ ^(off|e0|e1|e2|e3|e4|e5)$ ]] || die "--scheduler must be off or e0-e5"
[[ "$planning_processes" =~ ^[0-9]+$ ]] || die "--planning-processes must be a nonnegative integer"
[[ "$scheduler_workers" =~ ^[1-9][0-9]*$ ]] || die "--scheduler-workers must be a positive integer"
[[ "$tag" =~ ^[A-Za-z0-9_-]+$ ]] || die "--tag may contain only letters, digits, _ and -"
flags=("$(onoff worker-memory "$memory")" "$(onoff peer-communication "$peer")"
       "$(onoff communication "$comm")" "$(onoff estimate-updates "$estimates")")
if [[ "${comm,,}" =~ ^(off|false|no|0)$ && "${peer,,}" =~ ^(on|true|yes|1)$ ]]; then
    echo "note: --comm off turns off the message bus, so peer messages are off too." >&2
fi
(( workers == 1 )) && [[ "${peer,,}" =~ ^(on|true|yes|1)$ ]] && echo "note: one worker has no peers; --peer on has no effect." >&2

"$ui_only" || (( ${#task_args[@]} )) || die "give at least one task index, e.g. 25 or 3,7 or 10-13 (or use --ui-only)"
if "$ui_only" && "$check"; then die "--ui-only and --check cannot be combined"; fi
if "$start_services" && { "$ui_only" || "$check"; }; then die "--start-services requires a real task, not --ui-only or --check"; fi
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

open_studio() {
    local ui_command=(python scripts/studio_ctl.py --runs-dir "$runs_dir" ensure --port "$port")
    "$browser" && ui_command+=(--open)
    if "$dry_run"; then printf '%q ' "${ui_command[@]}"; printf '\n'; return; fi
    "${ui_command[@]}"
}
if "$ui_only"; then
    echo "Opening Studio for saved runs. No new inference will run."
    open_studio
    exit $?
fi
if "$start_services"; then
    setup=(python scripts/ensure_local_services.py --agent-config "$agent_config")
    if "$dry_run"; then
        printf '%q ' "${setup[@]}"; printf '\n'
    else
        open_studio
        "${setup[@]}" || exit $?
    fi
fi

# ---- the model and tool services must be up before a run starts ------------------------
# Without this check a run waits minutes on connection retries and then fails with an
# error buried in its events. SKIP_SERVICE_CHECK=1 bypasses it.
if ! "$dry_run" && ! "$check" && [[ "${SKIP_SERVICE_CHECK:-0}" != 1 ]]; then
    up() { curl --fail -s -o /dev/null --max-time 5 "$1"; }
    model_url="${MODEL_BASE_URL:-http://127.0.0.1:8222/v1}"; model_url="${model_url%/}"
    router_url="${TOOL_SERVER_URL:-http://127.0.0.1:8101}"; router_url="${router_url%/}"
    missing=()
    up "$model_url/models" || missing+=("  model server  $model_url   start: bash scripts/service.sh qwen        (GPUs 0,1; loading takes a few minutes)")
    up "$router_url/health" || missing+=("  tool router   $router_url   start: AGENT_CONFIG=$agent_config bash scripts/service.sh router")
    if (( ${#missing[@]} )); then
        echo "error: required services are not running, so no run was started:" >&2
        printf '%s\n' "${missing[@]}" >&2
        echo "Use --start-services to start missing local services and wait, or see README.md for manual startup." >&2
        echo "Opening Studio for saved runs now; the requested task has NOT started." >&2
        open_studio || echo "Studio could not open. Retry with: bash scripts/run_custom_inference.sh --ui-only" >&2
        exit 3
    fi
    for svc in "SAM3 grounding|${SAM3_SERVER_URL:-}|sam3" "OCR|${OCR_SERVER_URL:-}|ocr" "depth|${DEPTH_ESTIMATION_SERVER_URL:-}|depth"; do
        IFS='|' read -r name url start <<< "$svc"
        [[ -z "$url" ]] && continue
        up "${url%/}/health" || up "${url%/}/v1/models" || up "${url%/}" || \
            echo "warning: $name service at $url is not answering; its tool calls will fail (start: bash scripts/service.sh $start)." >&2
    done
fi

on() { [[ "${1,,}" =~ ^(on|true|yes|1)$ ]] && echo on || echo off; }
effective_peer="$(on "$peer")"
[[ "$(on "$comm")" == off ]] && effective_peer=off   # no message bus, no peer messages
cfg_tag="w${workers}_mem$(on "$memory")_peer${effective_peer}"
[[ "$(on "$comm")" == off ]] && cfg_tag+="_commoff"
[[ "$(on "$estimates")" == off ]] && cfg_tag+="_estoff"
[[ "$scheduler" != off ]] && cfg_tag+="_sched${scheduler}"
stamp="$(date -u +%Y%m%d_%H%M%S)"

printf 'Dataset %s · tasks: %s\n' "$dataset" "${rows[*]}"
printf 'Team: coordinator + %s worker(s) · memory %s · peer %s · message bus %s · estimates %s · %s · follow-ups %s · scheduler %s\n' \
    "$workers" "$(on "$memory")" "$effective_peer" "$(on "$comm")" "$(on "$estimates")" "$mode" "$follow_ups" "$scheduler"

status=0
for i in "${!rows[@]}"; do
    row="${rows[$i]}"
    run_id="${tag}_${dataset,,}_row${row}_${cfg_tag}_${stamp}"
    task=(python scripts/run_studio_dataset_task.py --dataset "$dataset" --row "$row"
          --agent-config "$agent_config" --num-agents "$workers" --mode "$mode" "${flags[@]}"
          --follow-up-rounds "$follow_ups" --tool-scheduler "$scheduler" --scheduler-workers "$scheduler_workers"
          --planning-processes "$planning_processes"
          --output-dir "$runs_dir" --run-id "$run_id")
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
