"""Explicit one-sample development pilot using the configured public router."""

import csv
import json
from pathlib import Path

from dotenv import load_dotenv

from openvlharness.bootstrap import build_capabilities, load_agent_config, memory_factory
from openvlharness.media import local_image_to_data_url

from evaluation_kit.bite_calibration.matching import load_dataset_ground_truth
from evaluation_kit.bite_calibration.records import build_collection_records
from evaluation_kit.bite_calibration.validation import validate_records

from .action_selection import deterministic_coverage, randomized_selection
from .branch_runner import BranchRunner
from .eligibility import get_action_alternatives, make_action
from .persistence import atomic_json, save_collection
from .snapshot import freeze_state
from .state_builder import execute_prefix, source_image_identity
from .validation import validate_collection


def _row(data_root, dataset, sample_id):
    with (Path(data_root) / (dataset + ".tsv")).open(newline="") as stream:
        rows = [row for row in csv.DictReader(stream, delimiter="\t") if row["index"] == sample_id]
    if len(rows) != 1:
        raise ValueError("Pilot sample must resolve to exactly one local TSV row")
    return rows[0]


def run_live_pilot(*, config, data_root, dataset, sample_id, output_dir):
    """Collect exactly the approved prefix and three controlled alternatives."""
    load_dotenv(".env", override=False)
    config_data = load_agent_config(config)
    capabilities = build_capabilities(config_data)
    required = {"Visual_Grounding_Tool", "Zoom_In_Tool"}
    if not required <= set(capabilities):
        raise ValueError("Pilot configuration lacks grounding or zoom capability")
    row = _row(data_root, dataset, sample_id)
    classes_raw = json.loads(row["dataset_classes"])
    permitted = [str(item.get("name", item.get("category_name", ""))).strip()
                 for item in classes_raw if str(item.get("name", item.get("category_name", ""))).strip()]
    if not {"person", "horse"} <= {name.casefold() for name in permitted}:
        raise ValueError("Pilot task vocabulary does not contain person and horse")
    image_path = Path(data_root) / "images" / "ODinW" / row["image_path"]
    image_data = local_image_to_data_url(str(image_path))
    memory = memory_factory(config_data["memory"])()
    memory.start([{"type": "image", "value": image_data},
                  {"type": "text", "value": row["question"]}])
    source_sha = source_image_identity(memory)
    task = {"dataset": dataset, "sample_id": sample_id, "question": row["question"],
            "permitted_classes": permitted, "root_image_id": "input_image_1",
            "source_image_local_reference": str(image_path.resolve()),
            "model_tool_config_id": str(Path(config).resolve())}
    prefix_action = make_action("root_grounding", "Visual_Grounding_Tool", "sam3_segment",
                                {"image_id": "input_image_1", "query": "person"})
    prefix = execute_prefix(memory, capabilities, task=task,
                            source_group_id="sha256:" + source_sha,
                            source_image_sha256=source_sha, actions=[prefix_action])
    snapshot = freeze_state(
        memory, task=task, source_group_id="sha256:" + source_sha, source_image_sha256=source_sha,
        capabilities=capabilities, previous_actions=prefix.actions,
        previous_observations=prefix.observations, candidate_history=prefix.candidates,
        provenance=prefix.provenance, prefix_logical_cost=prefix.branch_cost, native_history=None,
    )
    probe = type("Probe", (), {"capabilities": capabilities, "task": task, "memory": memory,
                               "actions": prefix.actions, "candidates": prefix.candidates})()
    eligible, ineligible = get_action_alternatives(probe, alternative_queries=["horse"], remaining_budget=3)
    declared = [item for item in eligible if item["path_name"].startswith(("repeat:person", "zoom_focus:", "root:horse"))]
    if len(declared) != 3:
        raise ValueError("Expected repeat, zoom-focus and horse alternatives to be eligible")
    randomized = randomized_selection(declared, count=1, seed=417)
    selections = deterministic_coverage(declared, limit=3, design_id="development_deterministic_coverage.v1")
    runner = BranchRunner(snapshot, collection_run_id="pascalvoc_val_262_phase04b1",
                          eligible_actions=declared, ineligible_actions=ineligible, branch_budget=3)
    branches = runner.run_all(selections)
    validation = validate_collection(snapshot.record, branches)
    manifest = save_collection(output_dir, snapshot, branches, design={
        "coverage": "development_deterministic_coverage.v1",
        "randomized_selection_validation_not_executed": randomized,
    })
    # GT is loaded only after immutable runtime collection has been saved.
    gt = load_dataset_ground_truth(data_root, dataset, sample_id)
    rows, matching = build_collection_records(branches, gt)
    calibration_validation = validate_records(rows)
    output = Path(output_dir)
    labels = output / "offline_labels"
    labels.mkdir(parents=True, exist_ok=True)
    (labels / "calibration_records.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=True, allow_nan=False) + "\n" for record in rows))
    atomic_json(labels / "matching_summary.json", matching)
    latency = [observation["latency_ms"] for branch in branches for observation in branch["observations"]
               if observation.get("latency_ms") is not None]
    report = {
        **validation, "calibration_validation": calibration_validation,
        "sample_id": sample_id, "development_debug_only": True,
        "prefix_dispatches": prefix.branch_cost,
        "prefix_latency_ms": sum(item.get("latency_ms") or 0 for item in prefix.observations),
        "continuation_dispatches": validation["actual_continuation_expenditure"],
        "total_actual_dispatches": prefix.branch_cost + validation["actual_continuation_expenditure"],
        "branch_path_costs": [branch["hypothetical_path_cost"] for branch in branches],
        "latency_ms": latency, "latency_sum_ms": sum(latency),
        "randomized_design_validated_without_dispatch": randomized,
        "model_calls": 0, "offline_gt_loaded_after_collection_persistence": True,
    }
    atomic_json(output / "validation" / "live_pilot.json", report)
    return {"snapshot": snapshot, "branches": branches, "manifest": manifest,
            "rows": rows, "report": report}
