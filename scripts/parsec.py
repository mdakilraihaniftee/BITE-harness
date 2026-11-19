#!/usr/bin/env python
"""PARSEC-VL command line: scheduling, planning, speculation, experiments, and visualization.

  python scripts/parsec.py profile                 # recorded real runs in outputs/multi_agent
  python scripts/parsec.py probe                   # real tool services, no model calls
  python scripts/parsec.py bench                   # synthetic DAG workloads, E0/E1/E2, worker scaling
  python scripts/parsec.py harness                 # whole multi-agent fixture runs, scheduler off/e0/e1/e2
  python scripts/parsec.py plan-bench              # multicore Monte Carlo planning
  python scripts/parsec.py spec-bench              # speculation scenarios A-E (S0/S1/S2)
  python scripts/parsec.py actions-bench           # declared parallel plan in the harness (E0/E1/E2)
  python scripts/parsec.py agents-bench            # coordinator + workers, OFF/E2/E3/E4/E5
  python scripts/parsec.py outcome-model           # empirical outcome model from recorded runs
  python scripts/parsec.py demo                    # one-command course demonstration (no model)
  python scripts/parsec.py figures                 # course figures from recorded results

Outputs (raw JSON plus a Markdown summary) go to outputs/parsec_vl/<command>/.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

OUT = Path("outputs/parsec_vl")


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


def _environment() -> dict:
    import platform
    return {"python": platform.python_version(), "cpus": os.cpu_count(), "platform": platform.platform(),
            "recorded_at": datetime.now(UTC).isoformat()}


# ---- profile ---------------------------------------------------------------------------------
def cmd_profile(args) -> int:
    from openvlharness.parsec_vl.profiling import aggregate, profile_run

    dirs = [Path(d) for d in args.runs] or sorted(p.parent for p in Path(args.runs_dir).glob("*/events.jsonl"))
    profiles, skipped = [], []
    for run_dir in dirs:
        try:
            profile = profile_run(run_dir)
        except Exception as exc:  # noqa: BLE001 - report and continue
            skipped.append({"run": str(run_dir), "reason": f"{type(exc).__name__}: {exc}"})
            continue
        if args.include_fixtures or profile["real_model_service"]:
            profiles.append(profile)
        else:
            skipped.append({"run": str(run_dir), "reason": "scripted test policy (no real model service)"})
    summary = aggregate(profiles) if profiles else {}
    out = Path(args.out)
    _write(out / "profile.json", {"environment": _environment(), "aggregate": summary, "runs": profiles, "skipped": skipped})
    lines = ["| run | workers | mode | scheduler | wall s | model busy/wall | tool busy/wall | tool calls | peak tools | peak model | T1 s | Tinf s | T1/Tinf | multi-call turns |",
             "|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for p in profiles:
        d = p["dependencies"]
        lines.append(f"| {p['run_id']} | {p['workers']} | {p['execution_mode']} | {p['tool_scheduler']} | {p['wall_seconds']:.1f} | "
                     f"{p['share_of_wall']['model']:.2f} | {p['share_of_wall']['tools']:.2f} | {p['tool_calls']['count']} | "
                     f"{p['peak_concurrent_tool_calls']} | {p['peak_concurrent_model_requests']} | {d['T1']:.1f} | {d['Tinf_current']:.1f} | "
                     f"{d['available_parallelism_current']} | {d['multi_call_turns']}/{d['turns_with_tools']} |")
    (out / "profile.md").write_text("\n".join(lines) + "\n\n```json\n" + json.dumps(summary, indent=1) + "\n```\n")
    print("\n".join(lines))
    print(json.dumps(summary, indent=1))
    print(f"\n{len(profiles)} run(s) profiled, {len(skipped)} skipped -> {out}/profile.json")
    return 0


# ---- probe -----------------------------------------------------------------------------------
PROBE_CALLS = {
    "grounding": ("Visual_Grounding_Tool", {"image_id": "input_image_1", "query": "grape"}),
    "ocr": ("OCR_Tool", {"image_id": "input_image_1"}),
    "depth": ("Depth_Estimation_Tool", {"image_id": "input_image_1"}),
    "zoom": ("Zoom_In_Tool", {"image_id": "input_image_1", "coords": [100, 100, 600, 600]}),
}


def cmd_probe(args) -> int:
    """Real tool-service latency and throughput at several client concurrencies (no model calls)."""
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from openvlharness.bootstrap import build_capabilities, load_agent_config, memory_factory
    from openvlharness.contracts import VirtualCall

    config = load_agent_config(args.agent_config)
    capabilities = build_capabilities(config)
    make_memory = memory_factory(config["memory"])
    image = Path(args.image)
    mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"
    data_url = f"data:{mime};base64,{base64.b64encode(image.read_bytes()).decode()}"
    results = {}
    for key in args.tools.split(","):
        name, arguments = PROBE_CALLS[key]
        capability = capabilities[name]

        def one(index: int) -> dict:
            memory = make_memory()
            memory.register_image(data_url, aliases=("input_image_1",))
            began = time.monotonic()
            result = capability.invoke(VirtualCall(f"probe_{key}_{index}", name, dict(arguments)), memory)
            return {"seconds": time.monotonic() - began, "ok": result.ok,
                    "error": (result.error or {}).get("code") if not result.ok else None}

        one(-1)  # warm-up, not recorded
        per_level = {}
        for level in [int(c) for c in args.concurrency.split(",")]:
            began = time.monotonic()
            with ThreadPoolExecutor(max_workers=level) as pool:
                calls = list(pool.map(one, range(args.requests)))
            wall = time.monotonic() - began
            latencies = [c["seconds"] for c in calls]
            per_level[level] = {"requests": args.requests, "wall_seconds": round(wall, 4),
                                "throughput_per_s": round(args.requests / wall, 4),
                                "latency_median": round(statistics.median(latencies), 4),
                                "latency_max": round(max(latencies), 4),
                                "failures": [c["error"] for c in calls if not c["ok"]]}
        base = per_level[min(per_level)]["throughput_per_s"]
        for level, row in per_level.items():
            row["throughput_vs_1"] = round(row["throughput_per_s"] / base, 3)
        results[key] = {"tool": name, "pool": None, "levels": per_level}
        print(key, json.dumps(per_level))
    from openvlharness.parsec_vl.harness import resource_pool
    for key, row in results.items():
        row["pool"] = resource_pool(capabilities[row["tool"]], name=row["tool"])
    out = Path(args.out)
    _write(out / "probe.json", {"environment": _environment(), "image": str(image), "measurement": "REAL services",
                                "results": results})
    lines = ["| tool | pool | concurrency | requests | wall s | throughput /s | vs c=1 | median latency s | failures |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for key, row in results.items():
        for level, r in row["levels"].items():
            lines.append(f"| {row['tool']} | {row['pool']} | {level} | {r['requests']} | {r['wall_seconds']} | {r['throughput_per_s']} | "
                         f"{r['throughput_vs_1']} | {r['latency_median']} | {len(r['failures'])} |")
    (out / "probe.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


# ---- bench -----------------------------------------------------------------------------------
def _mean_sd(values):
    return (statistics.fmean(values), statistics.stdev(values) if len(values) > 1 else 0.0)


def cmd_bench(args) -> int:
    from openvlharness.parsec_vl.dag import graph_metrics, lower_bound
    from openvlharness.parsec_vl.workloads import WORKLOADS, run_workload

    out = Path(args.out)
    raw, rows = [], []
    workloads = args.workloads.split(",")
    policies = args.policies.split(",")
    for name in workloads:
        tasks, capacities = WORKLOADS[name]()
        # Bounds use durations measured in the uncontended sequential (E0) runs, not the
        # declared estimates (which may be wrong on purpose, see M_misestimated).
        reference = [run_workload(name, "e0", 1) for _ in range(args.trials)]
        measured = {r["task_id"]: statistics.median(t_["records"][i]["finish_time"] - t_["records"][i]["start_time"]
                                                    for t_ in reference)
                    for i, r in enumerate(reference[0]["records"])}
        metrics = graph_metrics(tasks, durations=measured)
        for workers in [int(w) for w in args.workers.split(",")]:
            for policy in policies:
                if policy == "e0" and workers != 1:
                    continue  # E0 is single-slot by definition; measured once
                trials = reference if policy == "e0" else [run_workload(name, policy, workers) for _ in range(args.trials)]
                for trial in trials:
                    raw.append({k: v for k, v in trial.items()})
                spans = [t["makespan"] for t in trials]
                mean, sd = _mean_sd(spans)
                bound = lower_bound(metrics, capacities, workers=trials[0]["workers"]) if not metrics["unknown_durations"] else None
                rows.append({"workload": name, "policy": policy, "workers": trials[0]["workers"], "trials": len(trials),
                             "makespan_mean": mean, "makespan_sd": sd, "makespan_min": min(spans), "makespan_max": max(spans),
                             "peak_concurrency": max(t["peak_concurrency"] for t in trials),
                             "budget_used": trials[0]["budget_used"], "status": trials[0]["status"],
                             "queue_wait_mean": statistics.fmean(t["queue_wait"]["mean"] or 0 for t in trials),
                             "dependency_wait_mean": statistics.fmean(t["dependency_wait"]["mean"] or 0 for t in trials),
                             "dispatch_latency_mean": statistics.fmean(t["dispatch_latency"]["mean"] or 0 for t in trials),
                             "decision_seconds_mean": statistics.fmean(t["scheduler_decision_seconds"] for t in trials),
                             "worker_idle_mean": statistics.fmean(t["worker_idle_seconds"] for t in trials),
                             "saturation": {pool: round(statistics.fmean(t["resources"][pool]["saturation"] for t in trials), 3)
                                            for pool in trials[0]["resources"]},
                             "T1": metrics["T1"], "Tinf": metrics["Tinf"],
                             "T_LB": bound["T_LB"] if bound else None, "binding": bound["binding_term"] if bound else None})
                print(f"{name:18} {policy} p={trials[0]['workers']} makespan {mean:.3f}±{sd:.3f}s peak={rows[-1]['peak_concurrency']}")
    # Speedup vs E0 (the fixed-workload sequential reference) of the same workload.
    for row in rows:
        reference = next((r for r in rows if r["workload"] == row["workload"] and r["policy"] == "e0"), None)
        if reference is None:
            reference = next((r for r in rows if r["workload"] == row["workload"] and r["workers"] == 1), None)
        row["speedup_vs_e0"] = reference["makespan_mean"] / row["makespan_mean"] if reference else None
        row["efficiency"] = row["speedup_vs_e0"] / row["workers"] if row["speedup_vs_e0"] else None
        row["observed_over_LB"] = row["makespan_mean"] / row["T_LB"] if row["T_LB"] else None
    _write(out / "bench_raw.json", {"environment": _environment(), "measurement": "SYNTHETIC sleep-based workloads; real wall-clock",
                                    "trials": raw})
    _write(out / "bench_summary.json", {"environment": _environment(), "rows": rows})
    lines = ["| Workload | Policy | Workers | Makespan s (mean ± sd, n) | Speedup vs E0 | Efficiency | Peak concurrency | T_LB s | Observed/T_LB | Budget used |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        bound = "" if r["T_LB"] is None else f"{r['T_LB']:.3f}"
        ratio = "" if r["observed_over_LB"] is None else f"{r['observed_over_LB']:.3f}"
        lines.append(f"| {r['workload']} | {r['policy'].upper()} | {r['workers']} | {r['makespan_mean']:.3f} ± {r['makespan_sd']:.3f} ({r['trials']}) | "
                     f"{r['speedup_vs_e0']:.2f} | {r['efficiency']:.2f} | {r['peak_concurrency']} | {bound} | {ratio} | {r['budget_used']} |")
    (out / "bench_summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


# ---- harness ---------------------------------------------------------------------------------
def cmd_harness(args) -> int:
    """Whole multi-agent runs (deterministic visual fixture, no models) with the scheduler off/e0/e1/e2."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from studio_config_matrix import run_visual

    from openvlharness.parsec_vl.profiling import load_events, profile_run

    out = Path(args.out)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    rows, raw = [], []
    for policy in args.policies.split(","):
        walls = []
        for trial in range(args.trials):
            run_dir, result = run_visual(out / "runs", workers=args.workers, mode="concurrent", run_id=f"{policy}_{trial}_{stamp}",
                                         reference=False, tool_delay=args.tool_delay, tool_scheduler=policy)
            events = load_events(run_dir)
            stamps = {e["event_type"]: e["timestamp"] for e in events}
            profile = profile_run(run_dir)
            wall = (datetime.fromisoformat(stamps["RUN_COMPLETED"]) - datetime.fromisoformat(stamps["RUN_STARTED"])).total_seconds()
            final = json.loads((run_dir / "final_result.json").read_text())
            walls.append(wall)
            raw.append({"policy": policy, "trial": trial, "wall_seconds": wall, "answer": result["prediction"],
                        "status": result["extra_records"]["status"], "tool_calls": profile["tool_calls"]["count"],
                        "peak_concurrent_tool_calls": profile["peak_concurrent_tool_calls"],
                        "tool_request_to_start": profile["tool_request_to_start"], "scheduler": final.get("scheduler")})
        mean, sd = _mean_sd(walls)
        rows.append({"policy": policy, "trials": len(walls), "wall_mean": mean, "wall_sd": sd,
                     "answers": sorted({r["answer"] for r in raw if r["policy"] == policy}),
                     "peak_tool_concurrency": max(r["peak_concurrent_tool_calls"] for r in raw if r["policy"] == policy),
                     "request_to_start_mean_ms": 1000 * statistics.fmean(r["tool_request_to_start"]["mean"] for r in raw if r["policy"] == policy)})
        print(f"{policy}: wall {mean:.3f} ± {sd:.3f} s")
    _write(out / "harness.json", {"environment": _environment(), "workers": args.workers, "tool_delay": args.tool_delay,
                                  "measurement": "deterministic fixture (scripted model, local tool transports with injected delay); real wall clock",
                                  "rows": rows, "trials": raw})
    lines = ["| scheduler | trials | run wall s (mean ± sd) | answers | peak concurrent tool calls | request→start mean ms |",
             "|---|---:|---:|---|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['policy']} | {r['trials']} | {r['wall_mean']:.3f} ± {r['wall_sd']:.3f} | {r['answers']} | "
                     f"{r['peak_tool_concurrency']} | {r['request_to_start_mean_ms']:.1f} |")
    (out / "harness.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0



# ---- Phase 2 ----------------------------------------------------------------------------------
P2 = OUT


def _table(path: Path, header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---:" if i else "---" for i in range(len(header))) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    text = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return text


def cmd_plan_bench(args) -> int:
    from openvlharness.parsec_vl.experiments import decision_quality, multicore

    out = Path(args.out)
    procs = [int(x) for x in args.processes.split(",")]
    result = multicore(procs, args.rollouts, args.trials)
    result["environment"] = _environment()
    _write(out / "multicore.json", result)
    print(_table(out / "multicore.md", ["Processes", "Mode", "Rollouts", "Wall s (mean ± sd)", "Speedup vs 1 proc", "Efficiency",
                                        "Speedup vs in-process", "CPU utilization", "Cold start s", "Overhead s", "Identical estimates"],
                 [[r["processes"], r["mode"], r["rollouts_total"], f"{r['wall_mean']:.3f} ± {r['wall_sd']:.3f}",
                   "" if r["speedup_vs_1_process"] is None else f"{r['speedup_vs_1_process']:.2f}",
                   "" if r["efficiency"] is None else f"{r['efficiency']:.2f}", f"{r['speedup_vs_in_process']:.2f}",
                   f"{r['cpu_utilization']:.2f}", "" if r["cold_start_seconds"] is None else f"{r['cold_start_seconds']:.2f}",
                   f"{r.get('overhead_seconds', 0):.3f}", r["identical_estimates"]] for r in result["rows"]]))
    if args.quality_instances:
        quality = decision_quality(args.quality_instances, [float(b) for b in args.budgets.split(",")], args.quality_processes,
                                   args.reference_rollouts)
        quality["environment"] = _environment()
        _write(out / "decision_quality.json", quality)
        print(_table(out / "decision_quality.md", ["Method", "Time budget s", "Rollouts / candidate", "Best choice", "Mean regret", "Max regret"],
                     [[r["method"], r["time_budget_s"], f"{r['rollouts_per_candidate_mean']:.0f}", f"{r['best_choice_rate']:.2f}",
                       f"{r['regret_mean']:.4f}", f"{r['regret_max']:.4f}"] for r in quality["rows"]]))
    return 0


def cmd_spec_bench(args) -> int:
    from openvlharness.parsec_vl.experiments import SPECULATION_POLICIES, speculation

    capacities = dict((k, int(v)) for k, v in (x.split("=") for x in args.capacities.split(",") if x)) if args.capacities else None
    result = speculation(args.trials, [(n, dict(o)) for n, o in SPECULATION_POLICIES], processes=args.processes,
                         scenarios=args.scenarios.split(",") if args.scenarios else None,
                         budgets=[int(b) for b in args.budgets.split(",")] if args.budgets else None, capacities=capacities)
    result["environment"] = _environment()
    out = Path(args.out)
    _write(out / "speculation.json", result)
    print(_table(out / "speculation.md", ["Scenario", "Policy", "Budget", "Latency s (mean ± sd)", "p90 s", "Tool calls", "Wasted calls",
                                          "Wasted s", "Completion", "Planning s", "Necessary queue wait s"],
                 [[r["scenario"], r["policy"], r["budget"], f"{r['latency_mean']:.3f} ± {r['latency_sd']:.3f}", f"{r['latency_p90']:.3f}",
                   f"{r['tool_calls_mean']:.2f}", f"{r['wasted_calls_mean']:.2f}", f"{r['wasted_seconds_mean']:.3f}",
                   f"{r['completion_rate']:.2f}", f"{r['planning_seconds_mean']:.3f}", f"{r['necessary_queue_wait_mean']:.3f}"]
                  for r in result["rows"]]))
    return 0


def cmd_actions_bench(args) -> int:
    import tempfile

    from openvlharness.parsec_vl.experiments import fixed_plan_actions

    out = Path(args.out)
    result = fixed_plan_actions(args.policies.split(","), args.trials, args.tool_delay, Path(tempfile.mkdtemp()))
    result["environment"] = _environment()
    _write(out / "actions.json", result)
    print(_table(out / "actions.md", ["Dispatch", "Trials", "Tool span s (mean ± sd)", "Speedup vs E0", "Answer wall s",
                                      "Overlapping tool pairs", "Answers"],
                 [[r["policy"], r["trials"], f"{r['tool_span_mean']:.3f} ± {r['tool_span_sd']:.3f}", f"{r['speedup_vs_first']:.2f}",
                   f"{r['answer_wall_mean']:.3f} ± {r['answer_wall_sd']:.3f}", f"{r['overlapping_pairs_mean']:.1f}", r["answers"]]
                  for r in result["rows"]]))
    for policy, trace in result["traces"].items():
        print(policy, trace)
    return 0


def cmd_agents_bench(args) -> int:
    from openvlharness.parsec_vl.experiments import multi_agent_matrix

    out = Path(args.out)
    extra = {"planning_processes": args.planning_processes, "rollouts": args.rollouts}
    if args.global_tool_calls:
        extra["global_tool_calls"] = args.global_tool_calls
    if args.cpu_capacity:
        extra["capacities"] = {"cpu": args.cpu_capacity}
    result = multi_agent_matrix([int(w) for w in args.workers.split(",")], args.policies.split(","), args.trials,
                                args.tool_delay, out / "runs", plan=args.plan, **extra)
    result["environment"] = _environment()
    result["settings"] = extra
    _write(out / "agents.json", result)
    print(_table(out / "agents.md", ["Workers", "Mode", "Trials", "Run wall s (mean ± sd)", "Tool calls", "Speculative calls",
                                     "Cancel-requested", "Planning s", "Answers", "Status"],
                 [[r["workers"], r["policy"], r["trials"], f"{r['wall_mean']:.3f} ± {r['wall_sd']:.3f}", f"{r['tool_calls_mean']:.1f}",
                   f"{r['speculative_calls_mean']:.1f}", f"{r['cancel_requested_mean']:.1f}", f"{r['planning_seconds_mean']:.3f}",
                   r["answers"], r["statuses"]] for r in result["rows"]]))
    return 0


def cmd_outcome_model(args) -> int:
    """Empirical per-tool durations and evidence rates from earlier recorded real runs only."""
    from collections import defaultdict

    from openvlharness.parsec_vl.profiling import load_events, profile_run

    durations, ok, total, used = defaultdict(list), defaultdict(int), defaultdict(int), []
    for run_dir in sorted(p.parent for p in Path(args.runs_dir).glob("*/events.jsonl")):
        if run_dir.name in set(args.exclude or []):
            continue
        try:
            if not profile_run(run_dir)["real_model_service"]:
                continue
        except Exception:  # noqa: BLE001 - unreadable runs are skipped
            continue
        used.append(run_dir.name)
        for e in load_events(run_dir):
            if e["event_type"] not in ("TOOL_CALL_COMPLETED", "TOOL_CALL_FAILED"):
                continue
            p = e.get("payload") or {}
            tool = e.get("tool_name")
            if isinstance(p.get("latency_seconds"), (int, float)):
                durations[tool].append(round(float(p["latency_seconds"]), 4))
            data = p.get("canonical_result") or {}
            useful = bool(p.get("ok")) and (bool(data.get("boxes_normalized") or data.get("boxes")) if tool == "Visual_Grounding_Tool"
                                            else bool(str(data.get("text") or "").strip()) if tool == "OCR_Tool" else True)
            total[tool] += 1
            ok[tool] += useful
    model = {"source": "empirical", "runs": used,
             "durations": {t: ["empirical", sorted(v)] for t, v in durations.items() if len(v) >= 3},
             "p_ok": {t: round(ok[t] / total[t], 4) for t in total if total[t] >= 3},
             "counts": dict(total)}
    _write(Path(args.out), model)
    print(json.dumps({k: v for k, v in model.items() if k != "durations"}, indent=1))
    print({t: len(v[1]) for t, v in model["durations"].items()})
    return 0



# ---- demo, figures, report data -------------------------------------------------------
def _intervals(events: list[dict]) -> list[tuple[str, float, float]]:
    """Tool execution intervals: scheduler records when present, else latency-anchored tool events."""
    from datetime import datetime as _dt

    sched = [e["payload"] for e in events if e["event_type"] == "SCHEDULER_TASK_FINISHED" and e["payload"].get("start_wall")]
    if sched:
        return [(r["operation"], _dt.fromisoformat(r["start_wall"]).timestamp(), _dt.fromisoformat(r["finish_wall"]).timestamp())
                for r in sched]
    result = []
    for e in events:
        p = e["payload"]
        if e["event_type"] == "TOOL_CALL_COMPLETED" and isinstance(p.get("latency_seconds"), (int, float)):
            end = _dt.fromisoformat(e["timestamp"]).timestamp()
            result.append((e["tool_name"], end - p["latency_seconds"], end))
    return result


def cmd_demo(args) -> int:
    """Deterministic course demonstration (no model): the same visual-tool plan, sequential vs parallel."""
    from openvlharness.parsec_vl.fixture import run_plan_fixture

    out = Path(args.out)
    runs = out / "runs"
    delay = 0.1 if args.fast else args.tool_delay
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    cases = [
        ("original runtime: one tool call per turn (OFF)", "off", {"plan": "parallel"}),
        ("declared plan, sequential dispatch (E3, E0 order)", "e3", {"plan": "parallel", "plan_dispatch": "e0"}),
        ("declared plan, parallel dispatch (E3, E2 order)", "e3", {"plan": "parallel", "plan_dispatch": "e2"}),
        ("fallback plan with speculation (E4)", "e4", {"plan": "fallback"}),
    ]
    rows = []
    for index, (label, policy, extra) in enumerate(cases, 1):
        orchestrator, _, result, events = run_plan_fixture(runs, policy=policy, workers=1, tool_delay=delay, planning_processes=0,
                                                           run_id=f"demo_{stamp}_{index}_{policy}", **extra)
        stamps = [datetime.fromisoformat(e["timestamp"]).timestamp() for e in events]
        spans = _intervals(events)
        tool_span = (max(e for _, _, e in spans) - min(s for _, s, _ in spans)) if spans else 0.0
        overlaps = sum(1 for i, a in enumerate(spans) for b in spans[i + 1:] if a[1] < b[2] and b[1] < a[2])
        rows.append({"case": label, "policy": policy.upper(), "run_id": orchestrator.run_id, "status": result["extra_records"]["status"],
                     "answer": result["prediction"], "run_wall_s": round(stamps[-1] - stamps[0], 3), "tool_span_s": round(tool_span, 3),
                     "tool_calls": len(spans), "overlapping_tool_pairs": overlaps,
                     "speculation_adopted": any(e["event_type"] == "SPECULATIVE_RESULT_ADOPTED" for e in events)})
    _write(out / "demo.json", {"label": "FIXTURE (scripted model, real agent loop and capabilities, local tools with "
                                        f"{delay} s injected latency)", "environment": _environment(), "rows": rows})
    lines = ["| Case | Run wall s | Tool span s | Tool calls | Overlapping pairs | Answer |", "|---|---:|---:|---:|---:|---|"]
    lines += [f"| {r['case']} | {r['run_wall_s']} | {r['tool_span_s']} | {r['tool_calls']} | {r['overlapping_tool_pairs']} | {r['answer']} |"
              for r in rows]
    print("PARSEC-VL demo — FIXTURE: scripted model, no real model inference.\n")
    print("\n".join(lines))
    seq, par = rows[1]["tool_span_s"], rows[2]["tool_span_s"]
    if par:
        print(f"\nSame declared plan: parallel dispatch is {seq / par:.2f}x faster than sequential dispatch on tool time "
              f"({seq:.3f} s -> {par:.3f} s). The OFF row uses the original protocol (one call per model turn).")
    print(f"\nRuns: {runs}\nOpen them in the Investigation Studio:\n  python scripts/studio_ctl.py --runs-dir {runs} ensure")
    if args.studio:
        import subprocess

        subprocess.run([sys.executable, "scripts/studio_ctl.py", "--runs-dir", str(runs),
                        "ensure", "--run", rows[2]["run_id"], "--open"], check=True)
    return 0



def cmd_compare(args) -> int:
    """Whole coordinator + worker runs for a named variant set (FIXTURE)."""
    from openvlharness.parsec_vl.experiments import VARIANT_SETS, run_variants

    out = Path(args.out) / args.set
    result = run_variants(VARIANT_SETS[args.set], [int(w) for w in args.workers.split(",")], args.trials, args.tool_delay,
                          out / "runs", plan=args.plan)
    result["environment"] = _environment()
    result["variant_set"] = args.set
    _write(out / "variants.json", result)
    print(_table(out / "variants.md", ["Workers", "Variant", "Trials", "Run wall s (mean ± sd)", "First run s", "Later runs s",
                                       "Tool calls", "Speculative", "Planning s", "Pool start-up s", "Runs with pool start", "Answers"],
                 [[r["workers"], r["variant"], r["trials"], f"{r['wall_mean']:.3f} ± {r['wall_sd']:.3f}", f"{r['wall_first']:.3f}",
                   "" if r["wall_rest_mean"] is None else f"{r['wall_rest_mean']:.3f}", f"{r['tool_calls_mean']:.1f}",
                   f"{r['speculative_calls_mean']:.1f}", f"{r['planning_seconds_mean']:.3f}", f"{r['pool_startup_seconds_mean']:.3f}",
                   r["runs_with_pool_start"], r["answers"]] for r in result["rows"]]))
    return 0


def cmd_matrix(args) -> int:
    """16 deterministic configurations: 1-4 workers x memory on/off x peer messages on/off."""
    from openvlharness.parsec_vl.experiments import config_matrix

    out = Path(args.out)
    result = config_matrix(args.policy, out / "runs")
    result["environment"] = _environment()
    _write(out / "matrix.json", result)
    print(_table(out / "matrix.md", ["Workers", "Memory", "Peer", "Status", "Answer", "max_concurrent_workers", "Recorded memory",
                                     "Recorded peer", "Tool calls", "Messages"],
                 [[r["workers"], r["memory"], r["peer"], r["status"], r["answer"], r["max_concurrent_workers"], r["recorded_memory"],
                   r["recorded_peer"], r["tool_calls"], r["messages"]] for r in result["rows"]]))
    return 0


def cmd_figures(args) -> int:
    from openvlharness.parsec_vl.report import make_figures

    for path in make_figures(args.results, args.out):
        print(path)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("profile", help="profile recorded runs from their event logs")
    p.add_argument("runs", nargs="*", help="run directories (default: every run in --runs-dir)")
    p.add_argument("--runs-dir", default="outputs/multi_agent")
    p.add_argument("--include-fixtures", action="store_true", help="also profile scripted (no-model) runs")
    p.add_argument("--out", default=str(OUT / "profile"))
    p.set_defaults(func=cmd_profile)
    p = sub.add_parser("probe", help="measure real tool-service latency/throughput vs client concurrency")
    p.add_argument("--agent-config", default="examples/local_grounding_tools.yaml")
    p.add_argument("--image", default="data/images/FSC147/234.jpg")
    p.add_argument("--tools", default="grounding,ocr,depth,zoom")
    p.add_argument("--concurrency", default="1,2,4")
    p.add_argument("--requests", type=int, default=8)
    p.add_argument("--out", default=str(OUT / "probe"))
    p.set_defaults(func=cmd_probe)
    p = sub.add_parser("bench", help="E0/E1/E2 on the controlled DAG workloads")
    p.add_argument("--workloads", default="A_independent,B_chain,C_mixed,D_contention,M_misestimated,V_visual_pipeline,X_cpu_bound")
    p.add_argument("--policies", default="e0,e1,e2")
    p.add_argument("--workers", default="1,2,4,8")
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--out", default=str(OUT / "bench"))
    p.set_defaults(func=cmd_bench)
    p = sub.add_parser("harness", help="whole multi-agent fixture runs with the scheduler off/e0/e1/e2")
    p.add_argument("--policies", default="off,e0,e1,e2")
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--tool-delay", type=float, default=0.5)
    p.add_argument("--out", default=str(OUT / "harness"))
    p.set_defaults(func=cmd_harness)
    p = sub.add_parser("plan-bench", help="multicore Monte Carlo planning + decision quality per time budget")
    p.add_argument("--processes", default="1,2,4,8,16")
    p.add_argument("--rollouts", type=int, default=50000, help="rollouts per candidate (6 candidates)")
    p.add_argument("--trials", type=int, default=3)
    p.add_argument("--quality-instances", type=int, default=40)
    p.add_argument("--budgets", default="0.05,0.2")
    p.add_argument("--quality-processes", type=int, default=8)
    p.add_argument("--reference-rollouts", type=int, default=40000)
    p.add_argument("--out", default=str(P2 / "planning"))
    p.set_defaults(func=cmd_plan_bench)
    p = sub.add_parser("spec-bench", help="speculation scenarios A-E under S0/S1/S2")
    p.add_argument("--trials", type=int, default=30)
    p.add_argument("--processes", type=int, default=4)
    p.add_argument("--scenarios", default="")
    p.add_argument("--budgets", default="", help="global tool budgets to sweep, e.g. 3,4,5,8,12 (budget sensitivity)")
    p.add_argument("--capacities", default="", help="pool capacities, e.g. gpu=2 (resource contention)")
    p.add_argument("--out", default=str(P2 / "speculation"))
    p.set_defaults(func=cmd_spec_bench)
    p = sub.add_parser("actions-bench", help="one declared parallel plan in the real harness under E0/E1/E2")
    p.add_argument("--policies", default="e0,e1,e2")
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--tool-delay", type=float, default=0.3)
    p.add_argument("--out", default=str(P2 / "actions"))
    p.set_defaults(func=cmd_actions_bench)
    p = sub.add_parser("agents-bench", help="coordinator + N workers, OFF/E2/E3/E4/E5 (fixture)")
    p.add_argument("--workers", default="1,2,3,4")
    p.add_argument("--policies", default="off,e2,e3,e4,e5")
    p.add_argument("--trials", type=int, default=3)
    p.add_argument("--tool-delay", type=float, default=0.2)
    p.add_argument("--plan", default="fallback", choices=("fallback", "parallel"))
    p.add_argument("--planning-processes", type=int, default=4)
    p.add_argument("--rollouts", type=int, default=2000)
    p.add_argument("--global-tool-calls", type=int, default=0)
    p.add_argument("--cpu-capacity", type=int, default=0)
    p.add_argument("--out", default=str(P2 / "agents"))
    p.set_defaults(func=cmd_agents_bench)
    p = sub.add_parser("outcome-model", help="empirical tool outcome model from earlier recorded real runs")
    p.add_argument("--runs-dir", default="outputs/multi_agent")
    p.add_argument("--exclude", nargs="*", help="run ids to leave out (e.g. the task being evaluated)")
    p.add_argument("--out", default=str(P2 / "outcome_model.json"))
    p.set_defaults(func=cmd_outcome_model)
    p = sub.add_parser("demo", help="deterministic course demo (same plan sequential vs parallel; no model)")
    p.add_argument("--tool-delay", type=float, default=0.3)
    p.add_argument("--fast", action="store_true", help="low-resource mode: 0.1 s injected tool latency")
    p.add_argument("--studio", action="store_true", help="start or reuse an Investigation Studio for the demo runs")
    p.add_argument("--out", default=str(OUT / "demo"))
    p.set_defaults(func=cmd_demo)
    p = sub.add_parser("compare", help="whole-run variants (whole = OFF/E0-E5, overhead = planner pool/gate, contention)")
    p.add_argument("--set", choices=("whole", "overhead", "contention"), default="whole")
    p.add_argument("--workers", default="1,2,4")
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--tool-delay", type=float, default=0.2)
    p.add_argument("--plan", default="fallback", choices=("fallback", "parallel"))
    p.add_argument("--out", default=str(OUT))
    p.set_defaults(func=cmd_compare)
    p = sub.add_parser("matrix", help="16-configuration deterministic validation (workers x memory x peer)")
    p.add_argument("--policy", default="e5")
    p.add_argument("--out", default=str(OUT / "config_matrix"))
    p.set_defaults(func=cmd_matrix)
    p = sub.add_parser("figures", help="course figures from recorded results")
    p.add_argument("--results", default=str(ROOT / "results/reference"))
    p.add_argument("--out", default="docs/figures")
    p.set_defaults(func=cmd_figures)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
