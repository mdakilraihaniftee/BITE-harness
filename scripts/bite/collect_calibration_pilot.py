#!/usr/bin/env python3
"""Run the frozen Aquarium Task V canary/pilot without an orchestrator model."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from evaluation_kit.bite_calibration.common import file_hash
from evaluation_kit.bite_collection.batch_runner import TaskVBatchRunner
from evaluation_kit.bite_collection.collection_audit import (
    build_pilot_audit,
    export_pilot_tables,
)
from evaluation_kit.bite_collection.dataset_adapter import AquariumDatasetAdapter
from evaluation_kit.bite_collection.integrity import (
    validate_canary,
    validate_run_directory,
)
from evaluation_kit.bite_collection.manifest_iterator import select_states
from evaluation_kit.bite_collection.persistence import atomic_json
from openvlharness.bootstrap import build_capabilities, load_agent_config


def _service(url):
    started = time.monotonic()
    response = requests.get(url, timeout=5)
    response.raise_for_status()
    return {"url": url, "status_code": response.status_code, "latency_ms": (time.monotonic() - started) * 1000,
            "response": response.json()}


def _gpu_inventory():
    command = ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.SubprocessError) as error:
        return {"available": False, "reason": type(error).__name__, "gpus": []}
    gpus = []
    for line in result.stdout.splitlines():
        index, name, total, used, free = [value.strip() for value in line.split(",", 4)]
        gpus.append({"index": int(index), "name": name, "memory_total_mib": int(total),
                     "memory_used_mib": int(used), "memory_free_mib": int(free)})
    return {"available": True, "gpus": gpus}


def _preflight(output, adapter, selection, config_path, config):
    output.mkdir(parents=True, exist_ok=True)
    health = {
        "router": _service(config["services"]["client"]["base_url"].rstrip("/") + "/health"),
        "sam3": _service(config["services"]["tools"]["sam3_segment"]["server_url"].rstrip("/") + "/health"),
    }
    storage = os.statvfs(output)
    report = {
        "schema_version": "bite.task_v_preflight.v1", "valid": True,
        "dataset": adapter.preflight, "selection": {
            "source_groups": selection["source_group_count"], "images": selection["image_count"],
            "queries": selection["scheduled_query_count"], "maximum_dispatches": selection["maximum_public_dispatches"],
        },
        "services": health, "gpus": _gpu_inventory(),
        "storage": {"available_bytes": storage.f_bavail * storage.f_frsize},
        "configuration": {
            "path": str(Path(config_path).resolve()), "sha256": file_hash(config_path),
            "router_timeout_seconds": config["services"]["client"].get("timeout_seconds"),
            "router_retry": config["services"]["client"].get("retry"),
            "sam3_server_url": config["services"]["tools"]["sam3_segment"]["server_url"],
            "checkpoint_identity": "facebook/sam3 (configured service; exact worker revision not exposed by health API)",
            "checkpoint_verified_by_worker": False, "serving_parameters_changed": False,
            "qwen_calls_required": False,
        },
        "resource_policy": {"existing_services_reused": True, "unrelated_jobs_stopped": False,
                            "driver_or_serving_configuration_changed": False},
    }
    atomic_json(output / "preflight_report.json", report)
    atomic_json(output / "sample_selection_manifest.json", selection)
    return report


def _canary_gate(run_dir, selection, destination):
    audit = build_pilot_audit(run_dir, selection)
    gate = {**validate_canary(run_dir, selection, dispatch_cap=160), "audit": audit}
    atomic_json(destination, gate)
    return gate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04b2b2"))
    parser.add_argument("--config", default="configs/agent/qwen3_8b_paper.yaml")
    parser.add_argument("--stage", choices=("preflight", "canary", "pilot", "audit"), required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-groups", type=int, default=20)
    parser.add_argument("--seed", type=int, default=417)
    args = parser.parse_args()
    load_dotenv(".env", override=False)
    output = args.output.resolve()
    for name in ("preflight", "canary", "pilot", "observations", "offline_labels", "audits", "validation"):
        (output / name).mkdir(parents=True, exist_ok=True)
    adapter = AquariumDatasetAdapter()
    selection = select_states(adapter, seed=args.seed, max_groups=args.max_groups, max_queries=2)
    config = load_agent_config(args.config)
    run_dir = output / "observations" / f"aquarium_task_v_seed{args.seed}_g{args.max_groups}"
    if args.stage == "audit":
        audit = build_pilot_audit(run_dir, selection)
        integrity = validate_run_directory(run_dir)
        print(json.dumps({"status": "SUCCESS", "stage": "audit", "audit": audit,
                          "integrity": integrity}, indent=2))
        return
    preflight = _preflight(output / "preflight", adapter, selection, args.config, config)
    if args.stage == "preflight":
        print(json.dumps({"status": "SUCCESS", "stage": "preflight", "report": preflight}, indent=2))
        return
    capabilities = build_capabilities(config)
    runner = TaskVBatchRunner(
        adapter=adapter, selection=selection, capabilities=capabilities, memory_config=config["memory"],
        run_dir=run_dir, collection_run_id=f"aquarium_task_v_seed{args.seed}_g{args.max_groups}",
        resume=args.resume, dispatch_cap=160, branch_budget=3, stage_evidence=True,
    )
    if args.stage == "canary":
        execution = runner.run(canary_only=True)
        gate = _canary_gate(run_dir, selection, output / "canary" / "canary_gate.json")
        atomic_json(output / "canary" / "execution.json", execution)
        if not gate["pass"]:
            raise SystemExit("Canary did not validate both required Task V branches; pilot stopped")
        print(json.dumps({"status": "SUCCESS", "stage": "canary", "execution": execution, "gate": gate}, indent=2))
        return
    gate_path = output / "canary" / "canary_gate.json"
    if not gate_path.is_file() or not json.loads(gate_path.read_text()).get("pass"):
        raise SystemExit("A passing two-group canary is required before pilot continuation")
    execution = runner.run(canary_only=False)
    atomic_json(output / "pilot" / "execution.json", execution)
    audit = build_pilot_audit(run_dir, selection, output_path=output / "audits" / "pilot_audit.json")
    export_pilot_tables(run_dir, output)
    integrity = validate_run_directory(run_dir)
    atomic_json(output / "validation" / "integrity_report_v2.json", integrity)
    print(json.dumps({"status": "SUCCESS", "stage": "pilot", "execution": execution, "audit": audit}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "FAILED", "error": type(error).__name__, "message": str(error)}), file=sys.stderr)
        raise

