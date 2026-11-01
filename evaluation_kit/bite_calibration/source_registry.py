"""Versioned calibration-source metadata with no acquisition side effects."""

from __future__ import annotations

import copy
from pathlib import Path


REGISTRY_VERSION = "bite.calibration_source_registry.v1"
SOURCE_STATUSES = (
    "source_discovered",
    "metadata_verified",
    "locally_available",
    "annotations_verified",
    "license_review_required",
    "partition_verified",
    "approved_for_calibration",
    "unavailable",
)

_ODINW = {
    "AerialMaritimeDrone_large": ("AerialMaritimeDrone", 47681829, "4bf97c0e0f0264bc2c778114d8da70114ab01be3ccb71033e8cea30201f874bd", ["boat", "car", "dock", "jetski", "lift"], "Public Domain"),
    "Aquarium_Aquarium_Combined.v2-raw-1024.coco": ("Aquarium", 70037905, "4affbfd66ef640b6154c694da3f2e730a97fe0fb0f8a22aa7ec8d32c2f04a536", ["fish", "jellyfish", "penguin", "puffin", "shark", "starfish", "stingray"], "CC BY 4.0"),
    "CottontailRabbits": ("CottontailRabbits", 153305581, "ccf510a1fe0ffbae37f6a4227a27f882444ddf86c3c1bd7802a72c6b4ee83870", ["Cottontail-Rabbit"], "Public Domain"),
    "EgoHands_generic": ("EgoHands", 720990333, "f6bb5ee1ddf81a84b9d2566a02eaebcda0701d32d84fb9afa22f3e78ae7d152c", ["hand"], "CC BY 4.0"),
    "NorthAmericaMushrooms_North_American_Mushrooms.v1-416x416.coco": ("NorthAmericaMushrooms", 9804594, "1ce68a64cc45f09e9c263b444b17e193ee1fbac6d9f5d3a9da17cf3ae2a88ba0", ["CoW", "chanterelle"], "Public Domain"),
    "Packages_Raw": ("Packages", 10768880, "0a5eb9f86407f9cd71932686ed5e5124f01e3006a43c9946b0615e9b21bb7d68", ["package"], "Public Domain"),
    "PascalVOC": ("PascalVOC", 740774846, "670a574991d516e94570722d842b874d14c47db5d20ce8aeabc3bb266bb7794c", ["aeroplane", "bicycle", "bird", "boat", "bottle", "bus", "car", "cat", "chair", "cow", "diningtable", "dog", "horse", "motorbike", "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor"], "CC BY 4.0"),
    "Raccoon_Raccoon.v2-raw.coco": ("Raccoon", 27092904, "52e86c2debf427c6184b6fe93e09df4f4c540b2f0b9dcd6f34fb87a8ff60b914", ["raccoon"], "MIT"),
    "ShellfishOpenImages_raw": ("ShellfishOpenImages", 153436493, "b2da220eedcfb5085bc69221cb8e7f3ad27ca6b5e77b9b0d523f217fd1e00c2e", ["Crab", "Lobster", "Shrimp"], "CC BY 4.0"),
    "VehiclesOpenImages_416x416": ("VehiclesOpenImages", 87006326, "0b70ec3947334836d4e2457bc32c4b2ecbc1652e43f4fdeb24b362b266c1626a", ["Ambulance", "Bus", "Car", "Motorcycle", "Truck"], "CC BY 4.0"),
    "pistols_export": ("pistols", 121434350, "0a3627abeb1c1b34f56953e4e615ee1f67e5651e551cb515ec44d9c8d22adc18", ["pistol"], "Public Domain"),
    "pothole": ("pothole", 96656058, "c1ace1ef64c47ba99b066a4100c17c23d74cd4746782339c0c9c45eceaf44ee5", ["pothole"], "ODbL v1.0"),
    "thermalDogsAndPeople": ("thermalDogsAndPeople", 10072076, "879bddcd071b93125919b7764cae45e9551b5622d1f1ec2352b51b8f65797679", ["dog", "person"], "Unknown"),
}


