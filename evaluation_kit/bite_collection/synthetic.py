"""Deterministic CPU-only collection demonstration and fixtures."""

import base64
import io
from pathlib import Path

from PIL import Image, ImageDraw

from openvlharness.capabilities.grounding import Capability as GroundingCapability
from openvlharness.capabilities.zoom import Capability as ZoomCapability
from openvlharness.services.tools.zoom_in_image_by_bbox.tool import Zoom_In_Tool

from evaluation_kit.bite_calibration.matching import GroundTruth
from evaluation_kit.bite_calibration.records import build_collection_records
from evaluation_kit.bite_calibration.validation import validate_records

from .action_selection import deterministic_coverage, randomized_selection
from .branch_runner import BranchRunner
from .eligibility import get_action_alternatives, make_action
from .persistence import atomic_json, save_collection
from .snapshot import freeze_state
from .state_builder import execute_prefix, new_memory, source_image_identity
from .validation import validate_collection


def synthetic_image_data_url():
    image = Image.new("RGB", (200, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 20, 90, 100), fill="red")
    draw.rectangle((110, 30, 180, 90), fill="blue")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


class GroundingClient:
    def execute(self, concrete_name, args, tool_call_id=None):
        raw = args["image_base64"]
        with Image.open(io.BytesIO(base64.b64decode(raw.split(",", 1)[1]))) as image:
            width, height = image.size
        query = args["query"].strip().casefold()
        if query == "person" and (width, height) == (200, 120):
            boxes, scores = [[40, 20, 90, 100]], [.9]
        elif query == "person":
            boxes, scores = [[5, 5, max(6, width-5), max(6, height-5)]], [.8]
        elif query == "horse":
            boxes, scores = [[110, 30, 180, 90], [112, 32, 178, 88]], [.88, .6]
        else:
            boxes, scores = [], []
        result = {"model": "synthetic-grounder-v1", "prompt": args["query"],
                  "pred_boxes": boxes, "pred_scores": scores,
                  "pred_masks": [f"synthetic-rle-{i}" for i in range(len(boxes))],
                  "orig_img_h": height, "orig_img_w": width, "num_masks": len(boxes)}
        return {"ok": True, "result": result, "error": None, "meta": {"synthetic": True}}


class ZoomClient:
    def __init__(self):
        self.tool = Zoom_In_Tool()

    def execute(self, concrete_name, args, tool_call_id=None):
        return {"ok": True, "result": self.tool.execute(**args), "error": None,
                "meta": {"synthetic": True}}


def synthetic_capabilities():
    client_config = {"base_url": "http://unused", "timeout_seconds": 1, "max_retries": 0}
    return {
        "Visual_Grounding_Tool": GroundingCapability(
            backend="sam3_segment", client_config=client_config, client=GroundingClient()),
        "Zoom_In_Tool": ZoomCapability(
            backend="zoom_in_image_by_bbox", client_config=client_config, client=ZoomClient()),
    }


def run_synthetic_demo(output_dir):
    output = Path(output_dir)
    data_url = synthetic_image_data_url()
    memory = new_memory([{"type": "image", "value": data_url},
                         {"type": "text", "value": "Find person and horse."}])
    source_sha = source_image_identity(memory)
    task = {"dataset": "synthetic_shapes", "sample_id": "synthetic_001",
            "question": "Find person and horse.", "permitted_classes": ["person", "horse"],
            "root_image_id": "input_image_1", "model_tool_config_id": "synthetic-v1"}
    capabilities = synthetic_capabilities()
    prefix_action = make_action("root_grounding", "Visual_Grounding_Tool", "sam3_segment",
                                {"image_id": "input_image_1", "query": "person"})
    prefix = execute_prefix(memory, capabilities, task=task, source_group_id="synthetic_scene_001",
                            source_image_sha256=source_sha, actions=[prefix_action])
    snapshot = freeze_state(
        memory, task=task, source_group_id="synthetic_scene_001", source_image_sha256=source_sha,
        capabilities=capabilities, previous_actions=prefix.actions,
        previous_observations=prefix.observations, candidate_history=prefix.candidates,
        provenance=prefix.provenance, prefix_logical_cost=prefix.branch_cost,
        native_history=[{"role": "user", "content": "synthetic history preserved only"}],
    )
    probe_branch = type("Probe", (), {"capabilities": capabilities, "task": task, "memory": memory,
                                       "actions": prefix.actions, "candidates": prefix.candidates})()
    eligible, ineligible = get_action_alternatives(
        probe_branch, alternative_queries=["horse"], remaining_budget=3,
    )
    selections = deterministic_coverage(eligible, limit=3)
    randomized = randomized_selection(eligible, count=2, seed=417)
    runner = BranchRunner(snapshot, collection_run_id="synthetic_phase04b1",
                          eligible_actions=eligible, ineligible_actions=ineligible, branch_budget=3)
    branches = runner.run_all(selections)
    validation = validate_collection(snapshot.record, branches)
    manifest = save_collection(output, snapshot, branches, design={
        "coverage": "deterministic_coverage.v1", "randomized_validation": randomized,
    })
    gt = GroundTruth(
        image={"id": 1, "width": 200, "height": 120},
        categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "horse"}],
        annotations=[
            {"id": 1, "image_id": 1, "category_id": 1, "bbox": [40, 20, 50, 80],
             "bbox_xyxy": [40, 20, 90, 100], "area": 4000, "iscrowd": 0, "ignore": 0},
            {"id": 2, "image_id": 1, "category_id": 2, "bbox": [110, 30, 70, 60],
             "bbox_xyxy": [110, 30, 180, 90], "area": 4200, "iscrowd": 0, "ignore": 0},
        ],
        provenance={"source": "synthetic_test_annotations", "sample_id": "synthetic_001",
                    "source_image_sha256": source_sha}, dropped_annotation_ids=[],
    )
    rows, matching = build_collection_records(branches, gt)
    calibration_validation = validate_records(rows)
    labels_dir = output / "offline_labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    (labels_dir / "calibration_records.jsonl").write_text(
        "".join(__import__("json").dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows))
    atomic_json(labels_dir / "matching_summary.json", matching)
    atomic_json(output / "validation" / "branch_isolation.json", {
        **validation, "calibration_validation": calibration_validation,
        "snapshot_unchanged_after_branches": True,
        "distinct_terminal_states": len({branch["terminal_state_digest"] for branch in branches}),
        "candidate_ids_unique": len({item["candidate"]["candidate_id"] for branch in branches
                                     for item in branch["candidate_rows"]}) == sum(
                                         len(branch["candidate_rows"]) for branch in branches),
    })
    return {"snapshot": snapshot, "branches": branches, "manifest": manifest,
            "validation": validation, "calibration_rows": rows, "matching": matching,
            "eligible": eligible, "ineligible": ineligible, "randomized": randomized}
