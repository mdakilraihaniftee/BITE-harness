"""Machine-readable collection templates, not an executor or planner."""
ACTION_SPEC = {
    "schema_version": "bite.action_space.v1",
    "backend": "sam3_segment",
    "actions": [
        {"name": "root_grounding", "capability": "Visual_Grounding_Tool", "available": True,
         "requires": ["registered_root_image", "runtime_query"], "cost": 1},
        {"name": "repeated_grounding", "capability": "Visual_Grounding_Tool", "available": True,
         "requires": ["registered_root_image", "same_prior_query_and_backend"], "cost": 1},
        {"name": "crop_generation", "capability": "Zoom_In_Tool", "available": True,
         "requires": ["registered_image", "region_from_runtime_evidence"], "cost": 1},
        {"name": "focused_grounding", "capability": "Visual_Grounding_Tool", "available": True,
         "requires": ["registered_crop_image", "runtime_query"], "cost": 1},
        {"name": "alternative_backend_verification", "capability": "Visual_Grounding_Tool", "available": False,
         "backend": "grounding_dino", "requires": ["independently_configured_and_tested_backend_dispatch"],
         "reason": "Standard paper configuration exposes one grounding backend, not per-action backend selection", "cost": None},
    ],
    "discovery_hypothesis_schema": {"version": "bite.discovery_hypothesis.v1", "implemented": False,
                                    "origin_required": "runtime_visible_region_or_image_evidence",
                                    "gt_coordinates_allowed": False},
    "collection_designs": [
        {"name": "deterministic_coverage", "execute_in_phase04a": False,
         "selection_probability": 1.0, "scope": "Every prespecified eligible state/action in the coverage design"},
        {"name": "randomized_eligible_uniform", "execute_in_phase04a": False,
         "selection_probability_formula": "1 / number_of_eligible_actions", "seed_required": True,
         "requires": ["frozen_prior_snapshot", "complete_eligible_action_list", "independent_branch_clone"]},
    ],
}


def validate_action(action, *, images, crop_images=(), previous=(), backend="sam3_segment", runtime_regions=()):
    template = next((a for a in ACTION_SPEC["actions"] if a["name"] == action.get("name")), None)
    if template is None or not template["available"]:
        raise ValueError("Action template is unavailable")
    expected_backend = "zoom_in_image_by_bbox" if action["name"] == "crop_generation" else backend
    if action.get("backend", expected_backend) != expected_backend:
        raise ValueError("Action cannot override the configured backend")
    args = action.get("arguments", {})
    image_id = args.get("image_id")
    if image_id not in images:
        raise ValueError("Action requires a registered image")
    if action["name"] == "focused_grounding" and image_id not in crop_images:
        raise ValueError("Focused grounding requires an actual registered crop")
    if action["name"] in {"root_grounding", "repeated_grounding"} and image_id in crop_images:
        raise ValueError("Root grounding cannot silently use a crop")
    if action["name"] != "crop_generation" and not isinstance(args.get("query"), str):
        raise ValueError("Grounding requires a runtime query")
    if action["name"] == "repeated_grounding" and not any(
            p.get("arguments") == args and p.get("backend") == backend for p in previous):
        raise ValueError("Repeated grounding requires a matching prior action")
    if action["name"] == "crop_generation":
        region = runtime_regions.get(action.get("region_evidence_id")) if isinstance(runtime_regions, dict) else None
        if not region or args.get("coords") != region.get("coords"):
            raise ValueError("Crop region must come from runtime-visible evidence, not GT")
    from jsonschema import validate
    from openvlharness.capabilities.grounding import PUBLIC_SCHEMA as GROUNDING
    from openvlharness.capabilities.zoom import PUBLIC_SCHEMA as ZOOM
    parameters = (ZOOM if action["name"] == "crop_generation" else GROUNDING)["function"]["parameters"]
    if set(args) - set(parameters["properties"]):
        raise ValueError("Unsupported task/deployment argument")
    validate(args, parameters)
    return True
