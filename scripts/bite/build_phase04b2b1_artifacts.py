#!/usr/bin/env python3
"""Generate Phase 4B-2B-1 approval, amendment and provisional artifacts."""

import argparse
import hashlib
import json
from pathlib import Path

from evaluation_kit.bite_calibration.query_schedule import schedule_queries
from evaluation_kit.bite_calibration.research_amendment import amendment_schema, default_amendment, validate_amendment
from evaluation_kit.bite_calibration.source_acquisition import acquisition_plan, approval_request


SOURCE_IDS = [
    "odinw13:AerialMaritimeDrone_large",
    "odinw13:Aquarium_Aquarium_Combined.v2-raw-1024.coco",
]


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
    registry = json.loads((root / "docs/bite/dataset_source_registry_v1.json").read_text())
    destination = root / "data/calibration_sources/odinw13"
    amendment = default_amendment()
    validate_amendment(amendment)
    request = approval_request(registry, SOURCE_IDS, destination)
    request["terms_evidence"] = [
        {
            "source_id": SOURCE_IDS[0],
            "publisher_dataset_url": "https://universe.roboflow.com/jacob-solawetz/aerial-maritime",
            "publisher_page_current_claim": "MIT",
            "installed_export_metadata_claim": "Public Domain / CC0 1.0",
            "status": "LICENSE_METADATA_DISCREPANCY_REQUIRES_RESEARCHER_REVIEW",
            "limitations": ["No warranty", "publicity/privacy and other rights may remain", "do not imply endorsement"],
        },
        {
            "source_id": SOURCE_IDS[1],
            "publisher_dataset_url": "https://universe.roboflow.com/brad-dwyer/aquarium-combined",
            "publisher_page_current_claim": "CC BY 4.0",
            "installed_export_metadata_claim": "CC BY 4.0",
            "status": "ATTRIBUTION_TERMS_REQUIRE_RESEARCHER_ACCEPTANCE",
            "limitations": ["Give appropriate credit and license link", "indicate modifications", "do not imply endorsement", "other rights may remain"],
        },
    ]
    request["precise_commands_after_approval"] = [
        ".venv/bin/python scripts/bite/acquire_calibration_sources.py --source-id " + source_id +
        " --destination data/calibration_sources/odinw13 --approval-record outputs/bite/phase04b2b1/acquisition/researcher_approval.json --execute --output outputs/bite/phase04b2b1/acquisition/" +
        source_id.split(":", 1)[1] + "_acquisition.json"
        for source_id in SOURCE_IDS
    ]
    request["redistribution_planned"] = False
    plans = [acquisition_plan(registry, source_id, destination) for source_id in SOURCE_IDS]
    annotation = {
        "schema_version": "bite.phase04b2b1_annotation_status.v1", "status": "NOT_ACQUIRED",
        "sources": [{"source_id": source_id, "structural_completeness": "not_checked",
                     "class_conditional_exhaustiveness": "unknown", "visual_completeness": "not_reviewed",
                     "task_v_readiness": "blocked", "task_d_readiness": "blocked"}
                    for source_id in SOURCE_IDS],
        "manual_qa": "pending source acquisition; selection will use source-group hash seed 417",
    }
    split = {
        "schema_version": "bite.phase04b2b1_split_status.v1", "status": "SOURCE_PENDING",
        "train_entries": 0, "approved_train_source_groups": 0,
        "exact_heldout_audit": "not_run_without_acquired_train_images",
        "near_duplicate_audit": "not_run_without_acquired_train_images",
        "known_reference_finding": {"domain": "PascalVOC", "val_test_exact_alias_images": 3422},
        "debug_exclusion": {"sample_id": "PascalVOC_val_262", "image_sha256": "a18039d3edc2c8ae46fb2b8347318c79f91f5643c3811181d366ed4a4403e1b5"},
        "calibration_fit": [], "calibration_validation": [], "internal_test": [],
        "freeze_permitted": False,
    }
    schedule = {
        "schema_version": "bite.query_schedule_amendment.v2", "seed": 417,
        "formula": "scheduled_count=min(requested_classes_per_group, available_verified_classes)",
        "one_class_example": schedule_queries("synthetic-one-class", ["package"], requested_count=2),
        "aerial_example": schedule_queries("example-aerial-group", ["boat", "car", "dock", "jetski", "lift"], requested_count=2),
        "aquarium_example": schedule_queries("example-aquarium-group", ["fish", "jellyfish", "penguin", "puffin", "shark", "starfish", "stingray"], requested_count=2),
        "status": "AMENDMENT_FROZEN_SOURCE_PENDING",
    }
    collector = {
        "schema_version": "bite.phase04b2b1_collector_interface.v1", "validation_mode": "mock_only",
        "supported": ["original image registration", "permitted class query", "shared prefix",
                      "tool-executable snapshot", "isolated eligible paths", "logical budget <=3",
                      "raw-before-offline-label boundary", "target-aligned runtime summary"],
        "gt_required_for_runtime_construction": False,
        "gaps": ["no dataset-manifest iterator", "no acquired source adapter", "no automatic manual-QA workflow",
                 "physical retry attempts remain uninstrumented"],
        "multi_image_collection_authorized": False,
    }
    provisional = {
        "schema_version": "bite.phase04b2b1_manifest_status.v1", "status": "AWAITING_DATA_APPROVAL",
        "approved_source_ids": [], "entries": [], "manifest_checksum": None,
        "reason": "No researcher approval record and no acquired/verified training source.",
        "frozen_ready": False,
    }
    outputs = root / "outputs/bite/phase04b2b1"
    files = {
        root / "docs/bite/calibration_research_amendment_v1.json": amendment,
        root / "docs/bite/calibration_research_amendment_schema_v1.json": amendment_schema(),
        outputs / "acquisition/approval_request.json": request,
        outputs / "acquisition/dry_run_plans.json": {"schema_version": "bite.acquisition_dry_runs.v1", "plans": plans},
        outputs / "validation/annotation_readiness.json": annotation,
        outputs / "validation/split_integrity.json": split,
        outputs / "validation/collector_interface.json": collector,
        outputs / "protocol/research_amendment.json": amendment,
        outputs / "protocol/query_schedule_amendment.json": schedule,
        outputs / "manifests/provisional_status.json": provisional,
    }
    if args.dry_run:
        print(json.dumps({"status": "AWAITING_DATA_APPROVAL", "would_write": [str(path.relative_to(root)) for path in files]}, indent=2))
        return
    for path, value in files.items():
        write_json(path, value)
    checksums = {str(path.relative_to(root)): digest(path) for path in sorted(files, key=str)}
    write_json(outputs / "manifest_checksums.json", {
        "schema_version": "bite.phase04b2b1_checksums.v1", "algorithm": "sha256", "files": checksums,
    })
    print(json.dumps({"status": "AWAITING_DATA_APPROVAL", "written": len(files) + 1}, sort_keys=True))


if __name__ == "__main__":
    main()