def _odinw_record(domain, values):
    archive, size, digest, classes, license_name = values
    return {
        "source_id": f"odinw13:{domain}",
        "dataset_name": "ODinW-13",
        "original_publisher": "Roboflow source datasets; GLIP-curated archive by Microsoft",
        "publisher_url": "https://github.com/microsoft/GLIP#the-object-detection-in-the-wild-benchmark",
        "source_type": "official_project_hosted_archive",
        "domain": domain,
        "release_version": "GLIP odinw_35 host commit 66ee3ae9a3b8cee0cf78f10ef5fc9a3725db02a1",
        "annotation_format": "COCO detection JSON",
        "label_completeness": "publisher_declared_detection_labels_unverified_until_local_archive_audit",
        "partitions": ["train", "val", "test"],
        "classes": classes,
        "archive": {
            "url": f"https://huggingface.co/GLIPModel/GLIP/resolve/main/odinw_35/{archive}.zip",
            "bytes": size,
            "sha256": digest,
            "destination_relative": f"ODinW-13/{archive}.zip",
        },
        "image_root": None,
        "annotation_path": None,
        "image_content_hashes": [],
        "known_alias_or_duplicate_groups": ["PascalVOC val/test alias"] if domain == "PascalVOC" else [],
        "license_access": {
            "local_export_metadata_claim": license_name,
            "publisher_terms_verified": False,
            "credentials_required": False,
            "user_acceptance_required": False,
            "review_note": "Per-domain image and annotation terms require human review; archive hosting is not blanket permission.",
        },
        "acquisition_status": ["source_discovered", "metadata_verified", "license_review_required"],
        "verification_status": {
            "archive_metadata": "verified",
            "local_archive": "not_downloaded",
            "annotations": "not_verified",
            "annotation_completeness": "not_verified",
            "source_identity_overlap": "not_audited",
            "partition": "not_verified",
            "approval": "not_approved",
        },
        "appropriate_tasks": ["candidate_verification", "object_discovery"],
        "domain_shift_note": "Preferred in-family source; train-to-heldout identity and scene overlap still require audit.",
    }


