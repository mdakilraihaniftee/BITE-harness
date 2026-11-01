"""Local COCO/LVIS structural and content-identity verification."""

from __future__ import annotations

import json
from pathlib import Path

from .common import file_hash, identity
from .split_integrity import audit_partitions


def verify_detection_source(source, heldout_entries=()):
    annotation = Path(source.get("annotation_path") or "")
    image_root = Path(source.get("image_root") or "")
    report = {
        "schema_version": "bite.calibration_source_verification.v1",
        "source_id": source["source_id"],
        "verified": False,
        "checks": {},
        "entries": [],
        "partition_audit": None,
        "approval_eligible": False,
    }
    report["checks"]["annotation_exists"] = annotation.is_file()
    report["checks"]["image_root_exists"] = image_root.is_dir()
    if not annotation.is_file() or not image_root.is_dir():
        report["reason"] = "local_paths_missing"
        return report
    try:
        document = json.loads(annotation.read_text())
    except (OSError, json.JSONDecodeError) as error:
        report["reason"] = f"annotation_unreadable:{type(error).__name__}"
        return report
    required = all(isinstance(document.get(key), list) for key in ("images", "annotations", "categories"))
    report["checks"]["detection_structure"] = required
    if not required:
        report["reason"] = "not_coco_or_lvis_detection_json"
        return report
    image_ids = {image.get("id") for image in document["images"]}
    category_ids = {category.get("id") for category in document["categories"]}
    category_names = {str(category.get("name", "")).casefold() for category in document["categories"]}
    required_classes = source.get("classes") if isinstance(source.get("classes"), list) else []
    report["checks"]["required_class_mapping_known"] = all(str(name).casefold() in category_names for name in required_classes)
    valid_annotations = True
    for ann in document["annotations"]:
        box = ann.get("bbox")
        if ann.get("image_id") not in image_ids or ann.get("category_id") not in category_ids:
            valid_annotations = False
        if not isinstance(box, list) or len(box) != 4 or box[2] <= 0 or box[3] <= 0:
            valid_annotations = False
    report["checks"]["annotation_references_and_boxes_valid"] = valid_annotations
    namespace = source["source_id"]
    missing = []
    for image in document["images"]:
        relative = image.get("file_name") or Path(image.get("coco_url", "")).name
        path = image_root / relative
        if not path.is_file() and relative:
            path = image_root / Path(relative).name
        if not path.is_file():
            missing.append(relative)
            continue
        digest = file_hash(path)
        report["entries"].append({
            "entry_id": identity([source["source_id"], image.get("id"), digest], "source_entry"),
            "partition": f"candidate/{source['source_id']}",
            "source_namespace": namespace,
            "source_image_id": relative,
            "source_parent_id": image.get("source_parent_id"),
            "scene_id": image.get("scene_id"),
            "image_path": str(path.resolve()),
            "image_sha256": digest,
            "annotation_file": str(annotation.resolve()),
            "annotation_sha256": file_hash(annotation),
        })
    report["checks"]["all_images_present"] = not missing and len(report["entries"]) == len(document["images"])
    report["missing_image_count"] = len(missing)
    combined = list(report["entries"]) + [dict(entry) for entry in heldout_entries]
    report["partition_audit"] = audit_partitions(combined)
    candidate_prefix = f"candidate/{source['source_id']}"
    overlaps = [item for item in report["partition_audit"]["overlaps"] if candidate_prefix in item["partitions"] and len(item["partitions"]) > 1]
    report["checks"]["no_exact_or_declared_heldout_overlap"] = not overlaps
    report["heldout_overlap_findings"] = overlaps
    report["checks"]["annotation_completeness_verified"] = source.get("verification_status", {}).get("annotation_completeness") == "verified"
    report["verified"] = all(report["checks"].values())
    report["approval_eligible"] = report["verified"] and bool(source.get("license_access", {}).get("publisher_terms_verified"))
    report["reason"] = None if report["verified"] else "one_or_more_verification_checks_failed"
    return report
