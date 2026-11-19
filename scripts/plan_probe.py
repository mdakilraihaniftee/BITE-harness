#!/usr/bin/env python
"""Bounded real-model probe: does the model propose (valid) Execute_Action_Plan calls?

REAL model, first decision only: the agent is built from the normal agent
configuration with plan mode attached; the first model response is captured
and nothing is executed (no tool calls, no scheduler work). Each returned plan
goes through the real validator. Use only when the model service is running and
real inference is authorized; the default is 5 samples x 3 conditions.

  python scripts/plan_probe.py --samples 5 --schema both
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


class _Stop(Exception):
    pass


def first_decision(agent, message) -> dict:
    captured = {}
    original = agent.adapter.request

    def once(*args, **kwargs):
        began = time.monotonic()
        response = original(*args, **kwargs)
        captured.update(response=response, seconds=time.monotonic() - began, tools=args[1] if len(args) > 1 else None)
        raise _Stop

    agent.adapter.request = once
    try:
        agent.generate(message)
    except _Stop:
        pass
    finally:
        agent.adapter.request = original
    return captured


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--agent-config", default="examples/local_grounding_tools.yaml")
    parser.add_argument("--schema", choices=("current", "simple", "both"), default="both")
    parser.add_argument("--out", default="outputs/parsec_vl/phase3/plan_probe")
    parser.add_argument("--execute", type=int, default=0,
                        help="also run N complete single-agent investigations of the explicit sign question "
                             "(real model + real tools, E2 scheduler, simple plan schema)")
    parser.add_argument("--revalidate", action="store_true",
                        help="re-check the recorded proposals in plan_probe.json with the current parser (no inference)")
    parser.add_argument("--recorded", type=Path,
                        help="Recorded plan_probe.json to revalidate; --out receives the new report.")
    args = parser.parse_args()
    if args.revalidate:
        return revalidate(Path(args.out), args.agent_config, args.recorded)
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from openvlharness.bootstrap import build_agent, load_agent_config
    from openvlharness.parsec_vl import Scheduler
    from openvlharness.parsec_vl.controller import PlanningConfig
    from openvlharness.parsec_vl.fixture import create_sign_scene
    from openvlharness.parsec_vl.harness import PlanController, attach_plan_mode, pools_for
    from openvlharness.parsec_vl.plans import PLAN_TOOL

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sign = create_sign_scene(out / "sign_scene.png")
    grape_image = Path("data/images/FSC147/234.jpg")  # FSC147_val row 25 (grapes), used in the Phase 2 real runs
    conditions = [
        ("sign_natural", sign, "What does the sign say? Answer with the exact text."),
        ("sign_explicit", sign, "What does the sign say? Answer with the exact text. Use Execute_Action_Plan: read the whole "
                                "image with OCR and, in parallel, ground the sign, zoom into it, and read the zoomed crop."),
        ("count_natural", grape_image, "How many grape are there in the image? Your final answer should be a single integer."),
    ]
    if args.execute:
        return execute(args, out, sign, conditions[1][2])
    schemas = ["current", "simple"] if args.schema == "both" else [args.schema]
    config = load_agent_config(args.agent_config)
    results = []
    for schema in schemas:
        for name, image, question in conditions:
            for sample in range(args.samples):
                agent = build_agent(config)
                scheduler = Scheduler(policy="e2", workers=1, capacities=pools_for([agent]))
                attach_plan_mode(agent, PlanController(scheduler, "probe", PlanningConfig.for_mode("e3")), schema=schema)
                decision = first_decision(agent, [{"type": "image", "value": str(image)}, {"type": "text", "value": question}])
                scheduler.shutdown()
                text, calls, _ = agent.adapter.parse(decision["response"], 0)
                offered = [t["function"]["name"] for t in (decision.get("tools") or [])]
                row = {"schema": schema, "condition": name, "sample": sample, "seconds": round(decision["seconds"], 3),
                       "plan_tool_offered": PLAN_TOOL in offered, "tools_offered": len(offered),
                       "calls": [c["name"] for c in calls], "parse_errors": [c.get("parse_error", {}).get("code") for c in calls if c.get("parse_error")],
                       "plan_proposed": False, "plan_valid": None, "plan_reason": None, "independent_actions": None, "plan": None}
                plan_call = next((c for c in calls if c["name"] == PLAN_TOOL and not c.get("parse_error")), None)
                if plan_call:
                    row["plan_proposed"] = True
                    row["plan"] = plan_call.get("args")
                    row.update(check_plan(row["plan"], agent.capabilities))
                results.append(row)
                print(json.dumps({k: v for k, v in row.items() if k != "plan"}))
    summary = summarize(results)
    (out / "plan_probe.json").write_text(json.dumps({"label": "REAL model (first decision only; nothing executed)",
                                                     "recorded_at": datetime.now(UTC).isoformat(),
                                                     "agent_config": args.agent_config, "summary": summary, "rows": results},
                                                    indent=2, default=str))
    print(json.dumps(summary, indent=1))
    return 0


def check_plan(arguments, capabilities) -> dict:
    """Validate one model-proposed plan with the current parser (no model call, no tool call)."""
    from openvlharness.parsec_vl.harness import _has_independent_work
    from openvlharness.parsec_vl.plans import PlanError, normalize_simple_plan, parse_plan, validate_plan

    try:
        raw = arguments or {}
        raw = normalize_simple_plan(raw) if "steps" in raw else raw
        plan = parse_plan(raw, run_id="probe", agent_id="probe", origin_type="model")
        validate_plan(plan, capabilities, {"input_image_1"})
        return {"plan_valid": True, "plan_reason": None, "independent_actions": _has_independent_work(plan),
                "inferred_dependencies": plan.estimates.get("inferred_dependencies")}
    except PlanError as exc:
        return {"plan_valid": False, "plan_reason": f"{exc.reason}: {exc}", "independent_actions": None}


def revalidate(out: Path, agent_config: str, recorded_path: Path | None = None) -> int:
    """Re-check the plans already recorded in plan_probe.json with the current parser.

    Nothing is sent to the model: the recorded proposals are the evidence. The original file
    is left unchanged; the result goes to plan_probe_revalidated.json.
    """
    import yaml

    from openvlharness.bootstrap import build_capabilities

    source = recorded_path or out / "plan_probe.json"
    recorded = json.loads(source.read_text())
    # Schema validation needs capability schemas, not an agent, model adapter,
    # tokenizer, credentials, or live transports. This placeholder client is
    # constructed but never called by check_plan/validate_plan.
    config = yaml.safe_load(Path(recorded.get("agent_config") or agent_config).read_text())
    config["services"]["client"] = {"base_url": "http://127.0.0.1:1", "timeout_seconds": 1, "retry": 0}
    capabilities = build_capabilities(config)
    rows = []
    for row in recorded["rows"]:
        row = dict(row, original_plan_valid=row["plan_valid"], original_plan_reason=row["plan_reason"])
        if row["plan_proposed"]:
            row.update(check_plan(row["plan"], capabilities))
        rows.append(row)
    summary = summarize(rows)
    out.mkdir(parents=True, exist_ok=True)
    (out / "plan_probe_revalidated.json").write_text(json.dumps({
        "label": "REAL model proposals (recorded) re-validated with the current parser; no new inference",
        "source": str(source), "source_recorded_at": recorded.get("recorded_at"),
        "revalidated_at": datetime.now(UTC).isoformat(), "summary": summary, "rows": rows}, indent=2, default=str))
    print(json.dumps(summary, indent=1))
    return 0


def summarize(results) -> dict:
    from openvlharness.parsec_vl.plans import PLAN_TOOL

    summary = {}
    for row in results:
        key = f"{row['schema']}/{row['condition']}"
        entry = summary.setdefault(key, {"samples": 0, "plan_proposed": 0, "plan_valid": 0, "independent": 0, "other_calls": {}})
        entry["samples"] += 1
        entry["plan_proposed"] += row["plan_proposed"]
        entry["plan_valid"] += bool(row["plan_valid"])
        entry["independent"] += bool(row["independent_actions"])
        for call in row["calls"]:
            if call != PLAN_TOOL:
                entry["other_calls"][call] = entry["other_calls"].get(call, 0) + 1
    return summary


def execute(args, out: Path, image: Path, question: str) -> int:
    """Complete investigations: the model's own plan (if any) runs on the real tool services."""
    from openvlharness.bootstrap import build_agent, load_agent_config
    from openvlharness.parsec_vl import Scheduler
    from openvlharness.parsec_vl.controller import PlanningConfig
    from openvlharness.parsec_vl.harness import PlanController, ToolScheduling, attach_plan_mode, pools_for

    config = load_agent_config(args.agent_config)
    summaries = []
    for index in range(args.execute):
        agent = build_agent(config)
        events = []
        agent.event_sink = lambda t, p, **m: (events.append({"event_type": t, "payload": p, "time": time.time(), **m}),
                                              {"event_id": f"e{len(events)}"})[1]
        records = []
        scheduler = Scheduler(policy="e2", workers=4, capacities=pools_for([agent]),
                              event_sink=lambda kind, record: records.append({"kind": kind, **record}))
        agent.tool_scheduler = ToolScheduling(scheduler, "worker_01")
        controller = PlanController(scheduler, "worker_01", PlanningConfig.for_mode("e3", planning_processes=0), run_id=f"real_exec_{index}")
        attach_plan_mode(agent, controller, schema="simple")
        began = time.monotonic()
        result = agent.generate([{"type": "image", "value": str(image)}, {"type": "text", "value": question}])
        wall = time.monotonic() - began
        scheduler.shutdown()
        finished = [r for r in records if r["kind"] == "SCHEDULER_TASK_FINISHED"]
        intervals = sorted(((r["operation"], round(r["start_time"], 3), round(r["finish_time"], 3), r["resource_pool"],
                             (r.get("metadata") or {}).get("action_id")) for r in finished if r.get("start_time") is not None),
                           key=lambda x: x[1])
        overlaps = sum(1 for i, a in enumerate(intervals) for b in intervals[i + 1:] if a[1] < b[2] and b[1] < a[2])
        summary = {"run": index, "label": "REAL model + REAL tool services (explicitly asked to plan)", "answer": result["prediction"],
                   "wall_seconds": round(wall, 3), "plan_stats": controller.stats,
                   "plan_reports": [{k: v for k, v in r.items() if k in ("plan_id", "satisfied", "winning_branch", "decision_latency_s")}
                                    for r in controller.reports],
                   "tool_intervals": intervals, "overlapping_pairs": overlaps,
                   "tool_calls": [e["tool_name"] for e in events if e["event_type"] == "TOOL_CALL_REQUESTED"],
                   "model_requests": sum(1 for e in events if e["event_type"] == "MODEL_REQUEST_STARTED")}
        summaries.append(summary)
        (out / f"execute_{index}_events.jsonl").write_text("\n".join(json.dumps(e, default=str) for e in events) + "\n")
        (out / f"execute_{index}_scheduler.json").write_text(json.dumps(records, indent=1, default=str))
        print(json.dumps(summary, indent=1, default=str))
    (out / "execute_summary.json").write_text(json.dumps(summaries, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
