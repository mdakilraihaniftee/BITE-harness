import ast
import copy
import json
from pathlib import Path

import numpy as np
import pytest
from jsonschema import validate

from openvlharness.bite.schemas import OBSERVATION_SCHEMA
from openvlharness.contracts import VirtualCall

from evaluation_kit.bite_calibration.validation import CALIBRATION_SCHEMA, validate_records
from evaluation_kit.bite_collection.action_selection import deterministic_coverage, randomized_selection
from evaluation_kit.bite_collection.branch_runner import BranchRunner
from evaluation_kit.bite_collection.budget import check_budget, experimental_expenditure, path_cost
from evaluation_kit.bite_collection.cloning import clone_snapshot
from evaluation_kit.bite_collection.eligibility import get_action_alternatives, make_action, validate_step
from evaluation_kit.bite_collection.executor import execute_action
from evaluation_kit.bite_collection.persistence import hydrate_snapshot_record
from evaluation_kit.bite_collection.schemas import COLLECTION_SCHEMA, SNAPSHOT_SCHEMA
from evaluation_kit.bite_collection.snapshot import freeze_state, load_snapshot
from evaluation_kit.bite_collection.state_builder import execute_prefix, new_memory, source_image_identity
from evaluation_kit.bite_collection.synthetic import (
    GroundingClient, run_synthetic_demo, synthetic_capabilities, synthetic_image_data_url,
)
from evaluation_kit.bite_collection.validation import validate_collection


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    return run_synthetic_demo(tmp_path_factory.mktemp("collection"))


def test_snapshot_and_branch_schemas(demo):
    validate(demo["snapshot"].record, SNAPSHOT_SCHEMA)
    for branch in demo["branches"]:
        validate(branch, COLLECTION_SCHEMA)


def test_all_branches_share_exact_parent(demo):
    parent = demo["snapshot"].record
    assert {branch["parent_snapshot_id"] for branch in demo["branches"]} == {parent["snapshot_id"]}
    assert {branch["parent_state_digest"] for branch in demo["branches"]} == {parent["state_digest"]}


def test_snapshot_is_tool_complete_but_not_vlm_continuation(demo):
    record = demo["snapshot"].record
    assert record["snapshot_completeness"] == "tool_execution_complete"
    assert record["history_mode"] == "preserved_not_extended"
    assert any("VLM-continuation" in item for item in record["limitations"])


def test_memory_clone_isolation_for_crop_binding_counter_and_array(demo):
    snapshot = demo["snapshot"]
    a = clone_snapshot(snapshot, branch_id="A")
    b = clone_snapshot(snapshot, branch_id="B")
    original = snapshot.record
    a.memory.register_image(synthetic_image_data_url(), aliases=["a-only"], provenance="test")
    a.memory.store_binding(prefix="array", query="q", value={"x": np.array([1, 2])},
                           source_tool="test", source_args={}, descriptions={"x": "array"})
    assert "a-only" in a.memory.state.images.alias_to_ref
    assert "a-only" not in b.memory.state.images.alias_to_ref
    assert a.memory.state.bindings.bindings
    assert not any(key.startswith("array") for key in b.memory.state.bindings.bindings)
    assert snapshot.record == original


def test_reused_image_bytes_do_not_share_mutable_metadata(demo):
    a = clone_snapshot(demo["snapshot"], branch_id="A")
    b = clone_snapshot(demo["snapshot"], branch_id="B")
    data = a.memory.state.images.registry["input_image_1"]["data_url"]
    a.memory.register_image(data, aliases=["shared-bytes-a"], provenance="test")
    assert "shared-bytes-a" in a.memory.state.images.alias_to_ref
    assert "shared-bytes-a" not in b.memory.state.images.alias_to_ref


def test_branch_histories_and_candidate_ids_are_distinct(demo):
    assert len({branch["terminal_state_digest"] for branch in demo["branches"]}) == 3
    candidate_ids = [row["candidate"]["candidate_id"] for branch in demo["branches"] for row in branch["candidate_rows"]]
    assert len(candidate_ids) == len(set(candidate_ids))


