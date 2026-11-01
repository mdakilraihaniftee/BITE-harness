"""Read retained observer evidence, construct runtime records, then label offline."""
import copy
import json
from pathlib import Path
import re
import math

from jsonschema import validate
from openvlharness.bite.schemas import OBSERVATION_SCHEMA
from .candidate_association import associate, association_groups
from .common import file_hash, identity, valid_box
from .matching import label_candidates
from .outcomes import outcome
from .split_integrity import validate_partition_manifest


def _reference(record, path):
    if path is None:
        return None
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*|\[\d+\])*", path):
        raise ValueError("Invalid observer reference path")
    value = record
    for key, index in re.findall(r"([A-Za-z_][A-Za-z_0-9]*)|\[(\d+)\]", path):
        value = value[key] if key else value[int(index)]
    return value


def load_trace(sidecar_path, canonical_path=None):
    sidecar_path = Path(sidecar_path)
    observer = json.loads(sidecar_path.read_text())
    validate(observer, OBSERVATION_SCHEMA)
    if canonical_path is None:
        matches = list((sidecar_path.parent.parent/"results").glob(f"*/{observer['sample_id']}/record.json"))
        if len(matches) != 1:
            raise FileNotFoundError("Expected one retained canonical record; pass --canonical explicitly otherwise")
        canonical_path = matches[0]
    canonical_path = Path(canonical_path)
    canonical = json.loads(canonical_path.read_text())
    embedded = canonical.get("extra_records", {}).get("bite_observer")
    without_origin = {k: v for k, v in observer.items() if k != "origin"}
    if embedded is not None and embedded != without_origin:
        raise ValueError("Sidecar differs from the canonical observer")
    for event in observer["events"]:
        if event["type"] != "tool_observation" or not event.get("success") or not event.get("grounding"):
            continue
        actual = _reference(canonical, event["canonical_result_ref"])
        if not isinstance(actual, dict):
            raise ValueError("Successful grounding lacks retained canonical evidence")
        detections = event["grounding"]["detections"]
        if len(detections) != len(actual.get("boxes") or []):
            raise ValueError("Observer/canonical detection count disagreement")
        for rank, detection in enumerate(detections):
            if detection["bbox_local_xyxy"] != actual["boxes"][rank]:
                raise ValueError("Observer/canonical box disagreement")
            scores = actual.get("scores")
            if isinstance(scores, list) and detection["score"] != scores[rank]:
                raise ValueError("Observer/canonical score disagreement")
            if detection.get("mask"):
                from openvlharness.bite.serialization import digest
                if detection["mask"]["sha256"] != digest(actual["masks"][rank]):
                    raise ValueError("Observer/canonical mask disagreement")
    return observer, canonical, {"observer_path": str(sidecar_path.resolve()), "observer_sha256": file_hash(sidecar_path),
                                  "canonical_path": str(canonical_path.resolve()), "canonical_sha256": file_hash(canonical_path),
                                  "observer_capture_complete": observer["capture_complete"]}


def _source(observer, event):
    images = [a for a in observer["artifacts"] if a.get("kind") == "image"]
    originals = [n["image_id"] for n in observer["provenance_nodes"] if n["kind"] == "original_image"]
    inputs = event.get("image_inputs", [])
    source = inputs[0] if len(inputs) == 1 else {}
    frame = source.get("frame") or {}
    matrix = frame.get("child_to_root_transform")
    valid_matrix = (not source.get("frame_reason") and isinstance(matrix, list) and len(matrix) == 3 and all(isinstance(r, list) and len(r) == 3 for r in matrix)
                    and all(isinstance(x, (int, float)) and math.isfinite(x) for r in matrix for x in r)
                    and [matrix[0][:2], matrix[1][:2], matrix[2]] == [[1, 0], [0, 1], [0, 0, 1]])
    root_id = frame.get("root_image_id") if valid_matrix else None
    # This fallback establishes a grouping unit, never missing root geometry.
    primary_id = root_id or (originals[0] if len(originals) == 1 else None)
    root = next((a for a in images if a.get("image_id") == primary_id), {})
    source_hash = root.get("sha256")
    group = "sha256:"+source_hash if source_hash else identity([observer["run_id"], observer["question_id"]], "unresolved_source_group")
    return source, root_id, root, group


