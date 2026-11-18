#!/usr/bin/env python3
"""Deterministic multi-agent configuration runs and the 16-configuration matrix.

TEST FIXTURE ONLY: every actor is a real MainAgent whose model endpoint is a
scripted policy (openvlharness.multi_agent.testing). No model server is used,
and results are engineering validation, never model performance.

Single run (for the Studio demo or a screenshot):
    python scripts/studio_config_matrix.py run --workers 3 --memory on --peer off

Full matrix with runtime and UI-model validation and a report:
    python scripts/studio_config_matrix.py matrix --output-dir outputs/studio_matrix
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openvlharness.multi_agent import MultiAgentOrchestrator  # noqa: E402
from openvlharness.multi_agent.testing import (  # noqa: E402
    FIXTURE_TASK,
    ScriptedAgentBuilder,
    create_scene,
    fixture_config,
    write_fixture_reference,
)
from openvlharness.studio.replay import public_snapshot  # noqa: E402
from openvlharness.studio.schema import validate_event  # noqa: E402

TERMINAL_EVENTS = {"RUN_COMPLETED", "RUN_FAILED", "RUN_CANCELLED"}


def run_fixture(
    output_dir: Path,
    *,
    workers: int,
    memory: bool,
    peer: bool,
    mode: str = "cooperative",
    estimates: bool = True,
    run_id: str | None = None,
    step_delay: float = 0.0,
    reference: bool = True,
    scenario: str = "standard",
) -> tuple[Path, ScriptedAgentBuilder, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    image = create_scene(output_dir / "fixture_scene.png")
    builder = ScriptedAgentBuilder(image, scenario=scenario, delay=step_delay)
    factory = builder.factory()
    config = fixture_config(
        output_dir, workers=workers, memory=memory, peer=peer, mode=mode,
        estimate_updates=estimates,
    )
    run_id = run_id or (
        f"fixture_w{workers}_mem{'on' if memory else 'off'}_peer{'on' if peer else 'off'}_"
        f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}"
    )
    orchestrator = MultiAgentOrchestrator(config, factory=factory, run_id=run_id)
    if reference:
        # Label-free task identity (like a dataset row) so the Studio can show the
        # reference as sealed while the run executes. The value is written to the
        # evaluator-only store after the run; agents never read either file.
        (orchestrator.run_dir / "inputs").mkdir(parents=True, exist_ok=True)
        (orchestrator.run_dir / "inputs" / "dataset_task.json").write_text(json.dumps({
            "schema_version": "studio.dataset-task.v1", "dataset": "deterministic_fixture",
            "row_position": 0, "dataset_index": "synthetic_scene_v1", "question": FIXTURE_TASK,
            "ground_truth_policy": "sealed_not_passed_to_runtime_or_persisted_run",
        }, indent=2) + "\n", encoding="utf-8")
    result = orchestrator.run(
        FIXTURE_TASK,
        [{"type": "image", "value": str(image.resolve())}, {"type": "text", "value": FIXTURE_TASK}],
    )
    # The evaluator-side label is written only after the run is terminal.
    if reference:
        write_fixture_reference(output_dir / ".references", run_id)
    return orchestrator.run_dir, builder, result


def _events(run_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines() if line.strip()]


def validate_run(run_dir: Path, builder: ScriptedAgentBuilder, *, workers: int, memory: bool, peer: bool) -> dict[str, Any]:
    """Runtime checks for one fixture run. Each value is (passed, detail)."""
    events = _events(run_dir)
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    budgets = json.loads((run_dir / "budgets.json").read_text())
    state = json.loads((run_dir / "run_state.json").read_text())
    types = [e["event_type"] for e in events]
    worker_ids = [f"worker_{i:02d}" for i in range(1, workers + 1)]
    checks: dict[str, tuple[bool, str]] = {}
    for event in events:
        validate_event(event)
    checks["event_schema_and_order"] = (
        [e["sequence"] for e in events] == list(range(len(events))) and types[-1] in TERMINAL_EVENTS,
        f"{len(events)} events, last {types[-1]}",
    )
    checks["lifecycle"] = (state["status"] == "COMPLETED", state["status"])
    checks["worker_count"] = (
        manifest["worker_count"] == workers and manifest["topology"]["worker_ids"] == worker_ids,
        f"manifest {manifest['worker_count']}",
    )
    actors = {e["agent_id"] for e in events if e["agent_id"] not in {"orchestrator"}}
    checks["coordinator_count"] = (
        manifest["coordinator_count"] == 1 and actors <= {"coordinator", *worker_ids},
        f"actors {sorted(actors)}",
    )
    object_ids = {a["agent_object_id"] for a in manifest["actors"].values()}
    adapter_ids = {a["adapter_object_id"] for a in manifest["actors"].values()}
    tool_agents = {e["agent_id"] for e in events if e["event_type"] == "TOOL_CALL_STARTED"}
    checks["harness_ownership"] = (
        len(object_ids) == workers + 1 and len(adapter_ids) == workers + 1 and tool_agents <= set(worker_ids),
        f"{len(object_ids)} agents, {len(adapter_ids)} adapters, tool users {sorted(tool_agents)}",
    )
    # No contamination: each worker's model requests only ever name that worker.
    leaks = []
    for worker_id in worker_ids:
        text = json.dumps(builder.policies[worker_id].requests)
        for other in worker_ids:
            if other != worker_id and f"You are {other}" in text:
                leaks.append(f"{worker_id}<-{other}")
    checks["no_state_contamination"] = (not leaks, ", ".join(leaks) or "isolated")
    notebook_events = [e for e in events if e["event_type"].startswith("OPTIONAL_MEMORY_")]
    files = [p for p in (run_dir / "workers").glob("*/private_memory.json")]
    effective = manifest["effective_config"]
    if memory:
        writers = {e["agent_id"] for e in notebook_events if e["event_type"] == "OPTIONAL_MEMORY_WRITTEN"}
        mem_ok = writers == set(worker_ids) and len(files) == workers and effective["optional_worker_memory_enabled"]
    else:
        mem_ok = not notebook_events and not files and not effective["optional_worker_memory_enabled"]
    working = sum(1 for e in events if e["event_type"] in {"MEMORY_WRITTEN", "MEMORY_READ"})
    checks["memory_policy"] = (mem_ok, f"{len(notebook_events)} notebook events, {len(files)} notebook files, {working} working-context events")
    peer_messages = [e for e in events if e["event_type"] == "MESSAGE_SENT" and e["payload"].get("channel") == "peer"]
    assignments = [e for e in events if e["event_type"] == "MESSAGE_SENT" and e["payload"].get("message_type") == "TASK_ASSIGNMENT"]
    reports = [e for e in events if e["event_type"] == "MESSAGE_SENT" and e["payload"].get("message_type") == "CANDIDATE_ANSWER"]
    expect_peer = peer and workers > 1
    checks["communication_policy"] = (
        (bool(peer_messages) == expect_peer) and len(assignments) >= workers and len(reports) >= workers
        and effective["peer_communication_enabled"] == peer,
        f"{len(peer_messages)} peer, {len(assignments)} assignments, {len(reports)} reports",
    )
    over = [
        f"{k}:{v['used']}/{v['limit']}" for k, v in budgets["global"].items() if v["used"] > v["limit"]
    ] + [
        f"{actor}.{k}" for actor, items in budgets["actors"].items() for k, v in items.items() if v["used"] > v["limit"]
    ]
    checks["budget_enforced"] = (not over, ", ".join(over) or f"tools {budgets['global']['tool_calls']['used']}/{budgets['global']['tool_calls']['limit']}")
    estimates = [e for e in events if e["event_type"] == "COORDINATOR_ESTIMATE_UPDATED"]
    first_estimate = types.index("COORDINATOR_ESTIMATE_UPDATED") if estimates else None
    first_report = next((i for i, e in enumerate(events) if e["event_type"] == "HYPOTHESIS_UPDATED"), None)
    checks["coordinator_estimates"] = (
        bool(estimates) and estimates[-1]["payload"]["status"] == "final"
        and first_report is not None and first_estimate > first_report
        and [e["payload"]["revision"] for e in estimates] == list(range(1, len(estimates) + 1)),
        " → ".join(f"{e['payload']['estimate']}({e['payload']['change_kind']})" for e in estimates),
    )
    snapshot = public_snapshot(run_dir.parent, run_dir.name)
    topology = snapshot["topology"]
    annotated = all("activity" in e for e in snapshot["events"])
    checks["replay_snapshot"] = (
        annotated and len(snapshot["events"]) == len(events) and topology["agents"] == ["coordinator", *worker_ids],
        f"{len(snapshot['events'])} annotated events, {len(topology['nodes'])} topology nodes",
    )
    counts = {
        "events": len(events),
        "tool_calls": types.count("TOOL_CALL_STARTED"),
        "tool_failures": types.count("TOOL_CALL_FAILED"),
        "model_requests": types.count("MODEL_REQUEST_STARTED"),
        "peer_messages": len(peer_messages),
        "notebook_events": len(notebook_events),
        "estimate_revisions": len(estimates),
        "retained_assessments": sum(1 for e in events if e["event_type"] == "COORDINATOR_REASSESSMENT_RECORDED" and e["payload"].get("outcome") == "retained"),
        "follow_ups": types.count("FOLLOW_UP_ASSIGNED"),
        "final_answer": json.loads((run_dir / "final_result.json").read_text()).get("final_answer"),
    }
    return {"checks": {k: {"passed": v[0], "detail": v[1]} for k, v in checks.items()}, "counts": counts, "snapshot": snapshot}


def ui_check(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run the real frontend modules (team model, answer state, story) in Node."""
    node = shutil.which("node")
    if node is None:
        return [{"passed": False, "detail": "Node.js unavailable"} for _ in snapshots]
    payload = json.dumps(snapshots)
    completed = subprocess.run(
        [node, str(ROOT / "scripts" / "studio_ui_model_check.cjs")],
        input=payload, capture_output=True, text=True, cwd=ROOT, timeout=120, check=False,
    )
    if completed.returncode != 0:
        return [{"passed": False, "detail": completed.stderr.strip()[-400:]} for _ in snapshots]
    return json.loads(completed.stdout)


