"""Offline Phase 4C-1F preflight for the frozen semantic-verification pilot.

Re-derives every frozen case from its stored collection state, re-renders every
model input, reproduces the GT-blind group selection, checks scoped identities and
original raw-before-GT provenance, and estimates request size with the processor
resize rule. Nothing here contacts a model service or reads offline labels.
"""

from __future__ import annotations

import base64
import math
import statistics
from collections import Counter
from pathlib import Path

from evaluation_kit.bite_collection.integrity import validate_stage_events

from .semantic_comparison_design import design_record
from .semantic_observation_schema import (
    ONTOLOGY_SHA256,
    PROMPT_SHA256,
    SYSTEM_PROMPT,
    USER_PROMPT,
    canonical_sha256,
)
from .semantic_pilot_protocol import (
    _guarded_read_json,
    build_case,
    load_initial_states,
    scoped_identity,
    select_groups,
    verify_manifest,
)
from .semantic_region_action import CASE_FIELDS, render_region, validate_case
from .zoom_conditional_protocol import GT_MARKERS

PREFLIGHT_VERSION = "bite.semantic_pilot_preflight.v1"
QWEN3_VL_RESIZE_FACTOR = 32
CHATML_OVERHEAD_TOKENS = 32


def smart_resize_tokens(width, height, *, min_pixels, max_pixels, factor=QWEN3_VL_RESIZE_FACTOR):
    """Visual tokens for one image under the Qwen-VL smart-resize rule (estimate:
    the server's own processor settings are authoritative)."""
    h_bar = max(factor, round(height / factor) * factor)
    w_bar = max(factor, round(width / factor) * factor)
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt(height * width / max_pixels)
        h_bar = max(factor, math.floor(height / beta / factor) * factor)
        w_bar = max(factor, math.floor(width / beta / factor) * factor)
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor
    return (h_bar // factor) * (w_bar // factor)


def verify_frozen_pilot(manifest, *, root, run_dir, selection, runtime_rows):
    """Return ``(report, case_rows)``; raise on any frozen-identity violation."""
    verify_manifest(manifest)
    root = Path(root)
    checks = {}
    cohort = selection["selected_source_groups"]
    checks["source_cohort_matches_selection_manifest"] = manifest["source_cohort"] == selection["cohort_id"]
    checks["group_selection_reproduced"] = (
        select_groups(cohort, count=manifest["selection"]["group_count"], seed=manifest["selection"]["seed"])
        == manifest["selected_source_groups"]
    )
    states = load_initial_states(root / run_dir)
    by_state = {record["state_id"]: (state_dir, record) for state_dir, record in states}
    in_groups = [r for _, r in states if r["source_group_id"] in set(manifest["selected_source_groups"])]
    no_candidate = sorted(r["state_id"] for r in in_groups if r["no_candidate_state"] or not r["candidate_usable"])
    checks["in_group_state_count_matches"] = len(in_groups) == manifest["in_group_initial_state_count"]
    checks["no_candidate_states_match"] = no_candidate == manifest["excluded_no_candidate_state_ids"]
    checks["no_candidate_state_dispatched"] = bool(set(no_candidate) & {c["state_id"] for c in manifest["cases"]})
    runtime = {row["state_id"]: row for row in runtime_rows}
    case_rows = []
    provenance_failures = []
    for case in manifest["cases"]:
        validate_case(case)
        state_dir, record = by_state[case["state_id"]]
        rebuilt = build_case(state_dir, record, root=root)
        frozen = {key: value for key, value in case.items() if key != "region_render_sha256"}
        if rebuilt != frozen:
            raise ValueError(f"Frozen case differs from its stored state: {case['state_id']}")
        images, render = render_region(root / case["source_image_path"], case["candidate_bbox_root_xyxy"],
                                       expected_sha256=case["source_image_sha256"])
        if render["render_sha256"] != case["region_render_sha256"]:
            raise ValueError(f"Rendered input digest changed: {case['state_id']}")
        events = validate_stage_events(state_dir / "stage_events.jsonl", state_dir=state_dir)
        if not events["valid"]:
            provenance_failures.append({"state_id": case["state_id"], "reason": events["reason"]})
        score = record["selected_candidate"]["raw_scores"][0]
        zoom_row = runtime[case["state_id"]]
        if zoom_row["initial_score"] != score or zoom_row["query"] != case["query"]:
            raise ValueError(f"Initial score or query disagrees with the 4C-1D runtime table: {case['state_id']}")
        case_rows.append({
            "schema_version": "bite.semantic_pilot_case_identity.v1",
            "scoped_identity": scoped_identity(manifest, case),
            "case_id": case["case_id"],
            "source_group_id": case["source_group_id"],
            "query": case["query"],
            "initial_score": score,
            "initial_score_sent_to_model": False,
            "source_image_sha256": case["source_image_sha256"],
            "candidate_bbox_root_xyxy": case["candidate_bbox_root_xyxy"],
            "region_render_sha256": render["render_sha256"],
            "rendered_image_sha256": render["image_sha256"],
            "rendered_image_sizes": render["image_sizes"],
            "request_image_base64_bytes": sum(
                len(base64.b64encode(entry["png"])) for entry in images.values()),
            "initial_observation_id": case["initial_observation_id"],
            "parent_snapshot_id": case["parent_snapshot_id"],
            "original_collection_raw_before_gt_valid": events["valid"],
        })
    checks["all_cases_rebuilt_from_stored_states"] = True
    checks["all_render_digests_reproduced"] = True
    checks["original_raw_before_gt_chain_valid"] = not provenance_failures
    keys = [canonical_sha256(row["scoped_identity"]) for row in case_rows]
    candidate_ids = Counter(case["original_candidate_id"] for case in manifest["cases"])
    checks["state_ids_unique"] = len({c["state_id"] for c in manifest["cases"]}) == len(manifest["cases"])
    checks["case_ids_unique"] = len({c["case_id"] for c in manifest["cases"]}) == len(manifest["cases"])
    checks["scoped_identities_unique"] = len(set(keys)) == len(keys)
    checks["case_fields_within_runtime_whitelist"] = all(set(c) <= CASE_FIELDS for c in manifest["cases"])
    leaked = GT_MARKERS & {key.lower() for case in manifest["cases"] for key in case}
    checks["no_gt_marker_in_cases"] = not leaked
    checks["all_cases_calibration_fit"] = all(c["partition"] == "calibration_fit" for c in manifest["cases"])
    checks["prompt_digest_matches_module"] = manifest["frozen_contract"]["prompt_sha256"] == PROMPT_SHA256
    checks["ontology_digest_matches_module"] = manifest["frozen_contract"]["ontology_sha256"] == ONTOLOGY_SHA256
    failed = sorted(name for name, ok in checks.items() if not ok and name != "no_candidate_state_dispatched")
    if checks["no_candidate_state_dispatched"]:
        failed.append("no_candidate_state_dispatched")
    report = {
        "schema_version": PREFLIGHT_VERSION,
        "status": "PASS" if not failed else "FAIL",
        "failed_checks": failed,
        "checks": checks,
        "manifest_sha256": manifest["manifest_sha256"],
        "prompt_sha256": PROMPT_SHA256,
        "ontology_sha256": ONTOLOGY_SHA256,
        "design_sha256": design_record()["design_sha256"],
        "selected_source_groups": manifest["selected_source_groups"],
        "source_group_count": len(manifest["selected_source_groups"]),
        "in_group_initial_states": len(in_groups),
        "no_candidate_state_ids": no_candidate,
        "case_count": len(case_rows),
        "provenance_failures": provenance_failures,
        "identifier_safety": {
            "distinct_local_candidate_ids": len(candidate_ids),
            "cases_sharing_a_local_candidate_id": sum(n for n in candidate_ids.values() if n > 1),
            "candidate_id_alone_is_a_safe_join_key": len(candidate_ids) == len(manifest["cases"]),
            "scoped_identity": ["source_run_id", "state_id", "candidate_id", "action_version"],
            "label_join_key": ["state_id", "candidate_id"],
        },
        "offline_labels_accessed": False,
        "model_service_contacted": False,
    }
    return report, case_rows


def request_estimate(case_rows, *, min_pixels, max_pixels, prompt_tokens, max_output_tokens, max_model_len):
    visual = [
        sum(smart_resize_tokens(w, h, min_pixels=min_pixels, max_pixels=max_pixels)
            for w, h in row["rendered_image_sizes"].values())
        for row in case_rows
    ]
    per_request_max = max(visual) + prompt_tokens + CHATML_OVERHEAD_TOKENS + max_output_tokens
    return {
        "method": "Qwen-VL smart resize (factor 32) with the cached processor min/max pixels; estimate only",
        "requests": len(case_rows),
        "visual_tokens_total": sum(visual),
        "visual_tokens_per_request_min": min(visual),
        "visual_tokens_per_request_max": max(visual),
        "text_prompt_tokens_per_request": prompt_tokens + CHATML_OVERHEAD_TOKENS,
        "text_input_tokens_total": (prompt_tokens + CHATML_OVERHEAD_TOKENS) * len(case_rows),
        "output_tokens_cap_total": max_output_tokens * len(case_rows),
        "largest_request_tokens_upper_estimate": per_request_max,
        "max_model_len": max_model_len,
        "fits_context": per_request_max < max_model_len,
        "largest_request_image_base64_bytes": max(row["request_image_base64_bytes"] for row in case_rows),
        "total_image_base64_bytes": sum(row["request_image_base64_bytes"] for row in case_rows),
    }


def _latency_summary(values):
    values = sorted(values)
    if not values:
        return {"count": 0}
    return {"count": len(values), "median_ms": statistics.median(values),
            "p90_ms": values[min(len(values) - 1, int(0.9 * len(values)))],
            "maximum_ms": values[-1], "total_ms": sum(values)}


def measured_zoom_costs(root, run_dir, state_ids=None):
    """Client-side wall-clock latencies recorded during the 4B-2B-3 collection
    (GT-free branch records only): initial grounding and Zoom crop + focused SAM 3."""
    initial, crop, focused, total = [], [], [], []
    for state_dir, record in load_initial_states(Path(root) / run_dir):
        if state_ids is not None and record["state_id"] not in state_ids:
            continue
        initial.append(record["prefix_observation"]["latency_ms"])
        for path in sorted((state_dir / "raw_collection/branches").glob("*.json")):
            branch = _guarded_read_json(path)
            steps = branch.get("selected_path") or []
            if [step.get("action_template") for step in steps] != ["crop_generation", "focused_grounding"]:
                continue
            crop.append(steps[0]["latency_ms"])
            focused.append(steps[1]["latency_ms"])
            total.append(steps[0]["latency_ms"] + steps[1]["latency_ms"])
    return {
        "source": "client-side latency_ms recorded in Phase 4B-2B-3 collection records",
        "initial_sam3_grounding": _latency_summary(initial),
        "zoom_crop_local": _latency_summary(crop),
        "zoom_focused_sam3": _latency_summary(focused),
        "zoom_total_two_dispatches": _latency_summary(total),
        "gpu_time_measured": False,
        "comparable_to_future_vlm_latency": "only approximately: different service, load and date",
    }


def prompt_text():
    return SYSTEM_PROMPT + "\n" + USER_PROMPT
