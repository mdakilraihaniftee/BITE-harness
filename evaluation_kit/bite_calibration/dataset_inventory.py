"""Read-only local dataset inventory. No dataset constructors or downloads."""
import csv
import json
from pathlib import Path
import yaml
from .common import file_hash
from .split_integrity import audit_partitions


def audit_sources(data_root):
    root = Path(data_root).resolve()
    entries, mappings, tsvs = [], [], []
    hash_cache = {}

    def hashed(path):
        path = path.resolve()
        if path not in hash_cache:
            hash_cache[path] = file_hash(path)
        return hash_cache[path]

    for config in sorted((root/"GLIP/configs/odinw_13").glob("*.yaml")):
        cfg = yaml.safe_load(config.read_text())
        domain = config.stem
        for split, spec in cfg.get("DATASETS", {}).get("REGISTER", {}).items():
            if split not in {"train", "val", "test"}:
                continue
            annotation = root/"GLIP/DATASET"/spec["ann_file"]
            mapping = {"domain": domain, "split": split, "annotation_file": str(annotation),
                       "exists": annotation.is_file(), "config": str(config)}
            mappings.append(mapping)
            if not annotation.is_file():
                continue
            doc = json.loads(annotation.read_text())
            mapping.update(annotation_sha256=hashed(annotation), images=len(doc["images"]),
                           annotations=len(doc["annotations"]), licenses_declared=doc.get("licenses", []),
                           source_info=doc.get("info", {}), license_verification="metadata_claim_not_independent_permission_verification")
            for image in doc["images"]:
                path = root/"images/ODinW"/domain/Path(image["file_name"]).name
                entries.append({"entry_id": f"ODinW:{domain}:{split}:{image['id']}",
                                "partition": f"ODinW/{domain}/{split}", "source_namespace": f"ODinW/{domain}",
                                "source_image_id": image["file_name"], "annotation_image_id": image["id"],
                                "image_path": str(path), "image_exists": path.is_file(),
                                "image_sha256": hashed(path) if path.is_file() else None,
                                "annotation_file": str(annotation), "annotation_sha256": mapping["annotation_sha256"], "scene_id": None})
    fsc_rows = {}
    for tsv in sorted(root.glob("*.tsv")):
        with tsv.open(newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            rows = list(reader)
            fields = reader.fieldnames or []
        has_detection = all(k in fields for k in ["image_width", "image_height", "category_id", "answer"])
        tsvs.append({"path": str(tsv), "rows": len(rows), "columns": fields, "sha256": hashed(tsv),
                     "label_kind": "prepared_detection_boxes" if has_detection else "count_or_other_not_detection_boxes"})
        if tsv.stem == "FSC147_val":
            fsc_rows = {r["image_path"]: r for r in rows}
    for image in sorted((root/"images/FSC147").glob("*")):
        if not image.is_file():
            continue
        split = "val" if image.name in fsc_rows else "unassigned_local_images"
        entries.append({"entry_id": f"FSC147:{image.name}", "partition": f"FSC147/{split}",
                        "source_namespace": "FSC147", "source_image_id": image.name,
                        "image_path": str(image), "image_sha256": hashed(image), "image_exists": True,
                        "annotation_file": None, "scene_id": None})
    expected = ["FSCD_147_bbox_val", "FSCD_147_bbox_test", "FSCD_LVIS_bbox_train",
                "FSCD_LVIS_bbox_val", "FSCD_LVIS_bbox_test", "FSCD_LVIS_unseen_bbox_train", "FSCD_LVIS_unseen_bbox_test"]
    inventory = {"schema_version": "bite.dataset_inventory.v1", "data_root": str(root),
                 "odinw_mappings": mappings, "tsvs": tsvs,
                 "missing_prepared_detection_tsvs": [x for x in expected if not (root/(x+".tsv")).is_file()],
                 "train_named_annotation_files": [str(f) for f in root.rglob("*.json") if "train" in str(f.relative_to(root)).lower()],
                 "images_missing_from_annotation_inventory": sum(not r["image_exists"] for r in entries),
                 "license_clearance_complete": False, "clean_final_holdout_established": False,
                 "partition_decision": "Unresolved: acquire verified disjoint training labels; current manifests are unassigned, not calibration partitions",
                 "image_entries": entries}
    return inventory, audit_partitions(entries)