def matrix(output_dir: Path, report: Path) -> int:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    rows = []
    snapshots = []
    for workers, memory, peer in product((1, 2, 3, 4), (True, False), (True, False)):
        run_id = f"matrix_w{workers}_mem{'on' if memory else 'off'}_peer{'on' if peer else 'off'}"
        started = time.monotonic()
        run_dir, builder, result = run_fixture(output_dir, workers=workers, memory=memory, peer=peer, run_id=run_id)
        validation = validate_run(run_dir, builder, workers=workers, memory=memory, peer=peer)
        snapshots.append({"snapshot": validation.pop("snapshot"),
                          "expected": {"workers": workers, "memory": memory, "peer": peer}})
        rows.append({"run_id": run_id, "workers": workers, "memory": memory, "peer": peer,
                     "status": result["extra_records"]["status"], "seconds": round(time.monotonic() - started, 2), **validation})
    for row, ui in zip(rows, ui_check(snapshots)):
        row["ui"] = ui
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(rows, indent=2, default=str) + "\n")
    lines = [
        "| Workers | Memory | Peer comm. | Runtime success | UI success | Memory policy verified | Communication policy verified | Tool calls | Peer msgs | Notebook events | Estimates | Final |",
        "|---:|---|---|---|---|---|---|---:|---:|---:|---|---|",
    ]
    all_ok = True
    for row in rows:
        c = row["checks"]
        runtime_ok = all(item["passed"] for item in c.values())
        all_ok &= runtime_ok and row["ui"]["passed"]
        yes = lambda flag: "✅" if flag else "❌"  # noqa: E731
        lines.append(
            f"| {row['workers']} | {'ON' if row['memory'] else 'OFF'} | {'ON' if row['peer'] else 'OFF'}"
            f"{' (no peers)' if row['peer'] and row['workers'] == 1 else ''} | {yes(runtime_ok)} | {yes(row['ui']['passed'])} | "
            f"{yes(c['memory_policy']['passed'])} | {yes(c['communication_policy']['passed'])} | {row['counts']['tool_calls']} | "
            f"{row['counts']['peer_messages']} | {row['counts']['notebook_events']} | {c['coordinator_estimates']['detail']} | {row['counts']['final_answer']} |"
        )
    report.with_suffix(".md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    failures = [(r["run_id"], k, v["detail"]) for r in rows for k, v in r["checks"].items() if not v["passed"]]
    failures += [(r["run_id"], "ui", r["ui"]["detail"]) for r in rows if not r["ui"]["passed"]]
    for failure in failures:
        print("FAILED", *failure)
    print(f"Report: {report} and {report.with_suffix('.md')}")
    return 0 if all_ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("run", help="One deterministic fixture run")
    one.add_argument("--workers", type=int, default=2, choices=(1, 2, 3, 4))
    one.add_argument("--memory", choices=("on", "off"), default="on")
    one.add_argument("--peer", choices=("on", "off"), default="on")
    one.add_argument("--mode", choices=("concurrent", "cooperative"), default="cooperative")
    one.add_argument("--estimates", choices=("on", "off"), default="on")
    one.add_argument("--scenario", choices=("standard", "withdrawal"), default="standard")
    one.add_argument("--output-dir", type=Path, default=Path("outputs/multi_agent"))
    one.add_argument("--run-id")
    one.add_argument("--step-delay", type=float, default=0.0, help="Seconds per scripted model request (live demos).")
    one.add_argument("--no-reference", action="store_true", help="Do not write an evaluator reference (NOT_AVAILABLE case).")
    full = sub.add_parser("matrix", help="All 16 worker/memory/peer configurations")
    full.add_argument("--output-dir", type=Path, default=Path("outputs/studio_matrix"))
    full.add_argument("--report", type=Path, default=Path("outputs/studio_matrix_report/matrix_report.json"))
    args = parser.parse_args(argv)
    if args.command == "matrix":
        return matrix(args.output_dir, args.report)
    run_dir, builder, result = run_fixture(
        args.output_dir, workers=args.workers, memory=args.memory == "on", peer=args.peer == "on",
        mode=args.mode, estimates=args.estimates == "on", run_id=args.run_id, step_delay=args.step_delay,
        reference=not args.no_reference, scenario=args.scenario,
    )
    print(f"Deterministic fixture run (test only): {run_dir}")
    print(f"Status: {result['extra_records']['status']}  Final answer: {result['prediction']}")
    return 0 if result["extra_records"]["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
