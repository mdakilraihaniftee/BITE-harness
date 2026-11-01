#!/usr/bin/env python3
"""Exercise the Phase 4B-1 collector on one frozen Aquarium image using CPU mocks."""

from __future__ import annotations

import argparse
import base64
import io
import json
from pathlib import Path

from PIL import Image

from openvlharness.capabilities.grounding import Capability as GroundingCapability
from openvlharness.capabilities.zoom import Capability as ZoomCapability
from openvlharness.services.tools.zoom_in_image_by_bbox.tool import Zoom_In_Tool

from evaluation_kit.bite_calibration.matching import GroundTruth
from evaluation_kit.bite_calibration.records import build_collection_records
from evaluation_kit.bite_calibration.validation import validate_records
from evaluation_kit.bite_collection.action_selection import deterministic_coverage
from evaluation_kit.bite_collection.branch_runner import BranchRunner
from evaluation_kit.bite_collection.eligibility import get_action_alternatives, make_action
from evaluation_kit.bite_collection.persistence import atomic_json, save_collection
from evaluation_kit.bite_collection.snapshot import freeze_state
from evaluation_kit.bite_collection.state_builder import execute_prefix, new_memory, source_image_identity
from evaluation_kit.bite_collection.validation import validate_collection


SOURCE_ID = "odinw13:Aquarium_Aquarium_Combined.v2-raw-1024.coco"
ANNOTATION = Path("data/calibration_sources/odinw13/extracted/Aquarium_Aquarium_Combined.v2-raw-1024.coco/Aquarium/Aquarium Combined.v2-raw-1024.coco/train/annotations_without_background.json")


class AquariumMockGroundingClient:
    def execute(self, concrete_name, args, tool_call_id=None):
        raw = base64.b64decode(args["image_base64"].split(",", 1)[1])
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
        box = [width * .25, height * .25, width * .75, height * .75]
        result = {
            "model": "aquarium-cpu-mock-grounder-v1", "prompt": args["query"],
            "pred_boxes": [box], "pred_scores": [.75], "pred_masks": ["mock-rle"],
            "orig_img_h": height, "orig_img_w": width, "num_masks": 1,
        }
        return {"ok": True, "result": result, "error": None, "meta": {"cpu_mock": True}}


class AquariumMockZoomClient:
    def __init__(self):
        self.tool = Zoom_In_Tool()

    def execute(self, concrete_name, args, tool_call_id=None):
        return {"ok": True, "result": self.tool.execute(**args), "error": None,
                "meta": {"cpu_mock": True}}


