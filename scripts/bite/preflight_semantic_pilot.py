#!/usr/bin/env python3
"""Phase 4C-1F offline preflight: frozen-pilot integrity, backend readiness and the
authorization gate. Contacts no model service, sends no image, reads no label."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from tokenizers import Tokenizer

from evaluation_kit.bite_calibration.semantic_observation_schema import (
    ONTOLOGY_SHA256,
    PROMPT_SHA256,
)
from evaluation_kit.bite_calibration.semantic_pilot_preflight import (
    measured_zoom_costs,
    prompt_text,
    request_estimate,
    verify_frozen_pilot,
)
from evaluation_kit.bite_calibration.semantic_pilot_protocol import (
    CANARY_MAX_CASES,
    CONSECUTIVE_FAILURE_LIMIT,
    LOOPBACK_HOSTS,
)
from evaluation_kit.bite_calibration.semantic_region_action import (
    INFERENCE_OPTIONS,
    INFERENCE_SEED,
    MODEL_ALIAS,
    build_adapter,
)
from evaluation_kit.bite_calibration.zoom_conditional_protocol import (
    file_sha256,
    read_jsonl,
)
from evaluation_kit.bite_collection.persistence import atomic_json
from openvlharness.services.models import load_profile

ROOT = Path(__file__).resolve().parents[2]
PHASE04C1E = ROOT / "outputs/bite/phase04c1e"
RUN_DIR = "outputs/bite/phase04b2b3/expansion/aquarium_task_v_expansion_seed418_g30"
RUNTIME_TABLE = ROOT / "outputs/bite/phase04c1d/runtime_features/expansion_runtime_features_v1.jsonl"
QWEN_CACHE = ROOT / ".cache/huggingface/hub/models--Qwen--Qwen3-VL-8B-Instruct"
PINNED_REVISION = "0c351dd01ed87e9c1b53cbc748cba10e6187ff3b"
LIVE_OUTPUT_DIR = "outputs/bite/phase04c1f/raw_observations/semantic_pilot_run"


def _relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def _run(command):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=30, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _dotenv():
    values = {}
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text().splitlines():
            match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line.strip())
            if match:
                values[match.group(1)] = match.group(2).strip().strip("'\"")
    return values


def _artifact_identity():
    inventory = json.loads((PHASE04C1E / "manifest_checksums.json").read_text())["artifact_sha256"]
    files = {}
    for name in ("semantic_pilot_manifest/manifest.json", "semantic_pilot_manifest/paired_comparison_design.json",
                 "semantic_action/contract.json", "execution_readiness/semantic_pilot_execution_plan.json"):
        relative = _relative(PHASE04C1E / name)
        actual = file_sha256(ROOT / relative)
        files[relative] = {"sha256": actual, "phase04c1e_inventory_sha256": inventory[relative],
                           "unchanged": actual == inventory[relative]}
    return {"schema_version": "bite.phase04c1f_frozen_artifact_identity.v1",
            "all_unchanged": all(entry["unchanged"] for entry in files.values()), "files": files}


def _launch_configuration():
    text = (ROOT / "scripts/service.sh").read_text()
    block = text.split("qwen)", 1)[1].split(";;", 1)[0]
    flags = {name: value or True for name, value in re.findall(
        r"--([a-z0-9-]+)(?:[ \t]+(?!--)('[^']*'|\"[^\"]*\"|[^\s\\]+))?", block)}
    return {"source": "scripts/service.sh qwen", "flags": flags,
            "hf_hub_offline": "HF_HUB_OFFLINE=1" in text}


def _weights(verify):
    refs = (QWEN_CACHE / "refs/main").read_text().strip() if (QWEN_CACHE / "refs/main").is_file() else None
    snapshot = QWEN_CACHE / "snapshots" / PINNED_REVISION
    result = {"pinned_revision": PINNED_REVISION, "refs_main": refs, "refs_main_matches_pin": refs == PINNED_REVISION,
              "snapshot_present": snapshot.is_dir(), "weight_files": {}}
    for path in sorted(snapshot.glob("*.safetensors")):
        blob = path.resolve()
        entry = {"blob": blob.name, "bytes": blob.stat().st_size}
        if verify:
            digest = hashlib.sha256()
            with blob.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1 << 24), b""):
                    digest.update(chunk)
            entry["sha256"] = digest.hexdigest()
            entry["matches_lfs_blob_name"] = entry["sha256"] == blob.name
        result["weight_files"][path.name] = entry
    for name in ("generation_config.json", "preprocessor_config.json", "config.json"):
        result[f"{name}_sha256"] = file_sha256(snapshot / name)
    result["generation_defaults"] = json.loads((snapshot / "generation_config.json").read_text())
    result["preprocessor"] = json.loads((snapshot / "preprocessor_config.json").read_text())
    result["status"] = "CACHE_CONTENT_VERIFIED_ONLY" if verify else "CACHE_REFERENCE_ONLY"
    result["load_time_identity"] = "UNVERIFIED: no server running; OpenAI-compatible endpoint exposes no weight digest"
    return result


def _backend(env, weights):
    profile = load_profile(MODEL_ALIAS)
    base = env.get("MODEL_BASE_URL", "")
    endpoint = build_adapter(base).endpoint if base else None
    parsed = urlparse(base) if base else None
    port = parsed.port if parsed else None
    listening = bool(port) and bool(re.search(rf":{port}\b", _run(["ss", "-ltn"])))
    processes = [line.strip()[:160] for line in _run(["ps", "-eo", "pid,args"]).splitlines()
                 if re.search(r"vllm|cloudflared|ngrok", line) and "grep" not in line]
    gpus = [line.strip() for line in _run([
        "nvidia-smi", "--query-gpu=index,name,memory.total,memory.used", "--format=csv,noheader"]).splitlines() if line]
    usage = shutil.disk_usage(ROOT)
    launch = _launch_configuration()
    return {
        "schema_version": "bite.phase04c1f_backend_readiness.v1",
        "model_alias": MODEL_ALIAS,
        "configured_model_id": profile["model_id"],
        "protocol": profile["adapter"],
        "served_model_name_in_launch_script": launch["flags"].get("served-model-name"),
        "inference_options": INFERENCE_OPTIONS,
        "seed": INFERENCE_SEED,
        "adapter_timeout_seconds": inspect.signature(build_adapter).parameters["timeout"].default,
        "adapter_transport_retries": 0,
        "retry_policy": "no automatic retry; failures recorded and counted against the cap",
        "consecutive_failure_halt": CONSECUTIVE_FAILURE_LIMIT,
        "canary_max_cases": CANARY_MAX_CASES,
        "greedy_decoding": INFERENCE_OPTIONS["temperature"] == 0.0,
        "sampling_defaults_inert_under_greedy": ["top_k", "top_p", "temperature"],
        "endpoint": {
            "source": ".env MODEL_BASE_URL (value read for host only; key never read into outputs)",
            "configured": bool(base),
            "resolved_chat_completions_url": endpoint,
            "host": parsed.hostname if parsed else None,
            "port": port,
            "loopback": bool(parsed) and parsed.hostname in LOOPBACK_HOSTS,
            "api_key_configured": bool(env.get("MODEL_API_KEY")),
            "port_listening": listening,
        },
        "service_running": listening and any("vllm" in line for line in processes),
        "launch_configuration": launch,
        "qwen_context_length_env": env.get("QWEN_CONTEXT_LENGTH") or None,
        "gpus": gpus,
        "relevant_processes": processes,
        "public_tunnel_processes_present": any(re.search(r"cloudflared|ngrok", line) for line in processes),
        "semantic_action_uses_image_host_or_tunnel": False,
        "image_transport": "inline base64 in the request body to the authorized endpoint only",
        "disk_free_bytes": usage.free,
        "weights": weights,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/bite/phase04c1f")
    parser.add_argument("--skip-weight-hash", action="store_true")
    args = parser.parse_args()
    output = args.output
    identity = _artifact_identity()
    atomic_json(output / "preflight/frozen_artifact_identity.json", identity)
    manifest = json.loads((PHASE04C1E / "semantic_pilot_manifest/manifest.json").read_text())
    selection = json.loads((ROOT / RUN_DIR / "sample_selection_manifest.json").read_text())
    report, case_rows = verify_frozen_pilot(
        manifest, root=ROOT, run_dir=RUN_DIR, selection=selection, runtime_rows=read_jsonl(RUNTIME_TABLE))
    report["frozen_artifacts_unchanged"] = identity["all_unchanged"]
    atomic_json(output / "preflight/pilot_integrity.json", report)
    path = output / "preflight/case_identity.jsonl"
    with path.open("w") as stream:
        for row in case_rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")

    weights = _weights(verify=not args.skip_weight_hash)
    backend = _backend(_dotenv(), weights)
    atomic_json(output / "preflight/backend_readiness.json", backend)
    tokenizer = Tokenizer.from_file(str(QWEN_CACHE / "snapshots" / PINNED_REVISION / "tokenizer.json"))
    pixels = weights["preprocessor"]["size"]
    max_len = int(backend["qwen_context_length_env"] or
                  re.search(r"(\d+)", backend["launch_configuration"]["flags"].get("max-model-len", "168000")).group(1))
    estimate = request_estimate(
        case_rows, min_pixels=pixels["shortest_edge"], max_pixels=pixels["longest_edge"],
        prompt_tokens=len(tokenizer.encode(prompt_text()).ids),
        max_output_tokens=INFERENCE_OPTIONS["max_tokens"], max_model_len=max_len)
    estimate["phase04c1e_estimate_superseded"] = manifest["resource_estimate"]
    atomic_json(output / "preflight/request_estimate.json", estimate)
    pilot_states = {case["state_id"] for case in manifest["cases"]}
    atomic_json(output / "preflight/zoom_measured_costs.json", {
        "schema_version": "bite.zoom_measured_costs.v1",
        "all_expansion_states": measured_zoom_costs(ROOT, RUN_DIR),
        "semantic_pilot_states": measured_zoom_costs(ROOT, RUN_DIR, pilot_states),
    })

    candidates = sorted((output / "authorization").glob("*.json"))
    found = [p for p in candidates if p.name not in {"status.json", "authorization_requirements.json"}]
    requirements = {
        "schema_version": "bite.phase04c1f_authorization_requirements.v1",
        "must_be_written_by": "the researcher; the coding agent does not create or approve authorizations",
        "required_fields": {
            "live_semantic_inference_authorized": True,
            "authorized_by": "<researcher name>",
            "manifest_sha256": manifest["manifest_sha256"],
            "prompt_sha256": PROMPT_SHA256,
            "ontology_sha256": ONTOLOGY_SHA256,
            "model_alias": MODEL_ALIAS,
            "model_id": backend["configured_model_id"],
            "endpoint": backend["endpoint"]["resolved_chat_completions_url"],
            "output_dir": LIVE_OUTPUT_DIR,
            "dispatch_cap": f"integer 1..{manifest['case_count']} (cumulative, includes canary)",
        },
        "optional_fields": {
            "valid_until_utc": "ISO-8601 with timezone; runner refuses after this time",
            "non_loopback_endpoint_approved": "must be true only if the endpoint is not loopback",
        },
        "commands": {
            "start_service (researcher-operated)": "bash scripts/service.sh qwen",
            "canary": (f"MODEL_BASE_URL=<base> .venv/bin/python scripts/bite/run_semantic_verification_pilot.py "
                       f"--mode live --authorization <file> --output {LIVE_OUTPUT_DIR} --canary 5"),
            "continue": (f"MODEL_BASE_URL=<base> .venv/bin/python scripts/bite/run_semantic_verification_pilot.py "
                         f"--mode live --authorization <file> --output {LIVE_OUTPUT_DIR} --resume"),
            "analyze": ".venv/bin/python scripts/bite/analyze_semantic_pilot.py",
        },
    }
    atomic_json(output / "authorization/authorization_requirements.json", requirements)
    status = {
        "schema_version": "bite.phase04c1f_authorization_status.v1",
        "status": "AUTHORIZATION_PRESENT_UNVALIDATED" if found else "AUTHORIZATION_ABSENT",
        "searched": _relative(output / "authorization"),
        "files_found": [_relative(p) for p in found],
        "live_inference_executed": False,
        "vlm_calls": 0,
    }
    atomic_json(output / "authorization/status.json", status)
    print(json.dumps({"integrity": report["status"], "failed": report["failed_checks"],
                      "frozen_artifacts_unchanged": identity["all_unchanged"],
                      "service_running": backend["service_running"],
                      "endpoint": backend["endpoint"], "weights_status": weights["status"],
                      "weights_match": {k: v.get("matches_lfs_blob_name") for k, v in weights["weight_files"].items()},
                      "estimate": estimate, "authorization": status["status"]}, indent=2))


if __name__ == "__main__":
    main()
