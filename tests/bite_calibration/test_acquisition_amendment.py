"""Phase 4B-2B-1 acquisition, readiness and research-amendment tests."""

import copy
import io
import json
from pathlib import Path
import stat
import zipfile

from PIL import Image
import pytest

from evaluation_kit.bite_calibration.annotation_readiness import inspect_detection_annotations, select_manual_qa
from evaluation_kit.bite_calibration.duplicate_audit import audit_train_against_heldout
from evaluation_kit.bite_calibration.operational_state import build_operational_state
from evaluation_kit.bite_calibration.query_schedule import schedule_queries
from evaluation_kit.bite_calibration.research_amendment import default_amendment, validate_amendment
from evaluation_kit.bite_calibration.source_acquisition import (
    APPROVAL_VERSION, acquire_source, acquisition_plan, approval_request, inspect_zip,
    safe_extract_zip, validate_approval,
)
from evaluation_kit.bite_calibration.source_registry import default_registry
from evaluation_kit.bite_calibration.target_outcomes import summarize_discovery, summarize_target_aligned
from evaluation_kit.bite_collection.synthetic import run_synthetic_demo


SOURCE_ID = "odinw13:AerialMaritimeDrone_large"


def zip_bytes(members=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in members or [("train/one.jpg", b"image"), ("train/labels.json", b"{}")]:
            if isinstance(name, zipfile.ZipInfo):
                archive.writestr(name, value)
            else:
                archive.writestr(name, value)
    return stream.getvalue()


def registry_for(data):
    import hashlib
    registry = default_registry()
    source = next(item for item in registry["sources"] if item["source_id"] == SOURCE_ID)
    source["archive"]["bytes"] = len(data)
    source["archive"]["sha256"] = hashlib.sha256(data).hexdigest()
    source["archive"]["url"] = "https://huggingface.co/GLIPModel/GLIP/resolve/main/test.zip"
    return registry


def approval(registry, destination, approved_by="researcher-1"):
    source = next(item for item in registry["sources"] if item["source_id"] == SOURCE_ID)
    archive = source["archive"]
    return {
        "schema_version": APPROVAL_VERSION, "approval_id": "approval-test-1",
        "approval_authority": "researcher", "approved_by": approved_by,
        "approved_at": "2026-10-30T00:00:00-04:00", "researcher_attestation": True,
        "intended_use": "internal_non_redistributed_research_calibration", "redistribution": False,
        "sources": [{"source_id": SOURCE_ID, "url": archive["url"],
                     "expected_bytes": archive["bytes"], "expected_sha256": archive["sha256"]}],
        "terms_reviewed": ["https://universe.roboflow.com/jacob-solawetz/aerial-maritime"],
        "destination_root": str(Path(destination).resolve()),
    }


class Response:
    def __init__(self, data):
        self.stream = io.BytesIO(data)

    def read(self, size=-1):
        return self.stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_dry_run_is_default_semantics_and_has_no_network(tmp_path):
    registry = default_registry()
    request = approval_request(registry, [SOURCE_ID], tmp_path)
    assert request["status"] == "AWAITING_RESEARCHER_APPROVAL"
    plan = acquisition_plan(registry, SOURCE_ID, tmp_path)
    assert plan["mode"] == "dry_run" and plan["network_requested"] is False
    assert plan["approval_status"] == "not_supplied"
    assert plan["expected_bytes"] == 47681829


def test_approval_must_be_researcher_supplied_and_exact(tmp_path):
    registry = default_registry()
    source = next(item for item in registry["sources"] if item["source_id"] == SOURCE_ID)
    with pytest.raises(ValueError, match="assistant-generated"):
        validate_approval(approval(registry, tmp_path, "Codex"), source, tmp_path)
    wrong = approval(registry, tmp_path)
    wrong["sources"][0]["expected_bytes"] += 1
    with pytest.raises(ValueError, match="exactly match"):
        validate_approval(wrong, source, tmp_path)


def test_verified_download_stream_and_safe_extract(tmp_path):
    data = zip_bytes()
    registry = registry_for(data)
    seen = []

    def opener(request, timeout):
        seen.append((request.full_url, timeout))
        return Response(data)

    result = acquire_source(registry, SOURCE_ID, tmp_path, approval(registry, tmp_path), opener=opener)
    assert seen == [("https://huggingface.co/GLIPModel/GLIP/resolve/main/test.zip", 60)]
    assert Path(result["archive_path"]).read_bytes() == data
    assert Path(result["extraction_path"], "train/one.jpg").read_bytes() == b"image"
    assert result["verified_sha256"] == next(item for item in registry["sources"] if item["source_id"] == SOURCE_ID)["archive"]["sha256"]


@pytest.mark.parametrize("mutation,message", [
    ("short", "byte length mismatch"), ("hash", "SHA-256 mismatch"),
])
def test_interrupted_and_incorrect_hash_are_rejected(tmp_path, mutation, message):
    data = zip_bytes()
    registry = registry_for(data)
    if mutation == "short":
        payload = data[:-1]
    else:
        payload = data
        next(item for item in registry["sources"] if item["source_id"] == SOURCE_ID)["archive"]["sha256"] = "0" * 64
    record = approval(registry, tmp_path)
    with pytest.raises(ValueError, match=message):
        acquire_source(registry, SOURCE_ID, tmp_path, record, opener=lambda *args, **kwargs: Response(payload))
    assert not list((tmp_path / "archives").glob("*.part"))


def test_existing_archive_is_never_silently_overwritten(tmp_path):
    data = zip_bytes()
    registry = registry_for(data)
    archive = tmp_path / "archives/test.zip"
    archive.parent.mkdir()
    archive.write_bytes(data)
    with pytest.raises(FileExistsError):
        acquire_source(registry, SOURCE_ID, tmp_path, approval(registry, tmp_path), opener=lambda *a, **k: Response(data))


@pytest.mark.parametrize("members,message", [
    ([('../escape.jpg', b'x')], "traversal"),
    ([('/absolute.jpg', b'x')], "absolute"),
    ([('script.py', b'x')], "Unexpected archive file type"),
    ([('A.jpg', b'x'), ('a.jpg', b'y')], "Duplicate or case-conflicting"),
])
def test_unsafe_zip_paths_and_types_are_rejected(tmp_path, members, message):
    path = tmp_path / "bad.zip"
    path.write_bytes(zip_bytes(members))
    with pytest.raises(ValueError, match=message):
        inspect_zip(path)


def test_zip_symlinks_are_rejected(tmp_path):
    info = zipfile.ZipInfo("link.jpg")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    path = tmp_path / "link.zip"
    path.write_bytes(zip_bytes([(info, b"target")]))
    with pytest.raises(ValueError, match="symlink"):
        safe_extract_zip(path, tmp_path / "out")


def annotation_fixture(tmp_path, *, missing=False, bad_box=False, classes=("person",)):
    images = tmp_path / "images"
    images.mkdir()
    if not missing:
        Image.new("RGB", (20, 10), "white").save(images / "one.png")
    document = {
        "images": [{"id": 1, "file_name": "one.png", "width": 20, "height": 10},
                   {"id": 2, "file_name": "empty.png", "width": 20, "height": 10}],
        "categories": [{"id": index + 1, "name": name} for index, name in enumerate(classes)],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 1,
                         "bbox": [0, 0, 0 if bad_box else 5, 5], "iscrowd": 0, "ignore": 0}],
    }
    Image.new("RGB", (20, 10), "black").save(images / "empty.png")
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(document))
    return path, images