def runtime_records(observer, *, same_threshold=.8, distinct_threshold=.1, source_groups=None):
    """GT-free transformation. Input contains no labels/metrics from an evaluator."""
    proposals, rows, previous_actions, previous_outcomes, crops = [], [], [], [], set()
    dispatches = {e["logical_action_id"]: e for e in observer["events"] if e["type"] == "tool_dispatch"}
    pending = {e["logical_action_id"]: e for e in observer["events"] if e["type"] == "tool_proposal" and e.get("logical_action_id")}
    observed_actions = {e["logical_action_id"] for e in observer["events"] if e["type"] == "tool_observation"}
    work_events = []
    for event in observer["events"]:
        if event["type"] == "tool_observation":
            work_events.append(event)
        elif event["type"] == "tool_dispatch" and event["logical_action_id"] not in observed_actions:
            work_events.append({**event, "observation_id": None, "success": None, "missing_observation": True})
    calls_so_far = 0
    for event in work_events:
        row_start = len(rows)
        dispatch = dispatches.get(event["logical_action_id"])
        proposal = pending.get(event["logical_action_id"])
        if dispatch is None or proposal is None:
            raise ValueError("Observation missing dispatch/proposal identity")
        args = copy.deepcopy(proposal["parsed_arguments"])
        source, root_id, root, group = _source(observer, event)
        group = (source_groups or {}).get(root.get("sha256"), group)
        state_id = identity({"run_id": observer["run_id"], "question_id": observer["question_id"], "source_group_id": group,
                             "proposals": proposals, "actions": previous_actions, "outcomes": previous_outcomes}, "state")
        action_name = None
        if event["capability"] == "Zoom_In_Tool":
            action_name = "crop_generation"
        elif event["capability"] == "Visual_Grounding_Tool":
            if source.get("resolved_image_id") in crops:
                action_name = "focused_grounding"
            elif root_id and source.get("resolved_image_id") == root_id:
                action_name = "repeated_grounding" if any(
                    a["capability"] == event["capability"] and a["backend"] == event["backend"]
                    and a["resolved_image_id"] == source.get("resolved_image_id")
                    and str(a["arguments"].get("query", "")).strip().casefold() == str(args.get("query", "")).strip().casefold()
                    for a in previous_actions) else "root_grounding"
        action = {"name": action_name, "capability": event["capability"], "backend": event["backend"],
                  "logical_action_id": event["logical_action_id"], "provider_tool_call_id": event["provider_tool_call_id"],
                  "cost_accounting_id": identity([observer["run_id"], observer["question_id"], "observed_trajectory", event["logical_action_id"]], "logical_action"),
                  "arguments": args, "executed": True, "prior_state_id": state_id,
                  "resolved_image_id": source.get("resolved_image_id"),
                  "selection_probability": None, "selection_probability_reason": "Observational VLM trace; randomized action propensity not recorded",
                  "sampling_design": "observational_agent_trace", "selection_seed": None,
                  "logical_tool_cost": dispatch["logical_tool_cost"], "latency_ms": event.get("latency_ms"),
                  "physical_attempts": event.get("physical_attempts"), "physical_attempts_reason": "Not instrumented by observer v1",
                  "provenance_event_id": event["event_id"]}
        detections = event.get("grounding", {}).get("detections", []) if event.get("success") else []
        for detection in detections or [None]:
            candidate = None
            association = None
            if detection is not None:
                root_box = copy.deepcopy(detection["bbox_root_xyxy"]) if root_id else None
                frame_reason = None if root_id else source.get("frame_reason") or "unknown_or_invalid_root_transform"
                local_box = detection["bbox_local_xyxy"]
                if root_box is not None and isinstance(local_box, list) and len(local_box) == 4:
                    matrix = source["frame"]["child_to_root_transform"]
                    expected = [local_box[0]+matrix[0][2], local_box[1]+matrix[1][2],
                                local_box[2]+matrix[0][2], local_box[3]+matrix[1][2]]
                    if root_box != expected:
                        root_box, frame_reason = None, "inconsistent_reported_root_coordinates"
                candidate = {"schema_version": "bite.candidate.v1",
                    "candidate_id": identity([observer["run_id"], observer["question_id"], detection["detection_id"]], "candidate"),
                    "sample_id": observer["sample_id"], "class_name": detection.get("label") or event["grounding"].get("query"),
                    "source_observation_id": event["observation_id"], "source_detection_ids": [detection["detection_id"]],
                    "bbox_local_xyxy": copy.deepcopy(detection["bbox_local_xyxy"]),
                    "bbox_root_xyxy": root_box, "bbox_root_reported_xyxy": copy.deepcopy(detection["bbox_root_xyxy"]),
                    "frame_reason": frame_reason,
                    "root_image_id": root_id, "resolved_image_id": source.get("resolved_image_id"),
                    "source_group_id": group, "source_image_sha256": root.get("sha256"),
                    "source_backend": event["backend"], "raw_scores": [] if detection.get("score") is None else [detection["score"]],
                    "mask_ref": copy.deepcopy(detection.get("mask")), "candidate_origin": "grounding",
                    "association_status": "unresolved"}
                association = associate(candidate, proposals, same_threshold, distinct_threshold)
                candidate["association_status"] = association["status"]
            category = outcome(event, association)
            if event.get("missing_observation"):
                category = {"observed": False, "category": None, "reason": "dispatch_without_retained_result", "failure_subtype": None}
            box = candidate["bbox_root_xyxy"] if candidate else None
            width, height = root.get("width"), root.get("height")
            feature_context = {"class_name": candidate["class_name"] if candidate else None,
                    "relative_box_area": (box[2]-box[0])*(box[3]-box[1])/(width*height) if valid_box(box) and width and height else None,
                    "retained_score": candidate["raw_scores"][0] if candidate and candidate["raw_scores"] else None,
                    "preceding_proposals": len(proposals), "action_frame": "crop" if action_name == "focused_grounding" else "root" if root_id else "unknown",
                    "shared_backend": any(a["backend"] == action["backend"] for a in previous_actions),
                    "known_overlapping_preceding_proposals": sum((c.get("iou") or 0) > 0 for c in (association or {}).get("comparisons", [])),
                    "uncomparable_preceding_proposals": sum(c.get("iou") is None for c in (association or {}).get("comparisons", [])),
                    "state_completeness": "observer_projection_not_full_model_or_memory_state",
                    "remaining_reference_budget_before_action": None if observer["budget"]["reference_limit"] is None else observer["budget"]["reference_limit"]-calls_so_far,
                    "frame_valid": root_id is not None and source.get("frame") is not None,
                    "root_dimensions_width_height": [width, height]}
            feature_context["source_image_sha256"] = root.get("sha256")
            rows.append({"schema_version": "bite.calibration.v1", "partition": "development_debug",
                "record_id": identity([observer["run_id"], observer["question_id"], event["logical_action_id"], event["observation_id"], candidate["candidate_id"] if candidate else None], "calibration"),
                "run_id": observer["run_id"], "question_id": observer["question_id"], "sample_id": observer["sample_id"],
                "state_id": state_id, "branch_id": identity([observer["run_id"], observer["question_id"], "observed_trajectory"], "branch"),
                "source_group_id": group, "joint_observation_id": event["observation_id"],
                "runtime_features": {"candidate": copy.deepcopy(candidate), "association": association,
                    "preceding_candidate_ids": [p["candidate_id"] for p in proposals], "prior_outcomes": copy.deepcopy(previous_outcomes),
                    "context": feature_context}, "action": copy.deepcopy(action), "outcome": category,
                "offline_labels": {"labels": [], "reason": "not_labeled"}})
            if candidate is not None:
                proposals.append(candidate)
        if event.get("crop", {}).get("child_image_id"):
            crops.add(event["crop"]["child_image_id"])
        previous_actions.append(action)
        previous_outcomes.extend(r["outcome"]["category"] for r in rows[row_start:])
        calls_so_far += 1
    return rows, proposals, association_groups(proposals, same_threshold, distinct_threshold)


