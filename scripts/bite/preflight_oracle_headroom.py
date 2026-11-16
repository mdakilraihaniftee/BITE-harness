#!/usr/bin/env python3
"""Phase 4C-1G offline preflight (no model calls, no labels).

* verifies the frozen task manifest and its sources;
* records backend, GPU, storage and process readiness (reusing the 4C-1F probes);
* estimates request sizes for every branch;
* records the authorization status of both gates (4C-1F semantic pilot and 4C-1G
  final answers) and writes the 4C-1G authorization requirements;
* runs a mock B0/B1 contract run over all 101 frozen inputs with a local
  requester. That run writes nothing under raw_continuations/ and opens no labels.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from pathlib import Path

from tokenizers import Tokenizer

from evaluation_kit.bite_calibration.branch_evidence_renderer import (
    RENDERER_SHA256,
    render_branch,
)
from evaluation_kit.bite_calibration.semantic_pilot_preflight import smart_resize_tokens
from evaluation_kit.bite_calibration.semantic_pilot_protocol import (
    mock_requester,
    verify_manifest,
)
from evaluation_kit.bite_calibration.task_level_branch_runner import (
    build_adapter,
    finalize_outcomes,
    run_branches,
    semantic_dispatch_count,
)
from evaluation_kit.bite_calibration.task_level_probe_protocol import (
    FINAL_ANSWER_OPTIONS,
    MAX_PHASE_DISPATCHES,
    SYSTEM_PROMPT,
    authorization_requirements,
    verify_task_manifest,
)
from evaluation_kit.bite_calibration.zoom_conditional_protocol import file_sha256
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
PHASE = ROOT / "outputs/bite/phase04c1g"
PHASE04C1F = ROOT / "outputs/bite/phase04c1f"
SEMANTIC_MANIFEST = "outputs/bite/phase04c1e/semantic_pilot_manifest/manifest.json"
SEMANTIC_RUN = "outputs/bite/phase04c1f/raw_observations/semantic_pilot_run"
LIVE_RUN = "outputs/bite/phase04c1g/raw_continuations/branch_run"
SEMANTIC_BLOCK_CHARACTER_ALLOWANCE = 600


def _load_4c1f_preflight():
    spec = importlib.util.spec_from_file_location("preflight_4c1f", ROOT / "scripts/bite/preflight_semantic_pilot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _authorization_status(directory, ignore):
    found = sorted(p for p in Path(directory).glob("*.json") if p.name not in ignore) if Path(directory).is_dir() else []
    return {"searched": str(Path(directory).relative_to(ROOT)), "files_found": [str(p.relative_to(ROOT)) for p in found],
            "status": "AUTHORIZATION_PRESENT_UNVALIDATED" if found else "AUTHORIZATION_ABSENT"}


def _estimate(manifest, tokenizer, pixels):
    per_branch = {}
    for branch in ("B0", "B1"):
        visual, text = [], []
        for task in manifest["tasks"]:
            messages, record = render_branch(task, branch, root=ROOT)
            sizes = [(task["image_width"], task["image_height"])]
            if record["image_count"] == 2:
                sizes.append((task["zoom"]["crop"]["crop_width"], task["zoom"]["crop"]["crop_height"]))
            visual.append(sum(smart_resize_tokens(w, h, min_pixels=pixels["shortest_edge"],
                                                  max_pixels=pixels["longest_edge"]) for w, h in sizes))
            body = SYSTEM_PROMPT + "".join(p["text"] for p in messages[1]["content"] if p["type"] == "text")
            text.append(len(tokenizer.encode(body).ids))
        per_branch[branch] = {"visual_tokens_total": sum(visual), "visual_tokens_max": max(visual),
                              "text_tokens_total": sum(text), "text_tokens_max": max(text)}
    allowance = SEMANTIC_BLOCK_CHARACTER_ALLOWANCE // 3
    per_branch["B2"] = {k: v + (allowance * len(manifest["tasks"]) if "total" in k and "text" in k else
                                allowance if "text_tokens_max" == k else 0)
                        for k, v in per_branch["B0"].items()}
    per_branch["B3"] = {k: v + (allowance * len(manifest["tasks"]) if "total" in k and "text" in k else
                                allowance if "text_tokens_max" == k else 0)
                        for k, v in per_branch["B1"].items()}
    largest = max(v["visual_tokens_max"] + v["text_tokens_max"] for v in per_branch.values())
    return {
        "method": "Qwen-VL smart resize (factor 32) + cached tokenizer on the rendered text; B2/B3 add an "
                  f"allowance of {allowance} text tokens for the semantic block (outputs not yet available)",
        "per_branch": per_branch,
        "output_tokens_cap_per_request": FINAL_ANSWER_OPTIONS["max_tokens"],
        "largest_request_tokens_upper_estimate": largest + FINAL_ANSWER_OPTIONS["max_tokens"] + 64,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-mock-run", action="store_true")
    args = parser.parse_args()
    legacy = _load_4c1f_preflight()
    manifest = verify_task_manifest(json.loads((PHASE / "task_manifest/task_manifest.json").read_text()))
    semantic_manifest = verify_manifest(json.loads((ROOT / SEMANTIC_MANIFEST).read_text()))
    inventory = json.loads((ROOT / "outputs/bite/phase04c1e/manifest_checksums.json").read_text())["artifact_sha256"]
    identity = {
        "schema_version": "bite.phase04c1g_input_identity.v1",
        "task_manifest_sha256": manifest["manifest_sha256"],
        "semantic_manifest_file_sha256": file_sha256(ROOT / SEMANTIC_MANIFEST),
        "semantic_manifest_matches_phase04c1e_inventory": file_sha256(ROOT / SEMANTIC_MANIFEST) == inventory[SEMANTIC_MANIFEST],
        "semantic_manifest_sha256": semantic_manifest["manifest_sha256"],
        "phase04c1f_preflight_status": json.loads((PHASE04C1F / "preflight/pilot_integrity.json").read_text())["status"],
        "tasks": len(manifest["tasks"]),
        "source_groups": manifest["population"]["source_group_count"],
        "zoom_branches_complete": sum(t["zoom"]["branch_status"] == "complete" for t in manifest["tasks"]),
        "zoom_crops_present": sum(bool(t["zoom"]["crop"]["crop_image_path"]) for t in manifest["tasks"]),
        "focused_grounding_success": sum(t["zoom"]["focused"]["success"] for t in manifest["tasks"]),
        "genuine_agent_prefixes_available": False,
        "genuine_agent_prefix_reason": ("stored Task V states were produced by controlled capability execution "
                                        "(origin=controlled_collection_action); no agent conversation, model turns "
                                        "or tool-call messages were recorded, so Protocol B is not reconstructible"),
        "offline_labels_accessed": False,
    }
    atomic_json(PHASE / "preflight/input_identity.json", identity)

    weights = legacy._weights(verify=False)
    weights["content_verification"] = "reused from Phase 4C-1F backend_readiness.json (all 4 shards matched)"
    backend = legacy._backend(legacy._dotenv(), weights)
    backend["schema_version"] = "bite.phase04c1g_backend_readiness.v1"
    backend["final_answer_options"] = FINAL_ANSWER_OPTIONS
    backend["image_transport"] = "inline base64 to the authorized loopback endpoint only; no image host or tunnel"
    backend["cloudflared_used_by_experiment"] = False
    backend["disk_free_bytes"] = shutil.disk_usage(ROOT).free
    atomic_json(PHASE / "preflight/backend_readiness.json", backend)

    snapshot = legacy.QWEN_CACHE / "snapshots" / legacy.PINNED_REVISION
    estimate = _estimate(manifest, Tokenizer.from_file(str(snapshot / "tokenizer.json")), weights["preprocessor"]["size"])
    atomic_json(PHASE / "preflight/request_estimate.json", estimate)

    semantic_dir = ROOT / SEMANTIC_RUN
    budget = {
        "schema_version": "bite.phase04c1g_dispatch_budget.v1",
        "semantic_observations_required": len(semantic_manifest["cases"]),
        "semantic_observations_dispatched_so_far": semantic_dispatch_count(semantic_dir),
        "final_answers_required": 4 * len(manifest["tasks"]),
        "phase_total_cap": MAX_PHASE_DISPATCHES,
        "shared_across": ["semantic canary", "semantic main", "final-answer canary", "final-answer main", "resumes"],
        "retries": "none automatic; every attempt counts",
    }
    atomic_json(PHASE / "preflight/dispatch_budget.json", budget)

    endpoint = backend["endpoint"]["resolved_chat_completions_url"]
    requirements = authorization_requirements(manifest, endpoint=endpoint, output_dir=LIVE_RUN,
                                              semantic_run_dir=SEMANTIC_RUN, renderer_sha256=RENDERER_SHA256)
    requirements["prerequisite"] = ("B2/B3 need the Phase 4C-1F semantic pilot to be complete and live, under its own "
                                    "researcher-written authorization (outputs/bite/phase04c1f/authorization/"
                                    "authorization_requirements.json; dispatch_cap 101)")
    requirements["commands"] = {
        "1_start_service (researcher-operated)": "bash scripts/service.sh qwen",
        "2_semantic_canary": ("MODEL_BASE_URL=http://127.0.0.1:8222/v1 .venv/bin/python scripts/bite/"
                              "run_semantic_verification_pilot.py --mode live --authorization <4c1f_auth.json> "
                              f"--output {SEMANTIC_RUN} --canary 5"),
        "3_semantic_continue": ("MODEL_BASE_URL=http://127.0.0.1:8222/v1 .venv/bin/python scripts/bite/"
                                "run_semantic_verification_pilot.py --mode live --authorization <4c1f_auth.json> "
                                f"--output {SEMANTIC_RUN} --resume"),
        "4_branch_canary": ("MODEL_BASE_URL=http://127.0.0.1:8222/v1 .venv/bin/python scripts/bite/"
                            "run_oracle_headroom_branches.py --mode live --authorization <4c1g_auth.json> "
                            f"--output {LIVE_RUN} --canary 5"),
        "5_branch_continue": ("MODEL_BASE_URL=http://127.0.0.1:8222/v1 .venv/bin/python scripts/bite/"
                              "run_oracle_headroom_branches.py --mode live --authorization <4c1g_auth.json> "
                              f"--output {LIVE_RUN} --resume"),
        "6_analyze": ".venv/bin/python scripts/bite/analyze_oracle_headroom.py",
        "7_readiness_and_manifest": (".venv/bin/python scripts/bite/assess_phase04c1g_readiness.py && "
                                     ".venv/bin/python scripts/bite/build_phase04c1g_manifest.py"),
    }
    atomic_json(PHASE / "authorization/authorization_requirements.json", requirements)
    status = {
        "schema_version": "bite.phase04c1g_authorization_status.v1",
        "phase04c1f_semantic_gate": _authorization_status(
            PHASE04C1F / "authorization", {"status.json", "authorization_requirements.json"}),
        "phase04c1g_final_answer_gate": _authorization_status(
            PHASE / "authorization", {"status.json", "authorization_requirements.json"}),
        "authorizations_written_by_coding_agent": 0,
        "live_inference_executed": False,
        "vlm_calls": 0,
    }
    atomic_json(PHASE / "authorization/status.json", status)

    mock = None
    if not args.skip_mock_run:
        run = PHASE / "preflight/mock_contract_run"
        final = PHASE / "preflight/mock_contract_finalized"
        if run.exists() or final.exists():
            raise SystemExit("Mock contract run already exists; it is immutable")
        adapter = build_adapter("http://mock.invalid/v1", requester=mock_requester(lambda i, p: '{"count": 0}'))
        summary = run_branches(manifest, adapter, run, root=ROOT, mode="mock_dry_run", branches=["B0", "B1"])
        record, _ = finalize_outcomes(manifest, run, final, branches=("B0", "B1"), require_live=False)
        mock = {"dispatched_to_local_mock": summary["dispatched"], "statuses": summary["statuses"],
                "finalized_rows": record["row_count"], "table_sha256": record["table_sha256"],
                "labels_joined": False, "network_requests": 0}
        atomic_json(PHASE / "preflight/mock_contract_report.json", mock)
    print(json.dumps({"identity": identity, "service_running": backend["service_running"],
                      "endpoint": backend["endpoint"], "estimate": estimate, "budget": budget,
                      "authorization": status, "mock": mock}, indent=2))


if __name__ == "__main__":
    main()
