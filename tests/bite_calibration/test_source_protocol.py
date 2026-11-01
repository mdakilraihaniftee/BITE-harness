"""Phase 4B-2A source governance and frozen protocol tests."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import validate

from evaluation_kit.bite_calibration.manifest_freeze import freeze_manifest, provisional_manifest, validate_frozen_manifest
from evaluation_kit.bite_calibration.protocol_validation import default_protocol, protocol_schema, validate_protocol
from evaluation_kit.bite_calibration.source_preparation import acquisition_plan
from evaluation_kit.bite_calibration.source_registry import default_registry, validate_registry, validate_source
from evaluation_kit.bite_calibration.source_verification import verify_detection_source


def registry():
    value = default_registry()
    validate_registry(value)
    return value


def source(source_id="odinw13:Packages_Raw"):
    return copy.deepcopy(next(item for item in registry()["sources"] if item["source_id"] == source_id))


def approved_source():
    value = source()
    value["license_access"]["publisher_terms_verified"] = True
    value["verification_status"].update(annotations="verified", annotation_completeness="verified", source_identity_overlap="verified", partition="verified", approval="approved")
    value["acquisition_status"].append("approved_for_calibration")
    validate_source(value)
    return value


def test_registry_has_thirteen_odinw_and_two_separate_alternatives():
    value = registry()
    odinw = [item for item in value["sources"] if item["source_id"].startswith("odinw13:")]
    assert len(odinw) == 13
    assert {item["source_id"] for item in value["sources"]} >= {"coco:2017-train-detection", "lvis:v1-train"}
    assert sum(item["archive"]["bytes"] for item in odinw) == 2249062175
    assert all("train" in item["partitions"] for item in odinw)
    assert all("approved_for_calibration" not in item["acquisition_status"] for item in value["sources"])


def test_metadata_never_implies_approval():
    value = source()
    value["acquisition_status"].append("approved_for_calibration")
    with pytest.raises(ValueError, match="permissions"):
        validate_source(value)
    value["license_access"]["publisher_terms_verified"] = True
    with pytest.raises(ValueError, match="annotations"):
        validate_source(value)


def test_registry_rejects_unknown_status_and_duplicate_id():
    value = registry()
    value["sources"][0]["acquisition_status"].append("looks_good")
    with pytest.raises(ValueError, match="Unknown source status"):
        validate_registry(value)
    value = registry()
    value["sources"].append(copy.deepcopy(value["sources"][0]))
    with pytest.raises(ValueError, match="Duplicate source_id"):
        validate_registry(value)


@pytest.mark.parametrize("source_id,expected", [
    ("odinw13:AerialMaritimeDrone_large", 47681829),
    ("coco:2017-train-detection", 19589769339),
    ("lvis:v1-train", 19687126619),
])
def test_acquisition_plan_is_nonexecuting_and_exact(source_id, expected, tmp_path):
    plan = acquisition_plan(source(source_id), tmp_path)
    assert plan["dry_run_only"] is True
    assert plan["automatic_download_permitted"] is False
    assert plan["total_expected_bytes"] == expected
    assert all(str(tmp_path.resolve()) in item["destination"] for item in plan["archives"])


def test_missing_local_source_is_explicit(tmp_path):
    value = source()
    value["annotation_path"] = str(tmp_path / "missing.json")
    value["image_root"] = str(tmp_path / "images")
    report = verify_detection_source(value)
    assert report["verified"] is False and report["reason"] == "local_paths_missing"
    assert report["approval_eligible"] is False


def _tiny_source(tmp_path, *, overlap=False):
    image_root = tmp_path / "images"
    image_root.mkdir()
    (image_root / "one.jpg").write_bytes(b"image-one")
    annotation = tmp_path / "labels.json"
    annotation.write_text(json.dumps({
        "images": [{"id": 1, "file_name": "one.jpg", "width": 10, "height": 10}],
        "categories": [{"id": 1, "name": "package"}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [0, 0, 5, 5], "area": 25}],
    }))
    value = source()
    value["image_root"] = str(image_root)
    value["annotation_path"] = str(annotation)
    value["verification_status"]["annotation_completeness"] = "verified"
    heldout = []
    if overlap:
        from evaluation_kit.bite_calibration.common import file_hash
        heldout = [{"entry_id": "heldout", "partition": "final_evaluation", "source_namespace": "heldout",
                    "source_image_id": "same", "image_sha256": file_hash(image_root / "one.jpg") }]
    return value, heldout


def test_local_detection_source_verifies_structure_and_hashes(tmp_path):
    value, heldout = _tiny_source(tmp_path)
    report = verify_detection_source(value, heldout)
    assert report["verified"] is True
    assert report["approval_eligible"] is False  # permission review is an independent gate
    assert len(report["entries"]) == 1
    assert len(report["entries"][0]["image_sha256"]) == 64


def test_local_source_overlap_with_heldout_blocks_verification(tmp_path):
    value, heldout = _tiny_source(tmp_path, overlap=True)
    report = verify_detection_source(value, heldout)
    assert report["checks"]["no_exact_or_declared_heldout_overlap"] is False
    assert report["verified"] is False
    assert any(item["kind"] == "image_sha256" for item in report["heldout_overlap_findings"])


def test_invalid_boxes_and_missing_images_fail_structure(tmp_path):
    value, _ = _tiny_source(tmp_path)
    document = json.loads(Path(value["annotation_path"]).read_text())
    document["annotations"][0]["bbox"] = [0, 0, 0, 5]
    document["images"].append({"id": 2, "file_name": "missing.jpg"})
    Path(value["annotation_path"]).write_text(json.dumps(document))
    report = verify_detection_source(value)
    assert report["checks"]["annotation_references_and_boxes_valid"] is False
    assert report["checks"]["all_images_present"] is False


def test_provisional_manifest_assigns_nothing_and_names_debug_exclusion():
    exclusions = [{"sample_id": "PascalVOC_val_262", "reason": "previous development exposure"}]
    manifest = provisional_manifest(registry(), exclusions=exclusions)
    assert manifest["status"] == "SOURCE_PENDING" and manifest["entries"] == []
    assert manifest["partition_counts"]["calibration_fit"] == 0
    assert manifest["exclusions"] == exclusions


def test_freeze_requires_approval_and_nonempty_verified_identity():
    entries = [{"entry_id": "a", "partition": "candidate", "source_namespace": "s", "source_image_id": "a", "image_sha256": "a" * 64}]
    with pytest.raises(ValueError, match="not approved"):
        freeze_manifest(source(), entries)
    with pytest.raises(ValueError, match="Empty partition"):
        freeze_manifest(approved_source(), [])


def test_freeze_is_deterministic_groups_duplicates_and_excludes_hash():
    entries = [
        {"entry_id": "a", "partition": "candidate", "source_namespace": "s", "source_image_id": "a", "image_sha256": "a" * 64},
        {"entry_id": "a-copy", "partition": "candidate", "source_namespace": "s", "source_image_id": "a-copy", "image_sha256": "a" * 64},
        {"entry_id": "b", "partition": "candidate", "source_namespace": "s", "source_image_id": "b", "image_sha256": "b" * 64},
        {"entry_id": "excluded", "partition": "candidate", "source_namespace": "s", "source_image_id": "x", "image_sha256": "c" * 64},
    ]
    exclusions = [{"image_sha256": "c" * 64, "reason": "development exposure"}]
    one = freeze_manifest(approved_source(), entries, salt="fixed", exclusions=exclusions)
    two = freeze_manifest(approved_source(), entries, salt="fixed", exclusions=exclusions)
    assert one == two and len(one["manifest_sha256"]) == 64
    assert validate_frozen_manifest(one, approved_source())
    assert not any(item["image_sha256"] == "c" * 64 for item in one["entries"])
    duplicate_partitions = {item["partition"] for item in one["entries"] if item["image_sha256"] == "a" * 64}
    assert len(duplicate_partitions) == 1


def test_manifest_checksum_is_immutable_and_source_approval_is_rechecked():
    entries = [{"entry_id": "a", "partition": "candidate", "source_namespace": "s", "source_image_id": "a", "image_sha256": "a" * 64}]
    manifest = freeze_manifest(approved_source(), entries)
    manifest["entries"][0]["partition"] = "internal_test"
    with pytest.raises(ValueError, match="checksum mismatch"):
        validate_frozen_manifest(manifest, approved_source())
    clean = freeze_manifest(approved_source(), entries)
    with pytest.raises(ValueError, match="not approved"):
        validate_frozen_manifest(clean, source())


def test_protocol_schema_and_scientific_boundaries():
    protocol = default_protocol()
    assert validate_protocol(protocol)
    validate(protocol, protocol_schema())
    assert protocol["status"] == "FROZEN_SOURCE_PENDING"
    assert protocol["tasks"]["candidate_verification"]["thresholds"] == [0.5, 0.75]
    assert protocol["tasks"]["object_discovery"]["region_rule"] == "fixed_2x2_root_grid_center_membership_v1"
    assert protocol["budget"]["logical_public_capability_dispatches"] == 3
    assert protocol["model_identity"]["orchestrator_calls"] == 0


def test_protocol_rejects_gt_driven_schedule():
    protocol = default_protocol()
    protocol["sampling"]["ground_truth_positive_only"] = True
    with pytest.raises(ValueError, match="GT-derived"):
        validate_protocol(protocol)


def test_protocol_rejects_model_work_and_hypothesis_switch():
    protocol = default_protocol()
    protocol["budget"]["model_calls_planned"] = 1
    with pytest.raises(ValueError, match="model calls"):
        validate_protocol(protocol)


@pytest.mark.parametrize("mutation,message", [
    (("unsupported",), "Unsupported action"),
    (("negative_budget",), "nonnegative"),
    (("over_budget",), "exceeds budget"),
    (("missing_prerequisite",), "unresolved prerequisites"),
    (("missing_propensity",), "selection propensity"),
    (("false_checkpoint_attestation",), "cannot be represented as verified"),
])
def test_protocol_rejects_invalid_execution_claims(mutation, message):
    protocol = default_protocol()
    name = mutation[0]
    if name == "unsupported":
        protocol["action_paths"][0]["actions"] = ["alternative_backend_verification"]
    elif name == "negative_budget":
        protocol["budget"]["logical_public_capability_dispatches"] = -1
    elif name == "over_budget":
        protocol["action_paths"][0]["estimated_logical_cost"] = 4
    elif name == "missing_prerequisite":
        protocol["action_paths"][0]["prerequisites"] = []
    elif name == "missing_propensity":
        protocol["selection_design"].pop("randomized_propensity_rule")
    else:
        protocol["model_identity"]["checkpoint_verified_by_worker"] = True
    with pytest.raises(ValueError, match=message):
        validate_protocol(protocol)
    protocol = default_protocol()
    protocol["action_paths"][0]["same_hypothesis"] = False
    with pytest.raises(ValueError, match="declared hypothesis"):
        validate_protocol(protocol)


def test_ready_protocol_still_requires_manifest_gate():
    protocol = default_protocol(source_ready=True)
    protocol["sampling"]["partition_manifest_required"] = False
    with pytest.raises(ValueError, match="partition manifest"):
        validate_protocol(protocol)
