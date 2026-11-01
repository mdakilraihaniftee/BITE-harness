"""Execute controlled actions through the existing public capability lifecycle."""

import base64
import copy
import hashlib
import io
import time

from PIL import Image

from openvlharness.bite.geometry import compose, crop_rectangle, transform_box, translation
from openvlharness.contracts import VirtualCall

from evaluation_kit.bite_calibration.candidate_association import associate
from evaluation_kit.bite_calibration.common import identity

from .eligibility import validate_step


def _image_info(memory, image_id):
    entry = memory.state.images.registry.get(image_id, {})
    data_url = entry.get("data_url")
    if not isinstance(data_url, str) or "," not in data_url:
        return {"image_id": image_id, "sha256": None, "width": None, "height": None}
    raw = base64.b64decode(data_url.split(",", 1)[1])
    with Image.open(io.BytesIO(raw)) as image:
        return {"image_id": image_id, "sha256": hashlib.sha256(raw).hexdigest(),
                "width": image.width, "height": image.height}


def _scrub(value, key=""):
    if isinstance(value, dict):
        return {str(k): _scrub(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, key) for v in value]
    if isinstance(value, str) and (value.startswith("data:image/") or "base64" in key.lower() or key.lower().endswith("_b64")):
        return {"media_omitted": True, "encoded_sha256": hashlib.sha256(value.encode()).hexdigest()}
    return copy.deepcopy(value)


class DispatchProbe:
    """Exact branch-local signal for the post-validation dispatch boundary."""

    def __init__(self):
        self.dispatched = False
        self.resolution = None
        self.translated_arguments = None
        self.exception_type = None

    def dispatch(self, call, capability, memory, resolution=None, args=None):
        self.dispatched = True
        self.resolution = copy.deepcopy(resolution)
        self.translated_arguments = _scrub(args)

    def transport_error(self, call, exception):
        self.exception_type = type(exception).__name__


def _frame(branch, image_id):
    frames = branch.provenance.setdefault("crop_frames", {})
    if image_id in frames:
        return copy.deepcopy(frames[image_id])
    if image_id == branch.task.get("root_image_id", "input_image_1"):
        return {"root_image_id": image_id, "child_to_root_transform": translation(), "frame_reason": None}
    return {"root_image_id": None, "child_to_root_transform": None, "frame_reason": "unknown_geometry"}


def _outcome(capability, result, candidates, association):
    if not result.ok:
        return {"observed": True, "category": "execution_failure",
                "failure_subtype": (result.error or {}).get("code"), "reason": None}
    if capability == "Zoom_In_Tool":
        image_id = (result.data or {}).get("image")
        return {"observed": True, "category": "crop_created" if image_id else "crop_artifact_unavailable",
                "failure_subtype": None, "reason": None}
    if capability == "Visual_Grounding_Tool":
        if not isinstance((result.data or {}).get("boxes"), list):
            category = "invalid_or_unavailable_observation"
        elif not candidates:
            category = "no_detection"
        elif association is None:
            category = "invalid_or_unavailable_observation"
        else:
            category = {"likely_duplicate": "duplicate_existing_candidate"}.get(
                association["status"], association["status"])
        return {"observed": True, "category": category, "failure_subtype": None, "reason": None}
    return {"observed": True, "category": "invalid_or_unavailable_observation",
            "failure_subtype": None, "reason": "unsupported_observation_type"}


