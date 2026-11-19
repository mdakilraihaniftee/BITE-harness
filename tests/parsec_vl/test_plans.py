"""Action-plan schema, validation, provenance, and the controller heuristic."""

import pytest

from openvlharness.capabilities import grounding, ocr, zoom
from openvlharness.parsec_vl.plans import (
    PLAN_TOOL, PlanError, PlanLimits, heuristic_alternatives, parse_plan, validate_plan,
)
from openvlharness.parsec_vl.fixture import FALLBACK_PLAN, PARALLEL_PLAN


@pytest.fixture
def caps():
    class Coding:  # stands in for a tool whose backend reads memory
        parallel_safe = False
        name = "Python_Coding_Agent_Tool"

        def prepare(self, *a):
            pass
    return {"OCR_Tool": ocr.Capability(backend="ocr", client_config={}, client=object()),
            "Visual_Grounding_Tool": grounding.Capability(backend="sam3_segment", client_config={}, client=object()),
            "Zoom_In_Tool": zoom.Capability(backend="zoom_in_image_by_bbox", client_config={}, client=object()),
            "Python_Coding_Agent_Tool": Coding()}


IMAGES = {"input_image_1"}


def plan_of(arguments, origin="model"):
    return parse_plan(arguments, run_id="run_x", agent_id="worker_01", origin_type=origin)


def test_fixture_plans_are_valid_and_provenance_is_recorded(caps):
    plan = validate_plan(plan_of(PARALLEL_PLAN), caps, IMAGES)
    assert plan.status == "valid" and plan.origin_type == "model" and plan.origin_agent_id == "worker_01"
    assert plan.plan_id.startswith("run_x.worker_01.plan") and plan.primary.branch_id == f"{plan.plan_id}.primary"
    assert plan.primary.goal == "ocr_crop" and plan.input_artifact_refs == ("input_image_1",)
    fallback = validate_plan(plan_of(FALLBACK_PLAN, origin="fixture"), caps, IMAGES)
    assert [b.name for b in fallback.branches] == ["primary", "alt1"] and fallback.alternatives[0].goal == "ocr_crop"
    assert fallback.to_dict()["branches"][1]["speculation_safe"] is True


