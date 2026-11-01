"""Read-only preflight for the frozen Task V validation collection design."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .prior_model import L2_PENALTY, MODEL_NAMES
from .validation_protocol import validate_validation_protocol

VALIDATION_READINESS_VERSION = "bite.task_v_validation_preflight.v1"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _groups(entries):
    return {row["source_group_id"] for row in entries}


def preflight_validation(protocol_path, partition_manifest_path, exclusion_path,
                         phase04c1a_manifest_path, checkpoint_refs_path, prior_preflight_path):
    protocol = validate_validation_protocol(json.loads(Path(protocol_path).read_text()))
    manifest = json.loads(Path(partition_manifest_path).read_text())
    exclusions = json.loads(Path(exclusion_path).read_text())["entries"]
    prior_manifest = json.loads(Path(phase04c1a_manifest_path).read_text())
    checkpoint_refs = json.loads(Path(checkpoint_refs_path).read_text())
    earlier_preflight = json.loads(Path(prior_preflight_path).read_text())
    if manifest.get("status") != "frozen":
        raise ValueError("Partition manifest is not frozen")
    partitions = {
        name: [row for row in manifest["entries"] if row["partition"] == name]
        for name in ("calibration_fit", "calibration_validation", "internal_test")
    }
    group_sets = {name: _groups(entries) for name, entries in partitions.items()}
    overlaps = {
        "fit_validation": sorted(group_sets["calibration_fit"] & group_sets["calibration_validation"]),
        "fit_internal_test": sorted(group_sets["calibration_fit"] & group_sets["internal_test"]),
        "validation_internal_test": sorted(group_sets["calibration_validation"] & group_sets["internal_test"]),
    }
    excluded_hashes = {row["image_sha256"] for row in exclusions}
    validation_hashes = {row["image_sha256"] for row in partitions["calibration_validation"]}
    quarantine_overlap = sorted(excluded_hashes & validation_hashes)
    source = earlier_preflight["dataset"]
    checkpoint = checkpoint_refs["sam3"]
    exact_loaded_revision = earlier_preflight["configuration"].get("checkpoint_verified_by_worker", False)
    if any(overlaps.values()) or quarantine_overlap:
        raise ValueError("Frozen split integrity or quarantine exclusion failed")
    return {
        "schema_version": VALIDATION_READINESS_VERSION,
        "status": "ENGINEERING_COMPATIBLE / INFERENCE_NOT_AUTHORIZED",
        "source_and_split": {
            "source_id": source["source_id"],
            "approval_id": source["approval_id"],
            "license": "CC BY 4.0",
            "partition_manifest_sha256": manifest["manifest_sha256"],
            "partition_manifest_file_sha256": _sha(partition_manifest_path),
            "fit_group_count": len(group_sets["calibration_fit"]),
            "validation_group_count": len(group_sets["calibration_validation"]),
            "internal_test_group_count": len(group_sets["internal_test"]),
            "cross_partition_group_overlaps": overlaps,
            "quarantined_validation_image_count": len(quarantine_overlap),
            "validation_labels_or_outcomes_accessed": False,
            "internal_test_accessed": False,
        },
        "protocol": {
            "schema_version": protocol["schema_version"],
            "representatives_sha256": protocol["selection"]["representatives_sha256"],
            "group_count": protocol["selection"]["group_count"],
            "queries": protocol["query_design"]["queries"],
            "maximum_query_states": protocol["query_design"]["maximum_query_states"],
            "maximum_logical_dispatches": protocol["action_policy"]["maximum_logical_dispatches"],
            "candidate_rule": protocol["frozen_analysis"]["candidate_rule"],
            "raw_before_label": protocol["action_policy"]["raw_before_label_persistence"],
            "resume_strategy": "state-level atomic completion ledger; never reuse partial state as complete",
            "result_schema_compatible": True,
            "executed": False,
        },
        "frozen_model_evaluation": {
            "selection_rule": "score-only is primary; constant and compact remain prespecified comparators",
            "development_selection_optimism_acknowledged": True,
            "refit_before_blind_evaluation": (
                "refit each model once on all eligible seven-class expansion calibration_fit rows; "
                "do not use pilot or validation outcomes"
            ),
            "models": list(MODEL_NAMES),
            "constant_smoothing": "Beta(1,1)",
            "features": {
                "constant_prevalence": [],
                "score_only_logistic": ["initial_score"],
                "compact_initial_logistic": ["initial_score", "log_original_relative_area"],
            },
            "l2_lambda": L2_PENALTY,
            "score_handling": "identity on finite [0,1] retained initial SAM 3 score",
            "preprocessing": "fit mean/scale on calibration_fit only and freeze before evaluation",
            "missing_data": "unsupported prediction retained and counted; no imputation",
            "unknown_visual_labels": "excluded from visual-endpoint scoring and reported, never relabeled",
            "primary_loss": "case-level Brier under fixed seven-query validation design",
            "uncertainty": "paired source-group bootstrap over validation groups",
            "phase04c1a_manifest_status": prior_manifest["status"],
        },
        "checkpoint_provenance": {
            "configured_model_id": checkpoint["model_id"],
            "cached_revision": checkpoint["revision"],
            "cache_ref_verified_historically": checkpoint["cache_ref_verified_now"],
            "loaded_worker_model_identifier_attested": False,
            "loaded_worker_revision_attested": bool(exact_loaded_revision),
            "loaded_checkpoint_file_hash_attested": False,
            "loaded_preprocessing_configuration_attested": False,
            "worker_code_config_revision_attested": False,
            "checkpoint_verified_by_worker": False,
            "cross_run_identity_claim_permitted": False,
            "gate": "BLOCKED_PENDING_WORKER_ATTESTATION",
        },
        "human_label_readiness": "PENDING",
        "authorization": {
            "engineering_compatible": True,
            "new_inference_authorized": False,
            "collector_executed": False,
            "gpu_calls": 0,
            "network_inference_calls": 0,
            "separate_researcher_authorization_required": True,
        },
    }