def build_records(observer, gt, *, evidence=None, thresholds=(.5, .75), assignment_scope="per_observation", score_mode="retained",
                  partition="development_debug", partition_manifest=None, same_threshold=.8, distinct_threshold=.1):
    source_groups = {}
    if partition_manifest is not None:
        validate_partition_manifest(partition_manifest)
        source_groups = {e["image_sha256"]: e["source_group_id"] for e in partition_manifest["entries"]}
    rows, candidates, groups = runtime_records(observer, same_threshold=same_threshold, distinct_threshold=distinct_threshold, source_groups=source_groups)
    if partition != "development_debug":
        if partition_manifest is None:
            raise ValueError("Non-debug calibration needs a frozen verified partition manifest")
        dispatched = {e["logical_action_id"] for e in observer["events"] if e["type"] == "tool_dispatch"}
        observed = {e["logical_action_id"] for e in observer["events"] if e["type"] == "tool_observation"}
        if not observer["capture_complete"] or dispatched != observed:
            raise ValueError("Non-debug calibration requires complete retained action outcomes")
        for row in rows:
            if not any(e["source_group_id"] == row["source_group_id"] and e["partition"] == partition
                       and e["image_sha256"] == row["runtime_features"]["context"]["source_image_sha256"] for e in partition_manifest["entries"]):
                raise ValueError("Source group absent from requested partition")
    original_ids = {n["image_id"] for n in observer["provenance_nodes"] if n["kind"] == "original_image"}
    known_hashes = {a["sha256"] for a in observer["artifacts"] if a.get("image_id") in original_ids and a.get("sha256")}
    if gt.provenance.get("source_image_sha256") and known_hashes != {gt.provenance["source_image_sha256"]}:
        raise ValueError("Observer pixels and annotation sample image identity disagree")
    for row in rows:
        dims = row["runtime_features"]["context"]["root_dimensions_width_height"]
        if all(dims) and dims != [gt.image["width"], gt.image["height"]]:
            raise ValueError("Observer root dimensions and annotation dimensions disagree")
    labels, summary = label_candidates(candidates, gt, thresholds, assignment_scope=assignment_scope, score_mode=score_mode)
    for row in rows:
        row["partition"] = partition
        candidate = row["runtime_features"]["candidate"]
        row["offline_labels"] = {"labels": labels[candidate["candidate_id"]] if candidate else [],
                                 "reason": None if candidate else "No detection candidate for this action outcome",
                                 "ground_truth_provenance": gt.provenance}
        row["evidence"] = copy.deepcopy(evidence or {})
        row["matching_protocol"] = {"thresholds": list(thresholds), "assignment_scope": assignment_scope, "score_mode": score_mode,
                                    "association_same_threshold": same_threshold, "association_distinct_threshold": distinct_threshold,
                                    "max_detections_per_image_class": 100}
    summary.update(candidate_count=len(candidates), record_count=len(rows), association_groups=groups,
                   development_debug_only=partition == "development_debug", probability_model_fitted=False,
                   observer_capture_complete=observer["capture_complete"],
                   missing_observation_action_ids=[r["action"]["logical_action_id"] for r in rows if r["outcome"]["reason"] == "dispatch_without_retained_result"])
    return rows, summary


