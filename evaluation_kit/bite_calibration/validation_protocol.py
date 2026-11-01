"""Frozen metadata-only design for future Aquarium validation collection."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

VALIDATION_PROTOCOL_VERSION = "bite.task_v_validation_collection.v1"
QUERIES = ("fish", "jellyfish", "penguin", "puffin", "shark", "starfish", "stingray")


def build_validation_protocol(partition_manifest_path):
    path = Path(partition_manifest_path)
    manifest = json.loads(path.read_text())
    if manifest.get("status") != "frozen":
        raise ValueError("Validation design requires a frozen partition manifest")
    grouped = defaultdict(list)
    for entry in manifest["entries"]:
        if entry["partition"] == "calibration_validation":
            grouped[entry["source_group_id"]].append(entry)
    if len(grouped) != 72:
        raise ValueError(f"Expected 72 calibration-validation groups, found {len(grouped)}")
    representatives = []
    for group, entries in sorted(grouped.items()):
        chosen = min(entries, key=lambda row: row["entry_id"])
        representatives.append({
            "source_group_id": group,
            "representative_entry_id": chosen["entry_id"],
            "representative_image_sha256": chosen["image_sha256"],
            "selection_rule": "lexicographically_first_entry_id_within_frozen_group",
            "queries": list(QUERIES),
        })
    canonical = json.dumps(representatives, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": VALIDATION_PROTOCOL_VERSION,
        "status": "FROZEN_DESIGN_NOT_EXECUTED",
        "source": {
            "dataset": "Aquarium Combined (Roboflow), GLIP-curated archive",
            "license": "CC BY 4.0",
            "partition_manifest_sha256": manifest["manifest_sha256"],
            "partition": "calibration_validation",
            "internal_test_accessed": False,
            "validation_images_loaded": False,
            "validation_annotations_loaded": False,
        },
        "selection": {
            "unit": "source_group_id",
            "group_count": len(representatives),
            "representative_count": len(representatives),
            "representatives_sha256": hashlib.sha256(canonical).hexdigest(),
            "representatives": representatives,
            "difficulty_or_outcome_based_selection": False,
        },
        "query_design": {
            "queries": list(QUERIES),
            "queries_per_group": 7,
            "maximum_query_states": 72 * 7,
            "query_uses_gt": False,
        },
        "action_policy": {
            "initial": "Visual_Grounding_Tool on root image using scheduled source-vocabulary query",
            "eligible_followup": "Zoom_In_Tool then same-class Visual_Grounding_Tool",
            "routine_exact_repeat": False,
            "maximum_public_calls_per_candidate_present_state": 3,
            "maximum_logical_dispatches": 72 * 7 * 3,
            "maximum_counts_are_planning_bounds_not_measurements": True,
            "crop_selection": "same frozen candidate-centered runtime-only crop policy as calibration-fit",
            "raw_before_label_persistence": True,
        },
        "frozen_analysis": {
            "feature_schema": "bite.annotation_proxy_initial_state.v1 plus bite.focused_evidence_features.v1",
            "annotation_endpoints": ["H_annotation_0.50", "H_annotation_0.75"],
            "visual_endpoint": "bite.visual_plausibility.v1; separate and unknown unless human-reviewed",
            "candidate_rule": "highest retained initial detector score with stable detector-rank tie break",
            "missing_or_ambiguous": "retain explicit category; no complete-case substitution",
            "models": ["constant_prevalence", "score_only_logistic", "compact_initial_logistic"],
            "metrics": ["Brier score", "log loss", "forced decision error", "reliability bins"],
            "uncertainty": "source-group bootstrap; invalid single-class replicates reported",
            "failure_policy": "persist dispatched failure and logical cost; never relabel as empty detection",
        },
        "compatibility": {
            "required_backend": "sam3_segment",
            "exact_checkpoint_revision_must_be_attested_before_collection": True,
            "source_manifest_must_match": manifest["manifest_sha256"],
            "protocol_or_checkpoint_change_requires_new_run_identity": True,
        },
        "execution": {
            "authorized_in_phase04c1a": False,
            "canary_executed": False,
            "gpu_calls": 0,
            "model_calls": 0,
            "observed_dispatches": 0,
        },
    }


def validate_validation_protocol(protocol):
    if protocol.get("schema_version") != VALIDATION_PROTOCOL_VERSION:
        raise ValueError("Unexpected validation protocol version")
    if protocol["source"]["partition"] != "calibration_validation":
        raise ValueError("Validation protocol must use calibration_validation only")
    if protocol["source"]["internal_test_accessed"]:
        raise ValueError("Internal test must remain locked")
    if protocol["selection"]["group_count"] != 72:
        raise ValueError("Validation protocol must retain all 72 frozen groups")
    if protocol["action_policy"]["maximum_logical_dispatches"] != 1512:
        raise ValueError("Validation dispatch cap mismatch")
    if protocol["execution"]["authorized_in_phase04c1a"]:
        raise ValueError("Phase 4C-1A cannot execute validation collection")
    partitions = {"calibration_validation"}
    if partitions != {protocol["source"]["partition"]}:
        raise ValueError("Unexpected partition")
    return protocol
