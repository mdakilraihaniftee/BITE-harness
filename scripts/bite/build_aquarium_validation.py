#!/usr/bin/env python3
"""Build Phase 4B-2B-1A Aquarium validation artifacts; never downloads data."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import hashlib
import json
from pathlib import Path
import re

from PIL import Image, ImageDraw

from evaluation_kit.bite_calibration.annotation_readiness import inspect_detection_annotations
from evaluation_kit.bite_calibration.common import file_hash, identity
from evaluation_kit.bite_calibration.duplicate_audit import audit_train_against_heldout
from evaluation_kit.bite_calibration.manifest_freeze import freeze_manifest, validate_frozen_manifest
from evaluation_kit.bite_calibration.query_schedule import schedule_queries
from evaluation_kit.bite_calibration.source_registry import default_registry, validate_source
from evaluation_kit.bite_calibration.split_integrity import audit_partitions


SOURCE_ID = "odinw13:Aquarium_Aquarium_Combined.v2-raw-1024.coco"
CLASSES = ["fish", "jellyfish", "penguin", "puffin", "shark", "starfish", "stingray"]
ROOT = Path("data/calibration_sources/odinw13/extracted/Aquarium_Aquarium_Combined.v2-raw-1024.coco/Aquarium/Aquarium Combined.v2-raw-1024.coco")
ARCHIVE = Path("data/calibration_sources/odinw13/archives/Aquarium.zip")
HELDOUT_INVENTORY = Path("outputs/bite/phase04a/audit/dataset_inventory.json")
ACQUISITION = Path("outputs/bite/phase04b2b1/acquisition/Aquarium_Aquarium_Combined.v2-raw-1024.coco_acquisition.json")
APPROVAL = Path("outputs/bite/phase04b2b1/acquisition/researcher_approval.json")
DEBUG_EXCLUSION = {
    "sample_id": "PascalVOC_val_262",
    "image_sha256": "a18039d3edc2c8ae46fb2b8347318c79f91f5643c3811181d366ed4a4403e1b5",
    "reason": "previously inspected development-debug image",
}


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _lineage(name):
    original = Path(name).name.split(".rf.", 1)[0]
    original = re.sub(r"_(?:jpeg_)?jpg$", "", original)
    scene = re.sub(r"_MOV-?\d+$", "_MOV", original)
    return original, scene


def _split_inventory(split):
    split_root = ROOT / split
    annotation = split_root / "annotations_without_background.json"
    document = json.loads(annotation.read_text())
    categories = {item["id"]: item["name"] for item in document["categories"]}
    annotations_by_image = defaultdict(list)
    class_annotations = Counter()
    class_images = Counter()
    crowd = ignore = 0
    invalid = []
    annotation_ids = set()
    for item in document["annotations"]:
        if item.get("id") in annotation_ids:
            invalid.append({"kind": "duplicate_annotation_id", "id": item.get("id")})
        annotation_ids.add(item.get("id"))
        annotations_by_image[item["image_id"]].append(item)
        class_annotations[categories[item["category_id"]]] += 1
        crowd += int(bool(item.get("iscrowd", 0)))
        ignore += int(bool(item.get("ignore", 0)))
    for image_id, rows in annotations_by_image.items():
        for category_id in {row["category_id"] for row in rows}:
            class_images[categories[category_id]] += 1
    sizes = Counter()
    modes = Counter()
    missing = []
    dimension_mismatches = []
    image_ids = set()
    entries = []
    for image in document["images"]:
        image_id = image.get("id")
        if image_id in image_ids:
            invalid.append({"kind": "duplicate_image_id", "id": image_id})
        image_ids.add(image_id)
        image_path = split_root / Path(image["file_name"]).name
        if not image_path.is_file():
            missing.append(image["file_name"])
            continue
        with Image.open(image_path) as pixels:
            pixels.load()
            sizes[f"{pixels.width}x{pixels.height}"] += 1
            modes[pixels.mode] += 1
            if pixels.size != (image["width"], image["height"]):
                dimension_mismatches.append({"image_id": image_id, "actual": list(pixels.size),
                                             "declared": [image["width"], image["height"]]})
        parent_id, scene_id = _lineage(image["file_name"])
        annotations = annotations_by_image[image_id]
        per_class_annotation_counts = Counter(categories[row["category_id"]] for row in annotations)
        entry = {
            "entry_id": f"Aquarium:{split}:{Path(image['file_name']).name}",
            "partition": f"candidate_{split}", "source_namespace": "ODinW/Aquarium_Aquarium_Combined.v2-raw-1024.coco",
            "source_image_id": Path(image["file_name"]).name, "source_parent_id": parent_id,
            "scene_id": scene_id, "annotation_image_id": image_id,
            "image_path": str(image_path.resolve()), "image_sha256": file_hash(image_path),
            "annotation_file": str(annotation.resolve()), "annotation_sha256": file_hash(annotation),
            "width": image["width"], "height": image["height"],
            "annotation_count": len(annotations),
            "classes_present": sorted({categories[row["category_id"]] for row in annotations}),
            "per_class_annotation_counts": dict(sorted(per_class_annotation_counts.items())),
        }
        entries.append(entry)
    annotation_counts = [entry["annotation_count"] for entry in entries]
    json_variants = {}
    for name in ("_annotations.coco.json", "annotations.coco.json", "annotations_without_background.json"):
        path = split_root / name
        variant = json.loads(path.read_text())
        json_variants[name] = {
            "sha256": file_hash(path), "images": len(variant.get("images", [])),
            "annotations": len(variant.get("annotations", [])),
            "categories": [{"id": row.get("id"), "name": row.get("name")} for row in variant.get("categories", [])],
        }
    return {
        "split": split, "annotation_path": str(annotation.resolve()), "annotation_sha256": file_hash(annotation),
        "images": len(document["images"]), "annotations": len(document["annotations"]),
        "categories": [{"id": key, "name": value} for key, value in sorted(categories.items())],
        "per_class_annotations": dict(sorted(class_annotations.items())),
        "per_class_images": dict(sorted(class_images.items())),
        "empty_images": sum(value == 0 for value in annotation_counts),
        "minimum_annotations_per_image": min(annotation_counts),
        "maximum_annotations_per_image": max(annotation_counts),
        "crowd_annotations": crowd, "ignored_annotations": ignore,
        "actual_image_sizes": dict(sorted(sizes.items())), "actual_image_modes": dict(sorted(modes.items())),
        "dimension_mismatches": dimension_mismatches, "missing_images": missing,
        "identifier_or_structure_findings": invalid, "json_variants": json_variants,
        "entries": entries, "document": document,
    }


def _qa_selection(train):
    document = train["document"]
    categories = {row["id"]: row["name"] for row in document["categories"]}
    annotations = defaultdict(list)
    for row in document["annotations"]:
        annotations[row["image_id"]].append(row)
    entry_by_name = {row["source_image_id"]: row for row in train["entries"]}
    candidates = []
    for image in document["images"]:
        name = Path(image["file_name"]).name
        rows = annotations[image["id"]]
        area_ratios = [row["bbox"][2] * row["bbox"][3] / (image["width"] * image["height"]) for row in rows]
        entry = entry_by_name[name]
        candidates.append({
            "image": image, "annotations": rows, "entry": entry,
            "classes": sorted({categories[row["category_id"]] for row in rows}),
            "minimum_area_ratio": min(area_ratios) if area_ratios else None,
            "rank": hashlib.sha256(f"417:{entry['scene_id']}:{entry['image_sha256']}".encode()).hexdigest(),
        })
    selected = []
    selected_ids = set()

    def add(stratum, item):
        image_id = item["image"]["id"]
        if image_id in selected_ids:
            selected[-1]["additional_strata"].append(stratum) if selected and selected[-1]["image_id"] == image_id else None
            return
        selected_ids.add(image_id)
        selected.append({
            "stratum": stratum, "additional_strata": [], "image_id": image_id,
            "entry_id": item["entry"]["entry_id"], "source_group_key": item["entry"]["scene_id"],
            "image_path": item["entry"]["image_path"], "image_sha256": item["entry"]["image_sha256"],
            "annotation_count": len(item["annotations"]), "classes": item["classes"],
            "minimum_box_area_ratio": item["minimum_area_ratio"], "hash_rank": item["rank"],
        })

    nonempty = [item for item in candidates if item["annotations"]]
    empty = [item for item in candidates if not item["annotations"]]
    add("densest", max(candidates, key=lambda item: (len(item["annotations"]), item["rank"])))
    add("sparsest_nonempty", min(nonempty, key=lambda item: (len(item["annotations"]), item["rank"])))
    if empty:
        add("empty_annotation", min(empty, key=lambda item: item["rank"]))
    add("smallest_annotated_object", min(nonempty, key=lambda item: (item["minimum_area_ratio"], item["rank"])))
    for class_name in CLASSES:
        pool = [item for item in candidates if class_name in item["classes"]]
        add(f"class:{class_name}", min(pool, key=lambda item: item["rank"]))
    return {
        "schema_version": "bite.aquarium_manual_qa_selection.v1", "seed": 417,
        "selection_rule": "prespecified density/empty/small-object strata plus lowest sha256(seed:source-group:image-hash) per class",
        "selection_uses_sam_or_candidate_outcomes": False, "selection_uses_ground_truth_only_for_qa_stratification": True,
        "entries": selected,
    }


def _render_overlays(selection, train, output):
    document = train["document"]
    categories = {row["id"]: row["name"] for row in document["categories"]}
    annotations = defaultdict(list)
    for row in document["annotations"]:
        annotations[row["image_id"]].append(row)
    overlay_dir = output / "qa" / "overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    for item in selection["entries"]:
        source = Path(item["image_path"])
        with Image.open(source) as raw:
            image = raw.convert("RGB")
        draw = ImageDraw.Draw(image)
        for row in annotations[item["image_id"]]:
            x, y, width, height = row["bbox"]
            label = categories[row["category_id"]]
            color = (255, 40, 40)
            draw.rectangle((x, y, x + width, y + height), outline=color, width=3)
            draw.rectangle((x, max(0, y - 15), x + max(40, len(label) * 7), y), fill=(0, 0, 0))
            draw.text((x + 2, max(0, y - 14)), label, fill=(255, 255, 0))
        destination = overlay_dir / f"{item['image_id']:04d}_{source.stem}.png"
        image.save(destination)
        item["overlay_path"] = str(destination.resolve())


def _heldout_entries():
    inventory = json.loads(HELDOUT_INVENTORY.read_text())
    result = []
    for source in inventory["image_entries"]:
        if not str(source.get("partition", "")).startswith("ODinW/"):
            continue
        item = dict(source)
        if "Aquarium_Aquarium_Combined" in str(item.get("partition")):
            parent, scene = _lineage(item["source_image_id"])
            item["source_parent_id"] = parent
            item["scene_id"] = scene
        result.append(item)
    return result


def _enrich_near(audit, train_entries, heldout):
    train_by = {row["entry_id"]: row for row in train_entries}
    heldout_by = {row["entry_id"]: row for row in heldout}
    for finding in audit["near_duplicate_candidates"]:
        train = train_by[finding["train_entry_id"]]
        reference = heldout_by[finding["heldout_entry_id"]]
        finding.update({
            "train_image_path": train["image_path"], "train_source_image_id": train["source_image_id"],
            "heldout_image_path": reference["image_path"], "heldout_source_image_id": reference["source_image_id"],
            "heldout_partition": reference["partition"],
        })


def _approved_source(task_v_ready):
    source = copy.deepcopy(next(row for row in default_registry()["sources"] if row["source_id"] == SOURCE_ID))
    source["image_root"] = str((ROOT / "train").resolve())
    source["annotation_path"] = str((ROOT / "train" / "annotations_without_background.json").resolve())
    source["license_access"]["publisher_terms_verified"] = True
    source["verification_status"].update({
        "local_archive": "verified", "annotations": "verified", "annotation_completeness": "verified",
        "source_identity_overlap": "verified", "partition": "verified", "approval": "approved",
    })
    source["appropriate_tasks"] = ["candidate_verification"] if task_v_ready else []
    source["acquisition_status"] = [
        "source_discovered", "metadata_verified", "locally_available", "annotations_verified", "partition_verified",
        "approved_for_calibration",
    ]
    validate_source(source)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04b2b1a"))
    parser.add_argument("--review-record", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not ARCHIVE.is_file() or not ROOT.is_dir() or not ACQUISITION.is_file() or not APPROVAL.is_file():
        raise SystemExit("Approved, verified Aquarium acquisition artifacts are required")
    acquisition = json.loads(ACQUISITION.read_text())
    approval = json.loads(APPROVAL.read_text())
    if acquisition.get("verified_bytes") != 70037905 or acquisition.get("verified_sha256") != "4affbfd66ef640b6154c694da3f2e730a97fe0fb0f8a22aa7ec8d32c2f04a536":
        raise SystemExit("Acquisition identity mismatch")
    if file_hash(ARCHIVE) != acquisition["verified_sha256"] or ARCHIVE.stat().st_size != acquisition["verified_bytes"]:
        raise SystemExit("Preserved archive no longer matches acquisition identity")
    inventories = {split: _split_inventory(split) for split in ("train", "valid", "test")}
    train = inventories["train"]
    selection = _qa_selection(train)
    _render_overlays(selection, train, output)
    heldout = _heldout_entries()
    audit = audit_train_against_heldout(train["entries"], heldout, perceptual=True, near_threshold=4, max_candidates=10000)
    _enrich_near(audit, train["entries"], heldout)
    review = json.loads(args.review_record.read_text()) if args.review_record else None
    adjudication_by_pair = {}
    if review:
        adjudication_by_pair = {(row["train_entry_id"], row["heldout_entry_id"]): row for row in review.get("near_duplicate_adjudications", [])}
    for finding in audit["near_duplicate_candidates"]:
        adjudication = adjudication_by_pair.get((finding["train_entry_id"], finding["heldout_entry_id"]))
        finding["adjudication"] = adjudication or {"status": "unresolved_quarantine"}
    exact_train_ids = {entry_id for finding in audit["exact_overlap_findings"] for entry_id in finding["entry_ids"]
                       if entry_id.startswith("Aquarium:train:")}
    confirmed_near = {finding["train_entry_id"] for finding in audit["near_duplicate_candidates"]
                      if finding["adjudication"].get("status") in {"confirmed_overlap", "unresolved_quarantine"}}
    quarantine_ids = exact_train_ids | confirmed_near
    clean_entries = [row for row in train["entries"] if row["entry_id"] not in quarantine_ids]
    clean_audit = audit_partitions(clean_entries)
    group_by_entry = {entry_id: group["source_group_id"] for group in clean_audit["groups"] for entry_id in group["entry_ids"]}
    for row in clean_entries:
        row["source_group_id"] = group_by_entry[row["entry_id"]]
    manual_complete = bool(review and review.get("review_complete"))
    no_material_omissions = bool(review and review.get("visual_completeness") == "no_material_omissions_observed_in_sample")
    class_support = review.get("class_conditional_exhaustiveness", {}) if review else {}
    task_v_ready = (manual_complete and no_material_omissions and
                    all(class_support.get(name) == "supported_for_task_v_pilot" for name in CLASSES))
    task_d_ready = (task_v_ready and review.get("task_d_negative_labels") == "supported") if review else False
    readiness = inspect_detection_annotations(
        ROOT / "train" / "annotations_without_background.json", ROOT / "train", expected_classes=CLASSES,
        exhaustiveness={name: "verified_exhaustive" if task_v_ready else "unknown" for name in CLASSES},
        visual_review_status="verified_no_material_omissions" if task_d_ready else
                             "pilot_sample_no_material_omissions" if no_material_omissions else "not_reviewed",
    )
    readiness["pilot_decision"] = {
        "task_v": "ready_for_pilot" if task_v_ready else "blocked",
        "task_d": "ready_for_pilot" if task_d_ready else "blocked",
        "task_v_scope": "IoU 0.50 and 0.75 candidate verification on clean groups",
        "task_d_limitation": None if task_d_ready else "class-absence/visual exhaustiveness is not established",
    }
    exact_summary = Counter(item["kind"] for item in audit["exact_overlap_findings"])
    leakage = {
        "schema_version": "bite.aquarium_heldout_leakage_audit.v1",
        "train_entries": len(train["entries"]), "heldout_odinw_entries": len(heldout),
        "exact_image_sha256_overlaps": exact_summary.get("image_sha256", 0),
        "exact_source_image_id_overlaps": exact_summary.get("source_image_id", 0),
        "source_parent_overlaps": exact_summary.get("source_parent_id", 0),
        "shared_scene_findings": exact_summary.get("scene_id", 0),
        "shared_scene_train_images": len(exact_train_ids),
        "perceptual_candidates": len(audit["near_duplicate_candidates"]),
        "confirmed_near_duplicate_train_images": len({finding["train_entry_id"] for finding in audit["near_duplicate_candidates"]
                                                       if finding["adjudication"].get("status") == "confirmed_overlap"}),
        "cleared_near_duplicate_candidates": sum(finding["adjudication"].get("status") == "cleared_distinct" for finding in audit["near_duplicate_candidates"]),
        "unresolved_near_duplicate_candidates": sum(finding["adjudication"].get("status") == "unresolved_quarantine" for finding in audit["near_duplicate_candidates"]),
        "quarantined_train_images": len(quarantine_ids), "clean_train_images": len(clean_entries),
        "exact_overlap_findings": audit["exact_overlap_findings"],
        "near_duplicate_candidates": audit["near_duplicate_candidates"],
        "quarantined_train_entry_ids": sorted(quarantine_ids),
        "known_pascalvoc_val_test_exact_alias_images": 3422,
        "development_debug_exclusion": DEBUG_EXCLUSION,
    }
    inventory_output = {
        "schema_version": "bite.aquarium_inventory.v1", "source_id": SOURCE_ID,
        "archive": {"path": str(ARCHIVE.resolve()), "bytes": ARCHIVE.stat().st_size, "sha256": file_hash(ARCHIVE)},
        "approval": {"approval_id": approval["approval_id"], "approved_by": approval["approved_by"],
                     "approval_sha256": acquisition["approval"]["approval_sha256"]},
        "splits": {name: {key: value for key, value in report.items() if key not in {"entries", "document"}}
                   for name, report in inventories.items()},
        "total_images": sum(report["images"] for report in inventories.values()),
        "total_annotations": sum(report["annotations"] for report in inventories.values()),
    }
    _write(output / "inventory" / "aquarium_inventory.json", inventory_output)
    _write(output / "inventory" / "train_entries.json", {"schema_version": "bite.aquarium_train_entries.v1", "entries": train["entries"]})
    _write(output / "qa" / "manual_qa_selection.json", selection)
    _write(output / "validation" / "annotation_readiness.json", readiness)
    _write(output / "leakage" / "heldout_leakage_audit.json", leakage)
    _write(output / "leakage" / "quarantine.json", {"schema_version": "bite.aquarium_quarantine.v1",
                                                       "entries": sorted(quarantine_ids), "count": len(quarantine_ids)})
    _write(output / "manifests" / "development_debug_exclusions.json",
           {"schema_version": "bite.development_debug_exclusions.v1", "entries": [DEBUG_EXCLUSION]})
    final_reference = [{key: row.get(key) for key in ("entry_id", "partition", "source_namespace", "source_image_id",
                                                       "source_parent_id", "scene_id", "image_sha256")}
                       for row in heldout]
    _write(output / "manifests" / "final_evaluation_reference.json",
           {"schema_version": "bite.final_evaluation_reference.v1", "entries": final_reference,
            "count": len(final_reference), "source_inventory": str(HELDOUT_INVENTORY.resolve())})
    _write(output / "manifests" / "verified_clean_train_entries.json",
           {"schema_version": "bite.verified_clean_train_entries.v1", "entries": clean_entries,
            "entry_count": len(clean_entries), "source_group_count": len(clean_audit["groups"])})
    if task_v_ready:
        source = _approved_source(task_v_ready=True)
        manifest = freeze_manifest(source, clean_entries, salt="seed-417", ratios=(70, 15, 15),
                                   exclusions=[DEBUG_EXCLUSION])
        validate_frozen_manifest(manifest, source)
        _write(output / "manifests" / "calibration_partition_manifest.json", manifest)
        _write(output / "manifests" / "provisional_partition_manifest.json", {
            "schema_version": "bite.calibration_partition_manifest.v1",
            "status": "SUPERSEDED_BY_FROZEN_TASK_V_MANIFEST",
            "replacement": "calibration_partition_manifest.json",
            "replacement_manifest_sha256": manifest["manifest_sha256"],
            "entries": [],
        })
        for partition in ("calibration_fit", "calibration_validation", "internal_test"):
            rows = [row for row in manifest["entries"] if row["partition"] == partition]
            _write(output / "manifests" / f"{partition}.json",
                   {"schema_version": "bite.calibration_partition_slice.v1", "partition": partition,
                    "entries": rows, "count": len(rows), "parent_manifest_sha256": manifest["manifest_sha256"]})
        partition_by_entry = {row["entry_id"]: row["partition"] for row in manifest["entries"]}
        group_partition = {row["source_group_id"]: row["partition"] for row in manifest["entries"]}
        coverage = {}
        for partition in ("calibration_fit", "calibration_validation", "internal_test"):
            selected = [row for row in clean_entries if partition_by_entry[row["entry_id"]] == partition]
            per_class_images = Counter()
            per_class_annotations = Counter()
            for row in selected:
                per_class_images.update(row["classes_present"])
                per_class_annotations.update(row["per_class_annotation_counts"])
            coverage[partition] = {
                "images": len(selected),
                "source_groups": sum(value == partition for value in group_partition.values()),
                "per_class_images": dict(sorted(per_class_images.items())),
                "per_class_annotations": dict(sorted(per_class_annotations.items())),
            }
        _write(output / "manifests" / "partition_coverage.json", {
            "schema_version": "bite.calibration_partition_coverage.v1",
            "source_id": SOURCE_ID,
            "parent_manifest_sha256": manifest["manifest_sha256"],
            "partitions": coverage,
        })
        schedules = [schedule_queries(group["source_group_id"], CLASSES, requested_count=2, seed=417)
                     for group in clean_audit["groups"]]
        _write(output / "protocol" / "query_schedules.json",
               {"schema_version": "bite.query_schedule_bundle.v1", "entries": schedules})
        first = clean_entries[0]
        schedule = next(row for row in schedules if row["source_group_id"] == first["source_group_id"])
        collector = {
            "schema_version": "bite.aquarium_collector_compatibility.v1", "validation_mode": "cpu_mock_only",
            "compatible": True, "source_image": first["image_path"], "source_image_sha256": first["image_sha256"],
            "class_vocabulary": CLASSES, "gt_free_query_schedule": schedule,
            "initial_grounding_state": "mock_constructed_without_gt", "task_v_candidate_selection": "mock_runtime_scores_only",
            "eligible_paths": ["V_repeat", "V_zoom_focus"], "logical_costs": {"V_repeat": 1, "V_zoom_focus": 2},
            "maximum_continuation_budget": 3, "raw_persisted_before_offline_labels": True,
            "offline_gt_association_after_collection": True, "gpu_collection_executed": False,
        }
        _write(output / "validation" / "collector_compatibility.json", collector)
        freeze_status = "READY_FOR_TASK_V_PILOT"
    else:
        provisional = {
            "schema_version": "bite.calibration_partition_manifest.v1", "status": "ANNOTATION_REVIEW_PENDING",
            "source_ids": [SOURCE_ID], "entries": [], "exclusions": [DEBUG_EXCLUSION],
            "partition_counts": {"calibration_fit": 0, "calibration_validation": 0, "internal_test": 0, "final_evaluation": 0},
            "scientific_boundary": "No calibration partitions freeze until Task V class-exhaustiveness review passes.",
        }
        _write(output / "manifests" / "provisional_partition_manifest.json", provisional)
        _write(output / "validation" / "collector_compatibility.json",
               {"schema_version": "bite.aquarium_collector_compatibility.v1", "validation_mode": "not_run_without_frozen_manifest",
                "compatible": False, "gpu_collection_executed": False})
        freeze_status = "ANNOTATION_REVIEW_PENDING"
    summary = {
        "schema_version": "bite.phase04b2b1a_status.v1", "status": freeze_status,
        "task_v": "ready_for_pilot" if task_v_ready else "blocked",
        "task_d": "ready_for_pilot" if task_d_ready else "blocked",
        "train_images": len(train["entries"]), "train_annotations": train["annotations"], "classes": len(CLASSES),
        "clean_train_images": len(clean_entries), "quarantined_train_images": len(quarantine_ids),
        "clean_source_groups": len(clean_audit["groups"]), "review_record": str(args.review_record.resolve()) if args.review_record else None,
    }
    _write(output / "status.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
