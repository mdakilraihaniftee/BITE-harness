"""Leakage-safe provisional/frozen calibration partition manifests."""

from __future__ import annotations

import hashlib
import json

from .split_integrity import audit_partitions, validate_partition_manifest


def provisional_manifest(registry, *, exclusions=()):
    approved = [source for source in registry["sources"] if "approved_for_calibration" in source["acquisition_status"]]
    return {
        "schema_version": "bite.calibration_partition_manifest.v1",
        "status": "SOURCE_PENDING" if not approved else "SOURCE_APPROVED_NOT_FROZEN",
        "source_ids": [source["source_id"] for source in approved],
        "entries": [],
        "exclusions": list(exclusions),
        "partition_counts": {"calibration_fit": 0, "calibration_validation": 0, "internal_test": 0, "final_evaluation": 0},
        "scientific_boundary": "No row is assigned until source approval and identity grouping both pass.",
    }


def freeze_manifest(source, entries, *, salt="bite-calibration-v1", ratios=(70, 15, 15), exclusions=()):
    if "approved_for_calibration" not in source.get("acquisition_status", []):
        raise ValueError("Source is not approved_for_calibration")
    if sum(ratios) != 100 or any(value <= 0 for value in ratios):
        raise ValueError("Fit/validation/internal-test ratios must be positive and sum to 100")
    excluded_hashes = {item["image_sha256"] for item in exclusions if item.get("image_sha256")}
    usable = [dict(entry) for entry in entries if entry.get("image_sha256") not in excluded_hashes]
    audit = audit_partitions(usable)
    group_by_entry = {}
    for group in audit["groups"]:
        for entry_id in group["entry_ids"]:
            group_by_entry[entry_id] = group["source_group_id"]
    thresholds = (ratios[0], ratios[0] + ratios[1])
    assigned = []
    partition_by_group = {}
    for entry in usable:
        group_id = group_by_entry[entry["entry_id"]]
        bucket = int(hashlib.sha256(f"{salt}:{group_id}".encode()).hexdigest()[:12], 16) % 100
        partition = "calibration_fit" if bucket < thresholds[0] else "calibration_validation" if bucket < thresholds[1] else "internal_test"
        partition_by_group.setdefault(group_id, partition)
        assigned.append({
            "entry_id": entry["entry_id"], "source_id": source["source_id"], "source_group_id": group_id,
            "image_sha256": entry["image_sha256"], "scene_id": entry.get("scene_id"),
            "source_parent_id": entry.get("source_parent_id"), "partition": partition,
        })
    manifest = {
        "schema_version": "bite.calibration_partition_manifest.v1", "status": "frozen",
        "source_ids": [source["source_id"]], "partition_rule": {"algorithm": "sha256_group_bucket", "salt": salt, "ratios": list(ratios)},
        "entries": assigned, "exclusions": list(exclusions),
        "partition_counts": {name: sum(item["partition"] == name for item in assigned) for name in ("calibration_fit", "calibration_validation", "internal_test", "final_evaluation")},
        "source_audit": {"group_count": len(audit["groups"]), "cross_partition_overlap_count_before_assignment": audit["cross_partition_overlap_count"]},
    }
    validate_partition_manifest(manifest)
    manifest["manifest_sha256"] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return manifest


def validate_frozen_manifest(manifest, source):
    if "approved_for_calibration" not in source.get("acquisition_status", []):
        raise ValueError("Manifest source is not approved_for_calibration")
    expected = manifest.get("manifest_sha256")
    if not expected:
        raise ValueError("Frozen manifest requires manifest_sha256")
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    actual = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if actual != expected:
        raise ValueError("Frozen manifest checksum mismatch")
    validate_partition_manifest(manifest)
    return True