def test_annotation_readiness_separates_structure_exhaustiveness_and_visual_review(tmp_path):
    path, images = annotation_fixture(tmp_path)
    unknown = inspect_detection_annotations(path, images, expected_classes=["person"])
    assert unknown["structural_completeness"] == "verified"
    assert unknown["task_v_readiness"] == unknown["task_d_readiness"] == "blocked"
    assert unknown["empty_image_ids"] == [2]
    task_v = inspect_detection_annotations(path, images, expected_classes=["person"],
                                            exhaustiveness={"person": "verified_exhaustive"})
    assert task_v["task_v_readiness"] == "ready" and task_v["task_d_readiness"] == "blocked"
    both = inspect_detection_annotations(path, images, expected_classes=["person"],
                                          exhaustiveness={"person": "verified_exhaustive"},
                                          visual_review_status="verified_no_material_omissions")
    assert both["task_d_readiness"] == "ready"


@pytest.mark.parametrize("missing,bad_box,kind", [(True, False, "missing_images"), (False, True, "invalid_bbox_geometry")])
def test_annotation_errors_and_missing_images_block_readiness(tmp_path, missing, bad_box, kind):
    path, images = annotation_fixture(tmp_path, missing=missing, bad_box=bad_box)
    result = inspect_detection_annotations(path, images, expected_classes=["person"],
                                           exhaustiveness={"person": "verified_exhaustive"})
    assert result["structural_completeness"] == "failed"
    assert any(item["kind"] == kind for item in result["structural_findings"])


