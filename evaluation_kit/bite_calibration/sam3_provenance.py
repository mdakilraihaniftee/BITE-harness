"""Read-only SAM 3 cache, configuration, process and historical provenance audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

PROVENANCE_VERSION = "bite.sam3_loaded_checkpoint_provenance.v1"
CACHED_REVISION = "3c879f39826c281e95690f02c7821c4de09afae7"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _package_version(distribution_path, name):
    expected = name.lower().replace("-", "_")
    for metadata in Path(distribution_path).glob("*.dist-info/METADATA"):
        fields = {}
        for line in metadata.read_text(errors="replace").splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                if key in {"Name", "Version"} and key not in fields:
                    fields[key] = value
            if fields.keys() >= {"Name", "Version"}:
                break
        actual = fields.get("Name", "").lower().replace("-", "_")
        if actual == expected:
            return fields["Version"]
    return None


def audit_sam3_provenance(*, cache_root, site_packages, worker_source, worker_config,
                          worker_log_paths=(), active_process_lines=()):
    cache_root = Path(cache_root)
    snapshot = cache_root / "snapshots" / CACHED_REVISION
    refs_main = cache_root / "refs/main"
    cached_ref = refs_main.read_text().strip() if refs_main.is_file() else None
    files = {}
    for name in ("sam3.pt", "model.safetensors", "config.json", "processor_config.json"):
        path = snapshot / name
        files[name] = {
            "present": path.is_file(),
            "resolved_path": str(path.resolve()) if path.exists() else None,
            "size_bytes": path.stat().st_size if path.is_file() else None,
            "sha256": _sha(path) if path.is_file() else None,
        }
    direct_url_path = next(Path(site_packages).glob("sam3-*.dist-info/direct_url.json"), None)
    direct_url = json.loads(direct_url_path.read_text()) if direct_url_path else None
    process_lines = [line for line in active_process_lines if "sam3" in line.lower()]
    historical = []
    for path in map(Path, worker_log_paths):
        text = path.read_text(errors="replace") if path.is_file() else ""
        historical.append({
            "path": str(path),
            "sha256": _sha(path) if path.is_file() else None,
            "successful_segment_requests": text.count('"POST /v1/segment HTTP/1.1" 200 OK'),
            "health_successes": text.count('"GET /health HTTP/1.1" 200 OK'),
            "startup_complete": "Application startup complete" in text,
            "checkpoint_revision_recorded": CACHED_REVISION in text,
            "weight_hash_recorded": any(
                row["sha256"] and row["sha256"] in text for row in files.values()
            ),
        })
    source_commit = direct_url.get("vcs_info", {}).get("commit_id") if direct_url else None
    classification = "CACHE_CONFIG_VERIFIED_ONLY"
    return {
        "schema_version": PROVENANCE_VERSION,
        "status": classification,
        "configured_checkpoint": {
            "model_id": "facebook/sam3",
            "revision_explicitly_pinned_by_runtime_loader": False,
            "loader": "upstream build_sam3_image_model() -> hf_hub_download(repo_id, filename)",
            "worker_source_sha256": _sha(worker_source),
            "worker_config_sha256": _sha(worker_config),
            "sam3_source_commit": source_commit,
        },
        "cached_checkpoint": {
            "cache_root": str(cache_root),
            "refs_main": cached_ref,
            "expected_revision": CACHED_REVISION,
            "ref_matches_expected": cached_ref == CACHED_REVISION,
            "snapshot_present": snapshot.is_dir(),
            "files": files,
        },
        "running_process": {
            "active": bool(process_lines),
            "matching_process_lines": process_lines,
            "identity_attested": False,
        },
        "historical_worker": {
            "logs": historical,
            "service_was_observed_healthy": any(row["health_successes"] for row in historical),
            "load_event_revision_attested": False,
            "load_event_weight_hash_attested": False,
            "load_event_preprocessing_attested": False,
            "historical_process_to_cache_link_proven": False,
        },
        "environment": {
            "sam3": _package_version(site_packages, "sam3"),
            "torch": _package_version(site_packages, "torch"),
            "torchvision": _package_version(site_packages, "torchvision"),
            "huggingface_hub": _package_version(site_packages, "huggingface_hub"),
            "direct_url": direct_url,
        },
        "preprocessing": {
            "current_worker_behavior": [
                "upstream Sam3Processor",
                "presence-token multiplication disabled by local worker override",
                "confidence threshold inherited from upstream processor",
                "IoM overlap removal threshold 0.3",
                "left-to-right output ordering",
            ],
            "current_source_reconstructible": True,
            "historical_loaded_preprocessing_attested": False,
        },
        "cross_run_comparability": {
            "historical_fit_worker_exact_identity": "UNVERIFIED",
            "future_attested_worker_can_be_identified": True,
            "future_worker_equivalent_to_historical_claim_permitted": False,
            "risk": "checkpoint, preprocessing, package, or worker-code mismatch can impair transport",
            "recommended_remediation": (
                "Before blind validation, either approve the comparability limitation or authorize a "
                "matched-service fit-only consistency/recollection experiment using the attested worker."
            ),
        },
        "future_attestation_contract": {
            "capture_at_model_load": True,
            "fields": [
                "resolved checkpoint repository and immutable revision",
                "resolved weight paths, sizes, and SHA-256 digests",
                "preprocessing configuration and local overrides",
                "worker source and configuration digests",
                "SAM 3, Torch, Torchvision, Hugging Face Hub, CUDA and Python versions",
                "worker session identifier and initialization timestamp",
            ],
            "must_be_tied_to_actual_load_event": True,
            "retroactive_proof_claimed": False,
            "worker_restart_performed": False,
        },
        "network_accessed": False,
        "model_loaded_by_audit": False,
        "gpu_inference_executed": False,
    }


def validate_provenance(report):
    if report.get("schema_version") != PROVENANCE_VERSION:
        raise ValueError("Unexpected SAM 3 provenance schema")
    allowed = {
        "LOADED_MODEL_ATTESTED", "PROCESS_CONFIG_ATTESTED_ONLY",
        "CACHE_CONFIG_VERIFIED_ONLY", "PROVENANCE_UNVERIFIED",
    }
    if report.get("status") not in allowed:
        raise ValueError("Unknown SAM 3 provenance classification")
    if report["status"] == "LOADED_MODEL_ATTESTED" and not report["historical_worker"][
        "load_event_weight_hash_attested"
    ]:
        raise ValueError("Loaded-model attestation requires load-event weight hashes")
    return report