def capabilities():
    config = {"base_url": "http://unused", "timeout_seconds": 1, "max_retries": 0}
    return {
        "Visual_Grounding_Tool": GroundingCapability(
            backend="sam3_segment", client_config=config, client=AquariumMockGroundingClient()),
        "Zoom_In_Tool": ZoomCapability(
            backend="zoom_in_image_by_bbox", client_config=config, client=AquariumMockZoomClient()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--entries", type=Path, required=True)
    parser.add_argument("--schedules", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    entries = json.loads(args.entries.read_text())["entries"]
    schedules = json.loads(args.schedules.read_text())["entries"]
    by_entry = {row["entry_id"]: row for row in entries}
    selected_manifest = next(row for row in manifest["entries"] if row["partition"] == "calibration_fit")
    selected = by_entry[selected_manifest["entry_id"]]
    schedule = next(row for row in schedules if row["source_group_id"] == selected["source_group_id"])
    raw = Path(selected["image_path"]).read_bytes()
    data_url = "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
    query = schedule["queries"][0]
    question = f"Find {query}."
    memory = new_memory([{"type": "image", "value": data_url}, {"type": "text", "value": question}])
    source_sha = source_image_identity(memory)
    if source_sha != selected["image_sha256"]:
        raise RuntimeError("Collector root pixels differ from frozen manifest")
    task = {
        "dataset": SOURCE_ID, "sample_id": selected["entry_id"], "question": question,
        "permitted_classes": schedule["available_verified_classes"],
        "root_image_id": "input_image_1", "model_tool_config_id": "aquarium-cpu-mock-v1",
    }
    tools = capabilities()
    prefix_action = make_action(
        "root_grounding", "Visual_Grounding_Tool", "sam3_segment",
        {"image_id": "input_image_1", "query": query},
    )
    prefix = execute_prefix(memory, tools, task=task, source_group_id=selected["source_group_id"],
                            source_image_sha256=source_sha, actions=[prefix_action])
    snapshot = freeze_state(
        memory, task=task, source_group_id=selected["source_group_id"], source_image_sha256=source_sha,
        capabilities=tools, previous_actions=prefix.actions, previous_observations=prefix.observations,
        candidate_history=prefix.candidates, provenance=prefix.provenance,
        prefix_logical_cost=prefix.branch_cost, native_history=None,
    )
    probe = type("Probe", (), {"capabilities": tools, "task": task, "memory": memory,
                                "actions": prefix.actions, "candidates": prefix.candidates})()
    eligible, ineligible = get_action_alternatives(
        probe, alternative_queries=schedule["queries"][1:], remaining_budget=3,
    )
    selections = deterministic_coverage(eligible, limit=3)
    runner = BranchRunner(snapshot, collection_run_id="aquarium_phase04b2b1a_cpu_mock",
                          eligible_actions=eligible, ineligible_actions=ineligible, branch_budget=3)
    branches = runner.run_all(selections)
    validation = validate_collection(snapshot.record, branches)
    output = args.output.resolve()
    collection_manifest = save_collection(output, snapshot, branches, design={
        "mode": "cpu_mock_only", "query_schedule": schedule,
    })
    raw_records = sorted(output.glob("branches/*.json"))
    if len(raw_records) != len(branches):
        raise RuntimeError("Raw branch persistence incomplete before offline labeling")
    document = json.loads(ANNOTATION.read_text())
    image = next(row for row in document["images"] if Path(row["file_name"]).name == selected["source_image_id"])
    categories = document["categories"]
    ground_truth_rows = []
    for row in document["annotations"]:
        if row["image_id"] != image["id"]:
            continue
        x, y, width, height = row["bbox"]
        ground_truth_rows.append({
            **row, "bbox_xyxy": [x, y, x + width, y + height],
            "area": row.get("area", width * height), "iscrowd": row.get("iscrowd", 0),
            "ignore": row.get("ignore", 0),
        })
    ground_truth = GroundTruth(
        image=image, categories=categories, annotations=ground_truth_rows,
        provenance={"source": str(ANNOTATION.resolve()), "sample_id": selected["entry_id"],
                    "source_image_sha256": source_sha}, dropped_annotation_ids=[],
    )
    calibration_rows, matching = build_collection_records(branches, ground_truth)
    calibration_validation = validate_records(calibration_rows)
    labels_dir = output / "offline_labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    (labels_dir / "calibration_records.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in calibration_rows))
    atomic_json(labels_dir / "matching_summary.json", matching)
    result = {
        "schema_version": "bite.aquarium_collector_compatibility.v1", "compatible": True,
        "validation_mode": "cpu_mock_only", "source_entry_id": selected["entry_id"],
        "source_image_sha256": source_sha, "source_group_id": selected["source_group_id"],
        "query_schedule": schedule, "prefix_actions": len(prefix.actions),
        "snapshot_capture_complete": snapshot.record["capture_complete"],
        "eligible_paths": [row["path_name"] for row in eligible],
        "ineligible_paths": [{"path_name": row["path_name"], "reason": row["reason"]} for row in ineligible],
        "branch_count": len(branches), "branch_costs": [row["branch_cost"] for row in branches],
        "maximum_continuation_budget": 3, "raw_branches_persisted_before_labels": True,
        "offline_gt_association_after_raw_persistence": True,
        "calibration_record_count": len(calibration_rows), "collection_validation": validation,
        "calibration_validation": calibration_validation, "collection_manifest": collection_manifest,
        "gpu_collection_executed": False,
    }
    atomic_json(output / "collector_compatibility.json", result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
