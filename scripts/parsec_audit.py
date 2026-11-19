#!/usr/bin/env python3
"""Offline verification and advisor orchestration using existing PARSEC engines.

No inference or service probe is invoked. Every execution gets a new output root.
Bundled reference measurements are read-only. The shell entry points select .venv Python.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


def read(path):
    return json.loads(Path(path).read_text())


def close(actual, expected, label, tolerance=1e-7):
    if not math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance):
        raise AssertionError(f"{label}: {actual} != {expected}")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def environment():
    def capture(*command):
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        return result.stdout.strip() or result.stderr.strip()

    packages = {}
    for name in ("pytest", "fastapi", "uvicorn", "httpx", "numpy", "Pillow", "PyYAML", "jsonschema",
                 "pandas", "matplotlib", "ruff", "python-dotenv"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"date_utc": datetime.now(timezone.utc).isoformat(), "repository": str(ROOT),
            "branch": capture("git", "branch", "--show-current"), "commit": capture("git", "rev-parse", "HEAD"),
            "working_tree": capture("git", "status", "--short"), "python": sys.version, "executable": sys.executable,
            "platform": platform.platform(), "cpus": os.cpu_count(),
            "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
            "node": capture("node", "--version") if shutil.which("node") else None,
            "chrome": shutil.which("google-chrome") or shutil.which("chromium"), "packages": packages,
            "gpu_inventory": capture("nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader")
            if shutil.which("nvidia-smi") else "nvidia-smi not available; no GPU workload requested",
            "dataset_image_available": (ROOT / "data/images/FSC147/234.jpg").is_file()}


def check_intervals(records, capacities, budget=None):
    """Validate physical intervals, declared dependencies, capacity, and charges."""
    by_id = {r["task_id"]: r for r in records}
    points = defaultdict(list)
    dispatched = []
    for r in records:
        start, end = r.get("start_time"), r.get("finish_time")
        if start is None:
            continue
        require(end is not None and end >= start, f"Invalid interval: {r['task_id']}")
        dispatched.append(r)
        for dep in r.get("dependency_ids", []):
            require(by_id[dep]["status"] == "COMPLETED" and by_id[dep]["finish_time"] <= start,
                    f"Dependency violated: {dep} -> {r['task_id']}")
        points[r["resource_pool"]].extend([(start, 1), (end, -1)])
    for pool, events in points.items():
        used = 0
        for _, delta in sorted(events):
            used += delta
            require(0 <= used <= capacities[pool], f"Capacity exceeded in {pool}: {used}")
        require(used == 0, f"Resource leak in {pool}")
    if budget is not None:
        require(len(dispatched) <= budget, "Dispatched tool calls exceeded budget")
    return len(dispatched)


def inspect_fixture(run_dir, parallel):
    """Check the actual persisted tool intervals and input/output provenance."""
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    records = [e["payload"] for e in events if e["event_type"] == "SCHEDULER_TASK_FINISHED"]
    final = read(run_dir / "final_result.json")
    caps = {p: v["capacity"] for p, v in final["scheduler"]["resources"].items()}
    check_intervals(records, caps, final["budgets"]["global"]["tool_calls"]["limit"])
    actions = {r["metadata"]["action_id"]: r for r in records}
    full, ground, crop, text = [actions[k] for k in ("ocr_full", "g", "z", "ocr_crop")]
    overlaps = full["start_time"] < ground["finish_time"] and ground["start_time"] < full["finish_time"]
    require(overlaps == parallel, "Independent tool overlap disagrees with dispatch policy")
    require(crop["start_time"] >= ground["finish_time"], "Zoom started before grounding finished")
    require(text["start_time"] >= crop["finish_time"], "Crop OCR started before Zoom finished")
    completed = {e["payload"]["action_id"]: e for e in events
                 if e["event_type"] == "TOOL_CALL_COMPLETED" and e["payload"].get("action_id")}
    z, o = completed["z"], completed["ocr_crop"]
    zp, op = z["payload"], o["payload"]
    produced = zp["canonical_result"]["image"]
    consumed = op["visual"]["inputs"][0]
    require(consumed["registry_id"] == produced != "input_image_1", "OCR did not consume the actual Zoom crop")
    require(z["agent_id"] == o["agent_id"] == "worker_01", "Cross-agent image ownership")
    require(zp["image_scope"] == op["image_scope"], "Crop crossed image scopes")
    require([consumed["width"], consumed["height"]] == zp["visual"]["transform"]["output_size"], "Crop dimensions disagree")
    artifacts = read(run_dir / "artifacts.json")["artifacts"]
    artifact = artifacts[zp["visual"]["outputs"][0]["image"]["artifact_ref"]]
    require(artifact["source_agent_id"] == z["agent_id"] and artifact["run_id"] == run_dir.name,
            "Crop artifact has the wrong agent/run owner")
    require(final["final_answer"] == "EXIT 42", "Fixture answer changed")
    return {"run_id": run_dir.name, "span": max(r["finish_time"] for r in records) - min(r["start_time"] for r in records),
            "overlap": overlaps, "crop_registry_id": produced,
            "observations": {key: event["payload"]["canonical_result"] for key, event in completed.items()}}


def fixture_suite(out, trials=2, delay=0.3):
    from openvlharness.parsec_vl.fixture import run_plan_fixture

    rows, ids = [], {}
    cases = [("legacy", "off", {"plan": "parallel"}),
             ("sequential", "e3", {"plan": "parallel", "plan_dispatch": "e0"}),
             ("parallel", "e3", {"plan": "parallel", "plan_dispatch": "e2"}),
             ("adopted", "e4", {"plan": "fallback"}),
             ("pruned", "e4", {"plan": "fallback", "readable": True}),
             ("four_workers", "e5", {"plan": "fallback", "workers": 4})]
    reference = None
    for name, policy, settings in cases:
        count = trials if name in ("sequential", "parallel") else 1
        spans = []
        for trial in range(count):
            options = {"workers": 1, "planning_processes": 0, "tool_delay": delay, **settings}
            run_id = f"advisor_{name}_{trial}"
            orchestrator, _, result, events = run_plan_fixture(out / "runs", policy=policy, run_id=run_id, **options)
            require(result["extra_records"]["status"] == "COMPLETED", f"Fixture failed: {run_id}")
            ids[name] = run_id
            if name in ("sequential", "parallel"):
                verified = inspect_fixture(orchestrator.run_dir, parallel=name == "parallel")
                if reference is None:
                    reference = verified["observations"]
                require(verified["observations"] == reference, "Sequential and parallel logical tool results differ")
                spans.append(verified["span"])
            if name == "adopted":
                require(any(e["event_type"] == "SPECULATIVE_RESULT_ADOPTED" for e in events), "No speculative adoption")
            if name == "pruned":
                require(any(e["event_type"] in ("SPECULATIVE_TASK_CANCEL_REQUESTED", "SPECULATIVE_TASK_PRUNED",
                                               "PLAN_TASK_PRUNED") for e in events), "No speculative pruning/cancellation")
        if spans:
            rows.append({"case": name, "trials": count, "tool_span_mean": statistics.fmean(spans), "raw_spans": spans})
    speedup = rows[0]["tool_span_mean"] / rows[1]["tool_span_mean"]
    value = {"label": "FIXTURE: scripted model, real harness/capabilities, local transports",
             "tool_delay": delay, "rows": rows, "speedup": speedup, "run_ids": ids}
    write(out / "fixture_checks.json", value)
    return value


def reference_checks(out):
    """Check bundled results without depending on ignored local run directories."""
    base = ROOT / "results/reference"
    manifest = read(base / "manifest.json")
    for entry in manifest["files"]:
        path = base / entry["path"]
        require(hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"],
                f"Reference file changed: {entry['path']}")
    for folder in ("bench", "scaling"):
        raw = read(base / folder / "bench_raw.json")
        summary = read(base / folder / "bench_summary.json")
        groups = defaultdict(list)
        for trial in raw["trials"]:
            groups[trial["workload"], trial["policy"], trial["workers"]].append(trial)
            check_intervals(trial["records"], {p: v["capacity"] for p, v in trial["resources"].items()},
                            trial["budget"]["ledger"]["global"]["tool_calls"]["limit"])
        for row in summary["rows"]:
            trials = groups[row["workload"], row["policy"], row["workers"]]
            require(len(trials) == row["trials"], f"Trial count mismatch in {folder}")
            mean = statistics.fmean(t["makespan"] for t in trials)
            close(mean, row["makespan_mean"], folder)
            baseline = next(r for r in summary["rows"] if r["workload"] == row["workload"] and r["policy"] == "e0")
            close(baseline["makespan_mean"] / mean, row["speedup_vs_e0"], "scheduler speedup")
            close(row["speedup_vs_e0"] / row["workers"], row["efficiency"], "scheduler efficiency")
    value = {"status": "PASS", "files_checked": len(manifest["files"]),
             "checks": ["Reference hashes", "Scheduler raw trials, means, dependencies, capacity, budgets, speedups"],
             "limitations": "Other reference experiments include aggregate measurements; original per-trial records are not all bundled. See docs/REPORT.md."}
    write(out / "reference_checks.json", value)
    return value


def validate_measured(out):
    """Recompute this run's means and independently validate its raw work records."""
    raw = read(out / "bench/bench_raw.json")["trials"]
    summary = read(out / "bench/bench_summary.json")["rows"]
    groups = defaultdict(list)
    for trial in raw:
        require(trial["status"] == {"COMPLETED": trial["tasks"]}, "A controlled scheduler trial did not complete")
        check_intervals(trial["records"], {p: v["capacity"] for p, v in trial["resources"].items()}, trial["budget_used"])
        groups[trial["workload"], trial["policy"], trial["workers"]].append(trial["makespan"])
    for row in summary:
        values = groups[row["workload"], row["policy"], row["workers"]]
        require(len(values) == row["trials"], "New scheduler trial count mismatch")
        close(statistics.fmean(values), row["makespan_mean"], "New scheduler mean")
        baseline = next(r for r in summary if r["workload"] == row["workload"] and r["policy"] == "e0")
        close(baseline["makespan_mean"] / row["makespan_mean"], row["speedup_vs_e0"], "New scheduler speedup")
        close(row["speedup_vs_e0"] / row["workers"], row["efficiency"], "New scheduler efficiency")
    scaling = out / "scaling/bench_raw.json"
    if scaling.exists():
        for trial in read(scaling)["trials"]:
            require(trial["status"] == {"COMPLETED": trial["tasks"]}, "Scaling workload did not complete")
            check_intervals(trial["records"], {p: v["capacity"] for p, v in trial["resources"].items()}, trial["budget_used"])
    mc = read(out / "planning/multicore.json")
    for trial in mc["raw_trials"]:
        require(trial["complete"] and trial["batches"] == trial["batches_done"], "Incomplete fixed-rollout computation")
        require(trial["estimates"] == mc["estimates"], "Process-count-dependent Monte Carlo estimates")
        require(sum(e["rollouts"] for e in trial["estimates"]) == mc["candidates"] * mc["rollouts_per_candidate"], "MC workload changed")
        if trial["processes"] > 1:
            require(1 < len(trial["worker_pids"]) <= trial["processes"], "No actual CPU multiprocessing observed")
    for row in mc["rows"]:
        values = [t["wall_seconds"] for t in mc["raw_trials"] if t["processes"] == row["processes"]]
        require(len(values) == row["trials"], "New MC trial count mismatch")
        close(statistics.fmean(values), row["wall_mean"], "New MC mean")
    spec_results = []
    for folder in ("speculation", "budget"):
        path = out / folder / "speculation.json"
        if not path.exists():
            continue
        data = read(path)
        draws = {}
        for trial in data["raw_trials"]:
            key = trial["scenario"], trial["trial"]
            if key in draws:
                require(draws[key] == trial["outcomes"], "Speculation policies received different outcome draws")
            draws[key] = trial["outcomes"]
            ledger = trial["budget_snapshot"]["ledger"]["global"]["tool_calls"]
            require(0 <= ledger["used"] <= ledger["limit"] and ledger["remaining"] >= 0, "Speculation overspent its budget")
            require(ledger["used"] == trial["tool_calls"], "Speculation charge disagrees with ledger")
        for row in data["rows"]:
            trials = [t for t in data["raw_trials"] if (t["scenario"], t["policy"], t["budget"]) ==
                      (row["scenario"], row["policy"], row["budget"])]
            require(len(trials) == row["trials"], "Speculation trial count mismatch")
            for field, source in (("latency_mean", "latency"), ("tool_calls_mean", "tool_calls"),
                                  ("wasted_calls_mean", "wasted_calls"), ("completion_rate", "satisfied")):
                close(statistics.fmean(t[source] for t in trials), row[field], f"New speculation {field}")
            for t in trials:
                count = check_intervals(t["records"], row["capacities"], t["budget"])
                require(count == t["tool_calls"], "Dispatched speculative work was not charged exactly once")
        spec_results.extend(data["rows"])
    # Experiment commands must not pass just because they produced a table.
    # Validate the persisted harness runs, including every worker and ledger.
    fixture_runs = []
    for folder in ("fixture", "harness", "agents", "whole", "overhead", "contention", "matrix", "demo"):
        for path in (out / folder).rglob("final_result.json"):
            final = read(path)
            require(final["run_status"] == "COMPLETED", f"Run failed: {path.parent.name}")
            require(not final["execution_summary"]["failed_workers"], f"Worker failed: {path.parent.name}")
            for resource, ledger in final["budgets"]["global"].items():
                require(0 <= ledger["used"] <= ledger["limit"] and ledger["remaining"] >= 0,
                        f"Invalid {resource} ledger: {path.parent.name}")
            if final.get("scheduler"):
                records = [event["payload"] for event in map(json.loads, (path.parent / "events.jsonl").read_text().splitlines())
                           if event["event_type"] == "SCHEDULER_TASK_FINISHED"]
                check_intervals(records, {p: v["capacity"] for p, v in final["scheduler"]["resources"].items()},
                                final["budgets"]["global"]["tool_calls"]["limit"])
            fixture_runs.append(str(path.parent.relative_to(out)))
    result = {"status": "PASS", "scheduler_rows": summary, "montecarlo_rows": mc["rows"],
              "speculation_rows": spec_results, "fixture_runs_checked": fixture_runs,
              "worker_pids": {str(p): sorted({pid for t in mc["raw_trials"]
                         if t["processes"] == p for pid in t["worker_pids"]}) for p in (1, 2, 4, 8, 16)}}
    write(out / "measured_checks.json", result)
    return result


