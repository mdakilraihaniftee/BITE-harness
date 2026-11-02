"""Offline preparation for a future opt-in, checkpoint-attested SAM 3 worker."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from pathlib import Path

ATTESTATION_VERSION = "bite.sam3_attested_worker_preparation.v1"
EVENT_VERSION = "bite.sam3_worker_initialization_attestation.v1"
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_revision(revision):
    if not isinstance(revision, str) or not REVISION_PATTERN.fullmatch(revision):
        raise ValueError("SAM 3 revision must be an immutable lowercase 40-hex commit")
    return revision


def prepare_attested_worker(*, model_id, revision, cache_root, expected_weight_sha256,
                            expected_config_sha256, expected_processor_sha256,
                            worker_source, worker_config, environment):
    """Resolve and verify cached artifacts without importing or loading SAM 3."""
    validate_revision(revision)
    if model_id != "facebook/sam3":
        raise ValueError("The prepared bridge is specific to facebook/sam3")
    snapshot = Path(cache_root) / "snapshots" / revision
    artifacts = {}
    expected = {
        "sam3.pt": expected_weight_sha256,
        "config.json": expected_config_sha256,
        "processor_config.json": expected_processor_sha256,
    }
    for name, expected_digest in expected.items():
        path = snapshot / name
        if not path.is_file():
            raise ValueError(f"Required cached artifact is missing: {name}")
        actual_digest = sha256_file(path)
        if actual_digest != expected_digest:
            raise ValueError(f"Cached artifact digest mismatch: {name}")
        artifacts[name] = {
            "resolved_path": str(path.resolve()),
            "size_bytes": path.stat().st_size,
            "sha256": actual_digest,
            "verified": True,
        }
    source = Path(worker_source)
    config = Path(worker_config)
    plan = {
        "schema_version": ATTESTATION_VERSION,
        "status": "PREPARED_NOT_EXECUTED",
        "intended_configuration": {
            "model_id": model_id,
            "immutable_revision": revision,
            "revision_is_immutable": True,
            "offline_only": True,
            "network_download_permitted": False,
        },
        "cached_artifacts": artifacts,
        "load_plan": {
            "builder": "sam3.model_builder.build_sam3_image_model",
            "arguments": {
                "checkpoint_path": artifacts["sam3.pt"]["resolved_path"],
                "load_from_HF": False,
            },
            "actual_expected_loader_artifact": "sam3.pt",
            "model_safetensors_substituted": False,
            "production_startup_path_modified": False,
            "opt_in_isolated_path_required": True,
        },
        "preprocessing_intent": {
            "processor": "sam3.model.sam3_image_processor.Sam3Processor",
            "presence_token_multiplication": False,
            "iom_overlap_threshold": 0.3,
            "output_order": "left_to_right_by_box_x1",
            "processor_config": artifacts["processor_config.json"],
        },
        "worker_identity": {
            "worker_source_path": str(source),
            "worker_source_sha256": sha256_file(source),
            "worker_config_path": str(config),
            "worker_config_sha256": sha256_file(config),
            "environment": environment,
        },
        "future_initialization_event_contract": {
            "schema_version": EVENT_VERSION,
            "required_fields": [
                "session_id", "process_id", "process_start_time_utc", "model_load_time_utc",
                "model_id", "immutable_revision", "resolved_weight_path", "weight_sha256",
                "processor_config_sha256", "worker_source_sha256", "worker_config_sha256",
                "library_versions", "preprocessing", "load_succeeded",
            ],
            "must_be_emitted_after_successful_actual_model_load": True,
            "must_be_bound_to_process_session": True,
        },
        "historical_worker_identity_proven": False,
        "historical_comparability_status": "UNVERIFIED",
        "worker_started": False,
        "model_loaded": False,
        "gpu_inference_executed": False,
        "download_performed": False,
    }
    return plan


def validate_initialization_event(event, preparation):
    """Validate a future load-time event; safe for unit-test fixtures and mocks."""
    if event.get("schema_version") != EVENT_VERSION:
        raise ValueError("Unexpected initialization-attestation schema")
    required = preparation["future_initialization_event_contract"]["required_fields"]
    missing = [field for field in required if field not in event]
    if missing:
        raise ValueError(f"Initialization event is incomplete: {missing}")
    try:
        uuid.UUID(event["session_id"])
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("Initialization event session ID is invalid") from error
    if not isinstance(event["process_id"], int) or event["process_id"] <= 0:
        raise ValueError("Initialization event process ID is invalid")
    for field in ("process_start_time_utc", "model_load_time_utc"):
        try:
            datetime.fromisoformat(event[field].replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError(f"Initialization event has invalid {field}") from error
    intended = preparation["intended_configuration"]
    weight = preparation["cached_artifacts"]["sam3.pt"]
    processor = preparation["cached_artifacts"]["processor_config.json"]
    worker = preparation["worker_identity"]
    expected = {
        "model_id": intended["model_id"],
        "immutable_revision": intended["immutable_revision"],
        "resolved_weight_path": weight["resolved_path"],
        "weight_sha256": weight["sha256"],
        "processor_config_sha256": processor["sha256"],
        "worker_source_sha256": worker["worker_source_sha256"],
        "worker_config_sha256": worker["worker_config_sha256"],
    }
    for field, value in expected.items():
        if event[field] != value:
            raise ValueError(f"Initialization event mismatch: {field}")
    if event["load_succeeded"] is not True:
        raise ValueError("Initialization event does not attest a successful load")
    if not isinstance(event["library_versions"], dict) or not event["library_versions"]:
        raise ValueError("Initialization event lacks library versions")
    if not isinstance(event["preprocessing"], dict) or not event["preprocessing"]:
        raise ValueError("Initialization event lacks actual preprocessing configuration")
    return True
