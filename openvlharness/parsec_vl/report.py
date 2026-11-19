"""Recorded benchmark results -> normalized comparison tables and figures.

One source of truth for the Studio's comparison view (``/api/parsec/experiments``),
``scripts/parsec.py figures``, and the course report. Only fixed files under the
results directory are read; nothing is executed. Every experiment carries its
evidence level: REAL, FIXTURE, or SYNTHETIC. Rows inside one experiment share a
workload (paired); different experiments are never mixed in one table.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _first(base: Path, *candidates: str) -> tuple[Path | None, Any]:
    for rel in candidates:
        # Submission folders use experiment names. Older local recordings
        # retain their layout and remain readable.
        paths = [rel.split("/", 1)[1], rel] if rel.startswith(("phase2/", "phase3/")) else [rel]
        for name in paths:
            data = _load(base / name)
            if data is not None:
                return base / name, data
    return None, None


def _relative(source) -> str:
    """Show sources relative to the results directory (never an absolute home path)."""
    path = Path(str(source))
    for anchor in ("results", "parsec_vl"):
        if anchor in path.parts:
            return "/".join(path.parts[path.parts.index(anchor):])
    return path.name


def _variant_label(label: str) -> str:
    return label.replace(" (Phase 2)", "").replace(" (Phase 3 default)", " (default)")


def _experiment(eid, title, evidence, description, source, metrics, labels, units, rows, primary=None, notes=None, higher=None):
    return {"id": eid, "title": title, "evidence": evidence, "description": description, "source": _relative(source),
            "metrics": metrics, "metric_labels": labels, "units": units, "primary_metric": primary or metrics[0],
            "higher_is_better": higher or [], "rows": rows, "notes": notes or []}


def load_comparisons(base: str | Path = "outputs/parsec_vl") -> list[dict[str, Any]]:
    base = Path(base)
    out: list[dict[str, Any]] = []

    # FIXTURE: whole multi-agent runs, OFF and E0-E5 (adaptive: E3-E5 use the plan protocol).
    path, data = _first(base, "phase3/whole/variants.json")
    if data:
        for n in sorted({r["workers"] for r in data["rows"]}):
            rows = [{"label": _variant_label(r["variant"]), "values": {"wall": r["wall_mean"], "planning": r["planning_seconds_mean"],
                                                       "pool": r["pool_startup_seconds_mean"], "calls": r["tool_calls_mean"],
                                                       "spec": r["speculative_calls_mean"]}, "sd": {"wall": r["wall_sd"]}}
                    for r in data["rows"] if r["workers"] == n]
            out.append(_experiment(f"whole_harness_n{n}", f"Whole harness, {n} worker(s): OFF and E0–E5", "FIXTURE",
                                   "Coordinator + workers on the sign task (scripted model, real agent loop and capabilities, injected tool "
                                   "latency). OFF/E0–E2 use the original one-call protocol; E3–E5 use declared action plans, so they change "
                                   "the decision protocol, not only the schedule.", path,
                                   ["wall", "planning", "pool", "calls", "spec"],
                                   {"wall": "Run wall time", "planning": "Planning time", "pool": "Pool start-up", "calls": "Tool calls",
                                    "spec": "Speculative calls"}, {"wall": "s", "planning": "s", "pool": "s"}, rows,
                                   notes=[data.get("label", "")]))

    # FIXTURE: planning overhead variants (eager / lazy / shared / sequential / heuristic / gate).
    path, data = _first(base, "phase3/overhead/variants.json")
    if data:
        for n in sorted({r["workers"] for r in data["rows"]}):
            rows = [{"label": _variant_label(r["variant"]), "values": {"wall": r["wall_mean"], "first": r["wall_first"], "rest": r["wall_rest_mean"],
                                                       "planning": r["planning_seconds_mean"], "pool": r["pool_startup_seconds_mean"],
                                                       "pool_runs": r["runs_with_pool_start"]}, "sd": {"wall": r["wall_sd"]}}
                    for r in data["rows"] if r["workers"] == n]
            out.append(_experiment(f"planning_overhead_n{n}", f"Planning overhead, {n} worker(s)", "FIXTURE",
                                   "Same sign task and plan; only the planner's pool lifecycle and overhead gate change. "
                                   "'shared' keeps one warm pool across consecutive runs (first run cold, rest warm).", path,
                                   ["wall", "first", "rest", "planning", "pool", "pool_runs"],
                                   {"wall": "Run wall (mean)", "first": "First run", "rest": "Later runs (mean)", "planning": "Planning time",
                                    "pool": "Pool start-up", "pool_runs": "Runs that started a pool"},
                                   {"wall": "s", "first": "s", "rest": "s", "planning": "s", "pool": "s"}, rows))

    # FIXTURE: resource contention (scheduler slots, tool-pool capacity).
    path, data = _first(base, "phase3/contention/variants.json")
    if data:
        for n in sorted({r["workers"] for r in data["rows"]}):
            rows = [{"label": _variant_label(r["variant"]), "values": {"wall": r["wall_mean"], "calls": r["tool_calls_mean"],
                                                       "spec": r["speculative_calls_mean"]}, "sd": {"wall": r["wall_sd"]}}
                    for r in data["rows"] if r["workers"] == n]
            out.append(_experiment(f"contention_n{n}", f"Resource contention, {n} worker(s)", "FIXTURE",
                                   "Same sign task; scheduler slots and the tool pool's capacity change. Fewer slots or a capacity-1 "
                                   "pool serialize the workers' tool calls.", path, ["wall", "calls", "spec"],
                                   {"wall": "Run wall time", "calls": "Tool calls", "spec": "Speculative calls"}, {"wall": "s"}, rows))

    # FIXTURE: one declared plan, dispatched by E0/E1/E2 (fixed workload).
    path, data = _first(base, "phase3/actions/actions.json", "phase2/actions/actions.json")
    if data:
        rows = [{"label": r["policy"], "values": {"span": r["tool_span_mean"], "speedup": r["speedup_vs_first"],
                                                  "wall": r["answer_wall_mean"], "overlaps": r["overlapping_pairs_mean"]},
                 "sd": {"span": r["tool_span_sd"]}} for r in data["rows"]]
        out.append(_experiment("fixed_plan", "Same declared plan: E0 vs E1 vs E2", "FIXTURE",
                               "OCR(original) ∥ Grounding → Zoom → OCR(crop) in the real agent loop with real capabilities and a "
                               "scripted model; identical plan and outcomes in every mode (fixed workload).", path,
                               ["span", "speedup", "wall", "overlaps"],
                               {"span": "Tool span", "speedup": "Speedup vs E0", "wall": "Answer wall", "overlaps": "Overlapping tool pairs"},
                               {"span": "s", "wall": "s"}, rows, higher=["speedup", "overlaps"]))

    # SYNTHETIC: scheduler workloads at 4 workers.
    path, data = _first(base, "phase3/bench/bench_summary.json", "bench/bench_summary.json")
    if data:
        for workload in sorted({r["workload"] for r in data["rows"]}):
            rows = [{"label": f"{r['policy'].upper()} ({r['workers']} worker{'s' if r['workers'] > 1 else ''})",
                     "values": {"makespan": r["makespan_mean"], "speedup": r["speedup_vs_e0"], "efficiency": r["efficiency"],
                                "lb": r["T_LB"], "ratio": r["observed_over_LB"]}, "sd": {"makespan": r["makespan_sd"]}}
                    for r in data["rows"] if r["workload"] == workload and r["workers"] in (1, 4)]
            out.append(_experiment(f"bench_{workload}", f"Scheduler workload {workload}", "SYNTHETIC",
                                   ("Pure-Python CPU-bound work on threads (negative control); same work for every policy."
                                    if workload == "X_cpu_bound" else
                                    "Sleep-based tasks with declared durations (waiting work, not CPU work); same DAG for every policy."),
                                   path, ["makespan", "speedup", "efficiency", "lb", "ratio"],
                                   {"makespan": "Makespan", "speedup": "Speedup vs E0", "efficiency": "Efficiency", "lb": "Lower bound T_LB",
                                    "ratio": "Makespan / T_LB"}, {"makespan": "s", "lb": "s"}, rows, higher=["speedup", "efficiency"]))

    # SYNTHETIC: multicore Monte Carlo.
    path, data = _first(base, "phase3/planning/multicore.json", "phase2/planning/multicore.json")
    if data:
        rows = [{"label": "in-process" if r["processes"] == 0 else f"{r['processes']} processes",
                 "values": {"wall": r["wall_mean"], "speedup": r["speedup_vs_1_process"], "efficiency": r["efficiency"],
                            "cpu": r["cpu_utilization"], "cold": r["cold_start_seconds"]}, "sd": {"wall": r["wall_sd"]}}
                for r in data["rows"]]
        out.append(_experiment("multicore_mc", "Monte Carlo planning: CPU processes", "SYNTHETIC",
                               f"{data['candidates']} candidate plans × {data['rollouts_per_candidate']} rollouts, identical estimates for every "
                               "process count; warm pool (cold start reported separately).", path,
                               ["wall", "speedup", "efficiency", "cpu", "cold"],
                               {"wall": "Planning wall", "speedup": "Speedup vs 1 process", "efficiency": "Efficiency",
                                "cpu": "CPU utilization", "cold": "Cold start"}, {"wall": "s", "cold": "s"}, rows,
                               higher=["speedup", "efficiency", "cpu"]))

    # SYNTHETIC: speculation scenarios.
    path, data = _first(base, "phase3/speculation/speculation.json", "phase2/speculation/speculation.json")
    if data:
        for scenario in dict.fromkeys(r["scenario"] for r in data["rows"]):
            rows = [{"label": r["policy"], "values": {"latency": r["latency_mean"], "calls": r["tool_calls_mean"],
                                                      "wasted": r["wasted_calls_mean"], "completion": r["completion_rate"],
                                                      "queue": r["necessary_queue_wait_mean"]}, "sd": {"latency": r["latency_sd"]}}
                    for r in data["rows"] if r["scenario"] == scenario]
            about = next(r["about"] for r in data["rows"] if r["scenario"] == scenario)
            out.append(_experiment(f"spec_{scenario}", f"Speculation: {scenario}", "SYNTHETIC",
                                   f"{about}. Same per-trial outcomes for every policy (common random numbers).", path,
                                   ["latency", "calls", "wasted", "completion", "queue"],
                                   {"latency": "Decision latency", "calls": "Tool calls", "wasted": "Wasted calls",
                                    "completion": "Completion rate", "queue": "Necessary queue wait"},
                                   {"latency": "s", "queue": "s"}, rows, higher=["completion"]))

    # REAL: bundled tool-service measurements are available in a clean checkout,
    # even when the original model-run recordings are absent.
    path, data = _first(base, "probe/probe.json")
    if data:
        for tool, result in data["results"].items():
            rows = [{"label": f"{level} concurrent requests",
                     "values": {"throughput": row["throughput_per_s"], "relative": row["throughput_vs_1"],
                                "latency": row["latency_median"], "failures": len(row["failures"])}}
                    for level, row in sorted(result["levels"].items(), key=lambda item: int(item[0]))]
            out.append(_experiment(f"real_tool_{tool}", f"Real tool service: {tool}", "REAL",
                                   "Recorded requests to real tool services at different client concurrencies. "
                                   "These measure service throughput, not model accuracy or whole-run speedup.", path,
                                   ["throughput", "relative", "latency", "failures"],
                                   {"throughput": "Throughput", "relative": "Throughput vs baseline", "latency": "Median latency",
                                    "failures": "Failed requests"}, {"throughput": "requests/s", "latency": "s"}, rows,
                                   notes=[data.get("measurement", "")], higher=["throughput", "relative"]))

    # REAL: small real runs (different trajectories: not a paired speedup comparison).
    real = []
    for rel, label in (("phase2/real_runs/real_row25_e2", "E2 (legacy protocol)"), ("phase2/real_runs/real_row25_e5", "E5 (plan tool offered)"),
                       ("phase2/real_runs/real_row25_e5_prompted", "E5 + plan prompt note")):
        final = _load(base / rel / "final_result.json")
        if final:
            real.append({"label": label, "values": {"calls": final["budgets"]["global"]["tool_calls"]["used"],
                                                    "plans": sum(v["stats"]["plans"] for v in (final.get("planning") or {}).values()),
                                                    "answer": final.get("final_answer")}})
    if real:
        out.append(_experiment("real_fsc147", "Real model, FSC-147 row 25 (2 workers)", "REAL",
                               "Qwen3-VL-8B with real tool services. Trajectories differ between runs, so wall-time differences are "
                               "not attributable to scheduling; the model never proposed a plan.", base / "phase2/real_runs",
                               ["calls", "plans", "answer"], {"calls": "Tool calls", "plans": "Plans proposed", "answer": "Final answer"},
                               {}, real, notes=["Reference answer for this row: 38 (all runs answered 46)."]))
    return out


# ---- figures --------------------------------------------------------------------------------


def make_figures(base: str | Path, out: str | Path) -> list[str]:
    """Course figures from recorded results (matplotlib, Agg backend). Returns written paths."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    base, out = Path(base), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    style = {"E0": "#6b7280", "E1": "#2563eb", "E2": "#059669"}

    def save(fig, name):
        fig.tight_layout(rect=getattr(fig, "layout_rect", (0, 0, 1, 1)))
        path = out / name
        fig.savefig(path, dpi=150)
        plt.close(fig)
        written.append(str(path))

    _, bench = _first(base, "phase3/bench/bench_summary.json", "bench/bench_summary.json")
    _, scaling = _first(base, "phase3/scaling/bench_summary.json", "scaling/bench_summary.json")
    if scaling:
        rows = [r for r in scaling["rows"] if r["policy"] == "e1"]
        p = [r["workers"] for r in rows]
        fig, axes = plt.subplots(1, 2, figsize=(9, 3.4))
        axes[0].plot(p, [r["speedup_vs_e0"] for r in rows], "o-", label="measured (E1)")
        axes[0].plot(p, p, "--", color="#9ca3af", label="ideal")
        axes[0].set(xlabel="scheduler workers p", ylabel="speedup S(p)", title="SYNTHETIC: 32 independent waits")
        axes[0].legend()
        axes[1].plot(p, [r["efficiency"] for r in rows], "o-")
        axes[1].set(xlabel="scheduler workers p", ylabel="efficiency E(p)", ylim=(0, 1.1), title="Parallel efficiency")
        save(fig, "fig1_speedup_efficiency.png")
    if bench:
        workloads = [w for w in ["A_independent", "B_chain", "C_mixed", "D_contention", "M_misestimated", "V_visual_pipeline", "X_cpu_bound"]
                     if any(r["workload"] == w for r in bench["rows"])]
        fig, ax = plt.subplots(figsize=(10, 3.8))
        width = 0.26
        for k, policy in enumerate(["e0", "e1", "e2"]):
            vals = []
            for w in workloads:
                row = next((r for r in bench["rows"] if r["workload"] == w and r["policy"] == policy and r["workers"] == (1 if policy == "e0" else 4)), None)
                base_row = next((r for r in bench["rows"] if r["workload"] == w and r["policy"] == "e0"), None)
                vals.append(row["makespan_mean"] / base_row["makespan_mean"] if row and base_row else 0)
            ax.bar([i + (k - 1) * width for i in range(len(workloads))], vals, width, label=policy.upper(), color=style[policy.upper()])
        ax.axhline(1.0, color="#111827", lw=0.8)
        ax.set_xticks(range(len(workloads)), [w.replace("_", "\n", 1) for w in workloads], fontsize=8)
        ax.set(ylabel="makespan / E0 makespan", title="SYNTHETIC: scheduler policy vs makespan (4 workers; lower is better)")
        ax.legend()
        save(fig, "fig2_policy_makespan.png")
    _, multicore = _first(base, "phase3/planning/multicore.json", "phase2/planning/multicore.json")
    if multicore:
        rows = [r for r in multicore["rows"] if r["processes"] > 0]
        p = [r["processes"] for r in rows]
        fig, axes = plt.subplots(1, 2, figsize=(9, 3.4))
        axes[0].plot(p, [r["speedup_vs_1_process"] for r in rows], "o-", label="measured")
        axes[0].plot(p, p, "--", color="#9ca3af", label="ideal")
        axes[0].set(xlabel="CPU processes", ylabel="speedup vs 1 process", title="SYNTHETIC: Monte Carlo planning")
        axes[0].legend()
        axes[1].plot(p, [r["efficiency"] for r in rows], "o-", label="efficiency")
        axes[1].plot(p, [r["cpu_utilization"] for r in rows], "s--", label="CPU utilization")
        axes[1].set(xlabel="CPU processes", ylim=(0, 1.1), title=f"{multicore['candidates']}×{multicore['rollouts_per_candidate']} rollouts")
        axes[1].legend()
        save(fig, "fig3_montecarlo_scaling.png")
    _, quality = _first(base, "phase3/planning/decision_quality.json", "phase2/planning/decision_quality.json")
    if quality:
        fig, ax = plt.subplots(figsize=(7, 3.4))
        methods = list(dict.fromkeys(r["method"] for r in quality["rows"]))
        budgets = sorted({r["time_budget_s"] for r in quality["rows"] if r["time_budget_s"] > 0})
        styles = iter([("o", "-", 9), ("s", "--", 7), ("^", ":", 6), ("D", "-.", 5)])
        for method in methods:
            rows = [r for r in quality["rows"] if r["method"] == method]
            if method == "closed-form heuristic":
                ax.axhline(rows[0]["regret_mean"], ls="--", color="#9ca3af", label=method)
                continue
            marker, line, size = next(styles, ("o", "-", 5))  # distinct styles: identical results stay visible
            ax.plot([r["time_budget_s"] for r in rows], [r["regret_mean"] for r in rows], marker=marker, ls=line,
                    markersize=size, label=method)
        ax.set(xlabel="planning time budget (s)", ylabel="mean regret (synthetic score)", xticks=budgets,
               title="SYNTHETIC: planning usefulness vs time budget")
        ax.legend(fontsize=8)
        save(fig, "fig4_planning_budget.png")
    _, spec = _first(base, "phase3/speculation/speculation.json", "phase2/speculation/speculation.json")
    if spec:
        fig, ax = plt.subplots(figsize=(7.5, 4))
        markers = {"S0": "o", "S1 K=1": "s", "S1 K=2": "^", "S2": "D"}
        scenarios = list(dict.fromkeys(r["scenario"] for r in spec["rows"] if "budget_sweep" not in r.get("tag", "")))
        colors = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed"]
        for i, scenario in enumerate(scenarios):
            for r in [r for r in spec["rows"] if r["scenario"] == scenario]:
                key = next((k for k in markers if r["policy"].startswith(k)), "S0")
                ax.scatter(r["wasted_calls_mean"], r["latency_mean"], marker=markers[key], color=colors[i % len(colors)], s=40)
            ax.scatter([], [], color=colors[i % len(colors)], label=scenario.split("_", 1)[1].replace("_", " "))
        for key, marker in markers.items():
            ax.scatter([], [], marker=marker, color="#374151", label=key)
        ax.set(xlabel="wasted (speculative, unused) tool calls per decision", ylabel="decision latency (s)",
               title="SYNTHETIC: speculation latency vs wasted work")
        ax.legend(fontsize=7, ncol=2)
        save(fig, "fig5_speculation_tradeoff.png")
    _, sweep = _first(base, "phase3/budget/speculation.json")
    if sweep:
        fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.4))
        for policy in dict.fromkeys(r["policy"] for r in sweep["rows"]):
            rows = sorted([r for r in sweep["rows"] if r["policy"] == policy], key=lambda r: r["budget"])
            axes[0].plot([r["budget"] for r in rows], [r["completion_rate"] for r in rows], "o-", label=policy)
            axes[1].plot([r["budget"] for r in rows], [r["latency_mean"] for r in rows], "o-", label=policy)
        axes[0].set(xlabel="global tool budget B", ylabel="completion rate", ylim=(0, 1.05), title="SYNTHETIC: budget sensitivity")
        axes[1].set(xlabel="global tool budget B", ylabel="decision latency (s)")
        axes[0].legend(fontsize=7)
        save(fig, "fig6_budget_sensitivity.png")
    _, whole = _first(base, "phase3/whole/variants.json")
    if whole:
        workers = sorted({r["workers"] for r in whole["rows"]})
        variants = list(dict.fromkeys(r["variant"] for r in whole["rows"]))
        fig, ax = plt.subplots(figsize=(10, 3.8))
        width = 0.8 / max(1, len(variants))
        for k, variant in enumerate(variants):
            rows = [next((r for r in whole["rows"] if r["workers"] == n and r["variant"] == variant), None) for n in workers]
            ax.bar([i + (k - len(variants) / 2 + 0.5) * width for i in range(len(workers))], [r["wall_mean"] if r else 0 for r in rows],
                   width, yerr=[r["wall_sd"] if r else 0 for r in rows], label=variant, capsize=2)
        ax.set_xticks(range(len(workers)), [f"{n} worker{'s' if n > 1 else ''}" for n in workers])
        ax.set(ylabel="run wall time (s)", title="FIXTURE: whole multi-agent runs (E3–E5 change the decision protocol)")
        ax.legend(fontsize=7, ncol=4, loc="upper left")
        ax.set_ylim(0, ax.get_ylim()[1] * 1.25)
        save(fig, "fig7_whole_harness.png")
    _, overhead = _first(base, "phase3/overhead/variants.json")
    if overhead:
        counts = sorted({r["workers"] for r in overhead["rows"]})
        fig, axes = plt.subplots(1, len(counts), figsize=(6.5 + 3.5 * len(counts), 4.2), sharey=True, squeeze=False)
        for ax, n in zip(axes[0], counts):
            rows = [r for r in overhead["rows"] if r["workers"] == n]
            labels = [_variant_label(r["variant"]) for r in rows]
            ax.barh(labels, [r["wall_mean"] for r in rows], xerr=[r["wall_sd"] for r in rows], color="#60a5fa",
                    label="run wall (mean ± sd)")
            ax.barh(labels, [r["pool_startup_seconds_mean"] for r in rows], color="#dc2626", label="pool start-up")
            ax.barh(labels, [r["planning_seconds_mean"] for r in rows], left=[r["pool_startup_seconds_mean"] for r in rows],
                    color="#f59e0b", label="planning time, summed over agents")
            off = next((r["wall_mean"] for r in rows if r["variant"].startswith("OFF")), None)
            if off:
                ax.axvline(off, color="#374151", ls=":", lw=1, label="OFF run wall")
            ax.set(xlabel="seconds", title=f"{n} agent{'s' if n > 1 else ''}")
            ax.tick_params(axis="y", labelsize=7)
        axes[0][0].invert_yaxis()
        handles, labels = axes[0][-1].get_legend_handles_labels()
        fig.legend(handles, labels, fontsize=8, loc="lower center", ncol=len(labels), frameon=False)
        fig.layout_rect = (0, 0.07, 1, 1)  # room for the shared legend below the panels
        fig.suptitle("FIXTURE: planning overhead (planning is summed over concurrent agents; it is not all on the critical path)",
                     fontsize=9)
        save(fig, "fig8_planning_overhead.png")
    return written
