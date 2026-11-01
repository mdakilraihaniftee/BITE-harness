"""Schema and structural leakage barriers; semantic origin is enforced by construction."""
import json
import re
from jsonschema import validate
from .outcomes import GROUNDING_OUTCOMES, ZOOM_OUTCOMES

CANDIDATE_FIELDS = ["schema_version", "candidate_id", "sample_id", "class_name", "source_observation_id", "source_detection_ids",
                    "bbox_local_xyxy", "bbox_root_xyxy", "bbox_root_reported_xyxy", "frame_reason", "root_image_id", "resolved_image_id", "source_group_id", "source_image_sha256",
                    "source_backend", "raw_scores", "mask_ref", "candidate_origin", "association_status"]
ACTION_FIELDS = ["name", "capability", "backend", "logical_action_id", "provider_tool_call_id", "arguments", "executed", "prior_state_id",
                 "selection_probability", "selection_probability_reason", "logical_tool_cost", "latency_ms", "physical_attempts",
                 "physical_attempts_reason", "provenance_event_id", "sampling_design", "selection_seed", "resolved_image_id", "cost_accounting_id"]
CONTEXT_FIELDS = ["class_name", "relative_box_area", "retained_score", "preceding_proposals", "action_frame", "shared_backend",
                  "remaining_reference_budget_before_action", "frame_valid", "root_dimensions_width_height",
                  "known_overlapping_preceding_proposals", "uncomparable_preceding_proposals", "state_completeness", "source_image_sha256"]
CALIBRATION_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "additionalProperties": False,
    "required": ["schema_version", "partition", "record_id", "run_id", "question_id", "sample_id", "state_id", "branch_id", "source_group_id",
                 "joint_observation_id", "runtime_features", "action", "outcome", "offline_labels", "evidence", "matching_protocol"],
    "properties": {
        "schema_version": {"const": "bite.calibration.v1"},
        "partition": {"enum": ["development_debug", "calibration_fit", "calibration_validation", "internal_test", "final_evaluation"]},
        **{k: {"type": "string"} for k in ["record_id", "run_id", "question_id", "state_id", "branch_id", "source_group_id"]},
        "joint_observation_id": {"type": ["string", "null"]},
        "sample_id": {"type": ["string", "null"]},
        "runtime_features": {"type": "object", "additionalProperties": False,
            "required": ["candidate", "association", "preceding_candidate_ids", "prior_outcomes", "context"],
            "properties": {
                "candidate": {"type": ["object", "null"], "additionalProperties": False,
                              "properties": {**{k: {} for k in CANDIDATE_FIELDS}, "schema_version": {"const": "bite.candidate.v1"}}, "required": CANDIDATE_FIELDS},
                "association": {"type": ["object", "null"]}, "preceding_candidate_ids": {"type": "array", "items": {"type": "string"}},
                "prior_outcomes": {"type": "array"},
                "context": {"type": "object", "additionalProperties": False, "properties": {k: {} for k in CONTEXT_FIELDS}, "required": CONTEXT_FIELDS}}},
        "action": {"type": "object", "additionalProperties": False, "required": ACTION_FIELDS,
                   "properties": {**{k: {} for k in ACTION_FIELDS},
                                  "selection_probability": {"type": ["number", "null"], "exclusiveMinimum": 0, "maximum": 1},
                                  "executed": {"type": "boolean"}}},
        "outcome": {"type": "object", "additionalProperties": False,
                    "required": ["observed", "category", "reason", "failure_subtype"],
                    "properties": {"observed": {"type": "boolean"}, "category": {"enum": sorted(set(GROUNDING_OUTCOMES+ZOOM_OUTCOMES))+[None]},
                                   "reason": {"type": ["string", "null"]}, "failure_subtype": {"type": ["string", "null"]}}},
        "offline_labels": {"type": "object", "additionalProperties": False, "required": ["labels", "reason", "ground_truth_provenance"],
                           "properties": {"labels": {"type": "array", "items": {"type": "object", "required": ["iou_threshold", "geometric_valid", "official_tp", "novel_gt_instance", "matching_status"]}},
                                          "reason": {"type": ["string", "null"]}, "ground_truth_provenance": {"type": "object"}}},
        "evidence": {"type": "object"}, "matching_protocol": {"type": "object"},
    },
}

# Scientific values are typed explicitly; unknown is null, never a numeric zero.
_nullable_string = {"type": ["string", "null"]}
_nullable_number = {"type": ["number", "null"]}
_box = {"type": ["array", "null"], "minItems": 4, "maxItems": 4, "items": {"type": "number"}}
_candidate = CALIBRATION_SCHEMA["properties"]["runtime_features"]["properties"]["candidate"]["properties"]
for _field in ["candidate_id", "source_observation_id", "source_group_id", "candidate_origin", "association_status"]:
    _candidate[_field] = {"type": "string"}
for _field in ["sample_id", "class_name", "root_image_id", "resolved_image_id", "source_image_sha256", "source_backend", "frame_reason"]:
    _candidate[_field] = _nullable_string
