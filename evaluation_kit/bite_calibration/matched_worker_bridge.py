"""Future fit-only bridge protocol for an attested SAM 3 worker."""

from __future__ import annotations

import hashlib
import json

BRIDGE_VERSION = "bite.task_v_matched_worker_bridge.v1"


def build_bridge_protocol(expansion_protocol, annotation_protocol, attestation_preparation):
    if expansion_protocol.get("schema_version") != "bite.task_v_expansion.v1":
        raise ValueError("Unexpected expansion protocol")
    if expansion_protocol.get("source_group_count") != 30:
        raise ValueError("Matched-worker bridge requires the original 30 expansion groups")
    if expansion_protocol.get("queries_per_group") != 7:
        raise ValueError("Matched-worker bridge requires the original seven-query schedule")
    states = expansion_protocol.get("states", [])
    if len(states) != 210:
        raise ValueError("Matched-worker bridge requires exactly 210 original query states")
    expected_hashes = set(annotation_protocol["identity"]["fit_source_image_sha256"])
    state_hashes = {
        row["entry"]["image_sha256"] if "entry" in row else row["image_sha256"] for row in states
    }
    if state_hashes != expected_hashes:
        raise ValueError("Bridge source images differ from the frozen annotation protocol")
    state_digest = hashlib.sha256(
        json.dumps(states, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": BRIDGE_VERSION,
        "status": "PREPARED_NOT_AUTHORIZED_NOT_EXECUTED",
        "purpose": "measure functional consistency between a future attested worker and historical fit observations",
        "partition": "calibration_fit",
        "cohort_id": expansion_protocol["cohort_id"],
        "source_id": expansion_protocol["source_id"],
        "source_group_count": 30,
        "source_image_count": 30,
        "source_image_sha256": sorted(expected_hashes),
        "query_schedule": {
            "source_classes": expansion_protocol["source_classes"],
            "queries_per_group": 7,
            "state_count": 210,
            "states_sha256": state_digest,
            "selection_or_query_changes_permitted": False,
        },
        "dispatch_caps": {
            "initial_grounding_only": 210,
            "initial_plus_zoom_focused_if_separately_authorized": 630,
            "caps_are_planning_limits_not_calls": True,
        },
        "required_attested_worker": {
            "model_id": attestation_preparation["intended_configuration"]["model_id"],
            "immutable_revision": attestation_preparation["intended_configuration"]["immutable_revision"],
            "weight_sha256": attestation_preparation["cached_artifacts"]["sam3.pt"]["sha256"],
            "successful_load_time_event_required": True,
        },
        "frozen_tolerances": {
            "source_image_sha256": "exact",
            "preprocessing_input_dimensions": "exact integer equality",
            "candidate_presence": "exact",
            "selected_detector_rank": "exact",
            "proposal_count": "exact",
            "box_coordinate_max_absolute_pixel_difference": 1e-4,
            "matched_box_iou_minimum": 0.999999,
            "score_max_absolute_difference": 1e-6,
            "failure_status": "exact success/failure category equality",
            "thresholds_frozen_before_execution": True,
        },
        "comparison_checks": [
            "source and image identity",
            "preprocessing dimensions",
            "initial candidate presence",
            "candidate rank and selection",
            "proposal count",
            "root-frame box agreement",
            "score agreement",
            "model-reported failures",
            "focused-observation compatibility if separately collected",
        ],
        "no_go_conditions": [
            "missing or invalid load-time attestation",
            "source/image/query schedule mismatch",
            "candidate presence, rank, proposal count, dimensions, or failure-category mismatch",
            "box or score disagreement outside frozen tolerances",
            "unauthorized focused dispatches",
            "resource, storage, or resume-integrity preflight failure",
        ],
        "interpretation": {
            "agreement_supports_sample_functional_consistency": True,
            "agreement_retroactively_proves_historical_weight_identity": False,
            "material_disagreement_requires_versioned_fit_only_recollection_and_refit_before_validation": True,
        },
        "restrictions": {
            "validation_partition_accessed": False,
            "internal_test_accessed": False,
            "execution_authorized": False,
            "worker_started": False,
            "inference_executed": False,
        },
    }
