"""Frozen Task V/Task D protocol and scientific leakage checks."""

from __future__ import annotations

import copy
import json
import re

from jsonschema import validate


PROTOCOL_VERSION = "bite.calibration_protocol.v1"
_FORBIDDEN_RUNTIME = re.compile(r"(^gt($|_)|ground_truth|annotation|official_tp|geometric_valid|best_eligible|iou_with_gt)", re.I)

PROTOCOL_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "additionalProperties": False,
    "required": ["schema_version", "status", "original_task", "tasks", "sampling", "initial_state", "action_paths", "budget", "failure_policy", "selection_design", "model_identity", "persistence", "resource_plan", "phase_boundary"],
    "properties": {
        "schema_version": {"const": PROTOCOL_VERSION}, "status": {"enum": ["FROZEN_SOURCE_PENDING", "FROZEN_READY"]},
        "original_task": {"type": "object"}, "tasks": {"type": "object", "required": ["candidate_verification", "object_discovery"]},
        "sampling": {"type": "object"}, "initial_state": {"type": "object"}, "action_paths": {"type": "array", "minItems": 1},
        "budget": {"type": "object"}, "failure_policy": {"type": "object"}, "selection_design": {"type": "object"},
        "model_identity": {"type": "object"}, "persistence": {"type": "object"}, "resource_plan": {"type": "object"},
        "phase_boundary": {"const": "Do not start Phase 4B-2B or fit probabilities under this task."},
    },
}


