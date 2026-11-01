"""Observational action outcomes depend on prior proposals, never GT validity."""
GROUNDING_OUTCOMES = ["new_distinct_candidate", "duplicate_existing_candidate", "conflicting_candidate", "no_detection",
                      "ambiguous_association", "execution_failure", "invalid_or_unavailable_observation"]
ZOOM_OUTCOMES = ["crop_created", "crop_geometry_unavailable", "crop_artifact_unavailable", "execution_failure",
                 "invalid_or_unavailable_observation"]


def outcome(event, association=None):
    if event is None:
        return {"observed": False, "category": None, "reason": "not_executed", "failure_subtype": None}
    if not event.get("success"):
        return {"observed": True, "category": "execution_failure", "failure_subtype": event.get("error_category"), "reason": None}
    if event.get("capability") == "Zoom_In_Tool":
        crop = event.get("crop") or {}
        category = ("crop_artifact_unavailable" if not crop.get("child_image_id") else
                    "crop_geometry_unavailable" if crop.get("child_to_root_transform") is None else "crop_created")
    elif event.get("capability") == "Visual_Grounding_Tool":
        ground = event.get("grounding")
        if not ground or ground.get("boxes_reason"):
            category = "invalid_or_unavailable_observation"
        elif ground.get("empty_detection"):
            category = "no_detection"
        elif association is None or association["status"] == "unavailable_frame":
            category = "invalid_or_unavailable_observation"
        else:
            category = {"likely_duplicate": "duplicate_existing_candidate"}.get(association["status"], association["status"])
    else:
        category = "invalid_or_unavailable_observation"
    return {"observed": True, "category": category, "reason": None, "failure_subtype": None}
