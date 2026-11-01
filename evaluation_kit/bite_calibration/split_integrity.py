"""Content/identity grouping precedes any partition assignment."""
from collections import defaultdict
from pathlib import Path
from .common import identity


def audit_partitions(entries):
    """Audit declared partitions, retaining all duplicate evidence and group members.

    Source IDs must be globally meaningful within source_namespace. Annotation
    numeric image IDs, often restarted in every split, are not source identities.
    Shared annotation files are a leakage finding, not an assertion that all
    images inside one COCO file depict the same scene.
    """
    entries = list(entries)
    parent = list(range(len(entries)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    buckets = defaultdict(list)
    for index, row in enumerate(entries):
        features = {
            "image_sha256": row.get("image_sha256"),
            "image_path": str(Path(row["image_path"]).resolve()) if row.get("image_path") else None,
            "source_image_id": (row.get("source_namespace"), row.get("source_image_id")) if row.get("source_image_id") is not None else None,
            "scene_id": (row.get("source_namespace"), row.get("scene_id")) if row.get("scene_id") is not None else None,
            # Explicit common-source metadata groups crops/augmentations with parents.
            "source_parent_id": (row.get("source_namespace"), row.get("source_parent_id", row.get("source_image_id")))
                if row.get("source_parent_id", row.get("source_image_id")) is not None else None,
            "annotation_file": str(Path(row["annotation_file"]).resolve()) if row.get("annotation_file") else None,
            "annotation_sha256": row.get("annotation_sha256"),
        }
        for kind, value in features.items():
            if value is not None:
                buckets[(kind, value)].append(index)
    overlaps = []
    duplicate_counts = defaultdict(int)
    for (kind, value), indices in buckets.items():
        if kind not in {"annotation_file", "annotation_sha256"}:
            for index in indices[1:]:
                parent[find(index)] = find(indices[0])
        if len(indices) > 1:
            duplicate_counts[kind] += 1
        partitions = sorted({entries[i]["partition"] for i in indices})
        if len(partitions) > 1:
            overlaps.append({"kind": kind, "identity": value, "partitions": partitions,
                             "entry_ids": [entries[i]["entry_id"] for i in indices]})
    components = defaultdict(list)
    for index in range(len(entries)):
        components[find(index)].append(entries[index])
    groups = []
    for rows in components.values():
        hashes = sorted({r["image_sha256"] for r in rows if r.get("image_sha256")})
        group_id = ("sha256:" + hashes[0]) if len(hashes) == 1 else identity(sorted(r["entry_id"] for r in rows), "source_group")
        groups.append({"source_group_id": group_id, "image_hashes": hashes,
                       "entry_ids": sorted(r["entry_id"] for r in rows),
                       "source_partitions": sorted({r["partition"] for r in rows}),
                       "assigned_partition": None, "assignment_status": "unassigned_provisional"})
    return {"schema_version": "bite.split_integrity.v1", "entry_count": len(entries),
            "hashed_entry_count": sum(bool(r.get("image_sha256")) for r in entries),
            "cross_partition_overlap_count": len(overlaps), "overlaps": overlaps,
            "duplicate_identity_counts": dict(duplicate_counts),
            "groups": sorted(groups, key=lambda g: g["source_group_id"]),
            "near_duplicate_audit": "Not performed; exact bytes and explicit source/scene/parent identities only"}


def validate_partition_manifest(manifest):
    """Reject group/crop splits even if the sample and action IDs differ."""
    if manifest.get("status") != "frozen":
        raise ValueError("Calibration partitions must be explicitly frozen, not provisional")
    grouped = defaultdict(set)
    group_by_hash = defaultdict(set)
    for entry in manifest.get("entries", []):
        if not entry.get("source_group_id") or not entry.get("image_sha256"):
            raise ValueError("Partition entries require verified source group and image hash")
        group_by_hash[entry["image_sha256"]].add(entry["source_group_id"])
        for key in ["source_group_id", "image_sha256", "scene_id", "source_parent_id"]:
            if entry.get(key):
                grouped[(key, entry[key])].add(entry["partition"])
    if any(len(p) > 1 for p in grouped.values()):
        raise ValueError("Source group, image, scene or parent occurs in multiple partitions")
    if any(len(g) > 1 for g in group_by_hash.values()):
        raise ValueError("Identical image hash assigned inconsistent source groups")
    if not manifest.get("entries"):
        raise ValueError("Empty partition manifest")
    return True