def execute_action(branch, action, *, remaining_budget=None):
    """Validate and dispatch one action, charging only an reached execution boundary."""
    eligible, reason = validate_step(action, branch, remaining_budget=remaining_budget)
    if not eligible:
        return {"executed": False, "dispatched": False, "logical_cost": 0,
                "outcome": {"observed": False, "category": None, "failure_subtype": None, "reason": reason}}
    capability = branch.capabilities[action["capability"]]
    call_index = len(branch.actions) + 1
    call_id = f"controlled:{branch.branch_id}:{call_index:04d}"
    call = VirtualCall(call_id, action["capability"], copy.deepcopy(action["arguments"]))
    probe = DispatchProbe()
    prior_observer = getattr(branch.memory, "_bite_observer", None)
    branch.memory._bite_observer = probe
    started = time.monotonic()
    try:
        result = capability.invoke(call, branch.memory)
    finally:
        elapsed = (time.monotonic() - started) * 1000
        if prior_observer is None:
            delattr(branch.memory, "_bite_observer")
        else:
            branch.memory._bite_observer = prior_observer
    logical_cost = 1 if probe.dispatched else 0
    branch.branch_cost += logical_cost
    observation_id = identity([branch.parent_snapshot_id, branch.branch_id, call_id], "joint_observation") if probe.dispatched else None
    requested_image = action["arguments"].get("image_id", branch.task.get("root_image_id", "input_image_1"))
    resolved_image = requested_image
    rewrites = (probe.resolution or {}).get("rewrites", [])
    if rewrites and rewrites[0].get("image_ref"):
        resolved_image = rewrites[0]["image_ref"]
    source = _image_info(branch.memory, resolved_image)
    frame = _frame(branch, resolved_image)
    root_image = _image_info(branch.memory, frame.get("root_image_id")) if frame.get("root_image_id") else {
        "image_id": None, "sha256": None, "width": None, "height": None,
    }
    candidates = []
    association = None
    candidate_outcomes = {}
    if result.ok and action["capability"] == "Visual_Grounding_Tool":
        canonical = result.data or {}
        boxes = canonical.get("boxes") if isinstance(canonical.get("boxes"), list) else []
        labels = canonical.get("labels") or []
        scores = canonical.get("scores") or []
        masks = canonical.get("masks") or []
        association_prior = list(branch.candidates)
        for rank, box in enumerate(boxes):
            candidate_id = identity([branch.branch_id, observation_id, rank], "candidate")
            root_box = transform_box(box, frame.get("child_to_root_transform"))
            mask = masks[rank] if rank < len(masks) else None
            candidate = {
                "schema_version": "bite.candidate.v1", "candidate_id": candidate_id,
                "sample_id": branch.task.get("sample_id"),
                "class_name": labels[rank] if rank < len(labels) else canonical.get("query"),
                "source_observation_id": observation_id,
                "source_detection_ids": [observation_id + f":detection_{rank:04d}"],
                "bbox_local_xyxy": copy.deepcopy(box), "bbox_root_xyxy": root_box,
                "bbox_root_reported_xyxy": copy.deepcopy(root_box),
                "frame_reason": frame.get("frame_reason"), "root_image_id": frame.get("root_image_id"),
                "resolved_image_id": resolved_image, "source_group_id": branch.source_group_id,
                "source_image_sha256": branch.source_image_sha256, "source_backend": action["backend"],
                "raw_scores": [scores[rank]] if rank < len(scores) else [],
                "mask_ref": {"sha256": hashlib.sha256(mask.encode()).hexdigest(),
                             "encoding": "COCO_RLE_counts", "size_height_width": canonical.get("size")}
                            if isinstance(mask, str) else None,
                "candidate_origin": "controlled_collection_grounding", "association_status": "unresolved",
            }
            association = associate(candidate, association_prior)
            candidate["association_status"] = association["status"]
            candidates.append(candidate)
            association_prior.append(candidate)
            candidate_outcomes[candidate_id] = {
                "observed": True,
                "category": {"likely_duplicate": "duplicate_existing_candidate"}.get(
                    association["status"], association["status"]),
                "failure_subtype": None, "reason": None,
            }
    crop = None
    if result.ok and action["capability"] == "Zoom_In_Tool":
        child_id = (result.data or {}).get("image")
        if child_id:
            parent = source
            rectangle = crop_rectangle(action["arguments"]["coords"], action["arguments"].get("padding", 50),
                                       parent["width"], parent["height"])
            child = _image_info(branch.memory, child_id)
            child_to_parent = translation(rectangle[0], rectangle[1])
            child_to_root = compose(frame["child_to_root_transform"], child_to_parent) if frame.get("child_to_root_transform") else None
            child_frame = {"root_image_id": frame.get("root_image_id"),
                           "child_to_root_transform": child_to_root,
                           "frame_reason": frame.get("frame_reason")}
            branch.provenance.setdefault("crop_frames", {})[child_id] = child_frame
            crop = {"parent_image_id": resolved_image, "child_image_id": child_id,
                    "crop_rectangle_parent_xyxy": list(rectangle),
                    "child_to_parent_transform": child_to_parent,
                    "child_to_root_transform": child_to_root, "root_image_id": frame.get("root_image_id"),
                    "parent_width": parent["width"], "parent_height": parent["height"],
                    "child_width": child["width"], "child_height": child["height"],
                    "geometry_version": "zoom_padding_before_sort_round_v1"}
    outcome = _outcome(action["capability"], result, candidates, association)
    repeat_metadata = None
    if action.get("action_template") == "repeated_grounding":
        prior_action = next((item for item in reversed(branch.actions)
                             if item.get("capability") == action["capability"]
                             and item.get("backend") == action["backend"]
                             and item.get("arguments") == action["arguments"]), None)
        prior_observation = next((item for item in reversed(branch.observations)
                                  if prior_action and item.get("joint_observation_id") == prior_action.get("observation_id")), None)
        prior_boxes = (prior_observation or {}).get("canonical_result", {}).get("boxes")
        current_boxes = (result.data or {}).get("boxes") if result.ok else None
        repeat_metadata = {
            "previous_observation_id": (prior_observation or {}).get("joint_observation_id"),
            "repeat_index": action.get("repeat_index"),
            "same_source_image_sha256": source.get("sha256") == branch.source_image_sha256,
            "same_backend": bool(prior_action and prior_action.get("backend") == action["backend"]),
            "geometry_differs": None if prior_boxes is None or current_boxes is None else prior_boxes != current_boxes,
            "dependence_note": "Repeated output is not statistically independent evidence",
        }
    observation = {
        "joint_observation_id": observation_id, "controlled_call_id": call_id,
        "action_id": action["action_id"], "parent_snapshot_id": branch.parent_snapshot_id,
        "branch_id": branch.branch_id, "capability": action["capability"], "backend": action["backend"],
        "dispatched": probe.dispatched, "success": result.ok, "logical_tool_cost": logical_cost,
        "logical_cost_accounting_id": identity([branch.branch_id, call_id], "logical_cost"),
        "latency_ms": elapsed if probe.dispatched else None, "physical_backend_attempts": None,
        "physical_attempts_reason": "Transport retries are not instrumented",
        "requested_image_id": requested_image, "resolved_image_id": resolved_image,
        "source_image": source, "root_image": root_image, "source_frame": frame,
        "canonical_result": _scrub(result.data),
        "raw_tool_result": _scrub(result.payload), "artifact_refs": [vars(ref) for ref in result.artifact_refs],
        "crop": crop, "candidate_ids": [candidate["candidate_id"] for candidate in candidates],
        "candidate_outcomes": candidate_outcomes, "repeat_metadata": repeat_metadata,
        "outcome": outcome, "error": copy.deepcopy(result.error),
    }
    recorded_action = {**copy.deepcopy(action), "controlled_call_id": call_id,
                       "observation_id": observation_id, "dispatched": probe.dispatched,
                       "actual_logical_cost": logical_cost, "latency_ms": observation["latency_ms"]}
    branch.actions.append(recorded_action)
    branch.observations.append(observation)
    preceding = [candidate["candidate_id"] for candidate in branch.candidates]
    for candidate in candidates:
        branch.candidates.append(candidate)
        branch.provenance.setdefault("edges", []).append(
            {"source": observation_id, "target": candidate["candidate_id"], "relation": "produces_detection"})
        branch.provenance.setdefault("nodes", []).append(
            {"id": candidate["candidate_id"], "kind": "candidate", "joint_observation_id": observation_id})
    return {"executed": True, "dispatched": probe.dispatched, "logical_cost": logical_cost,
            "observation": observation, "candidates": candidates, "outcome": outcome,
            "recorded_action": recorded_action, "preceding_candidate_ids": preceding}