def test_zoom_branch_has_exact_provenance_and_two_calls(demo):
    branch = next(branch for branch in demo["branches"] if len(branch["selected_path"]) == 2)
    crop = branch["observations"][0]["crop"]
    assert crop["parent_image_id"] == "input_image_1"
    assert crop["child_image_id"].startswith("tool_generated_image_")
    assert crop["child_to_root_transform"][2] == [0, 0, 1]
    assert branch["branch_cost"] == 2
    assert branch["hypothetical_path_cost"] == branch["prefix_cost"] + 2
    assert len(branch["resulting_artifacts"]) >= 1


def test_multi_detection_is_one_joint_observation_and_one_cost(demo):
    branch = next(branch for branch in demo["branches"] if any(
        action["arguments"].get("query") == "horse" for action in branch["selected_path"]))
    assert len(branch["candidate_rows"]) == 2
    assert len({row["joint_observation_id"] for row in branch["candidate_rows"]}) == 1
    assert len({row["logical_cost_accounting_id"] for row in branch["candidate_rows"]}) == 1
    assert branch["branch_cost"] == 1


def test_repeat_records_dependency_and_geometry_comparison(demo):
    branch = next(branch for branch in demo["branches"] if any(
        action["action_template"] == "repeated_grounding" for action in branch["selected_path"]))
    repeat = branch["observations"][0]["repeat_metadata"]
    assert repeat["previous_observation_id"]
    assert repeat["same_source_image_sha256"] and repeat["same_backend"]
    assert repeat["geometry_differs"] is False
    assert "not statistically independent" in repeat["dependence_note"]


def test_prefix_and_experimental_costs_are_distinct(demo):
    assert {branch["prefix_cost"] for branch in demo["branches"]} == {1}
    assert experimental_expenditure(demo["branches"]) == 4
    assert [branch["hypothetical_path_cost"] for branch in demo["branches"]] == [2, 3, 2]


def test_offline_label_export_reuses_calibration_schema(demo):
    report = validate_records(demo["calibration_rows"])
    assert report["valid"]
    assert all(row["runtime_features"]["context"]["state_completeness"] ==
               "tool_execution_complete_snapshot" for row in demo["calibration_rows"])


def test_gt_is_absent_from_snapshot_and_branches(demo):
    runtime = json.dumps({"snapshot": demo["snapshot"].record, "branches": demo["branches"]}).lower()
    for forbidden in ["ground_truth", "official_tp", "offline_labels", "best_eligible_gt"]:
        assert forbidden not in runtime


def test_existing_observer_and_calibration_schemas_still_validate_fixtures():
    observer = json.loads(Path("tests/bite_calibration/fixtures/observer_v1.json").read_text())
    validate(observer, OBSERVATION_SCHEMA)
    rows = [json.loads(line) for line in Path("outputs/bite/phase04a/smoke/calibration_records.jsonl").read_text().splitlines()]
    validate_records(rows)
    validate(rows[0], CALIBRATION_SCHEMA)


def test_deterministic_coverage_propensity(demo):
    selections = deterministic_coverage(demo["eligible"])
    assert all(item["selection_probability"] == 1 for item in selections)
    assert len(selections) == len(demo["eligible"])


def test_randomized_without_replacement_is_repeatable(demo):
    one = randomized_selection(demo["eligible"], count=2, seed=9)
    two = randomized_selection(demo["eligible"], count=2, seed=9)
    assert one == two
    assert all(item["selection_probability"] == pytest.approx(2 / len(demo["eligible"])) for item in one)
    assert one[0]["path_draw_probability"] == pytest.approx(1 / len(demo["eligible"]))
    assert one[1]["path_draw_probability"] == pytest.approx(1 / (len(demo["eligible"])-1))


def test_empty_randomized_set_and_bad_count():
    assert randomized_selection([], count=0, seed=1) == []
    with pytest.raises(ValueError):
        randomized_selection([], count=1, seed=1)


def test_ineligible_backend_is_recorded(demo):
    assert any(item["path_name"] == "alternative_backend_verification" and
               item["reason"] == "alternative_backend_not_configured" for item in demo["ineligible"])


def test_unknown_image_invalid_query_and_budget_are_ineligible(demo):
    branch = clone_snapshot(demo["snapshot"], branch_id="eligibility")
    backend = branch.capabilities["Visual_Grounding_Tool"].backend
    unknown = make_action("root_grounding", "Visual_Grounding_Tool", backend,
                          {"image_id": "missing", "query": "person"})
    invalid = make_action("root_grounding", "Visual_Grounding_Tool", backend,
                          {"image_id": "input_image_1", "query": ""})
    assert validate_step(unknown, branch)[1] == "unknown_image_reference"
    assert validate_step(invalid, branch)[1] == "invalid_query"
    assert validate_step(unknown, branch, remaining_budget=0)[1] == "insufficient_branch_budget"


