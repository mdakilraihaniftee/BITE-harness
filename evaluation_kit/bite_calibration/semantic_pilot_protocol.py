"""GT-blind manifest and gated, resumable runner for the semantic-verification pilot.

Case construction reads only ``initial_raw_state.json`` and the snapshot image
artifact of each stored expansion state. Offline-label directories and any
prediction/label artifact are refused by path. Live execution requires an
authorization record bound to the exact manifest digest; dry runs require an
adapter with an injected local requester.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from evaluation_kit.bite_collection.integrity import StageEventLedger
from evaluation_kit.bite_collection.persistence import atomic_json
from evaluation_kit.bite_collection.resume import ResumeLedger, file_digest
from openvlharness.services.models import load_profile

from .semantic_observation_schema import (
    ACTION_NAME,
    DATASET_CATEGORIES,
    ONTOLOGY_SHA256,
    PROMPT_SHA256,
    SYSTEM_PROMPT,
    USER_PROMPT,
    canonical_sha256,
)
from .semantic_region_action import (
    INFERENCE_OPTIONS,
    INFERENCE_SEED,
    MODEL_ALIAS,
    inspect_region,
    render_region,
    validate_case,
)

MANIFEST_VERSION = "bite.semantic_pilot_manifest.v1"
PILOT_SEED = 465
PILOT_GROUP_COUNT = 15
PILOT_DISPATCH_CAP = 105
FORBIDDEN_PATH_PARTS = ("offline_labels", "human_adjudications", "crossfit", "internal_test")
QWEN_PIXELS_PER_VISUAL_TOKEN = 32 * 32
ESTIMATED_TEXT_INPUT_TOKENS_PER_CASE = 700
CANARY_MAX_CASES = 5
CONSECUTIVE_FAILURE_LIMIT = 3
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def _guarded_read_json(path):
    parts = Path(path).parts
    if any(marker in part for part in parts for marker in FORBIDDEN_PATH_PARTS):
        raise PermissionError(f"GT-blind pilot construction refused path: {path}")
    return json.loads(Path(path).read_text())


def load_initial_states(run_dir):
    states = []
    for state_dir in sorted((Path(run_dir) / "states").iterdir()):
        record = _guarded_read_json(state_dir / "initial_raw_state.json")
        if record.get("offline_gt_used") is not False:
            raise ValueError("Initial state does not certify GT-free construction")
        states.append((state_dir, record))
    return states


def _snapshot_image(state_dir, image_sha256):
    matches = sorted((state_dir / "raw_collection/snapshots/artifacts").glob(f"{image_sha256}.*"))
    if len(matches) != 1:
        raise ValueError(f"Expected one stored source image for {image_sha256}")
    if file_digest(matches[0]) != image_sha256:
        raise ValueError("Stored source image digest mismatch")
    return matches[0]


def build_case(state_dir, record, *, root):
    candidate = record["selected_candidate"]
    if candidate["candidate_id"] != record["prefix_observation"]["candidate_ids"][record["selected_detector_rank"]]:
        raise ValueError("Selected candidate does not match its detector rank")
    prefix = record["prefix_observation"]
    image = prefix["root_image"]
    path = _snapshot_image(state_dir, record["source_image_sha256"])
    case = {
        "case_id": "semantic_case:" + hashlib.sha256(
            f"{ACTION_NAME}:{record['state_id']}:{candidate['candidate_id']}".encode()).hexdigest(),
        "state_id": record["state_id"],
        "source_group_id": record["source_group_id"],
        "source_entry_id": record["source_entry_id"],
        "partition": record["partition"],
        "query": record["query"],
        "source_image_sha256": record["source_image_sha256"],
        "source_image_path": str(path.resolve().relative_to(Path(root).resolve())),
        "image_width": image["width"],
        "image_height": image["height"],
        "original_candidate_id": candidate["candidate_id"],
        "candidate_bbox_root_xyxy": candidate["bbox_root_xyxy"],
        "initial_observation_id": prefix["joint_observation_id"],
        "initial_controlled_call_id": prefix["controlled_call_id"],
        "initial_action_id": prefix["action_id"],
        "parent_snapshot_id": record["parent_snapshot_id"],
    }
    return case


def select_groups(groups, *, count=PILOT_GROUP_COUNT, seed=PILOT_SEED):
    ordered = sorted(set(groups))
    if count > len(ordered):
        raise ValueError("Requested more pilot groups than available")
    return sorted(random.Random(seed).sample(ordered, count))


def apply_dispatch_cap(cases, *, cap=PILOT_DISPATCH_CAP, seed=PILOT_SEED):
    """GT-blind cap: keep the cases with the lowest sha256(seed:state_id)."""
    if len(cases) <= cap:
        return sorted(cases, key=lambda case: case["state_id"]), []
    ranked = sorted(cases, key=lambda case: hashlib.sha256(f"{seed}:{case['state_id']}".encode()).hexdigest())
    return sorted(ranked[:cap], key=lambda case: case["state_id"]), sorted(case["state_id"] for case in ranked[cap:])


def _visual_tokens(width, height):
    return math.ceil(width / 32) * math.ceil(height / 32)


def build_manifest(run_dir, *, root, expansion_protocol, cohort_groups, seed=PILOT_SEED,
                   group_count=PILOT_GROUP_COUNT, cap=PILOT_DISPATCH_CAP):
    states = load_initial_states(Path(root) / run_dir)
    if {record["source_group_id"] for _, record in states} != set(cohort_groups):
        raise ValueError("Stored expansion states do not match the frozen 30-group cohort")
    if any(record["partition"] != "calibration_fit" for _, record in states):
        raise ValueError("Non-fit state found in the expansion cohort")
    selected = select_groups(cohort_groups, count=group_count, seed=seed)
    in_groups = [(d, r) for d, r in states if r["source_group_id"] in selected]
    no_candidate = sorted(r["state_id"] for _, r in in_groups if r["no_candidate_state"] or not r["candidate_usable"])
    cases = [build_case(d, r, root=root) for d, r in in_groups
             if r["candidate_usable"] and not r["no_candidate_state"]]
    cases, capped_out = apply_dispatch_cap(cases, cap=cap, seed=seed)
    estimates = []
    for case in cases:
        validate_case(case)
        _, render = render_region(Path(root) / case["source_image_path"], case["candidate_bbox_root_xyxy"],
                                  expected_sha256=case["source_image_sha256"])
        case["region_render_sha256"] = render["render_sha256"]
        estimates.append(sum(_visual_tokens(*size) for size in render["image_sizes"].values()))
    manifest = {
        "schema_version": MANIFEST_VERSION,
        "status": "FROZEN_NOT_EXECUTED",
        "action_name": ACTION_NAME,
        "partition": "calibration_fit",
        "source_cohort": expansion_protocol["cohort_id"],
        "source_cohort_group_count": len(cohort_groups),
        "selection": {
            "unit": "source_group",
            "rule": "python random.Random(seed).sample over sorted 30 expansion group ids",
            "seed": seed,
            "group_count": group_count,
            "uses_ground_truth": False,
            "uses_model_performance": False,
            "uses_phase04c1a_label_balanced_folds": False,
            "inclusion_probability_per_group": group_count / len(cohort_groups),
        },
        "selected_source_groups": selected,
        "in_group_initial_state_count": len(in_groups),
        "excluded_no_candidate_state_ids": no_candidate,
        "dispatch_cap": cap,
        "cap_rule": "if cases exceed cap keep lowest sha256(seed:state_id); GT-blind",
        "capped_out_state_ids": capped_out,
        "case_count": len(cases),
        "cases": cases,
        "frozen_contract": {
            "prompt_sha256": PROMPT_SHA256,
            "ontology_sha256": ONTOLOGY_SHA256,
            "model_alias": MODEL_ALIAS,
            "inference_options": INFERENCE_OPTIONS,
            "seed": INFERENCE_SEED,
        },
        "resource_estimate": {
            "logical_dispatches": len(cases),
            "physical_requests": len(cases),
            "estimated_visual_input_tokens_total": sum(estimates),
            "estimated_text_input_tokens_total": ESTIMATED_TEXT_INPUT_TOKENS_PER_CASE * len(cases),
            "maximum_output_tokens_total": INFERENCE_OPTIONS["max_tokens"] * len(cases),
            "visual_token_rule": "ceil(w/32)*ceil(h/32) per image (Qwen3-VL 16px patches, 2x2 merge); estimate only",
            "prompt_characters": len(SYSTEM_PROMPT) + len(USER_PROMPT),
            "gpu_time_measured": False,
            "monetary_cost_measured": False,
        },
        "validation_or_internal_test_cases": 0,
        "new_sam3_calls_required": 0,
    }
    if any(case["query"] not in DATASET_CATEGORIES for case in cases):
        raise ValueError("Pilot query outside the frozen vocabulary")
    manifest["manifest_sha256"] = canonical_sha256({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    return manifest


def verify_manifest(manifest):
    expected = canonical_sha256({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    if manifest.get("manifest_sha256") != expected:
        raise ValueError("Pilot manifest digest mismatch")
    if manifest["frozen_contract"]["prompt_sha256"] != PROMPT_SHA256:
        raise ValueError("Prompt changed after the pilot manifest was frozen")
    if manifest["frozen_contract"]["ontology_sha256"] != ONTOLOGY_SHA256:
        raise ValueError("Ontology changed after the pilot manifest was frozen")
    if len(manifest["cases"]) > manifest["dispatch_cap"]:
        raise ValueError("Manifest exceeds its dispatch cap")
    return manifest


def validate_authorization(authorization, manifest):
    """Live execution requires an explicit record bound to this manifest."""
    if not isinstance(authorization, dict):
        raise PermissionError("Live semantic inference requires an authorization record")
    required = {
        "live_semantic_inference_authorized": True,
        "manifest_sha256": manifest["manifest_sha256"],
        "prompt_sha256": PROMPT_SHA256,
        "model_alias": MODEL_ALIAS,
    }
    for key, value in required.items():
        if authorization.get(key) != value:
            raise PermissionError(f"Authorization does not approve {key}")
    if not isinstance(authorization.get("authorized_by"), str) or not authorization["authorized_by"].strip():
        raise PermissionError("Authorization must name the approving researcher")
    cap = authorization.get("dispatch_cap")
    if type(cap) is not int or not 0 < cap <= manifest["dispatch_cap"]:
        raise PermissionError("Authorization dispatch cap is missing or exceeds the manifest cap")
    return cap


def validate_live_binding(authorization, manifest, adapter, output_dir, *, root, now=None):
    """Phase 4C-1F binding: the authorization must also name the ontology, the exact
    model id and endpoint, the run directory, and a cap within the frozen case count.
    Non-loopback endpoints need an explicit, separate approval field."""
    cap = validate_authorization(authorization, manifest)
    model_id = load_profile(MODEL_ALIAS)["model_id"]
    if authorization.get("ontology_sha256") != ONTOLOGY_SHA256:
        raise PermissionError("Authorization does not approve ontology_sha256")
    if authorization.get("model_id") != model_id or adapter.model != model_id:
        raise PermissionError("Authorization or adapter does not match the frozen model id")
    if authorization.get("endpoint") != adapter.endpoint:
        raise PermissionError("Adapter endpoint differs from the authorized endpoint")
    if urlparse(adapter.endpoint).hostname not in LOOPBACK_HOSTS and (
            authorization.get("non_loopback_endpoint_approved") is not True):
        raise PermissionError("Non-loopback inference endpoint requires explicit approval")
    authorized_dir = (Path(root) / str(authorization.get("output_dir", ""))).resolve()
    if not authorization.get("output_dir") or authorized_dir != Path(output_dir).resolve():
        raise PermissionError("Run directory differs from the authorized output directory")
    if cap > manifest["case_count"]:
        raise PermissionError("Authorization dispatch cap exceeds the frozen case count")
    if authorization.get("valid_until_utc") is not None:
        deadline = datetime.fromisoformat(authorization["valid_until_utc"])
        if (now or datetime.now(timezone.utc)) > deadline:
            raise PermissionError("Authorization execution window has expired")
    return cap


def _case_status(ledger, case):
    state_dir = ledger.state_dir(case["case_id"])
    marker = state_dir / "raw_completion.json"
    if not marker.is_file():
        return "partial" if state_dir.exists() and any(state_dir.iterdir()) else "pending"
    record = json.loads(marker.read_text())
    if record.get("configuration_sha256") != ledger.config_digest:
        return "corrupt"
    for relative, expected in record["content_sha256"].items():
        path = state_dir / relative
        if not path.is_file() or file_digest(path) != expected:
            return "corrupt"
    return "complete"


def run_pilot(manifest, adapter, output_dir, *, root, mode, authorization=None, resume=False,
              max_new_dispatches=None, run_phase="main"):
    """Dispatch each pending case once. ``mode`` is ``mock_dry_run`` or ``live``.

    The dispatch cap is cumulative over every invocation on ``output_dir``: completed
    and partial case directories both count, so a canary plus later resumes can never
    exceed it. ``max_new_dispatches`` additionally limits this invocation (canary).
    The run halts after ``CONSECUTIVE_FAILURE_LIMIT`` consecutive timeouts or execution
    failures, and in live mode when the server reports a different model.
    """
    verify_manifest(manifest)
    if run_phase not in {"canary", "main"}:
        raise ValueError(f"Unknown run phase: {run_phase}")
    if run_phase == "canary" and not (isinstance(max_new_dispatches, int) and 0 < max_new_dispatches <= CANARY_MAX_CASES):
        raise ValueError(f"A canary must dispatch between 1 and {CANARY_MAX_CASES} cases")
    authorization_digest = None
    if mode == "mock_dry_run":
        if adapter.requester is None:
            raise PermissionError("Dry run requires an injected local requester; refusing a network client")
        cap = manifest["dispatch_cap"]
    elif mode == "live":
        cap = validate_live_binding(authorization, manifest, adapter, output_dir, root=root)
        authorization_digest = canonical_sha256(authorization)
    else:
        raise ValueError(f"Unknown pilot mode: {mode}")
    configuration = {
        "schema_version": "bite.semantic_pilot_run.v1",
        "mode": mode,
        "manifest_sha256": manifest["manifest_sha256"],
        "prompt_sha256": PROMPT_SHA256,
        "ontology_sha256": ONTOLOGY_SHA256,
        "model_id": adapter.model,
        "endpoint_host": adapter.endpoint.split("/")[2],
        "inference_options": INFERENCE_OPTIONS,
        "seed": INFERENCE_SEED,
        "dispatch_cap": cap,
    }
    if mode == "live":
        configuration["authorization_sha256"] = authorization_digest
        configuration["endpoint"] = adapter.endpoint
    ledger = ResumeLedger(output_dir, configuration, resume=resume)
    statuses = {case["case_id"]: _case_status(ledger, case) for case in manifest["cases"]}
    blocked = sorted(case_id for case_id, status in statuses.items() if status in {"partial", "corrupt"})
    if blocked:
        raise RuntimeError(f"Case {blocked[0]} is {statuses[blocked[0]]}; inspect before any new execution")
    prior = sum(status == "complete" for status in statuses.values())
    budget = cap - prior
    if max_new_dispatches is not None:
        budget = min(budget, max_new_dispatches)
    dispatched = 0
    consecutive_failures = 0
    summary = {"complete_before_run": prior, "dispatched": 0, "skipped_cap": 0, "statuses": {},
               "run_phase": run_phase, "cumulative_dispatch_cap": cap}
    for case in manifest["cases"]:
        if statuses[case["case_id"]] == "complete":
            continue
        if dispatched >= budget:
            summary["skipped_cap"] += 1
            continue
        state_dir = ledger.state_dir(case["case_id"])
        events = StageEventLedger(state_dir / "stage_events.jsonl")
        events.append("runtime_started", {"case_id": case["case_id"], "mode": mode,
                                          "run_phase": run_phase, "authorization_sha256": authorization_digest})
        absolute = {**case, "source_image_path": str(Path(root) / case["source_image_path"])}
        started = datetime.now(timezone.utc).isoformat()
        observation, response = inspect_region(absolute, adapter, mock=mode == "mock_dry_run")
        observation["lineage"]["source_image_path"] = case["source_image_path"]
        observation["execution_context"] = {
            "mode": mode,
            "run_phase": run_phase,
            "authorization_sha256": authorization_digest,
            "started_utc": started,
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "cumulative_dispatch_index": prior + dispatched,
            "scoped_identity": scoped_identity(manifest, case),
        }
        dispatched += 1
        observation_path = state_dir / "semantic_observation.json"
        response_path = state_dir / "raw_response.json"
        atomic_json(response_path, {"schema_version": "bite.semantic_raw_response.v1", "response": response})
        atomic_json(observation_path, observation)
        raw = ledger.mark_raw(case["case_id"], [observation_path, response_path], {
            "mode": mode, "response_status": observation["response_status"],
            "observation_id": observation["observation_id"],
        })
        events.append("raw_finalized", {"raw_completion_sha256": file_digest(state_dir / "raw_completion.json"),
                                        "content_sha256": raw["content_sha256"]})
        summary["statuses"][observation["response_status"]] = summary["statuses"].get(observation["response_status"], 0) + 1
        served = observation["backend"]["served_model_reported"]
        if mode == "live" and served is not None and served != adapter.model:
            _halt(output_dir, summary, dispatched, ledger, f"server reported model {served!r}, not {adapter.model!r}")
        failed = observation["response_status"] in {"timeout", "execution_failure"}
        consecutive_failures = consecutive_failures + 1 if failed else 0
        if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
            _halt(output_dir, summary, dispatched, ledger,
                  f"{consecutive_failures} consecutive timeouts or execution failures")
    summary["dispatched"] = dispatched
    summary["configuration_sha256"] = ledger.config_digest
    summary["offline_labels_accessed"] = False
    atomic_json(Path(output_dir) / "run_summary.json", summary)
    return summary


def _halt(output_dir, summary, dispatched, ledger, reason):
    summary.update(dispatched=dispatched, configuration_sha256=ledger.config_digest,
                   offline_labels_accessed=False, halted=True, halt_reason=reason)
    atomic_json(Path(output_dir) / "run_summary.json", summary)
    raise RuntimeError(f"Pilot halted after persisting the current case: {reason}")


def scoped_identity(manifest, case):
    """Globally safe key: collection candidate ids are only unique within a state."""
    return {
        "source_run_id": manifest.get("source_cohort"),
        "state_id": case["state_id"],
        "candidate_id": case["original_candidate_id"],
        "action_version": ACTION_NAME,
    }


def mock_requester(respond):
    """Local requester for dry runs. ``respond(call_index, payload)`` returns response
    text or raises; no network is touched."""
    calls = []

    def requester(payload):
        calls.append(payload)
        text = respond(len(calls) - 1, payload)
        return {
            "model": "mock-no-model",
            "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    requester.calls = calls
    return requester


def collect_observations(output_dir):
    return [
        json.loads(path.read_text())
        for path in sorted(Path(output_dir).glob("states/*/semantic_observation.json"))
    ]
