"""Verified, GT-sealed access to the approved Aquarium calibration source."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path

from evaluation_kit.bite_calibration.common import file_hash
from evaluation_kit.bite_calibration.manifest_freeze import validate_frozen_manifest
from evaluation_kit.bite_calibration.matching import load_coco
from evaluation_kit.bite_calibration.source_registry import (
    default_registry,
    validate_source,
)
from openvlharness.media import local_image_to_data_url

SOURCE_ID = "odinw13:Aquarium_Aquarium_Combined.v2-raw-1024.coco"
ARCHIVE_BYTES = 70_037_905
ARCHIVE_SHA256 = "4affbfd66ef640b6154c694da3f2e730a97fe0fb0f8a22aa7ec8d32c2f04a536"
MANIFEST_DIGEST = "61df2e5f2a817b022f07358ec5b63438c8cfb56973009cf854c7b460c86aebd4"
ANNOTATION_SHA256 = "5ca593fb53fc482790b51677fdd81b0e497d44e8bcdce00f8ec4275937ed097c"
APPROVAL_ID = "aquarium-research-2026-10-30"
CLASSES = ("fish", "jellyfish", "penguin", "puffin", "shark", "starfish", "stingray")


@dataclass(frozen=True)
class AquariumEntry:
    entry_id: str
    source_group_id: str
    image_sha256: str
    image_path: str
    annotation_image_id: int
    width: int
    height: int
    partition: str
    queries: tuple[str, ...]

    def runtime_image(self) -> str:
        return local_image_to_data_url(self.image_path)


class AquariumDatasetAdapter:
    """Resolve frozen entries without exposing GT during runtime collection."""

    def __init__(
        self,
        *,
        manifest_path="outputs/bite/phase04b2b1a/manifests/calibration_partition_manifest.json",
        entries_path="outputs/bite/phase04b2b1a/manifests/verified_clean_train_entries.json",
        schedules_path="outputs/bite/phase04b2b1a/protocol/query_schedules.json",
        quarantine_path="outputs/bite/phase04b2b1a/leakage/quarantine.json",
        approval_path="outputs/bite/phase04b2b1/acquisition/researcher_approval.json",
        acquisition_path="outputs/bite/phase04b2b1/acquisition/Aquarium_Aquarium_Combined.v2-raw-1024.coco_acquisition.json",
        archive_path="data/calibration_sources/odinw13/archives/Aquarium.zip",
        allowed_partition="calibration_fit",
    ):
        self.paths = {name: Path(value).resolve() for name, value in {
            "manifest": manifest_path, "entries": entries_path, "schedules": schedules_path,
            "quarantine": quarantine_path, "approval": approval_path,
            "acquisition": acquisition_path, "archive": archive_path,
        }.items()}
        self.allowed_partition = allowed_partition
        self.manifest = json.loads(self.paths["manifest"].read_text())
        self._entries_document = json.loads(self.paths["entries"].read_text())
        self._schedules_document = json.loads(self.paths["schedules"].read_text())
        self._quarantine_document = json.loads(self.paths["quarantine"].read_text())
        self.approval = json.loads(self.paths["approval"].read_text())
        self.acquisition = json.loads(self.paths["acquisition"].read_text())
        self._annotation_path = None
        self._annotation_sha256 = None
        self._runtime_gt_opened = False
        self.preflight = self._validate()

    @staticmethod
    def _approved_source(image_root, annotation_path):
        source = copy.deepcopy(next(row for row in default_registry()["sources"] if row["source_id"] == SOURCE_ID))
        source["image_root"] = str(image_root)
        source["annotation_path"] = str(annotation_path)
        source["license_access"]["publisher_terms_verified"] = True
        source["verification_status"].update({
            "local_archive": "verified", "annotations": "verified",
            "annotation_completeness": "verified", "source_identity_overlap": "verified",
            "partition": "verified", "approval": "approved",
        })
        source["appropriate_tasks"] = ["candidate_verification"]
        source["acquisition_status"] = [
            "source_discovered", "metadata_verified", "locally_available",
            "annotations_verified", "partition_verified", "approved_for_calibration",
        ]
        validate_source(source)
        return source

    def _validate(self):
        if self.allowed_partition != "calibration_fit":
            raise ValueError("The first real collection is restricted to calibration_fit")
        if self.manifest.get("manifest_sha256") != MANIFEST_DIGEST:
            raise ValueError("Unexpected frozen Aquarium manifest identity")
        if self.manifest.get("source_ids") != [SOURCE_ID]:
            raise ValueError("Frozen manifest source mismatch")
        archive = self.paths["archive"]
        if archive.stat().st_size != ARCHIVE_BYTES or file_hash(archive) != ARCHIVE_SHA256:
            raise ValueError("Approved Aquarium archive identity mismatch")
        approved = [row for row in self.approval.get("sources", []) if row.get("source_id") == SOURCE_ID]
        if (self.approval.get("approval_id") != APPROVAL_ID or not self.approval.get("researcher_attestation")
                or self.approval.get("redistribution") is not False or len(approved) != 1
                or approved[0].get("expected_bytes") != ARCHIVE_BYTES
                or approved[0].get("expected_sha256") != ARCHIVE_SHA256):
            raise ValueError("Researcher approval does not authorize this exact source")
        if (self.acquisition.get("verified_bytes") != ARCHIVE_BYTES
                or self.acquisition.get("verified_sha256") != ARCHIVE_SHA256):
            raise ValueError("Acquisition record does not match the approved archive")

        manifest_rows = {row["entry_id"]: row for row in self.manifest["entries"]}
        source_rows = {row["entry_id"]: row for row in self._entries_document["entries"]}
        schedules = {row["source_group_id"]: row for row in self._schedules_document["entries"]}
        quarantined = set(self._quarantine_document["entries"])
        if set(manifest_rows) != set(source_rows):
            raise ValueError("Frozen manifest and verified source inventory differ")
        partitions_by_group = {}
        annotation_paths = set()
        for entry_id, frozen in manifest_rows.items():
            source = source_rows[entry_id]
            if frozen["image_sha256"] != source["image_sha256"] or frozen["source_group_id"] != source["source_group_id"]:
                raise ValueError(f"Frozen identity mismatch for {entry_id}")
            partitions_by_group.setdefault(frozen["source_group_id"], set()).add(frozen["partition"])
            if entry_id in quarantined and frozen["partition"] == self.allowed_partition:
                raise ValueError(f"Quarantined entry present in allowed partition: {entry_id}")
            path = Path(source["image_path"])
            if not path.is_file() or file_hash(path) != frozen["image_sha256"]:
                raise ValueError(f"Source image cannot be resolved exactly: {entry_id}")
            if source["source_group_id"] not in schedules:
                raise ValueError(f"Missing frozen query schedule for {source['source_group_id']}")
            schedule = schedules[source["source_group_id"]]
            if schedule.get("gt_presence_used") is not False or schedule.get("fabricated_classes") is not False:
                raise ValueError("Query schedule is not GT-independent")
            if any(query not in CLASSES for query in schedule.get("queries", [])):
                raise ValueError("Query schedule contains an unverified source class")
            annotation_paths.add(source["annotation_file"])
        if any(len(partitions) != 1 for partitions in partitions_by_group.values()):
            raise ValueError("A source group crosses frozen partitions")
        if len(annotation_paths) != 1:
            raise ValueError("Expected one exact Aquarium train annotation source")
        annotation_path = Path(annotation_paths.pop())
        if not annotation_path.is_file() or file_hash(annotation_path) != ANNOTATION_SHA256:
            raise ValueError("Original Aquarium annotations are unavailable or changed")
        source = self._approved_source(annotation_path.parent, annotation_path)
        validate_frozen_manifest(self.manifest, source)
        self._manifest_rows = manifest_rows
        self._source_rows = source_rows
        self._schedules = schedules
        self._quarantined = quarantined
        self._annotation_path = annotation_path
        self._annotation_sha256 = ANNOTATION_SHA256
        counts = {name: sum(row["partition"] == name for row in self.manifest["entries"])
                  for name in ("calibration_fit", "calibration_validation", "internal_test")}
        groups = {name: len({row["source_group_id"] for row in self.manifest["entries"] if row["partition"] == name})
                  for name in counts}
        if counts != {"calibration_fit": 277, "calibration_validation": 78, "internal_test": 50}:
            raise ValueError("Frozen partition image counts changed")
        if groups != {"calibration_fit": 277, "calibration_validation": 72, "internal_test": 50}:
            raise ValueError("Frozen partition group counts changed")
        return {
            "valid": True, "source_id": SOURCE_ID, "manifest_sha256": self.manifest["manifest_sha256"],
            "manifest_file_sha256": file_hash(self.paths["manifest"]), "archive_sha256": ARCHIVE_SHA256,
            "archive_bytes": ARCHIVE_BYTES, "approval_id": APPROVAL_ID,
            "annotation_available_for_offline_stage": True, "annotation_sha256": ANNOTATION_SHA256,
            "partition_image_counts": counts, "partition_group_counts": groups,
            "allowed_partition": self.allowed_partition, "quarantine_count": len(quarantined),
            "gt_opened_during_preflight": False,
        }

    def entries(self):
        """Return runtime-safe entries; annotation labels are intentionally absent."""
        result = []
        for frozen in self.manifest["entries"]:
            if frozen["partition"] != self.allowed_partition:
                continue
            source = self._source_rows[frozen["entry_id"]]
            result.append(AquariumEntry(
                entry_id=frozen["entry_id"], source_group_id=frozen["source_group_id"],
                image_sha256=frozen["image_sha256"], image_path=source["image_path"],
                annotation_image_id=int(source["annotation_image_id"]), width=int(source["width"]),
                height=int(source["height"]), partition=frozen["partition"],
                queries=tuple(self._schedules[frozen["source_group_id"]]["queries"][:2]),
            ))
        return result

    def load_offline_ground_truth(self, entry):
        """Open GT only in the explicit post-persistence labeling stage."""
        self._runtime_gt_opened = True
        gt = load_coco(self._annotation_path, entry.annotation_image_id)
        gt.provenance.update({
            "dataset": SOURCE_ID, "sample_id": entry.entry_id,
            "source_group_id": entry.source_group_id,
            "source_image_path": str(Path(entry.image_path).resolve()),
            "source_image_sha256": entry.image_sha256,
            "cc_by_4_attribution": "Aquarium Combined dataset (Roboflow), CC BY 4.0; GLIP-curated archive",
        })
        return gt

    @property
    def runtime_gt_opened(self):
        return self._runtime_gt_opened