def default_registry():
    sources = [_odinw_record(domain, values) for domain, values in _ODINW.items()]
    sources.extend([
        {
            "source_id": "coco:2017-train-detection", "dataset_name": "COCO 2017", "original_publisher": "COCO Consortium",
            "publisher_url": "https://cocodataset.org/#download", "source_type": "alternative_official_dataset", "domain": "common_objects_in_context",
            "release_version": "2017", "annotation_format": "COCO detection JSON", "label_completeness": "exhaustive_for_80_declared_categories_under_COCO_protocol",
            "partitions": ["train2017"], "classes": "80 COCO thing categories", "image_root": None, "annotation_path": None,
            "image_content_hashes": [], "known_alias_or_duplicate_groups": [],
            "archives": [
                {"url": "http://images.cocodataset.org/zips/train2017.zip", "bytes": 19336861798, "etag": "62ff7d7fbcc7e0c0604cbb0f9047ce77-2306", "destination_relative": "COCO/train2017.zip"},
                {"url": "http://images.cocodataset.org/annotations/annotations_trainval2017.zip", "bytes": 252907541, "etag": "f4bbac642086de4f52a3fdda2de5fa2c", "destination_relative": "COCO/annotations_trainval2017.zip"},
            ],
            "license_access": {"annotations": "CC BY 4.0", "images": "Underlying Flickr terms/licenses; COCO disclaims image copyright", "publisher_terms_verified": True, "credentials_required": False, "review_note": "Retain attribution and review per-image use/redistribution constraints."},
            "acquisition_status": ["source_discovered", "metadata_verified", "license_review_required"],
            "verification_status": {"archive_metadata": "verified", "local_archive": "not_downloaded", "annotations": "not_verified", "annotation_completeness": "not_verified", "source_identity_overlap": "not_audited", "partition": "not_verified", "approval": "not_approved"},
            "appropriate_tasks": ["candidate_verification", "object_discovery"], "domain_shift_note": "Broad natural-image alternative; class and visual-domain coverage differ materially from ODinW-13.",
        },
        {
            "source_id": "lvis:v1-train", "dataset_name": "LVIS v1.0", "original_publisher": "LVIS",
            "publisher_url": "https://www.lvisdataset.org/dataset", "source_type": "alternative_official_dataset", "domain": "large_vocabulary_COCO_images",
            "release_version": "v1.0", "annotation_format": "LVIS instance segmentation JSON with boxes", "label_completeness": "federated_positive_and_negative_category_annotations_not_global_exhaustiveness",
            "partitions": ["train"], "classes": "1203 LVIS categories", "image_root": None, "annotation_path": None,
            "image_content_hashes": [], "known_alias_or_duplicate_groups": ["Uses COCO images; overlap with COCO is by design"],
            "archives": [
                {"url": "https://dl.fbaipublicfiles.com/LVIS/lvis_v1_train.json.zip", "bytes": 350264821, "etag": "8779cd98ba10bbad605de77de9e979e4-21", "destination_relative": "LVIS/lvis_v1_train.json.zip"},
                {"url": "http://images.cocodataset.org/zips/train2017.zip", "bytes": 19336861798, "etag": "62ff7d7fbcc7e0c0604cbb0f9047ce77-2306", "destination_relative": "COCO/train2017.zip"},
            ],
            "license_access": {"annotations": "Publisher terms require review before approval", "images": "COCO/Flickr image terms", "publisher_terms_verified": False, "credentials_required": False, "review_note": "LVIS is federated: absent categories cannot be treated as negatives unless image-level negative/not-exhaustive metadata permits it."},
            "acquisition_status": ["source_discovered", "metadata_verified", "license_review_required"],
            "verification_status": {"archive_metadata": "verified", "local_archive": "not_downloaded", "annotations": "not_verified", "annotation_completeness": "federated_requires_per_image_eligibility", "source_identity_overlap": "not_audited", "partition": "not_verified", "approval": "not_approved"},
            "appropriate_tasks": ["candidate_verification"], "domain_shift_note": "Large vocabulary and COCO imagery; federated annotations complicate object-discovery negatives.",
        },
    ])
    return {
        "schema_version": REGISTRY_VERSION,
        "generated_from": {
            "glip_git_commit": "9dda9558c1ef59bb6cdc8e896e2bcab775a68ff0",
            "glip_host_commit": "66ee3ae9a3b8cee0cf78f10ef5fc9a3725db02a1",
            "checked_utc_date": "2026-10-29",
        },
        "approval_policy": "Metadata verification never implies calibration approval.",
        "sources": sources,
    }


def validate_source(source):
    required = {"source_id", "dataset_name", "original_publisher", "publisher_url", "source_type", "domain",
                "release_version", "annotation_format", "label_completeness", "partitions", "license_access",
                "acquisition_status", "verification_status", "appropriate_tasks"}
    missing = sorted(required - set(source))
    if missing:
        raise ValueError(f"Source record missing fields: {missing}")
    unknown = sorted(set(source["acquisition_status"]) - set(SOURCE_STATUSES))
    if unknown:
        raise ValueError(f"Unknown source status: {unknown}")
    if "approved_for_calibration" in source["acquisition_status"]:
        checks = source["verification_status"]
        if not source["license_access"].get("publisher_terms_verified"):
            raise ValueError("Calibration approval requires verified source permissions")
        for key in ("annotations", "annotation_completeness", "source_identity_overlap", "partition"):
            if checks.get(key) != "verified":
                raise ValueError(f"Calibration approval requires {key}=verified")
    return True


def validate_registry(registry):
    if registry.get("schema_version") != REGISTRY_VERSION:
        raise ValueError("Unsupported calibration source registry version")
    ids = set()
    for source in registry.get("sources", []):
        validate_source(source)
        if source["source_id"] in ids:
            raise ValueError(f"Duplicate source_id: {source['source_id']}")
        ids.add(source["source_id"])
    if not ids:
        raise ValueError("Source registry cannot be empty")
    return True


def registry_with_local_paths(registry, source_id, *, image_root, annotation_path):
    result = copy.deepcopy(registry)
    matches = [source for source in result["sources"] if source["source_id"] == source_id]
    if len(matches) != 1:
        raise KeyError(source_id)
    matches[0]["image_root"] = str(Path(image_root).resolve())
    matches[0]["annotation_path"] = str(Path(annotation_path).resolve())
    return result