def test_focused_grounding_requires_crop(demo):
    branch = clone_snapshot(demo["snapshot"], branch_id="focus")
    backend = branch.capabilities["Visual_Grounding_Tool"].backend
    action = make_action("focused_grounding", "Visual_Grounding_Tool", backend,
                         {"image_id": "input_image_1", "query": "person"})
    assert validate_step(action, branch)[1] == "required_crop_not_available"


def test_repeat_requires_matching_prior(demo):
    branch = clone_snapshot(demo["snapshot"], branch_id="repeat")
    backend = branch.capabilities["Visual_Grounding_Tool"].backend
    action = make_action("repeated_grounding", "Visual_Grounding_Tool", backend,
                         {"image_id": "input_image_1", "query": "horse"})
    assert validate_step(action, branch)[1] == "matching_previous_grounding_not_available"


def test_rejected_pre_dispatch_costs_zero(demo):
    branch = clone_snapshot(demo["snapshot"], branch_id="reject")
    action = make_action("root_grounding", "Visual_Grounding_Tool", "sam3_segment",
                         {"image_id": "missing", "query": "person"})
    result = execute_action(branch, action)
    assert not result["executed"] and result["logical_cost"] == 0 and branch.branch_cost == 0


class FailedClient(GroundingClient):
    def execute(self, concrete_name, args, tool_call_id=None):
        return {"ok": False, "result": None, "error": {"code": "backend_failed", "message": "fixture"}, "meta": {}}


def test_failed_dispatched_call_costs_one(demo):
    branch = clone_snapshot(demo["snapshot"], branch_id="failed")
    cap = copy.copy(branch.capabilities["Visual_Grounding_Tool"])
    cap.client = FailedClient()
    branch.capabilities = {**branch.capabilities, "Visual_Grounding_Tool": cap}
    action = make_action("root_grounding", "Visual_Grounding_Tool", "sam3_segment",
                         {"image_id": "input_image_1", "query": "horse"})
    result = execute_action(branch, action)
    assert result["dispatched"] and result["logical_cost"] == 1
    assert result["outcome"]["category"] == "execution_failure"


class EmptyClient(GroundingClient):
    def execute(self, concrete_name, args, tool_call_id=None):
        value = super().execute(concrete_name, {**args, "query": "nothing"}, tool_call_id)
        value["result"]["prompt"] = args["query"]
        return value


def test_empty_detection_is_observed_not_missing(demo):
    branch = clone_snapshot(demo["snapshot"], branch_id="empty")
    cap = copy.copy(branch.capabilities["Visual_Grounding_Tool"])
    cap.client = EmptyClient()
    branch.capabilities = {**branch.capabilities, "Visual_Grounding_Tool": cap}
    action = make_action("root_grounding", "Visual_Grounding_Tool", "sam3_segment",
                         {"image_id": "input_image_1", "query": "horse"})
    result = execute_action(branch, action)
    assert result["outcome"] == {"observed": True, "category": "no_detection",
                                 "failure_subtype": None, "reason": None}


class InvalidClient(GroundingClient):
    def execute(self, concrete_name, args, tool_call_id=None):
        value = super().execute(concrete_name, args, tool_call_id)
        value["result"]["pred_boxes"] = [[1, 2, 3]]
        return value


def test_invalid_result_is_dispatched_failure_and_costs_one(demo):
    branch = clone_snapshot(demo["snapshot"], branch_id="invalid")
    cap = copy.copy(branch.capabilities["Visual_Grounding_Tool"])
    cap.client = InvalidClient()
    branch.capabilities = {**branch.capabilities, "Visual_Grounding_Tool": cap}
    action = make_action("root_grounding", "Visual_Grounding_Tool", "sam3_segment",
                         {"image_id": "input_image_1", "query": "horse"})
    result = execute_action(branch, action)
    assert result["dispatched"] and result["logical_cost"] == 1
    assert result["outcome"]["failure_subtype"] == "invalid_tool_result"


