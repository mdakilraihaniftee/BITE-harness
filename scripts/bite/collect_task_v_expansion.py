#!/usr/bin/env python3
"""Run the pre-registered Aquarium Task V seven-class expansion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from evaluation_kit.bite_collection.collection_audit import (
    build_pilot_audit,
    export_pilot_tables,
)
from evaluation_kit.bite_collection.dataset_adapter import AquariumDatasetAdapter
from evaluation_kit.bite_collection.expansion_protocol import freeze_expansion_protocol
from evaluation_kit.bite_collection.expansion_runner import TaskVExpansionRunner
from evaluation_kit.bite_collection.focused_analysis import analyze_focused_evidence
from evaluation_kit.bite_collection.integrity import (
    validate_canary,
    validate_run_directory,
)
from evaluation_kit.bite_collection.negative_audit import audit_original_candidates
from evaluation_kit.bite_collection.persistence import atomic_json
from evaluation_kit.bite_collection.support_analysis import build_support_summary
from openvlharness.bootstrap import build_capabilities, load_agent_config

try:
    from scripts.bite.collect_calibration_pilot import _preflight
except ModuleNotFoundError:  # Direct ``python scripts/bite/...`` execution.
    from collect_calibration_pilot import _preflight


def _freeze(path, value):
    path = Path(path)
    normalized = json.loads(json.dumps(value))
    if path.exists():
        if json.loads(path.read_text()) != normalized:
            raise ValueError(f"Frozen protocol differs from regenerated value: {path}")
        return
    atomic_json(path, normalized)


def _offline_audit(output, run_dir, selection, adapter):
    audit = build_pilot_audit(
        run_dir, selection, output_path=output / "analysis/expansion_collection_audit.json",
        execution_filename="expansion_execution.json", schema_version="bite.task_v_expansion_audit.v1")
    integrity = validate_run_directory(run_dir)
    atomic_json(output / "validation/expansion_integrity_v2.json", integrity)
    _, negative = audit_original_candidates(run_dir, adapter, output / "offline_labels/expansion_diagnostics")
    _, focused = analyze_focused_evidence(run_dir, adapter, output / "analysis/expansion_focused")
    export = export_pilot_tables(run_dir, output)
    support = build_support_summary(
        pilot_audit_path="outputs/bite/phase04b2b2/audits/pilot_audit.json",
        expansion_audit_path=output / "analysis/expansion_collection_audit.json",
        pilot_diagnostics_path=output / "audit_existing/negative_diagnostics.jsonl",
        expansion_diagnostics_path=output / "offline_labels/expansion_diagnostics/negative_diagnostics.jsonl",
        pilot_focused_path=output / "analysis/focused_analysis_summary.json",
        expansion_focused_path=output / "analysis/expansion_focused/focused_analysis_summary.json",
        output_path=output / "analysis/task_v_support_summary.json",
    )
    return {"audit": audit, "integrity": integrity, "negative": negative,
            "focused": focused, "offline_export": export,
            "support_summary": support["support_assessment"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04b2b3"))
    parser.add_argument("--config", default="configs/agent/qwen3_8b_paper.yaml")
    parser.add_argument("--stage", choices=("preflight", "canary", "collect", "audit"), required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    load_dotenv(".env", override=False)
    output = args.output.resolve()
    for name in ("audit_existing", "protocol", "preflight", "canary", "expansion",
                 "offline_labels", "analysis", "validation"):
        (output / name).mkdir(parents=True, exist_ok=True)
    adapter = AquariumDatasetAdapter()
    selection = freeze_expansion_protocol(adapter)
    protocol_path = output / "protocol/task_v_expansion_protocol.json"
    _freeze(protocol_path, selection)
    run_dir = output / "expansion/aquarium_task_v_expansion_seed418_g30"
    config = load_agent_config(args.config)

    existing_negative = json.loads((output / "audit_existing/negative_audit_summary.json").read_text())
    existing_integrity = json.loads((output / "validation/existing_pilot_integrity_v2.json").read_text())
    if existing_negative.get("systematic_defect_found") or not existing_negative.get("reconstructed_exactly"):
        raise SystemExit("Historical label audit blocks expansion")
    if not existing_integrity.get("valid"):
        raise SystemExit("Historical collection integrity blocks expansion")

    if args.stage == "audit":
        result = _offline_audit(output, run_dir, selection, adapter)
        print(json.dumps({"status": "SUCCESS", "stage": "audit", **result}, indent=2))
        return

    preflight = _preflight(output / "preflight", adapter, selection, args.config, config)
    preflight["historical_audit_gate"] = {
        "negative_labels_reconstructed": existing_negative["reconstructed_exactly"],
        "systematic_defect_found": existing_negative["systematic_defect_found"],
        "artifact_integrity_valid": existing_integrity["valid"],
        "historical_raw_before_label_independently_reconstructible": False,
    }
    preflight["protocol_sha256"] = selection["protocol_sha256"]
    atomic_json(output / "preflight/expansion_preflight.json", preflight)
    if args.stage == "preflight":
        print(json.dumps({"status": "SUCCESS", "stage": "preflight", "report": preflight}, indent=2))
        return

    capabilities = build_capabilities(config)
    runner = TaskVExpansionRunner(
        adapter=adapter, selection=selection, capabilities=capabilities, memory_config=config["memory"],
        run_dir=run_dir, collection_run_id="aquarium_task_v_expansion_seed418_g30", resume=args.resume,
    )
    if args.stage == "canary":
        execution = runner.run(canary_only=True)
        gate = validate_canary(run_dir, selection, dispatch_cap=665)
        atomic_json(output / "canary/execution.json", execution)
        atomic_json(output / "canary/canary_gate_v2.json", gate)
        if not gate["pass"]:
            raise SystemExit("Expansion canary integrity gate failed")
        print(json.dumps({"status": "SUCCESS", "stage": "canary", "execution": execution,
                          "gate": gate}, indent=2))
        return

    gate_path = output / "canary/canary_gate_v2.json"
    if not gate_path.is_file() or not json.loads(gate_path.read_text()).get("pass"):
        raise SystemExit("A passing expansion canary is required")
    execution = runner.run(canary_only=False)
    atomic_json(output / "expansion/execution.json", execution)
    result = _offline_audit(output, run_dir, selection, adapter)
    print(json.dumps({"status": "SUCCESS", "stage": "collect", "execution": execution,
                      **result}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "FAILED", "error": type(error).__name__,
                          "message": str(error)}), file=sys.stderr)
        raise