def test_recorded_plan_revalidation_needs_no_model_credentials_or_tokenizer(tmp_path, monkeypatch):
    import importlib.util
    import json
    from pathlib import Path

    import openvlharness.bootstrap as bootstrap
    from openvlharness.services.models import ModelAdapter

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline revalidation must not construct or call a model")

    monkeypatch.setattr(bootstrap, "build_agent", forbidden)
    monkeypatch.setattr(ModelAdapter, "load_tokenizer", forbidden)
    monkeypatch.setattr(ModelAdapter, "request", forbidden)
    for key in ("MODEL_BASE_URL", "MODEL_API_KEY", "TOOL_SERVER_URL", "SAM3_SERVER_URL", "OCR_SERVER_URL", "DEPTH_ESTIMATION_SERVER_URL"):
        monkeypatch.delenv(key, raising=False)
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("offline_plan_probe", root / "scripts/plan_probe.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    source = tmp_path / "recorded.json"
    source.write_text(json.dumps({"agent_config": str(root / "examples/local_grounding_tools.yaml"), "rows": [{
        "schema": "current", "condition": "explicit", "plan_proposed": True, "plan_valid": None,
        "plan_reason": None, "calls": [PLAN_TOOL], "plan": PARALLEL_PLAN}]}))
    before = source.read_bytes()
    assert probe.revalidate(tmp_path / "report", "unused.yaml", source) == 0
    report = json.loads((tmp_path / "report/plan_probe_revalidated.json").read_text())
    assert report["summary"]["current/explicit"]["plan_valid"] == 1
    assert source.read_bytes() == before


def test_plan_ids_are_unique_across_plans(caps):
    ids = {plan_of(PARALLEL_PLAN).plan_id for _ in range(20)}
    assert len(ids) == 20


@pytest.mark.parametrize("mutate, reason", [
    (lambda p: p["actions"][0].update(tool="Teleport_Tool"), "unknown_tool"),
    (lambda p: p["actions"][0]["arguments"].update(secret="x"), "bad_arguments"),
    (lambda p: p["actions"][0]["arguments"].update(image_id="tool_generated_image_9"), "missing_input"),
    (lambda p: p["actions"][0]["arguments"].update(image_id="other_run/input_image_1"), "missing_input"),
    (lambda p: p["actions"][2]["arguments"].update(coords=[500, 0, 100, 100]), "bad_geometry"),
    (lambda p: p["actions"][2]["arguments"].update(coords="$ghost.boxes_normalized.0"), "unknown_dependency"),
    (lambda p: p["actions"][2]["arguments"].update(coords="$g.size"), "bad_binding"),
    (lambda p: p["actions"][1].update(depends_on=["ocr_crop"]), "cycle"),
    (lambda p: p["actions"][3].update(depends_on=["z", "nowhere"]), "unknown_dependency"),
    (lambda p: p["actions"].append({"id": "g", "tool": "OCR_Tool", "arguments": {}}), "duplicate_id"),
    (lambda p: p["actions"].append({"id": "c", "tool": "Python_Coding_Agent_Tool", "arguments": {}}), "unsupported_tool"),
    (lambda p: p["actions"].append({"id": "n", "tool": PLAN_TOOL, "arguments": {}}), "nested_plan"),
])
def test_invalid_plans_are_rejected(caps, mutate, reason):
    import copy

    raw = copy.deepcopy(PARALLEL_PLAN)
    mutate(raw)
    with pytest.raises(PlanError) as info:
        validate_plan(plan_of(raw), caps, IMAGES)
    assert info.value.reason == reason


def test_structural_errors_and_limits(caps):
    with pytest.raises(PlanError) as info:
        plan_of({"actions": []})
    assert info.value.reason == "empty"
    with pytest.raises(PlanError):
        plan_of({"actions": [{"tool": "OCR_Tool"}]})
    with pytest.raises(PlanError):
        parse_plan(PARALLEL_PLAN, run_id="r", agent_id="w", origin_type="oracle")
    with pytest.raises(PlanError) as info:
        validate_plan(plan_of(PARALLEL_PLAN), caps, IMAGES, PlanLimits(max_plan_depth=2))
    assert info.value.reason == "too_deep"
    with pytest.raises(PlanError) as info:
        validate_plan(plan_of(PARALLEL_PLAN), caps, IMAGES, PlanLimits(max_actions=3))
    assert info.value.reason == "too_many_actions"


def test_conditional_alternative_and_goal(caps):
    plan = validate_plan(plan_of({**FALLBACK_PLAN, "alternatives": [{**FALLBACK_PLAN["alternatives"][0], "goal": "z"}]}), caps, IMAGES)
    assert plan.alternatives[0].goal == "z"
    with pytest.raises(PlanError) as info:
        validate_plan(plan_of({**FALLBACK_PLAN, "goal": "missing"}), caps, IMAGES)
    assert info.value.reason == "bad_goal"


def test_heuristic_alternative_uses_only_the_plan(caps):
    plan = validate_plan(plan_of({"actions": [{"id": "o", "tool": "OCR_Tool", "arguments": {"image_id": "input_image_1"}, "expect": "text"}]}), caps, IMAGES)
    [branch] = heuristic_alternatives(plan, caps)
    assert branch.origin_type == "controller_heuristic" and branch.goal == "h_ocr"
    assert [a.tool for a in branch.actions] == ["Visual_Grounding_Tool", "Zoom_In_Tool", "OCR_Tool"]
    plan.branches.append(branch)
    validate_plan(plan, caps, IMAGES)  # the added branch passes the same validation
    assert heuristic_alternatives(plan, caps) == []  # never stacks alternatives


def test_coding_is_never_speculation_safe(caps):
    from openvlharness.parsec_vl.plans import SPECULATION_SAFE
    assert "Python_Coding_Agent_Tool" not in SPECULATION_SAFE


def test_reference_implies_dependency_and_is_recorded(caps):
    """A "$id.value" argument is an explicit data dependency; a missing depends_on entry is added and recorded."""
    import copy

    raw = copy.deepcopy(PARALLEL_PLAN)
    raw["actions"][2]["depends_on"] = []   # Zoom binds $g.boxes_normalized.0
    raw["actions"][3]["depends_on"] = []   # crop OCR binds $z.image
    plan = validate_plan(plan_of(raw), caps, IMAGES)
    actions = {a.action_id: a for a in plan.primary.actions}
    assert actions["z"].depends_on == ("g",) and actions["ocr_crop"].depends_on == ("z",)
    assert plan.estimates["inferred_dependencies"] == [{"action": "z", "depends_on": ["g"]}, {"action": "ocr_crop", "depends_on": ["z"]}]


def test_simple_schema_translates_to_the_same_plan(caps):
    from openvlharness.parsec_vl.plans import normalize_simple_plan

    simple = {"steps": [{"id": "o", "tool": "OCR_Tool", "image_id": "input_image_1"},
                        {"id": "g", "tool": "Visual_Grounding_Tool", "image_id": "input_image_1", "query": "sign"},
                        {"id": "z", "tool": "Zoom_In_Tool", "image_id": "input_image_1", "coords": "$g.box"},
                        {"id": "o2", "tool": "OCR_Tool", "image_id": "$z.image"}],
              "fallback": [{"id": "d", "tool": "Depth_Estimation_Tool", "image_id": "input_image_1"}]}
    plan = validate_plan(plan_of(normalize_simple_plan({**simple, "fallback": []})), caps, IMAGES)
    actions = {a.action_id: a for a in plan.primary.actions}
    assert actions["z"].arguments["coords"] == "$g.boxes_normalized.0" and actions["z"].depends_on == ("g",)
    assert actions["o2"].depends_on == ("z",) and actions["o"].expect == "text"
