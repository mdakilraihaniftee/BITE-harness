#!/usr/bin/env python3
"""Regenerate the metadata-only Phase 4B-2A protocol and pending manifests."""

import argparse
import hashlib
import json
from pathlib import Path

from evaluation_kit.bite_calibration.manifest_freeze import provisional_manifest
from evaluation_kit.bite_calibration.protocol_validation import default_protocol, protocol_schema, validate_protocol
from evaluation_kit.bite_calibration.source_preparation import acquisition_plan
from evaluation_kit.bite_calibration.source_registry import default_registry, validate_registry


DEBUG_EXCLUSIONS = [{
    "sample_id": "PascalVOC_val_262",
    "image_sha256": "a18039d3edc2c8ae46fb2b8347318c79f91f5643c3811181d366ed4a4403e1b5",
    "partition": "development_debug",
    "reason": "Inspected and used for Phase 2/3/4A/4B-1 development; never blind or calibration fit.",
}]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    docs = root / "docs/bite"
    output = root / "outputs/bite/phase04b2a"
    manifests = output / "manifests"
    registry = default_registry()
    validate_registry(registry)
    protocol = default_protocol(source_ready=False)
    validate_protocol(protocol)
    pending = provisional_manifest(registry, exclusions=DEBUG_EXCLUSIONS)
    odinw = [source for source in registry["sources"] if source["source_id"].startswith("odinw13:")]
    readiness = {
        "schema_version": "bite.calibration_source_readiness.v1", "status": "DATA_SOURCE_PENDING",
        "official_odinw13_archives_discovered": 13,
        "official_odinw13_expected_compressed_bytes": sum(source["archive"]["bytes"] for source in odinw),
        "local_genuine_train_sources": 0, "approved_calibration_sources": 0,
        "local_reference_evidence": {"odinw_val_rows": 4938, "odinw_test_rows": 4575, "pascalvoc_val_test_exact_alias_images": 3422},
        "blockers": ["dataset archives not acquired", "per-domain terms not approved", "annotation completeness not locally verified", "train-to-heldout identity audit not run", "grouped partition manifest not frozen"],
        "decision": "No non-debug collection is permitted.",
    }
    separate = {}
    for partition in ("calibration_fit", "calibration_validation", "internal_test"):
        separate[f"{partition}.json"] = {
            "schema_version": "bite.calibration_partition_role.v1", "partition": partition,
            "status": "SOURCE_PENDING", "entries": [], "source_group_count": 0,
            "reason": "No approved locally verified training source exists.",
        }
    separate["final_evaluation_reference.json"] = {
        "schema_version": "bite.final_evaluation_reference.v1", "status": "REFERENCE_ONLY_NOT_CALIBRATION_PARTITION",
        "dataset": "ODinW13_bbox_val_qwen3 and configured test population", "calibration_fit_permitted": False,
        "known_aliases": [{"domain": "PascalVOC", "val_test_exact_shared_images": 3422, "handling": "one overlapping population"}],
        "debug_exclusions_file": "development_debug_exclusions.json",
        "note": "Existing public validation/test data are benchmark references, not newly blind calibration sources.",
    }
    separate["development_debug_exclusions.json"] = {
        "schema_version": "bite.development_debug_exclusions.v1", "status": "frozen_exclusions", "entries": DEBUG_EXCLUSIONS,
    }
    plans = [acquisition_plan(source, root / "data/calibration_sources") for source in odinw]
    all_plan = {
        "schema_version": "bite.calibration_acquisition_bundle.v1", "status": "REVIEW_REQUIRED_NO_DOWNLOAD",
        "source_count": len(plans), "total_expected_bytes": sum(plan["total_expected_bytes"] for plan in plans),
        "plans": plans,
    }
    phase_next = {
        "schema_version": "bite.phase04b2b_plan.v1", "status": "BLOCKED_SOURCE_PENDING", "launch_authorized": False,
        "source_groups": [20, 40], "queries_per_group": 2, "continuation_budget": 3,
        "selection_design": "deterministic_coverage.v1", "required_before_launch": readiness["blockers"],
        "runner_template": ".venv/bin/python scripts/bite/collect_tool_branches.py --snapshot <approved-state.json> --plan <frozen-action-plan.json> --output-dir outputs/bite/phase04b2b/pilot/<source-group-id>",
    }
    files = {
        docs / "dataset_source_registry_v1.json": registry,
        docs / "calibration_protocol_v1.json": protocol,
        docs / "calibration_protocol_schema_v1.json": protocol_schema(),
        manifests / "source_registry.json": registry,
        manifests / "source_readiness.json": readiness,
        manifests / "provisional_partition_manifest.json": pending,
        manifests / "odinw13_acquisition_plan.json": all_plan,
        manifests / "phase04b2b_plan.json": phase_next,
    }
    files.update({manifests / name: value for name, value in separate.items()})
    if args.dry_run:
        print(json.dumps({"would_write": [str(path.relative_to(root)) for path in files], "status": readiness["status"]}, indent=2))
        return
    for path, value in files.items():
        write_json(path, value)
    checksums = {str(path.relative_to(root)): digest(path) for path in sorted(files, key=str)}
    write_json(manifests / "manifest_checksums.json", {
        "schema_version": "bite.phase04b2a_checksums.v1", "algorithm": "sha256", "files": checksums,
    })
    print(json.dumps({"written": len(files) + 1, "status": readiness["status"], "output": str(output)}, sort_keys=True))


if __name__ == "__main__":
    main()