def build_collection_records(branches, gt, *, thresholds=(.5, .75), score_mode="retained",
                             partition="development_debug"):
    """Apply the existing matcher to persisted controlled branches, offline only.

    Each branch is matched independently so counterfactual alternatives never
    become one another's prior evidence. Empty and failed observations still
    produce candidate-null calibration rows and are never converted to negatives.
    """
    rows = []
    summaries = {}
    for branch in branches:
        if branch.get("offline_gt_used") is not False:
            raise ValueError("Collection branch must attest that runtime GT was unused")
        branch_candidates = [copy.deepcopy(item["candidate"]) for item in branch["candidate_rows"]]
        hashes = {item.get("source_image_sha256") for item in branch_candidates if item.get("source_image_sha256")}
        expected_hash = gt.provenance.get("source_image_sha256")
        if hashes and expected_hash and hashes != {expected_hash}:
            raise ValueError("Collection pixels and offline annotation image disagree")
        labels, summary = label_candidates(
            branch_candidates, gt, thresholds, assignment_scope="per_observation", score_mode=score_mode,
        )
        summaries[branch["branch_id"]] = summary
        by_observation = {}
        for item in branch["candidate_rows"]:
            by_observation.setdefault(item["joint_observation_id"], []).append(item)
        prior_candidates, prior_outcomes = [], []
        for observation in branch["observations"]:
            candidate_items = by_observation.get(observation["joint_observation_id"]) or [None]
            raw_action = next((action for action in branch["selected_path"]
                               if action.get("observation_id") == observation["joint_observation_id"]), None)
            if raw_action is None:
                raise ValueError("Collection observation lacks its selected controlled action")
            for source in candidate_items:
                candidate = copy.deepcopy(source["candidate"]) if source else None
                association = associate(candidate, prior_candidates) if candidate else None
                root = observation.get("root_image", {})
                width, height = root.get("width"), root.get("height")
                box = candidate.get("bbox_root_xyxy") if candidate else None
                relative_area = ((box[2]-box[0])*(box[3]-box[1])/(width*height)
                                 if valid_box(box) and width and height else None)
                outcome_value = copy.deepcopy(source["outcome"] if source else observation["outcome"])
                action = {
                    "name": raw_action["action_template"], "capability": raw_action["capability"],
                    "backend": raw_action["backend"], "logical_action_id": raw_action["action_id"],
                    "provider_tool_call_id": raw_action["controlled_call_id"],
                    "arguments": copy.deepcopy(raw_action["arguments"]),
                    "executed": bool(raw_action["dispatched"]),
                    "prior_state_id": branch["parent_snapshot_id"],
                    "selection_probability": branch["selection_probability"],
                    "selection_probability_reason": "Controlled path inclusion probability under the recorded design",
                    "logical_tool_cost": raw_action["actual_logical_cost"],
                    "latency_ms": raw_action.get("latency_ms"), "physical_attempts": None,
                    "physical_attempts_reason": "Transport retries are not instrumented",
                    "provenance_event_id": observation["joint_observation_id"],
                    "sampling_design": branch["selection_design"],
                    "selection_seed": branch.get("selection_seed"),
                    "resolved_image_id": observation.get("resolved_image_id"),
                    "cost_accounting_id": observation["logical_cost_accounting_id"],
                }
                context = {
                    "class_name": candidate.get("class_name") if candidate else None,
                    "relative_box_area": relative_area,
                    "retained_score": (candidate["raw_scores"][0]
                                       if candidate and candidate.get("raw_scores") else None),
                    "preceding_proposals": len(prior_candidates),
                    "action_frame": "crop" if raw_action["action_template"] == "focused_grounding" else "root",
                    "shared_backend": any(item.get("source_backend") == raw_action["backend"]
                                          for item in prior_candidates),
                    "remaining_reference_budget_before_action": None,
                    "frame_valid": candidate is not None and candidate.get("bbox_root_xyxy") is not None,
                    "root_dimensions_width_height": [width, height],
                    "known_overlapping_preceding_proposals": sum(
                        (item.get("iou") or 0) > 0 for item in (association or {}).get("comparisons", [])),
                    "uncomparable_preceding_proposals": sum(
                        item.get("iou") is None for item in (association or {}).get("comparisons", [])),
                    "state_completeness": "tool_execution_complete_snapshot",
                    "source_image_sha256": branch_candidates[0].get("source_image_sha256")
                    if branch_candidates else expected_hash,
                }
                record_id = identity([
                    branch["branch_id"], observation["joint_observation_id"],
                    candidate.get("candidate_id") if candidate else None,
                ], "calibration")
                rows.append({
                    "schema_version": "bite.calibration.v1", "partition": partition,
                    "record_id": record_id, "run_id": branch["collection_run_id"],
                    "question_id": branch["parent_snapshot_id"],
                    "sample_id": candidate.get("sample_id") if candidate else gt.provenance.get("sample_id"),
                    "state_id": branch["parent_snapshot_id"], "branch_id": branch["branch_id"],
                    "source_group_id": branch["source_group_id"],
                    "joint_observation_id": observation["joint_observation_id"],
                    "runtime_features": {"candidate": candidate, "association": association,
                        "preceding_candidate_ids": [item["candidate_id"] for item in prior_candidates],
                        "prior_outcomes": copy.deepcopy(prior_outcomes), "context": context},
                    "action": action, "outcome": outcome_value,
                    "offline_labels": {
                        "labels": labels[candidate["candidate_id"]] if candidate else [],
                        "reason": None if candidate else "No detection candidate for this action outcome",
                        "ground_truth_provenance": copy.deepcopy(gt.provenance),
                    },
                    "evidence": {"collection_schema": branch["schema_version"],
                        "parent_snapshot_id": branch["parent_snapshot_id"],
                        "branch_id": branch["branch_id"],
                        "action_origin": "controlled_collection_action",
                        "path_draw_probability": branch["path_draw_probability"]},
                    "matching_protocol": {"thresholds": list(thresholds),
                        "assignment_scope": "per_observation", "score_mode": score_mode,
                        "counterfactual_branches_matched_independently": True,
                        "max_detections_per_image_class": 100},
                })
                if candidate:
                    prior_candidates.append(candidate)
                prior_outcomes.append(outcome_value["category"])
    return rows, {"candidate_count": sum(bool(row["runtime_features"]["candidate"]) for row in rows),
                  "record_count": len(rows), "branch_summaries": summaries,
                  "counterfactual_branch_matching": "independent", "probability_model_fitted": False}