def test_unknown_class_mapping_and_hash_selected_manual_qa(tmp_path):
    path, images = annotation_fixture(tmp_path)
    result = inspect_detection_annotations(path, images, expected_classes=["horse"])
    assert any(item["kind"] == "missing_required_classes" for item in result["structural_findings"])
    qa1 = select_manual_qa(result["entries"], count=1, seed=417)
    qa2 = select_manual_qa(list(reversed(result["entries"])), count=1, seed=417)
    assert qa1 == qa2 and qa1["selection_uses_detection_outcomes"] is False


def test_exact_overlap_and_perceptual_candidates_are_quarantined(tmp_path):
    train_image = tmp_path / "train.png"
    held_image = tmp_path / "held.jpg"
    image = Image.new("RGB", (16, 16), "white")
    for x in range(8):
        for y in range(16):
            image.putpixel((x, y), (0, 0, 0))
    image.save(train_image)
    image.save(held_image, quality=95)
    import hashlib
    train_hash = hashlib.sha256(train_image.read_bytes()).hexdigest()
    held_hash = hashlib.sha256(held_image.read_bytes()).hexdigest()
    train = [{"entry_id": "train", "source_namespace": "a", "source_image_id": "one",
              "image_path": str(train_image), "image_sha256": train_hash}]
    held = [{"entry_id": "held", "source_namespace": "b", "source_image_id": "two",
             "image_path": str(held_image), "image_sha256": held_hash, "partition": "final"}]
    result = audit_train_against_heldout(train, held, perceptual=True)
    assert result["exact_overlap_findings"] == []
    assert result["near_duplicate_candidates"][0]["identity_confirmed"] is False
    assert result["quarantined_train_entry_ids"] == ["train"]
    held[0]["image_sha256"] = train_hash
    exact = audit_train_against_heldout(train, held)
    assert exact["exact_overlap_findings"] and exact["quarantined_train_entry_ids"] == ["train"]


def test_one_and_multi_class_query_schedule_is_deterministic_and_gt_free():
    one = schedule_queries("group", ["rabbit"], requested_count=2)
    assert one["scheduled_count"] == 1 and one["queries"] == ["rabbit"]
    first = schedule_queries("group", ["fish", "shark", "penguin"], requested_count=2)
    second = schedule_queries("group", ["penguin", "fish", "shark"], requested_count=2)
    assert first == second and first["scheduled_count"] == 2
    assert first["gt_presence_used"] is False and first["fabricated_classes"] is False


def candidate(candidate_id="c1", box=(0, 0, 10, 10), score=.9, status="new_distinct_candidate"):
    return {"candidate_id": candidate_id, "class_name": "person", "source_group_id": "group",
            "source_image_sha256": "a" * 64, "root_image_id": "input_image_1",
            "resolved_image_id": "input_image_1", "bbox_root_xyxy": list(box),
            "raw_scores": [score], "source_observation_id": "obs0", "association_status": status,
            "frame_reason": None}


def observation(boxes, *, success=True, repeat=False):
    return {"dispatched": True, "success": success, "joint_observation_id": "obs1",
            "backend": "sam3_segment", "canonical_result": {"boxes": boxes},
            "root_image": {"sha256": "a" * 64}, "source_frame": {"root_image_id": "input_image_1"},
            "repeat_metadata": {"previous_observation_id": "obs0", "same_backend": True,
                                "same_source_image_sha256": True} if repeat else None,
            "outcome": {"category": "duplicate_existing_candidate"}, "error": None}