def measurement_report(out):
    """Assemble fresh experiment tables without substituting reference timings."""
    env = read(out / "environment.json")
    lines = ["# Fresh PARSEC-VL experiment results", "", f"Recorded: {env['date_utc']}",
             f"Python: {env['python'].split()[0]}; logical CPUs: {env['cpus']}", "",
             "SYNTHETIC timings measure declared workloads. FIXTURE runs use scripted models and local tools.",
             "These results do not establish real-model accuracy or GPU throughput. Measurements include slowdowns.",
             "See [verification summary](SUMMARY.md) for check status and summary.json for commands and logs.", ""]
    fixture = out / "fixture/fixture_checks.json"
    if fixture.exists():
        data = read(fixture)
        lines += ["## Same visual plan: sequential and parallel dispatch", "",
                  f"Measured tool-span speedup: **{data['speedup']:.3f}x** (FIXTURE).",
                  "Independent OCR and grounding overlap; crop OCR consumes the actual generated crop.", ""]
    tables = [("Scheduler policies and workload bounds", "bench/bench_summary.md"),
              ("Independent-task worker scaling", "scaling/bench_summary.md"),
              ("CPU-process Monte Carlo scaling", "planning/multicore.md"),
              ("Planning decision quality", "planning/decision_quality.md"),
              ("Identical declared action plan", "actions/actions.md"),
              ("Original tool protocol", "harness/harness.md"),
              ("Worker and scheduler policy coverage", "agents/agents.md"),
              ("Speculation latency and waste", "speculation/speculation.md"),
              ("Tool budget sensitivity", "budget/speculation.md"),
              ("Whole harness OFF and E0-E5", "whole/variants.md"),
              ("Planning pool overhead", "overhead/variants.md"),
              ("Resource contention", "contention/variants.md"),
              ("Worker, memory and peer configuration matrix", "matrix/matrix.md")]
    included = []
    for title, name in tables:
        path = out / name
        if path.exists():
            lines += [f"## {title}", "", f"Source: [{name}]({name})", "", path.read_text(), ""]
            included.append(name)
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")
    return {"tables": included, "report": "REPORT.md"}


