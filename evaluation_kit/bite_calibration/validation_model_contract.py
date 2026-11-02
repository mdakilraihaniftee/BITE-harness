"""Endpoint-specific, metadata-only contract for future Task V validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .annotation_proxy_protocol import PROTOCOL_VERSION, validate_protocol
from .frozen_prior_export import EXPORT_VERSION, validate_frozen_artifact
from .sam3_provenance import validate_provenance
from .validation_protocol import (
    VALIDATION_PROTOCOL_VERSION,
    validate_validation_protocol,
)

CONTRACT_VERSION = "bite.task_v_validation_model_contract.v2"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_validation_contract(*, validation_protocol_path, prior_preflight_path,
                              annotation_protocol_path, frozen_prior_paths,
                              provenance_path, partition_manifest_path):
    collection = validate_validation_protocol(json.loads(Path(validation_protocol_path).read_text()))
    prior_preflight = json.loads(Path(prior_preflight_path).read_text())
    annotation_protocol = validate_protocol(json.loads(Path(annotation_protocol_path).read_text()))
    provenance = validate_provenance(json.loads(Path(provenance_path).read_text()))
    models = [validate_frozen_artifact(json.loads(Path(path).read_text())) for path in frozen_prior_paths]
    endpoints = {model["endpoint"] for model in models}
    model_names = {model["model_name"] for model in models}
    if endpoints != {"H_annotation_0.5", "H_annotation_0.75"}:
        raise ValueError("Frozen priors do not cover both annotation endpoints")
    if model_names != {"constant_prevalence", "score_only_logistic", "compact_initial_logistic"}:
        raise ValueError("Frozen prior comparator set is incomplete")
    if prior_preflight["source_and_split"]["cross_partition_group_overlaps"] != {
        "fit_validation": [], "fit_internal_test": [], "validation_internal_test": [],
    }:
        raise ValueError("Prior split-integrity preflight is not clean")
    if prior_preflight["source_and_split"]["quarantined_validation_image_count"]:
        raise ValueError("Quarantined image reached validation partition")
    partition_file_sha = _sha(partition_manifest_path)
    if partition_file_sha != prior_preflight["source_and_split"]["partition_manifest_file_sha256"]:
        raise ValueError("Frozen partition manifest file changed after prior preflight")
    checkpoint_comparable = provenance["status"] == "LOADED_MODEL_ATTESTED"
    return {
        "schema_version": CONTRACT_VERSION,
        "status": "METADATA_PREFLIGHT_PASS / EXECUTION_NOT_AUTHORIZED",
        "protocol_versions": {
            "annotation_proxy": PROTOCOL_VERSION,
            "collection": VALIDATION_PROTOCOL_VERSION,
            "frozen_prior": EXPORT_VERSION,
        },
        "source_and_split": {
            **prior_preflight["source_and_split"],
            "held_out_correctness_labels_accessed_in_phase04c1c": False,
            "internal_test_records_loaded_in_phase04c1c": False,
            "prior_preflight_reused_without_reopening_labels": True,
        },
        "collection": {
            "source_group_count": collection["selection"]["group_count"],
            "representative_count": collection["selection"]["representative_count"],
            "queries": collection["query_design"]["queries"],
            "maximum_query_states": collection["query_design"]["maximum_query_states"],
            "maximum_logical_dispatches": collection["action_policy"]["maximum_logical_dispatches"],
            "candidate_rule": collection["frozen_analysis"]["candidate_rule"],
            "action_policy": collection["action_policy"],
            "branch_isolation_required": True,
            "coordinate_transform_validation_required": True,
            "resume_and_corruption_detection_required": True,
            "executed": False,
        },
        "runtime_ordering": [
            "initial SAM 3 observation",
            "extract GT-free initial-state features",
            "apply frozen prior before any additional action or GT access",
            "persist original probability",
            "for eligible candidates execute frozen Zoom then focused-grounding branch",
            "finalize raw joint evidence and provenance",
            "open GT and derive official COCO annotation labels",
            "evaluate frozen prior against original-candidate label",
            "retain Zoom evidence separately for a future conditional-value experiment",
        ],
        "model_contract": {
            "primary": "score_only_logistic",
            "comparators": ["constant_prevalence", "compact_initial_logistic"],
            "endpoints": sorted(endpoints),
            "model_payload_sha256": {
                f"{model['endpoint']}:{model['model_name']}": model["serialized_model_payload_sha256"]
                for model in models
            },
            "initial_probability_never_modified_by_zoom": True,
            "unsupported_predictions_retained_and_reported": True,
        },
        "evaluation": {
            "primary": "candidate-level Brier score",
            "secondary": [
                "log loss", "equal-cost decision error", "group-balanced Brier",
                "source-group confidence intervals", "reliability bins with counts",
                "queried-class support", "unsupported coverage", "prediction-score distribution",
            ],
            "paired_source_group_comparisons": True,
            "validation_tuning_prohibited": True,
            "internal_test_locked": True,
        },
        "human_review": {
            "required_for_annotation_proxy_execution": False,
            "visual_truth_limitations_must_be_reported": True,
        },
        "checkpoint": {
            "provenance_status": provenance["status"],
            "historical_future_comparability_verified": checkpoint_comparable,
            "comparability_limitation_requires_explicit_approval": not checkpoint_comparable,
        },
        "authorization": {
            "metadata_preflight_passed": True,
            "researcher_execution_authorization_present": False,
            "worker_resource_readiness_checked": False,
            "storage_location_confirmed_for_new_run": False,
            "execution_budget_confirmed": False,
            "human_review_is_gate": False,
            "go_no_go": "NO_GO",
            "reason": "separate execution authorization and checkpoint comparability decision pending",
        },
        "restrictions": {
            "tool_inference_calls": 0,
            "validation_outcomes_accessed": False,
            "internal_test_accessed": False,
            "zoom_model_fitted": False,
            "posterior_computed": False,
        },
        "annotation_protocol_identity": annotation_protocol["identity"],
    }


def validate_contract(contract):
    if contract.get("schema_version") != CONTRACT_VERSION:
        raise ValueError("Unexpected validation model contract")
    if contract["collection"]["source_group_count"] != 72:
        raise ValueError("Validation group count changed")
    if contract["collection"]["maximum_query_states"] != 504:
        raise ValueError("Validation state cap changed")
    if contract["collection"]["maximum_logical_dispatches"] != 1512:
        raise ValueError("Validation dispatch cap changed")
    if contract["authorization"]["go_no_go"] != "NO_GO":
        raise ValueError("Phase 4C-1C cannot authorize validation execution")
    return contract
