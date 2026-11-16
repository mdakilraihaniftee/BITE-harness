"""Phase 4C-1G Protocol A: controlled fixed-decoder counting probe.

This is **not** a replay of the OpenVLHarness agent loop. The stored Task V
states come from controlled capability execution, and none of them carries an
agent conversation prefix. A fixed Qwen3-VL decoder answers one frozen counting
question per state under four evidence conditions:

* ``B0``: the original image and the recorded initial SAM 3 grounding;
* ``B1``: ``B0`` plus the recorded Zoom crop and focused SAM 3 grounding;
* ``B2``: ``B0`` plus the ``semantic_region_inspect_v1`` observation;
* ``B3``: ``B0`` plus Zoom, then the semantic observation (frozen order).

Everything here is GT-blind. Construction reads only ``initial_raw_state.json``,
GT-free branch records, stored image artifacts and the frozen 4C-1E semantic
manifest. Paths under ``offline_labels`` and similar folders are refused. The
official counts are joined only by ``task_level_branch_runner.build_count_labels``,
after the raw outcome table has been finalized and hashed.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from openvlharness.services.models import load_profile

from .semantic_observation_schema import (
    DATASET_CATEGORIES,
    ONTOLOGY,
    canonical_sha256,
)
from .semantic_pilot_protocol import (
    LOOPBACK_HOSTS,
    _guarded_read_json,
    _snapshot_image,
    verify_manifest,
)
from .semantic_region_action import MODEL_ALIAS
from .zoom_conditional_protocol import GT_MARKERS

TASK_VERSION = "bite.task_level_count_probe.v1"
MANIFEST_VERSION = "bite.phase04c1g_task_manifest.v1"
PROTOCOL_LABEL = "PROTOCOL_A_CONTROLLED_FIXED_DECODER_PROBE"
BRANCHES = ("B0", "B1", "B2", "B3")
BRANCH_EVIDENCE = {
    "B0": (),
    "B1": ("zoom",),
    "B2": ("semantic",),
    "B3": ("zoom", "semantic"),
}
INCREMENTAL_LOGICAL_COST = {"B0": 0, "B1": 2, "B2": 1, "B3": 3}
SINGLE_ACTION_BRANCHES = ("B0", "B1", "B2")
FINAL_ANSWER_OPTIONS = {"max_tokens": 128, "temperature": 0.0}
FINAL_ANSWER_SEED = 0
MAX_FINAL_ANSWER_DISPATCHES = len(BRANCHES) * 101
MAX_PHASE_DISPATCHES = 505
PRECALL_FEATURES = ("initial_score", "log_proposal_count", "top_box_relative_area", "score_gap")
FORBIDDEN_FEATURE_NAMES = frozenset({
    "source_group_id", "source_entry_id", "source_image_sha256", "state_id", "case_id",
    "official_count", "count", "zoom", "semantic", "oracle_branch",
})

SYSTEM_PROMPT = (
    "You are a careful visual assistant. You answer questions about photographs. "
    "Some tool results produced by automated vision tools may be provided. "
    "Tool results can be incomplete, duplicated or wrong; the photograph is the primary evidence."
)
QUESTION_TEMPLATE = "How many {query} objects are visible in this image?"
COMMON_HEADER_TEMPLATE = """Question: {question}

Category definition for this question: "{query}" means {definition}. The categories fish, jellyfish, penguin, puffin, shark, starfish and stingray are mutually exclusive; count only "{query}".