class Runner:
    def __init__(self, kind):
        parent = ROOT / "outputs/parsec_vl" / ("verification" if kind == "verify" else "advisor_demo")
        parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_")
        self.out = Path(tempfile.mkdtemp(prefix=stamp, dir=parent))
        self.steps = []
        self.env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                    "MPLCONFIGDIR": str(self.out / "matplotlib")}
        write(self.out / "environment.json", environment())
        print(f"Artifacts: {self.out.relative_to(ROOT)}", flush=True)

    def command(self, label, command, timeout=1200, junit=None):
        print(f"{label} …", end=" ", flush=True)
        log = self.out / (f"{len(self.steps):02d}_" + label.lower().replace(" ", "_").replace("/", "_") + ".log")
        began = time.monotonic()
        with log.open("w") as handle:
            handle.write(f"Command: {command!r}\n"); handle.flush()
            process = subprocess.Popen(command, cwd=ROOT, env=self.env, stdout=handle, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            try:
                code = process.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
                code = 124
        step = {"check": label, "status": "PASS" if code == 0 else "FAIL", "command": command,
                "seconds": round(time.monotonic() - began, 3), "exit_code": code, "log": str(log.relative_to(self.out))}
        if junit and Path(junit).exists():
            tree = ET.parse(junit).getroot()
            cases = tree.findall(".//testcase")
            # pytest-subtests includes subtests in the testsuite total but emits
            # one testcase per collected test. Keep those counts separate.
            counts = {"tests": len(cases), "failures": sum(c.find("failure") is not None for c in cases),
                      "errors": sum(c.find("error") is not None for c in cases),
                      "skipped": sum(c.find("skipped") is not None for c in cases)}
            counts["subtests"] = sum(int(s.get("tests", "0")) for s in tree.findall(".//testsuite")) - len(cases)
            counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
            step["tests"] = counts
            # A green exit with skipped checks is explicitly incomplete.
            if counts["skipped"]:
                step["warning"] = f"{counts['skipped']} tests skipped; inspect log"
        self.steps.append(step)
        print(f"{step['status']} ({step['seconds']:.1f}s)", flush=True)
        if code:
            print("\n".join(log.read_text().splitlines()[-18:]), flush=True)
        self.save()
        return code == 0

    def function(self, label, function):
        print(f"{label} …", end=" ", flush=True)
        began = time.monotonic()
        try:
            result = function()
            step = {"check": label, "status": "PASS", "seconds": round(time.monotonic() - began, 3)}
        except Exception as exc:
            result = None
            log = self.out / f"{len(self.steps):02d}_failure.log"
            log.write_text(traceback.format_exc())
            step = {"check": label, "status": "FAIL", "detail": str(exc), "log": log.name,
                    "seconds": round(time.monotonic() - began, 3)}
        self.steps.append(step)
        print(f"{step['status']} ({step['seconds']:.1f}s)", flush=True)
        if step["status"] == "FAIL":
            print(step["detail"], flush=True)
        self.save()
        return result

    def save(self):
        write(self.out / "summary.json", {"steps": self.steps})

    def finish(self):
        failed = any(s["status"] == "FAIL" for s in self.steps)
        lines = ["# PARSEC-VL verification", "", "| Check | Status | Duration |", "|---|---|---:|"]
        lines += [f"| {s['check']} | {s['status']} | {s.get('seconds', 0):.1f}s |" for s in self.steps]
        lines += ["", f"Overall result: {'FAIL' if failed else 'PASS (for the selected tier)'}", "",
                  "Only checks listed above ran. Reference-data limitations are documented in docs/REPORT.md.",
                  "No new real-model inference or GPU stress tests were run. Browser validation is a separate recorded check."]
        (self.out / "SUMMARY.md").write_text("\n".join(lines) + "\n")
        self.save()
        print(f"\nOverall result: {'FAIL' if failed else 'PASS (selected checks)'}")
        print(f"Summary: {self.out / 'SUMMARY.md'}", flush=True)
        return int(failed)


def prerequisites():
    value = environment()
    require(all(value["packages"].values()), f"Missing dependencies: {[k for k,v in value['packages'].items() if not v]}")
    require(value["node"] is not None, "Node is required for JavaScript checks")
    return value


def verify(quick):
    r = Runner("verify")
    r.function("Repository and dependencies", prerequisites)
    for label, target in (("PARSEC unit tests", "tests/parsec_vl"), ("Studio tests", "tests/studio")):
        junit = r.out / (label.split()[0].lower() + "_tests.xml")
        r.command(label, [sys.executable, "-m", "pytest", target, "-q", f"--junitxml={junit}"], junit=junit)
    if not quick:
        junit = r.out / "retained_tests.xml"
        r.command("Full retained tests", [sys.executable, "-m", "pytest", "tests", "-q", f"--junitxml={junit}"], junit=junit)
    else:
        r.steps.append({"check": "Full retained tests (quick mode)", "status": "NOT VERIFIED"})
    r.command("Python lint", [sys.executable, "-m", "ruff", "check", "--select", "E9,F63,F7,F82", "openvlharness", "evaluation_kit", "scripts", "tests"])
    files = sorted((ROOT / "openvlharness/studio/static").glob("*.js")) + sorted((ROOT / "scripts").glob("*.mjs")) + sorted((ROOT / "scripts").glob("*.cjs"))
    def syntax():
        for path in files:
            subprocess.run(["node", "--check", str(path)], check=True, capture_output=True)
        write(r.out / "javascript_syntax.json", {"files_checked": [str(p.relative_to(ROOT)) for p in files]})
    r.function("JavaScript syntax", syntax)
    r.function("Bundled reference results", lambda: reference_checks(r.out))
    r.command("Recorded plan revalidation", [sys.executable, "scripts/plan_probe.py", "--revalidate", "--recorded",
              str(ROOT / "results/reference/plan_probe/plan_probe.json"), "--out", str(r.out / "recorded_plans")])
    r.function("Fixture DAG overlap and provenance", lambda: fixture_suite(r.out / "fixture", trials=2 if quick else 3))
    base = [sys.executable, "scripts/parsec.py"]
    workloads = "B_chain,C_mixed,S_scaling" if quick else ",".join([
        "A_independent", "B_chain", "C_mixed", "D_contention", "M_misestimated", "V_visual_pipeline", "X_cpu_bound", "S_scaling"])
    r.command("Controlled scheduler benchmarks", base + ["bench", "--workloads", workloads, "--policies", "e0,e1,e2",
              "--workers", "1,2,8" if quick else "1,2,4,8", "--trials", "2", "--out", str(r.out / "bench")])
    r.command("Multicore Monte Carlo", base + ["plan-bench", "--processes", "1,2,4" if quick else "1,2,4,8,16",
              "--rollouts", "2000" if quick else "50000", "--trials", "1" if quick else "3",
              "--quality-instances", "0" if quick else "8", "--out", str(r.out / "planning")])
    r.command("Speculation tradeoffs", base + ["spec-bench", "--trials", "3" if quick else "10", "--processes", "0" if quick else "4",
              "--scenarios", "A_speculation_helps,B_speculation_wastes,E_small_budget" if quick else ",".join([
                  "A_speculation_helps", "B_speculation_wastes", "C_limited_resources", "D_wrong_estimates", "E_small_budget"]),
              "--out", str(r.out / "speculation")])
    if not quick:
        r.command("Independent task scaling", base + ["bench", "--workloads", "S_scaling", "--policies", "e0,e1,e2",
                  "--workers", "1,2,4,8,16,32", "--trials", "2", "--out", str(r.out / "scaling")])
        r.command("Fixed plan E0 E1 E2", base + ["actions-bench", "--trials", "3", "--out", str(r.out / "actions")])
        r.command("Original protocol harness", base + ["harness", "--workers", "4", "--trials", "2",
                  "--out", str(r.out / "harness")])
        r.command("All policies and worker counts", base + ["agents-bench", "--workers", "1,2,3,4",
                  "--policies", "off,e0,e1,e2,e3,e4,e5", "--trials", "1", "--planning-processes", "2",
                  "--rollouts", "400", "--out", str(r.out / "agents")])
        r.command("Small budget sweep", base + ["spec-bench", "--trials", "10", "--processes", "4", "--scenarios", "E_small_budget",
                  "--budgets", "3,4,5,8,12", "--out", str(r.out / "budget")])
        for variants in ("whole", "overhead", "contention"):
            r.command(f"Harness variants {variants}", base + ["compare", "--set", variants, "--workers", "1,4",
                      "--trials", "2", "--out", str(r.out)])
        r.command("Configuration matrix", base + ["matrix", "--out", str(r.out / "matrix")])
        r.command("Standalone visual demo", base + ["demo", "--fast", "--out", str(r.out / "demo")])
        r.command("Figures from recorded data", base + ["figures", "--out", str(r.out / "figures")])
        r.command("Figures from fresh experiments", base + ["figures", "--results", str(r.out), "--out", str(r.out / "fresh_figures")])
    r.function("Fresh traces budgets and numerical results", lambda: validate_measured(r.out))
    r.function("Fresh experiment report", lambda: measurement_report(r.out))
    return r.finish()


def demo(full, studio):
    r = Runner("demo")
    print("\nPARSEC-VL — parallel computing for multi-agent visual reasoning.\n"
          "1. Dependency-aware scheduling  2. Multicore Monte Carlo  3. Budget-aware speculation\n"
          "Evidence: FIXTURE (scripted model/local tools) and SYNTHETIC (declared workloads). No real model inference.\n\n"
          "OCR(original) ----------------------+\n"
          "Grounding(original) -> Zoom -> OCR(crop)\n\n"
          "OCR and grounding may overlap; Zoom waits for grounding; crop OCR waits for Zoom.\n", flush=True)
    if r.function("Environment", prerequisites) is None:
        return r.finish()
    fixture = r.function("Visual tool plan and speculation traces", lambda: fixture_suite(r.out, trials=3 if full else 2))
    if fixture:
        print(f"Sequential tool span: {fixture['rows'][0]['tool_span_mean']:.3f}s; parallel: "
              f"{fixture['rows'][1]['tool_span_mean']:.3f}s; measured speedup {fixture['speedup']:.2f}x.\n"
              "Verified: overlap, dependencies, identical results, actual crop input and agent ownership.\n", flush=True)
    base = [sys.executable, "scripts/parsec.py"]
    if r.command("Multicore planning", base + ["plan-bench", "--processes", "1,2,4", "--rollouts", "50000" if full else "12000",
                 "--trials", "3" if full else "2", "--quality-instances", "0", "--out", str(r.out / "planning")]):
        data = read(r.out / "planning/multicore.json")
        print("CPU-bound Monte Carlo; identical fixed rollout count and resulting estimates:")
        for row in data["rows"]:
            if row["processes"]:
                print(f"  {row['processes']} process(es): {row['wall_mean']:.3f}s warm, "
                      f"{row['speedup_vs_1_process']:.2f}x, efficiency {row['efficiency']:.2f}, "
                      f"cold pool startup {row['cold_start_seconds']:.3f}s (reported separately).")
        print("Timing depends on the machine and current load; slower parallel results are retained.\n", flush=True)
    if r.command("Speculation benefit and waste", base + ["spec-bench", "--trials", "10" if full else "5", "--processes", "0",
                 "--scenarios", "A_speculation_helps,B_speculation_wastes,E_small_budget", "--out", str(r.out / "speculation")]):
        rows = read(r.out / "speculation/speculation.json")["rows"]
        for row in rows:
            print(f"  {row['scenario']} / {row['policy']}: {row['latency_mean']:.3f}s, "
                  f"{row['tool_calls_mean']:.2f} calls, {row['wasted_calls_mean']:.2f} wasted, "
                  f"completion {row['completion_rate']:.0%}.")
        print("Speculation starts an alternative early; unused dispatched work stays charged. It can waste calls or budget.\n", flush=True)
    # An equivalent E0-E5 table for this demo's workload, not a claim of real-model speedup.
    r.command("Recorded E0-E5 comparison", base + ["compare", "--set", "whole", "--workers", "1", "--trials", "2" if full else "1",
              "--out", str(r.out / "comparisons")])
    if fixture and studio:
        r.command("Studio launch", [sys.executable, "scripts/studio_ctl.py", "--runs-dir", str(r.out / "runs"), "ensure",
                  "--run", fixture["run_ids"]["parallel"], "--open"])
        print((r.out / r.steps[-1]["log"]).read_text(), flush=True)
    elif fixture:
        print("Open this saved demo without rerunning it:", flush=True)
        print(f"  {sys.executable} scripts/studio_ctl.py --runs-dir {r.out / 'runs'} ensure --run {fixture['run_ids']['parallel']} --open", flush=True)
    print("\nWhat this demonstrates: independent tools overlap; dependencies and budgets stay enforced; "
          "CPU planning uses processes; speculation trades latency for work. End-to-end gains need useful parallel work.\n"
          "The parallel plan is a scripted fixture. Recorded real Qwen executions remain serial.\n", flush=True)
    status = r.finish()
    if not status:
        write(r.out.parent / "latest.json", {"directory": str(r.out), "parallel_run": fixture["run_ids"]["parallel"]})
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("verify", help="default full; --quick runs targeted tests and smaller benchmarks")
    tier = v.add_mutually_exclusive_group()
    tier.add_argument("--quick", action="store_true")
    tier.add_argument("--full", action="store_true")
    d = sub.add_parser("demo", help="default bounded offline demo; --studio opens its selected run")
    tier = d.add_mutually_exclusive_group()
    tier.add_argument("--quick", action="store_true", help="default bounded demonstration")
    tier.add_argument("--full", action="store_true", help="more trials and 50,000 rollouts per candidate")
    d.add_argument("--studio", action="store_true", help="open the last successful demo; combine with --quick/--full to regenerate")
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.command == "demo" and args.studio and not args.full and not args.quick:
        latest = ROOT / "outputs/parsec_vl/advisor_demo/latest.json"
        if latest.is_file():
            saved = read(latest)
            runs = Path(saved["directory"]) / "runs"
            if (runs / saved["parallel_run"] / "events.jsonl").is_file():
                return subprocess.call([sys.executable, "scripts/studio_ctl.py", "--runs-dir", str(runs),
                                        "ensure", "--run", saved["parallel_run"], "--open"])
    return verify(args.quick) if args.command == "verify" else demo(args.full, args.studio)


if __name__ == "__main__":
    raise SystemExit(main())