def test_operational_state_is_deterministic_gt_free_and_separates_audit_ids():
    kwargs = dict(task={"hypothesis_task": "candidate_verification", "source_domain": "demo"},
                  candidate=candidate(), previous_observation=observation([[0, 0, 10, 10]]),
                  current_action={"action_template": "repeated_grounding", "backend": "sam3_segment",
                                  "arguments": {"image_id": "input_image_1", "query": "person"}},
                  root_dimensions=(20, 20), remaining_budget=2, source_group_id="group",
                  source_image_sha256="a" * 64)
    one = build_operational_state(**kwargs)
    two = build_operational_state(**kwargs)
    assert one == two and one["predictive_features"]["raw_detector_score"] == .9
    assert "sha256" not in json.dumps(one["predictive_features"]).lower()
    assert one["audit_cluster"]["source_image_sha256"] == "a" * 64
    with pytest.raises(ValueError, match="Offline label"):
        build_operational_state(**{**kwargs, "task": {"ground_truth": "leak"}})


def test_repeated_false_positive_remains_same_lineage_not_independent_measurement():
    initial = candidate()
    repeated = candidate("c2")
    summary = summarize_target_aligned(initial, [repeated], observation([[0, 0, 10, 10]], repeat=True))
    assert summary["category"] == "same_geometry_repeated"
    assert summary["dependency_lineage"]["initial_observation_id"] == "obs0"
    assert summary["dependency_lineage"]["repeat_metadata"]["same_backend"] is True
    assert summary["score_is_candidate_belief"] is False
    offline_h_v = 0  # Synthetic test label; never passed into runtime summarization.
    assert offline_h_v == 0 and "ground_truth" not in json.dumps(summary).lower()


def test_target_outcome_retains_joint_detections_and_ambiguity():
    initial = candidate()
    outputs = [candidate("near1", (0, 0, 10, 10)), candidate("near2", (1, 0, 11, 10))]
    summary = summarize_target_aligned(initial, outputs, observation([item["bbox_root_xyxy"] for item in outputs]))
    assert summary["category"] == "ambiguous_target_association"
    assert len(summary["joint_observation"]["candidates"]) == 2
    empty = summarize_target_aligned(initial, [], observation([]))
    assert empty["category"] == "successful_empty_detection"


def test_verification_and_discovery_outcomes_are_separate_contracts():
    initial = candidate()
    new = candidate("far", (20, 20, 30, 30))
    verification = summarize_target_aligned(initial, [new], observation([[20, 20, 30, 30]]))
    discovery = summarize_discovery([initial], [new], observation([[20, 20, 30, 30]]))
    assert verification["schema_version"] != discovery["schema_version"]
    assert verification["category"] == "no_target_aligned_proposal"
    assert discovery["category"] == "new_runtime_proposal"
    assert discovery["offline_discovery_label_required"] is True


def test_research_amendment_rejects_score_probability_and_model_fitting():
    amendment = default_amendment()
    assert validate_amendment(amendment)
    amendment["candidate_belief"]["raw_detector_score_is_probability"] = True
    with pytest.raises(ValueError, match="detector score"):
        validate_amendment(amendment)
    amendment = default_amendment()
    amendment["conditional_observation_kernel"]["fitted_in_this_phase"] = True
    with pytest.raises(ValueError, match="cannot fit"):
        validate_amendment(amendment)


def test_existing_collector_consumes_gt_free_schedule_snapshot_and_target_summary(tmp_path):
    demo = run_synthetic_demo(tmp_path / "demo")
    schedule = schedule_queries("synthetic_scene_001", ["person", "horse"], requested_count=2)
    assert schedule["scheduled_count"] == 2
    snapshot = demo["snapshot"].record
    assert snapshot["snapshot_completeness"] == "tool_execution_complete"
    assert snapshot["prefix_logical_cost"] == 1
    assert all(branch["branch_cost"] <= 3 for branch in demo["branches"])
    repeat = next(branch for branch in demo["branches"] if branch["observations"][0]["repeat_metadata"])
    initial = snapshot["candidate_history"][0]
    observed = [row["candidate"] for row in repeat["candidate_rows"]]
    summary = summarize_target_aligned(initial, observed, repeat["observations"][0])
    assert summary["category"] == "same_geometry_repeated"
    assert repeat["offline_gt_used"] is False
    assert demo["calibration_rows"]  # Labels were produced only by the separate offline stage.