def default_protocol(*, source_ready=False):
    return {
        "schema_version": PROTOCOL_VERSION,
        "status": "FROZEN_READY" if source_ready else "FROZEN_SOURCE_PENDING",
        "original_task": {
            "supported_dataset_family": ["ODinW-13", "separately approved COCO-format detection source"],
            "permitted_classes": "source manifest class vocabulary only", "selected_hypothesis_tasks": ["candidate_verification", "object_discovery"],
            "iou_endpoints": [0.5, 0.75], "root_frame": "original decoded image pixel xyxy; crops map through exact integer translations",
            "final_evaluation_loss": {"primary": "Brier score per endpoint", "secondary": ["log loss", "group-aware calibration error"], "official_detection_metric_unchanged": True},
        },
        "tasks": {
            "candidate_verification": {
                "symbol": "H_V", "unit": "one retained proposal at one declared threshold",
                "positive_event": "same intended class and overlap with an eligible non-ignore non-crowd annotated instance at or above threshold",
                "negative_event": "matchable proposal fails the positive event",
                "unknown_event": "unknown frame/class mapping, invalid geometry, ignored/crowd-only compatibility, or unavailable annotation eligibility",
                "thresholds": [0.5, 0.75], "primary_loss": "Brier score", "secondary_losses": ["log loss", "group-aware calibration error"],
            },
            "object_discovery": {
                "symbol": "H_D", "unit": "prespecified root-image region and intended class",
                "positive_event": "at least one eligible intended-class GT instance intersects the region under the declared center-in-region rule and was not represented before the action",
                "negative_event": "region/class is exhaustively annotated and no eligible unrepresented instance satisfies the rule",
                "unknown_event": "class/region not exhaustively annotated, frame invalid, or prior representation ambiguous",
                "region_rule": "fixed_2x2_root_grid_center_membership_v1", "primary_loss": "Brier score", "secondary_losses": ["log loss", "source-group-aware recall of novel instances"],
            },
        },
        "sampling": {
            "source_unit": "source_group_id", "partition_manifest_required": True,
            "query_schedule": "sort source-declared class vocabulary; choose two classes by sha256(source_group_id + class + seed), without reading per-image annotations",
            "query_seed": 417, "queries_per_image": 2, "retain_empty_and_negative_pairs": True,
            "debug_exclusions": ["PascalVOC_val_262", "sha256:a18039d3edc2c8ae46fb2b8347318c79f91f5643c3811181d366ed4a4403e1b5"],
        },
        "initial_state": {
            "prefix": "one root grounding per scheduled image/query", "candidate_order": "retained score descending, stable detector rank tie break",
            "candidate_selection": "first candidate only for verification pilot; empty output retained as no-candidate state",
            "discovery_regions": [[0, 0, 500, 500], [500, 0, 1000, 500], [0, 500, 500, 1000], [500, 500, 1000, 1000]],
            "offline_strata_only": ["positive", "negative", "ambiguous"], "runtime_gt_used": False,
        },
        "action_paths": [
            {"name": "V_repeat", "task": "candidate_verification", "actions": ["repeated_grounding"], "public_capabilities": ["Visual_Grounding_Tool"], "prerequisites": ["prior same root/query/backend grounding"], "query_rule": "exact same source class string", "possible_outcomes": "Phase 4A grounding taxonomy", "estimated_logical_cost": 1, "same_hypothesis": True, "dependent_evidence": True, "directly_comparable": True},
            {"name": "V_zoom_focus", "task": "candidate_verification", "actions": ["crop_generation", "focused_grounding"], "public_capabilities": ["Zoom_In_Tool", "Visual_Grounding_Tool"], "prerequisites": ["valid root-frame candidate", "registered crop before focus"], "query_rule": "same source class string", "possible_outcomes": "crop outcome followed by joint grounding outcome", "estimated_logical_cost": 2, "same_hypothesis": True, "dependent_evidence": True, "directly_comparable": False},
            {"name": "V_alias_query", "task": "candidate_verification", "actions": ["root_grounding"], "public_capabilities": ["Visual_Grounding_Tool"], "prerequisites": ["prespecified source-level class alias"], "query_rule": "frozen alias table only", "possible_outcomes": "Phase 4A grounding taxonomy", "estimated_logical_cost": 1, "same_hypothesis": True, "dependent_evidence": True, "directly_comparable": True, "eligibility": "only a source-level prespecified alias, never image/GT-derived"},
            {"name": "D_repeat_broad", "task": "object_discovery", "actions": ["repeated_grounding"], "public_capabilities": ["Visual_Grounding_Tool"], "prerequisites": ["prior broad class grounding"], "query_rule": "same source class string", "possible_outcomes": "complete joint proposal set", "estimated_logical_cost": 1, "same_hypothesis": True, "dependent_evidence": True, "directly_comparable": True},
            {"name": "D_grid_focus", "task": "object_discovery", "actions": ["crop_generation", "focused_grounding"], "public_capabilities": ["Zoom_In_Tool", "Visual_Grounding_Tool"], "prerequisites": ["fixed grid region", "registered crop before focus"], "query_rule": "same source class string", "possible_outcomes": "crop outcome followed by complete joint proposal set", "estimated_logical_cost": 2, "same_hypothesis": True, "dependent_evidence": True, "directly_comparable": False},
        ],
        "budget": {"logical_public_capability_dispatches": 3, "charge_dispatched_failure": True, "charge_pre_dispatch_rejection": False, "physical_attempts_separate": True, "model_calls_planned": 0},
        "failure_policy": {
            "transport": "existing configured client retry policy: 8 retries after the initial attempt for transient failures; preserve one logical action ID",
            "tool_timeout_seconds": 600, "worker_timeout_seconds": 30,
            "retain_categories": ["no_detection", "execution_failure", "invalid_or_unavailable_observation", "dispatch_without_retained_result", "ineligible"],
            "failed_prerequisite": "stop path as partial and do not dispatch dependent action", "retry_selection": "no adaptive retry beyond configured transport policy",
        },
        "selection_design": {
            "pilot": "deterministic_coverage.v1", "expansion": "uniform_without_replacement.v1",
            "eligibility_frozen_before_selection": True, "record_seed_rng_and_positive_propensity": True,
            "randomized_propensity_rule": "marginal k/N and conditional 1/remaining eligible path count",
            "branch_isolation": "bite.collection_state.v1 tool_execution_complete snapshot",
        },
        "model_identity": {
            "orchestrator_calls": 0, "agent_config_reference": "configs/agent/qwen3_8b_paper.yaml",
            "grounding_backend": "sam3_segment", "checkpoint_repository": "facebook/sam3",
            "cached_revision_observed_in_phase01": "3c879f39826c281e95690f02c7821c4de09afae7",
            "checkpoint_verified_by_worker": False,
            "worker_checkpoint_attestation": "unavailable_in_current_service_contract",
            "score_semantics": "post-threshold retained sigmoid scores; unfiltered logits unavailable",
            "preprocessing_identity": "record source image hash, resolved frame, crop transform, worker/config/source digests",
        },
        "persistence": {
            "raw_before_labels": True, "schemas": ["bite.collection_state.v1", "bite.collection.v1", "bite.calibration.v1"],
            "source_group_namespace_required": True, "offline_gt_only": True, "retain_failures_and_empty_results": True,
        },
        "resource_plan": {
            "engineering_pilot_images": [20, 40], "queries_per_image": 2, "max_branch_dispatches_per_state": 3,
            "estimated_public_dispatch_range": [160, 320], "independence_units": "20-40 source groups, not branch or candidate rows",
            "power_analysis_status": "not_performed; expand only after pilot prevalence, variance, failure, and latency estimates",
        },
        "phase_boundary": "Do not start Phase 4B-2B or fit probabilities under this task.",
    }


