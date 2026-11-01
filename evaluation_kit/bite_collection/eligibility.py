"""Construct action alternatives from runtime-visible state only."""

import copy
import math

from jsonschema import Draft7Validator
from openvlharness.capabilities.grounding import PUBLIC_SCHEMA as GROUNDING_SCHEMA
from openvlharness.capabilities.zoom import PUBLIC_SCHEMA as ZOOM_SCHEMA

from .budget import check_budget
from .snapshot import canonical_digest


def _action(template, capability, backend, arguments, cost=1, **extra):
    body = {"action_template": template, "capability": capability, "backend": backend,
            "arguments": copy.deepcopy(arguments), "required_artifacts": [],
            "estimated_logical_cost": cost, "origin": "controlled_collection_action", **extra}
    body["action_id"] = "action:" + canonical_digest(body)
    return body


def make_action(template, capability, backend, arguments, cost=1, **extra):
    """Public deterministic constructor used by collectors and tests."""
    return _action(template, capability, backend, arguments, cost, **extra)


def _normalized(box, width, height):
    if (not isinstance(box, list) or len(box) != 4 or not width or not height or
            not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box)):
        return None
    return [max(0, min(1000, box[0] / width * 1000)),
            max(0, min(1000, box[1] / height * 1000)),
            max(0, min(1000, box[2] / width * 1000)),
            max(0, min(1000, box[3] / height * 1000))]


def validate_step(action, state, *, remaining_budget=None):
    template = action.get("action_template")
    capability = state.capabilities.get(action.get("capability"))
    if template == "alternative_backend_verification":
        return False, "alternative_backend_not_configured"
    if capability is None:
        return False, "capability_not_configured"
    if capability.backend != action.get("backend"):
        return False, "backend_override_forbidden"
    if remaining_budget is not None and action.get("estimated_logical_cost", 1) > remaining_budget:
        return False, "insufficient_branch_budget"
    arguments = action.get("arguments")
    if not isinstance(arguments, dict):
        return False, "arguments_not_object"
    schema = ZOOM_SCHEMA if action.get("capability") == "Zoom_In_Tool" else GROUNDING_SCHEMA
    if list(Draft7Validator(schema["function"]["parameters"]).iter_errors(arguments)):
        return False, "invalid_public_arguments"
    image_id = arguments.get("image_id", "input_image_1")
    if image_id == "$last_crop":
        return False, "required_crop_not_available"
    if image_id not in state.memory.state.images.registry:
        return False, "unknown_image_reference"
    query = arguments.get("query")
    if action.get("capability") == "Visual_Grounding_Tool":
        if not isinstance(query, str) or not query.strip():
            return False, "invalid_query"
        if query.strip().casefold() not in {str(v).strip().casefold() for v in state.task.get("permitted_classes", [])}:
            return False, "query_outside_permitted_vocabulary"
    if template == "repeated_grounding" and not any(
        old.get("capability") == action["capability"] and old.get("backend") == action["backend"]
        and old.get("arguments") == arguments for old in state.actions
    ):
        return False, "matching_previous_grounding_not_available"
    if template == "focused_grounding" and not str(image_id).startswith("tool_generated_image_"):
        return False, "required_crop_not_available"
    return True, None


def get_action_alternatives(state, *, alternative_queries=(), padding=50, remaining_budget=None):
    grounding = state.capabilities.get("Visual_Grounding_Tool")
    zoom = state.capabilities.get("Zoom_In_Tool")
    backend = grounding.backend if grounding else None
    root_id = state.task.get("root_image_id", "input_image_1")
    alternatives = []
    for old in state.actions:
        if old.get("capability") == "Visual_Grounding_Tool" and old.get("arguments", {}).get("image_id", root_id) == root_id:
            alternatives.append({"path_name": "repeat:" + old["arguments"]["query"], "steps": [
                _action("repeated_grounding", "Visual_Grounding_Tool", backend, old["arguments"],
                        previous_observation_id=old.get("observation_id"), repeat_index=1)
            ]})
            break
    from .executor import _image_info
    root_facts = _image_info(state.memory, root_id)
    for candidate in state.candidates:
        coords = _normalized(candidate.get("bbox_root_xyxy"), root_facts.get("width"), root_facts.get("height"))
        if coords and zoom:
            query = candidate.get("class_name")
            alternatives.append({"path_name": "zoom_focus:" + str(candidate.get("candidate_id")), "steps": [
                _action("crop_generation", "Zoom_In_Tool", zoom.backend,
                        {"image_id": root_id, "coords": coords, "padding": padding},
                        region_evidence_id=candidate.get("candidate_id")),
                _action("focused_grounding", "Visual_Grounding_Tool", backend,
                        {"image_id": "$last_crop", "query": query}, depends_on_previous_step=True),
            ]})
            break
    permitted = {str(v).strip().casefold(): str(v).strip() for v in state.task.get("permitted_classes", [])}
    for query in alternative_queries:
        key = str(query).strip().casefold()
        if key in permitted:
            alternatives.append({"path_name": "root:" + key, "steps": [
                _action("root_grounding", "Visual_Grounding_Tool", backend,
                        {"image_id": root_id, "query": permitted[key]})
            ]})
    alternatives.append({"path_name": "alternative_backend_verification", "steps": [
        _action("alternative_backend_verification", "Visual_Grounding_Tool", "grounding_dino",
                {"image_id": root_id, "query": next(iter(permitted.values()), "object")})
    ]})
    eligible, ineligible = [], []
    for path in alternatives:
        budget = check_budget(path["steps"], remaining_budget)
        reason = budget["reason"]
        if reason is None:
            # Dynamic focused grounding is checked after crop creation.
            for index, step in enumerate(path["steps"]):
                if step["arguments"].get("image_id") == "$last_crop":
                    continue
                ok, reason = validate_step(step, state, remaining_budget=remaining_budget)
                if not ok:
                    break
        item = {**copy.deepcopy(path), "estimated_branch_cost": budget["estimated_branch_cost"]}
        if reason is None:
            item["eligibility"] = "eligible"
            eligible.append(item)
        else:
            item.update(eligibility="ineligible", reason=reason)
            ineligible.append(item)
    return eligible, ineligible