for _field in ["bbox_local_xyxy", "bbox_root_xyxy", "bbox_root_reported_xyxy"]:
    _candidate[_field] = _box
_candidate["source_detection_ids"] = {"type": "array", "minItems": 1, "items": {"type": "string"}}
_candidate["raw_scores"] = {"type": "array", "items": {"type": "number"}}
_candidate["mask_ref"] = {"type": ["object", "null"]}
_context = CALIBRATION_SCHEMA["properties"]["runtime_features"]["properties"]["context"]["properties"]
for _field in ["class_name", "source_image_sha256"]:
    _context[_field] = _nullable_string
for _field in ["relative_box_area", "retained_score"]:
    _context[_field] = _nullable_number
for _field in ["preceding_proposals", "known_overlapping_preceding_proposals", "uncomparable_preceding_proposals"]:
    _context[_field] = {"type": "integer", "minimum": 0}
for _field in ["shared_backend", "frame_valid"]:
    _context[_field] = {"type": "boolean"}
_context["remaining_reference_budget_before_action"] = {"type": ["integer", "null"]}
_context["action_frame"] = {"enum": ["root", "crop", "unknown"]}
_context["root_dimensions_width_height"] = {"type": "array", "minItems": 2, "maxItems": 2, "items": _nullable_number}
_context["state_completeness"] = {"enum": [
    "observer_projection_not_full_model_or_memory_state",
    "tool_execution_complete_snapshot",
]}
_action = CALIBRATION_SCHEMA["properties"]["action"]["properties"]
for _field in ["capability", "logical_action_id", "provider_tool_call_id", "prior_state_id", "sampling_design", "cost_accounting_id"]:
    _action[_field] = {"type": "string"}
for _field in ["backend", "selection_probability_reason", "physical_attempts_reason", "provenance_event_id", "resolved_image_id"]:
    _action[_field] = _nullable_string
_action["name"] = {"enum": ["root_grounding", "repeated_grounding", "crop_generation", "focused_grounding", "alternative_backend_verification", None]}
_action["arguments"] = {"type": "object"}
_action["selection_seed"] = {"type": ["integer", "null"]}
for _field in ["logical_tool_cost", "physical_attempts"]:
    _action[_field] = {"type": ["integer", "null"], "minimum": 0}
_action["latency_ms"] = {"type": ["number", "null"], "minimum": 0}
_labels = CALIBRATION_SCHEMA["properties"]["offline_labels"]["properties"]["labels"]["items"]
_labels["properties"] = {"iou_threshold": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
                         "max_eligible_iou": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
                         "bbox_raw_root_xyxy": _box, "bbox_for_matching_xyxy": _box}
for _field in ["geometric_valid", "official_tp", "novel_gt_instance", "duplicate_gt_evidence", "class_compatible",
               "unmatched_eligible_gt", "validity_label_usable", "official_ignored", "official_unmatched"]:
    _labels["properties"][_field] = {"type": ["boolean", "null"]}
for _field in ["best_eligible_gt_id", "official_matched_gt_id"]:
    _labels["properties"][_field] = {"type": ["integer", "string", "null"]}

_FORBIDDEN = re.compile(r"(^gt($|_)|_gt($|_)|ground_truth|official_tp|offline_label|annotation|geometric_valid|novel_gt|best_eligible|api_key|authorization|password|access_token)", re.I)


def _check_runtime(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if _FORBIDDEN.search(key):
                raise ValueError(f"Offline-only field in runtime/action/outcome: {key}")
            _check_runtime(child)
    elif isinstance(value, list):
        for child in value:
            _check_runtime(child)


def validate_record(record):
    validate(record, CALIBRATION_SCHEMA)
    json.dumps(record, allow_nan=False)
    for key in ["runtime_features", "action", "outcome"]:
        _check_runtime(record[key])
    if record["outcome"]["observed"] and not record["action"]["executed"]:
        raise ValueError("Unexecuted action cannot have an observed outcome")
    if not record["outcome"]["observed"] and record["outcome"]["category"] is not None:
        raise ValueError("Missing/unexecuted outcome has no observed category")
    candidate = record["runtime_features"]["candidate"]
    if candidate and candidate["source_group_id"] != record["source_group_id"]:
        raise ValueError("Candidate and record independence unit disagree")
    return True


def validate_records(records):
    ids = set()
    partition_by_group = {}
    for record in records:
        validate_record(record)
        if record["record_id"] in ids:
            raise ValueError("Duplicate calibration record ID")
        ids.add(record["record_id"])
        keys = ["group:"+record["source_group_id"]]
        image_hash = record["runtime_features"]["context"]["source_image_sha256"]
        if image_hash:
            keys.append("image:"+image_hash)
        for key in keys:
            previous = partition_by_group.setdefault(key, record["partition"])
            if previous != record["partition"]:
                raise ValueError("Same source image/scene group crosses calibration partitions")
    return {"valid": True, "records": len(ids), "source_groups": sum(k.startswith("group:") for k in partition_by_group)}