Image 1 is the full original photograph. The question is about Image 1."""
COMMON_FOOTER_TEMPLATE = """Instructions:
- Count every visible "{query}" in Image 1, including partly visible ones.
- Answer 0 if there is none.
- Answer with exactly one JSON object and nothing else, in this form: {{"count": <non-negative integer>}}"""
EVIDENCE_HEADER = "Tool results recorded before answering (in execution order):"

PROMPT_TEMPLATE = {
    "schema_version": "bite.task_level_count_prompt.v1",
    "system": SYSTEM_PROMPT,
    "question_template": QUESTION_TEMPLATE,
    "common_header_template": COMMON_HEADER_TEMPLATE,
    "common_footer_template": COMMON_FOOTER_TEMPLATE,
    "evidence_header": EVIDENCE_HEADER,
    "category_definitions_source": ONTOLOGY["schema_version"],
    "contains_reference_count": False,
    "contains_correctness_hint": False,
    "contains_branch_quality_hint": False,
    "abstention_offered": False,
    "decoding": {"options": FINAL_ANSWER_OPTIONS, "seed": FINAL_ANSWER_SEED},
}
PROMPT_SHA256 = canonical_sha256(PROMPT_TEMPLATE)

ANSWER_STATUSES = ("valid", "empty_response", "malformed", "schema_violation", "execution_failure", "timeout")
ANSWER_PARSER = {
    "schema_version": "bite.task_level_count_parser.v1",
    "accepted_forms": [
        'one JSON object with exactly the key "count" whose value is a non-negative JSON integer',
        "the same object wrapped in one Markdown code fence",
        "a bare non-negative integer (digits only, surrounding whitespace allowed)",
    ],
    "everything_else": "invalid; never repaired, never coerced",
    "booleans_and_floats_are_integers": False,
    "invalid_answer_loss": 1,
    "abstention": "not offered; any non-answer is an invalid answer",
    "presence_prediction": "parsed count > 0; undefined for invalid answers (counted as incorrect)",
}
PARSER_SHA256 = canonical_sha256(ANSWER_PARSER)
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
_BARE_INTEGER = re.compile(r"^[0-9]+$")


def question_for(query):
    if query not in DATASET_CATEGORIES:
        raise ValueError(f"Query is outside the frozen vocabulary: {query}")
    return QUESTION_TEMPLATE.format(query=query)


def common_header(query):
    return COMMON_HEADER_TEMPLATE.format(
        question=question_for(query), query=query, definition=ONTOLOGY["category_definitions"][query])


def common_footer(query):
    return COMMON_FOOTER_TEMPLATE.format(query=query)


def parse_count(text):
    """Return ``(status, count_or_None, detail)`` under the frozen parser."""
    if not isinstance(text, str) or not text.strip():
        return "empty_response", None, "no text content"
    body = text.strip()
    if _BARE_INTEGER.match(body):
        return "valid", int(body), "bare_integer"
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1)
    try:
        value = json.loads(body)
    except json.JSONDecodeError as error:
        return "malformed", None, f"json decode error at position {error.pos}"
    if not isinstance(value, dict):
        return "schema_violation", None, "top-level value is not an object"
    if set(value) != {"count"}:
        return "schema_violation", None, f"keys={sorted(value)}"
    count = value["count"]
    if type(count) is not int or count < 0:
        return "schema_violation", None, "count is not a non-negative integer"
    return "valid", count, "json_object"


# --------------------------------------------------------------------------- cases

def _proposals(canonical):
    boxes = canonical.get("boxes") or []
    scores = canonical.get("scores") or []
    if len(boxes) != len(scores):
        raise ValueError("Grounding boxes and scores differ in length")
    return [{"rank": index, "box_xyxy": [float(v) for v in box], "score": float(score)}
            for index, (box, score) in enumerate(zip(boxes, scores))]


def _apply_transform(matrix, box):
    (a, b, tx), (c, d, ty), _ = matrix
    if b != 0 or c != 0:
        raise ValueError("Only axis-aligned crop transforms are supported")
    x0, y0, x1, y1 = box
    return [a * x0 + tx, d * y0 + ty, a * x1 + tx, d * y1 + ty]


def _zoom_evidence(state_dir, record):
    """GT-free Zoom→focused evidence from the stored branch record (never rebuilt)."""
    matches = []
    for path in sorted((state_dir / "raw_collection/branches").glob("*.json")):
        branch = _guarded_read_json(path)
        steps = branch.get("selected_path") or []
        if [step.get("action_template") for step in steps] == ["crop_generation", "focused_grounding"]:
            matches.append((path, branch))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one stored Zoom branch for {record['state_id']}")
    path, branch = matches[0]
    if branch.get("offline_gt_used") is not False:
        raise ValueError("Zoom branch does not certify GT-free construction")
    crop_step, focus_step = branch["selected_path"]
    crop_obs, focus_obs = branch["observations"][0], branch["observations"][1]
    if crop_obs["capability"] != "Zoom_In_Tool" or focus_obs["capability"] != "Visual_Grounding_Tool":
        raise ValueError("Unexpected Zoom branch capabilities")
    if crop_step.get("region_evidence_id") != record["selected_candidate"]["candidate_id"]:
        raise ValueError("Zoom crop is not anchored to the selected candidate")
    evidence = {
        "branch_id": branch["branch_id"],
        "branch_record_path": str(path),
        "branch_status": branch["status"],
        "crop": {
            "capability": crop_obs["capability"],
            "backend": crop_obs["backend"],
            "arguments": crop_step["arguments"],
            "success": bool(crop_obs["success"]),
            "outcome_category": (crop_obs.get("outcome") or {}).get("category"),
            "error": crop_obs.get("error"),
            "latency_ms": crop_step.get("latency_ms"),
            "observation_id": crop_obs["joint_observation_id"],
            "crop_rectangle_root_xyxy": None,
            "child_to_root_transform": None,
            "crop_width": None,
            "crop_height": None,
            "crop_image_sha256": None,
            "crop_image_path": None,
        },
        "focused": {
            "capability": focus_obs["capability"],
            "backend": focus_obs["backend"],
            "arguments": focus_step["arguments"],
            "success": bool(focus_obs["success"]),
            "outcome_category": (focus_obs.get("outcome") or {}).get("category"),
            "error": focus_obs.get("error"),
            "latency_ms": focus_step.get("latency_ms"),
            "observation_id": focus_obs["joint_observation_id"],
            "proposals_crop_frame": [],
            "proposals_root_frame": [],
        },
    }
    crop = crop_obs.get("crop")
    if crop_obs["success"] and crop:
        sha = focus_obs["source_image"]["sha256"]
        image = state_dir / f"raw_collection/observations/artifacts/{sha}.png"
        if not image.is_file():
            raise ValueError(f"Stored crop artifact missing for {record['state_id']}")
        evidence["crop"].update({
            "crop_rectangle_root_xyxy": crop["crop_rectangle_parent_xyxy"],
            "child_to_root_transform": crop["child_to_root_transform"],
            "crop_width": crop["child_width"],
            "crop_height": crop["child_height"],
            "crop_image_sha256": sha,
            "crop_image_path": str(image),
        })
    if focus_obs["success"]:
        proposals = _proposals(focus_obs["canonical_result"])
        transform = focus_obs["source_frame"]["child_to_root_transform"]
        evidence["focused"]["proposals_crop_frame"] = proposals
        evidence["focused"]["proposals_root_frame"] = [
            {**p, "box_xyxy": _apply_transform(transform, p["box_xyxy"])} for p in proposals]
    return evidence


def precall_features(record):
    """Small GT-free feature vector available before any additional action."""
    prefix = record["prefix_observation"]
    proposals = _proposals(prefix["canonical_result"])
    if not proposals:
        raise ValueError("Candidate-present state without proposals")
    width, height = prefix["root_image"]["width"], prefix["root_image"]["height"]
    selected = record["selected_candidate"]
    scores = sorted((p["score"] for p in proposals), reverse=True)
    x0, y0, x1, y1 = selected["bbox_root_xyxy"]
    return {
        "initial_score": float(selected["raw_scores"][0]),
        "log_proposal_count": math.log(len(proposals)),
        "top_box_relative_area": max(0.0, x1 - x0) * max(0.0, y1 - y0) / (width * height),
        "score_gap": scores[0] - scores[1] if len(scores) > 1 else scores[0],
    }


def build_task(case, state_dir, record, *, root):
    """One counting task from a frozen semantic-pilot case and its stored state."""
    if record["state_id"] != case["state_id"] or record["query"] != case["query"]:
        raise ValueError("Frozen semantic case does not match its stored state")
    if record["selected_candidate"]["candidate_id"] != case["original_candidate_id"]:
        raise ValueError("Frozen case candidate differs from the stored selected candidate")
    root = Path(root).resolve()
    prefix = record["prefix_observation"]
    image_path = _snapshot_image(state_dir, record["source_image_sha256"])
    zoom = _zoom_evidence(state_dir, record)

    def relative(path):
        return str(Path(path).resolve().relative_to(root)) if path else None

    zoom["branch_record_path"] = relative(zoom["branch_record_path"])
    zoom["crop"]["crop_image_path"] = relative(zoom["crop"]["crop_image_path"])
    task = {
        "task_id": "count_task:" + canonical_sha256([TASK_VERSION, record["state_id"], record["query"]]),
        "task_version": TASK_VERSION,
        "semantic_case_id": case["case_id"],
        "state_id": record["state_id"],
        "source_group_id": record["source_group_id"],
        "source_entry_id": record["source_entry_id"],
        "partition": record["partition"],
        "query": record["query"],
        "question": question_for(record["query"]),
        "source_image_sha256": record["source_image_sha256"],
        "source_image_path": relative(image_path),
        "image_width": prefix["root_image"]["width"],
        "image_height": prefix["root_image"]["height"],
        "initial_grounding": {
            "capability": prefix["capability"],
            "backend": prefix["backend"],
            "arguments": record["prefix_action"]["arguments"],
            "success": bool(prefix["success"]),
            "observation_id": prefix["joint_observation_id"],
            "latency_ms": prefix.get("latency_ms"),
            "proposals": _proposals(prefix["canonical_result"]),
            "selected_detector_rank": record["selected_detector_rank"],
            "selected_candidate_id": record["selected_candidate"]["candidate_id"],
            "selected_candidate_box_root_xyxy": record["selected_candidate"]["bbox_root_xyxy"],
        },
        "zoom": zoom,
        "semantic_region_render_sha256": case["region_render_sha256"],
        "precall_features": precall_features(record),
    }
    return task


def _leaked_keys(value):
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in GT_MARKERS:
                found.add(key)
            found |= _leaked_keys(child)
    elif isinstance(value, list):
        for child in value:
            found |= _leaked_keys(child)
    return found


def build_task_manifest(semantic_manifest, *, root, run_dir, semantic_manifest_path, renderer_contract):
    """Freeze the 101 counting tasks; never reads labels or model outputs."""
    verify_manifest(semantic_manifest)
    root = Path(root)
    tasks = []
    for case in semantic_manifest["cases"]:
        state_dir = root / run_dir / "states" / case["state_id"].replace(":", "_")
        record = _guarded_read_json(state_dir / "initial_raw_state.json")
        if record.get("offline_gt_used") is not False:
            raise ValueError("Initial state does not certify GT-free construction")
        tasks.append(build_task(case, state_dir, record, root=root))
    leaked = _leaked_keys(tasks)
    if leaked:
        raise ValueError(f"GT marker keys in task manifest: {sorted(leaked)}")
    groups = sorted({task["source_group_id"] for task in tasks})
    manifest = {
        "schema_version": MANIFEST_VERSION,
        "status": "FROZEN_NOT_EXECUTED",
        "protocol": PROTOCOL_LABEL,
        "genuine_agent_continuation": False,
        "task_version": TASK_VERSION,
        "population": {
            "source": "Phase 4C-1E frozen semantic pilot (seed 465, 15 calibration-fit groups)",
            "semantic_manifest_path": semantic_manifest_path,
            "semantic_manifest_sha256": semantic_manifest["manifest_sha256"],
            "in_group_initial_states": semantic_manifest["in_group_initial_state_count"],
            "excluded_no_candidate_state_ids": semantic_manifest["excluded_no_candidate_state_ids"],
            "task_count": len(tasks),
            "source_group_count": len(groups),
            "selected_source_groups": groups,
            "resampled_by_label_or_performance": False,
            "independent_held_out_validation": False,
        },
        "branches": {b: {"evidence": list(BRANCH_EVIDENCE[b]), "incremental_logical_cost": INCREMENTAL_LOGICAL_COST[b]}
                     for b in BRANCHES},
        "prompt_sha256": PROMPT_SHA256,
        "parser_sha256": PARSER_SHA256,
        "renderer_sha256": renderer_contract["renderer_sha256"],
        "model_alias": MODEL_ALIAS,
        "final_answer_options": FINAL_ANSWER_OPTIONS,
        "final_answer_seed": FINAL_ANSWER_SEED,
        "precall_feature_names": list(PRECALL_FEATURES),
        "tasks": tasks,
    }
    manifest["manifest_sha256"] = canonical_sha256({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    return manifest


def verify_task_manifest(manifest):
    expected = canonical_sha256({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    if manifest.get("manifest_sha256") != expected:
        raise ValueError("Task manifest digest mismatch")
    if manifest["prompt_sha256"] != PROMPT_SHA256 or manifest["parser_sha256"] != PARSER_SHA256:
        raise ValueError("Prompt or parser changed after the task manifest was frozen")
    if _leaked_keys(manifest["tasks"]):
        raise ValueError("Task manifest carries GT marker keys")
    if len({task["task_id"] for task in manifest["tasks"]}) != len(manifest["tasks"]):
        raise ValueError("Duplicate task ids")
    return manifest


# ------------------------------------------------------------------ authorization

AUTHORIZATION_REQUIRED_KEYS = (
    "live_final_answer_inference_authorized", "authorized_by", "task_manifest_sha256", "prompt_sha256",
    "parser_sha256", "renderer_sha256", "semantic_manifest_sha256", "model_alias", "model_id", "endpoint",
    "branches", "output_dir", "semantic_run_dir", "dispatch_cap", "phase_total_dispatch_cap", "valid_until_utc",
)


def validate_branch_authorization(authorization, manifest, adapter, output_dir, *, root, now=None):
    """A researcher-written record must bind every element of the live run."""
    if not isinstance(authorization, dict):
        raise PermissionError("Live final-answer inference requires an authorization record")
    missing = [key for key in AUTHORIZATION_REQUIRED_KEYS if key not in authorization]
    if missing:
        raise PermissionError(f"Authorization is missing {missing}")
    if authorization["live_final_answer_inference_authorized"] is not True:
        raise PermissionError("Authorization does not approve live final-answer inference")
    if not isinstance(authorization["authorized_by"], str) or not authorization["authorized_by"].strip():
        raise PermissionError("Authorization must name the approving researcher")
    if authorization["authorized_by"].strip().lower() in {"claude", "claude code", "coding agent", "assistant"}:
        raise PermissionError("The coding agent cannot approve its own live execution")
    expected = {
        "task_manifest_sha256": manifest["manifest_sha256"],
        "prompt_sha256": PROMPT_SHA256,
        "parser_sha256": PARSER_SHA256,
        "renderer_sha256": manifest["renderer_sha256"],
        "semantic_manifest_sha256": manifest["population"]["semantic_manifest_sha256"],
        "model_alias": MODEL_ALIAS,
        "model_id": load_profile(MODEL_ALIAS)["model_id"],
    }
    for key, value in expected.items():
        if authorization[key] != value:
            raise PermissionError(f"Authorization does not approve {key}")
    if adapter.model != expected["model_id"]:
        raise PermissionError("Adapter model differs from the authorized model id")
    if authorization["endpoint"] != adapter.endpoint:
        raise PermissionError("Adapter endpoint differs from the authorized endpoint")
    if urlparse(adapter.endpoint).hostname not in LOOPBACK_HOSTS and (
            authorization.get("non_loopback_endpoint_approved") is not True):
        raise PermissionError("Non-loopback inference endpoint requires explicit approval")
    branches = authorization["branches"]
    if (not isinstance(branches, list) or not branches or len(set(branches)) != len(branches)
            or not set(branches) <= set(BRANCHES)):
        raise PermissionError("Authorization branch set is invalid")
    if (Path(root) / str(authorization["output_dir"])).resolve() != Path(output_dir).resolve():
        raise PermissionError("Run directory differs from the authorized output directory")
    cap = authorization["dispatch_cap"]
    limit = len(branches) * len(manifest["tasks"])
    if type(cap) is not int or not 0 < cap <= limit:
        raise PermissionError(f"Authorization dispatch cap must be an integer in 1..{limit}")
    total = authorization["phase_total_dispatch_cap"]
    if type(total) is not int or not cap <= total <= MAX_PHASE_DISPATCHES:
        raise PermissionError(f"Phase total dispatch cap must be an integer in {cap}..{MAX_PHASE_DISPATCHES}")
    try:
        deadline = datetime.fromisoformat(authorization["valid_until_utc"])
    except (TypeError, ValueError) as error:
        raise PermissionError("valid_until_utc must be an ISO-8601 timestamp with timezone") from error
    if deadline.tzinfo is None:
        raise PermissionError("valid_until_utc must carry a timezone")
    if (now or datetime.now(timezone.utc)) > deadline:
        raise PermissionError("Authorization execution window has expired")
    return {"dispatch_cap": cap, "phase_total_dispatch_cap": total, "branches": list(branches)}


def authorization_requirements(manifest, *, endpoint, output_dir, semantic_run_dir, renderer_sha256):
    return {
        "schema_version": "bite.phase04c1g_authorization_requirements.v1",
        "must_be_written_by": "the researcher; the coding agent does not create or approve authorizations",
        "protocol": PROTOCOL_LABEL,
        "required_fields": {
            "live_final_answer_inference_authorized": True,
            "authorized_by": "<researcher name>",
            "task_manifest_sha256": manifest["manifest_sha256"],
            "prompt_sha256": PROMPT_SHA256,
            "parser_sha256": PARSER_SHA256,
            "renderer_sha256": renderer_sha256,
            "semantic_manifest_sha256": manifest["population"]["semantic_manifest_sha256"],
            "model_alias": MODEL_ALIAS,
            "model_id": load_profile(MODEL_ALIAS)["model_id"],
            "endpoint": endpoint,
            "branches": list(BRANCHES),
            "output_dir": output_dir,
            "semantic_run_dir": semantic_run_dir,
            "dispatch_cap": f"integer 1..{len(BRANCHES) * len(manifest['tasks'])} (final answers; cumulative incl. canary)",
            "phase_total_dispatch_cap": (f"integer dispatch_cap..{MAX_PHASE_DISPATCHES} "
                                         "(semantic observations + final answers, cumulative)"),
            "valid_until_utc": "ISO-8601 with timezone; runner refuses after this time",
        },
        "optional_fields": {
            "non_loopback_endpoint_approved": "true only if the endpoint is not loopback",
        },
    }