def _check_no_runtime_gt(value, path=""):
    if isinstance(value, dict):
        for key, child in value.items():
            if _FORBIDDEN_RUNTIME.search(key):
                raise ValueError(f"GT-derived runtime scheduling field forbidden: {path + key}")
            _check_no_runtime_gt(child, path + key + ".")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_no_runtime_gt(child, f"{path}{index}.")


def validate_protocol(protocol):
    validate(protocol, PROTOCOL_SCHEMA)
    json.dumps(protocol, allow_nan=False)
    _check_no_runtime_gt({key: protocol[key] for key in ("sampling", "initial_state", "action_paths", "budget", "selection_design")})
    if protocol["initial_state"].get("runtime_gt_used") is not False:
        raise ValueError("Initial state must be constructed without GT")
    if protocol["budget"].get("model_calls_planned") != 0:
        raise ValueError("Phase 4B-2A protocol cannot schedule model calls")
    maximum = protocol["budget"].get("logical_public_capability_dispatches")
    if not isinstance(maximum, int) or maximum < 0:
        raise ValueError("Logical continuation budget must be a nonnegative integer")
    supported = {"root_grounding", "repeated_grounding", "crop_generation", "focused_grounding"}
    for path in protocol["action_paths"]:
        unknown = set(path.get("actions", [])) - supported
        if unknown:
            raise ValueError(f"Unsupported action template: {sorted(unknown)}")
        if not path.get("prerequisites"):
            raise ValueError(f"Action path has unresolved prerequisites: {path.get('name')}")
        cost = path.get("estimated_logical_cost")
        if not isinstance(cost, int) or cost < 0 or cost > maximum:
            raise ValueError(f"Action path cost is invalid or exceeds budget: {path.get('name')}")
    if any(not path.get("same_hypothesis") for path in protocol["action_paths"]):
        raise ValueError("Every calibration branch must target the declared hypothesis")
    if protocol["status"] == "FROZEN_READY" and not protocol["sampling"].get("partition_manifest_required"):
        raise ValueError("Ready protocol requires a partition manifest")
    for task_name, task in protocol["tasks"].items():
        if not task.get("positive_event") or not task.get("negative_event") or not task.get("unknown_event") or not task.get("primary_loss"):
            raise ValueError(f"Hypothesis task has undefined labels or loss: {task_name}")
    if protocol["selection_design"].get("expansion", "").startswith("uniform") and not protocol["selection_design"].get("randomized_propensity_rule"):
        raise ValueError("Randomized collection requires a known selection propensity rule")
    identity = protocol["model_identity"]
    if identity.get("worker_checkpoint_attestation") == "unavailable_in_current_service_contract" and identity.get("checkpoint_verified_by_worker") is not False:
        raise ValueError("Unknown worker checkpoint identity cannot be represented as verified")
    return True


def protocol_schema():
    return copy.deepcopy(PROTOCOL_SCHEMA)
