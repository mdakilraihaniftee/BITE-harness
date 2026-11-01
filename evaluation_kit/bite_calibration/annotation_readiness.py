"""Structural annotation audit and separate Task V/Task D readiness gates."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .common import file_hash, identity


READINESS_VERSION = "bite.annotation_readiness.v1"


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def inspect_detection_annotations(annotation_path, image_root, *, expected_classes,
                                   exhaustiveness=None, visual_review_status="not_reviewed"):
    annotation_path = Path(annotation_path).resolve()
    image_root = Path(image_root).resolve()
    document = json.loads(annotation_path.read_text())
    findings = []
    for key in ("images", "annotations", "categories"):
        if not isinstance(document.get(key), list):
            raise ValueError(f"Annotation document requires list field: {key}")
    images = document["images"]
    categories = document["categories"]
    annotations = document["annotations"]
    image_by_id = {}
    for image in images:
        image_id = image.get("id")
        if image_id in image_by_id:
            findings.append({"kind": "duplicate_image_id", "id": image_id})
        width, height = image.get("width"), image.get("height")
        if not _finite_number(width) or not _finite_number(height) or width <= 0 or height <= 0:
            findings.append({"kind": "invalid_image_dimensions", "id": image_id})
        image_by_id[image_id] = image
    category_by_id = {}
    for category in categories:
        category_id = category.get("id")
        if category_id in category_by_id:
            findings.append({"kind": "duplicate_category_id", "id": category_id})
        if not isinstance(category.get("name"), str) or not category["name"].strip():
            findings.append({"kind": "invalid_category_name", "id": category_id})
        category_by_id[category_id] = category
    available = {category["name"].strip().casefold(): category["name"].strip()
                 for category in categories if isinstance(category.get("name"), str)}
    missing_classes = [name for name in expected_classes if name.strip().casefold() not in available]
    if missing_classes:
        findings.append({"kind": "missing_required_classes", "classes": missing_classes})
    annotation_ids = set()
    annotation_count_by_image = {image_id: 0 for image_id in image_by_id}
    crowd_count = ignore_count = 0
    for ann in annotations:
        annotation_id = ann.get("id")
        if annotation_id in annotation_ids:
            findings.append({"kind": "duplicate_annotation_id", "id": annotation_id})
        annotation_ids.add(annotation_id)
        image = image_by_id.get(ann.get("image_id"))
        if image is None:
            findings.append({"kind": "unknown_annotation_image", "annotation_id": annotation_id})
        else:
            annotation_count_by_image[ann["image_id"]] += 1
        if ann.get("category_id") not in category_by_id:
            findings.append({"kind": "unknown_annotation_category", "annotation_id": annotation_id})
        box = ann.get("bbox")
        if not isinstance(box, list) or len(box) != 4 or not all(_finite_number(value) for value in box):
            findings.append({"kind": "invalid_bbox", "annotation_id": annotation_id})
        elif image is not None:
            x, y, width, height = box
            if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > image["width"] + 1e-6 or y + height > image["height"] + 1e-6:
                findings.append({"kind": "invalid_bbox_geometry", "annotation_id": annotation_id, "bbox": box})
        for flag in ("iscrowd", "ignore"):
            value = ann.get(flag, 0)
            if value not in (0, 1, False, True):
                findings.append({"kind": "invalid_annotation_flag", "annotation_id": annotation_id, "field": flag})
        crowd_count += int(bool(ann.get("iscrowd", 0)))
        ignore_count += int(bool(ann.get("ignore", 0)))
    entries = []
    missing_images = []
    for image in images:
        relative = image.get("file_name")
        if not isinstance(relative, str) or not relative:
            missing_images.append({"image_id": image.get("id"), "reason": "missing_file_name"})
            continue
        path = image_root / relative
        if not path.is_file():
            path = image_root / Path(relative).name
        if not path.is_file():
            missing_images.append({"image_id": image.get("id"), "file_name": relative})
            continue
        digest = file_hash(path)
        entries.append({
            "entry_id": identity([str(annotation_path), image.get("id"), digest], "source_entry"),
            "source_image_id": relative, "source_parent_id": image.get("source_parent_id"),
            "scene_id": image.get("scene_id"), "image_path": str(path.resolve()),
            "image_sha256": digest, "annotation_file": str(annotation_path),
            "annotation_sha256": file_hash(annotation_path),
        })
    if missing_images:
        findings.append({"kind": "missing_images", "count": len(missing_images)})
    structural_complete = not findings
    declarations = {name: (exhaustiveness or {}).get(name, "unknown") for name in expected_classes}
    unknown_exhaustiveness = [name for name, status in declarations.items() if status != "verified_exhaustive"]
    task_v_ready = structural_complete and not unknown_exhaustiveness
    task_d_ready = task_v_ready and visual_review_status == "verified_no_material_omissions"
    return {
        "schema_version": READINESS_VERSION,
        "annotation_path": str(annotation_path), "annotation_sha256": file_hash(annotation_path),
        "image_root": str(image_root), "images": len(images), "annotations": len(annotations),
        "categories": [category.get("name") for category in categories],
        "empty_image_ids": sorted(image_id for image_id, count in annotation_count_by_image.items() if count == 0),
        "crowd_annotations": crowd_count, "ignored_annotations": ignore_count,
        "structural_completeness": "verified" if structural_complete else "failed",
        "structural_findings": findings, "missing_images": missing_images,
        "class_conditional_exhaustiveness": declarations,
        "visual_completeness": visual_review_status,
        "task_v_readiness": "ready" if task_v_ready else "blocked",
        "task_v_reason": None if task_v_ready else "structural_or_class_exhaustiveness_unverified",
        "task_d_readiness": "ready" if task_d_ready else "blocked",
        "task_d_reason": None if task_d_ready else "visual_completeness_or_class_absence_unsupported",
        "entries": entries,
    }


def select_manual_qa(entries, *, count, seed=417):
    if count < 0:
        raise ValueError("Manual QA count cannot be negative")
    ranked = sorted(entries, key=lambda entry: hashlib.sha256(
        f"{seed}:{entry.get('source_group_id', entry.get('image_sha256'))}".encode()).hexdigest())
    selected = ranked[:min(count, len(ranked))]
    return {
        "schema_version": "bite.annotation_manual_qa.v1", "seed": seed,
        "selection_rule": "lowest sha256(seed:source_group_id_or_image_sha256)",
        "requested_count": count, "actual_count": len(selected),
        "entries": [{"entry_id": item.get("entry_id"), "image_path": item.get("image_path"),
                     "image_sha256": item.get("image_sha256"), "review_status": "pending"}
                    for item in selected],
        "selection_uses_detection_outcomes": False,
    }