def test_nested_crop_transforms_compose_in_one_branch(demo):
    branch = clone_snapshot(demo["snapshot"], branch_id="nested")
    zoom = branch.capabilities["Zoom_In_Tool"].backend
    first = make_action("crop_generation", "Zoom_In_Tool", zoom,
                        {"image_id": "input_image_1", "coords": [200, 100, 600, 900], "padding": 50})
    one = execute_action(branch, first)
    child = one["observation"]["crop"]["child_image_id"]
    second = make_action("crop_generation", "Zoom_In_Tool", zoom,
                         {"image_id": child, "coords": [100, 100, 900, 900], "padding": 50})
    two = execute_action(branch, second)
    parent_transform = one["observation"]["crop"]["child_to_root_transform"]
    nested = two["observation"]["crop"]
    assert nested["parent_image_id"] == child
    assert nested["child_to_root_transform"][0][2] >= parent_transform[0][2]
    assert nested["child_to_root_transform"][1][2] >= parent_transform[1][2]


def test_failed_prerequisite_creates_explicit_partial_without_dispatch(demo):
    focused = make_action("focused_grounding", "Visual_Grounding_Tool", "sam3_segment",
                          {"image_id": "$last_crop", "query": "person"})
    selection = {"path": {"path_name": "missing_crop", "steps": [focused]},
                 "selection_design": "test", "selection_probability": 1.0,
                 "path_draw_probability": 1.0, "selection_steps": [], "selection_seed": None}
    runner = BranchRunner(demo["snapshot"], collection_run_id="partial",
                          eligible_actions=[], ineligible_actions=[], branch_budget=3)
    record, _ = runner.run(selection)
    assert record["status"] == "partial" and not record["capture_complete"]
    assert record["branch_cost"] == 0 and record["observations"] == []
    assert record["errors"][0]["reason"] == "failed_prerequisite_action"


def test_native_history_preserved_but_never_extended(demo):
    before = demo["snapshot"].record["native_history"]
    branch = clone_snapshot(demo["snapshot"], branch_id="history")
    assert branch.native_history == before
    branch.native_history.append({"role": "local-test"})
    assert demo["snapshot"].record["native_history"] == before
    assert all(item["native_history_extended"] is False for item in demo["branches"])


def test_persisted_snapshot_rehydrates_and_verifies(demo):
    path = Path(demo["manifest"]["snapshot"])
    hydrated = hydrate_snapshot_record(path)
    assert hydrated["memory"]["state"]["images"]["registry"]["input_image_1"]["data_url"].startswith("data:image/")
    loaded = load_snapshot(path, capabilities=synthetic_capabilities())
    assert loaded.record["state_digest"] == demo["snapshot"].record["state_digest"]


def test_incomplete_snapshot_cannot_clone():
    memory = new_memory([{"type": "image", "value": synthetic_image_data_url()}])
    memory.register_lazy_image("https://example.invalid/image.png", provenance="test")
    sha = source_image_identity(memory)
    task = {"sample_id": "x", "permitted_classes": ["person"], "root_image_id": "input_image_1"}
    snapshot = freeze_state(memory, task=task, source_group_id="x", source_image_sha256=sha,
                            capabilities=synthetic_capabilities())
    assert snapshot.record["snapshot_completeness"] == "incomplete"
    with pytest.raises(ValueError):
        clone_snapshot(snapshot, branch_id="x")


@pytest.mark.parametrize("prefix,branch,total", [(0, 0, 0), (1, 2, 3), (4, 1, 5)])
def test_path_cost(prefix, branch, total):
    assert path_cost(prefix, branch) == total


def test_budget_check_varied_path_costs():
    path = [{"estimated_logical_cost": 1}, {"estimated_logical_cost": 1}]
    assert check_budget(path, 2)["eligible"]
    assert check_budget(path, 1)["reason"] == "insufficient_branch_budget"


def test_original_agent_and_evaluator_do_not_import_collector():
    for path in [Path("openvlharness/agent/agent.py"), Path("evaluation_kit/cli.py"), Path("evaluation_kit/runner.py")]:
        tree = ast.parse(path.read_text())
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any(module and "bite_collection" in module for module in imports)


def test_validation_rejects_parent_mismatch(demo):
    bad = copy.deepcopy(demo["branches"][0])
    bad["parent_snapshot_id"] = "wrong"
    with pytest.raises(ValueError):
        validate_collection(demo["snapshot"].record, [bad])
