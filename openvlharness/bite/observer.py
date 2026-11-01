"""Passive question-local hooks. Capture failures never change agent execution."""
import copy
from functools import wraps
import os
import time
import uuid
from datetime import datetime, timezone

from .budget import Budget
from .geometry import compose, crop_rectangle, transform_box, translation
from .provenance import Provenance
from .schemas import SCHEMA_VERSION
from .serialization import Serializer, digest
from .state import BITEObserverState


def passive(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:
            # Exclude exception messages: they may contain credentials or media.
            error = {"hook": method.__name__, "exception_type": type(exc).__name__}
            self.state.errors.append(error)
            self.event("observer_error", **error)
            return None
    return guarded


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def create_observer(memory, sample_id, model):
    enabled = os.getenv("BITE_OBSERVER_ENABLED", "false").lower().strip()
    if enabled in ("false", "0", "no", "off", ""):
        return None
    if enabled not in ("true", "1", "yes", "on"):
        raise ValueError("BITE_OBSERVER_ENABLED must be a boolean")
    raw = os.getenv("BITE_OBSERVER_REFERENCE_BUDGET", "15")
    budget = None if raw.lower() == "none" else int(raw)
    if budget is not None and budget < 0:
        raise ValueError("BITE_OBSERVER_REFERENCE_BUDGET must be nonnegative or none")
    observer = EvidenceObserver(sample_id=sample_id, model=model, reference_budget=budget,
                                run_id=os.getenv("BITE_OBSERVER_RUN_ID"))
    observer.initialize(memory)
    return observer


class EvidenceObserver:
    def __init__(self, *, sample_id=None, model=None, reference_budget=15, run_id=None):
        self.state = BITEObserverState(run_id or uuid.uuid4().hex,
                                      None if sample_id is None else str(sample_id), uuid.uuid4().hex,
                                      Budget(reference_limit=reference_budget))
        self.model = model
        self.serializer = Serializer()
        self.graph = Provenance(self.state)
        self.pending = {}
        self.active = {}
        self.model_event = None
        self.iteration = 0

    def event(self, kind, **data):
        item = {"event_id": f"event_{len(self.state.events)+1:04d}", "type": kind, **data}
        self.state.events.append(item)
        return item

    @passive
    def initialize(self, memory):
        for image_id in memory.state.images.registry:
            self.graph.image(image_id, memory, original=True)
            self.graph.producers[image_id] = {None}

    @passive
    def model_start(self, index, phase="regular"):
        self.iteration = index + 1
        self.state.budget.model_iterations += 1
        self.model_event = self.event("model_turn", iteration=self.iteration, model=self.model,
                                      phase=phase, status="requesting", tools_proposed=None,
                                      final_response=None, parsing_failed=None)

    @passive
    def model_response(self, calls, final_response):
        self.model_event.update(status="responded", tools_proposed=bool(calls),
                                final_response=bool(final_response),
                                parsing_failed=any(bool(c.get("parse_error")) for c in calls))

    @passive
    def context_change(self, before, after, tools_enabled, reason="history_compacted_or_replaced"):
        if before != after:
            self.event("context_change", iteration=self.iteration, reason=reason,
                       before_digest=before, after_digest=after, tools_enabled=bool(tools_enabled))

    @passive
    def proposal(self, call, capability, *, rejected_reason=None):
        errors = []
        if call.get("parse_error"):
            errors.append(call["parse_error"].get("code", "parse_error"))
        if capability is None:
            errors.append("tool_not_found")
        elif getattr(capability, "validator", None) is not None:
            if list(capability.validator.iter_errors(call["args"])):
                errors.append("invalid_tool_arguments")
        if rejected_reason:
            errors.append(rejected_reason)
        item = self.event("tool_proposal", iteration=self.iteration,
                          provider_tool_call_id=call["id"], capability=call["name"],
                          raw_arguments=call.get("raw_arguments"), parsed_arguments=copy.deepcopy(call["args"]),
                          validation_status="rejected" if errors else "schema_valid_resolution_pending",
                          eligible_for_dispatch=False if errors else None, rejection_reasons=errors,
                          logical_action_id=None)
        self.pending[call["id"]] = item
        if errors:
            self.state.budget.rejected_proposals += 1

    @passive
    def dispatch(self, call, capability, memory, resolution=None, args=None):
        proposal = self.pending[call.call_id]
        if proposal.get("logical_action_id"):
            return
        action = f"action_{self.state.budget.logical_tool_calls+1:04d}"
        self.state.budget.logical_tool_calls += 1
        proposal.update(validation_status="dispatchable", eligible_for_dispatch=True, logical_action_id=action)
        inputs = []
        for rewrite in (resolution or {}).get("rewrites", []):
            image_id = rewrite.get("image_ref")
            if image_id:
                metadata = self.graph.image(image_id, memory)
                frame, reason = self.graph.frame(image_id)
                inputs.append({"requested_image_id": rewrite.get("original"), "resolved_image_id": image_id,
                               "resolution_mode": rewrite.get("fallback_mode", "matched"),
                               "width": metadata["width"], "height": metadata["height"],
                               "sha256": metadata["sha256"], "frame": copy.deepcopy(frame), "frame_reason": reason})
        backend = getattr(capability, "backend", None)
        self.graph.node(action, "tool_action", capability=call.name)
        backend_id = "backend:" + str(backend) if backend is not None else "backend:unknown:" + action
        self.graph.node(backend_id, "backend", backend=backend, checkpoint_revision=None,
                        checkpoint_reason="Worker contract does not publish a verified revision")
        self.graph.edge(action, backend_id, "uses_backend")
        for source in inputs:
            image_id = source["resolved_image_id"]
            self.graph.edge(action, "image:" + image_id, "uses_image")
            frame = source["frame"]
            if frame and frame["root_image_id"]:
                self.graph.edge(action, "image:" + frame["root_image_id"], "shares_root_image")
            producers = self.graph.producers.get(image_id, set())
            if len(producers) == 1 and None not in producers:
                self.graph.edge(action, next(iter(producers)), "derived_from_observation", basis="consumed_image_artifact")
        item = self.event("tool_dispatch", iteration=self.iteration, logical_action_id=action,
                          provider_tool_call_id=call.call_id, capability=call.name, backend=backend,
                          image_inputs=inputs, source_image_reason=None if inputs else "No resolved registry image metadata",
                          started_at=utc_now(), logical_tool_cost=1, selection_dependency="unknown",
                          physical_attempts=None, backend_node_id=backend_id)
        self.active[call.call_id] = {"event": item, "start": time.monotonic(),
                                     "args": copy.deepcopy(call.arguments)}
        for binding_id in (args or {}).get("binding_descriptors", {}):
            binding_node = "binding:" + binding_id
            self.graph.node(binding_node, "binding")
            self.graph.edge(action, binding_node, "supplied_binding")
            producers = self.graph.producers.get(binding_node, set())
            if len(producers) == 1:
                self.graph.edge(action, next(iter(producers)), "derived_from_observation",
                                basis="binding_supplied_to_capability_context_not_proof_of_code_read")

    @passive
    def transport_error(self, call, exception):
        if call.call_id in self.active:
            self.active[call.call_id]["exception_type"] = type(exception).__name__

    def invoke(self, capability, call, memory):
        """Preserve capability exceptions while closing the observer's dispatch."""
        try:
            return capability.invoke(call, memory)
        except Exception as exc:
            self.aborted(call, memory, exc)
            raise

    @passive
    def aborted(self, call, memory, exception):
        from ..capabilities._base import failure
        self.transport_error(call, exception)
        self.result(call, failure(call, "capability_exception", type(exception).__name__), memory)
        for event in reversed(self.state.events):
            if event["type"] == "tool_observation" and event["provider_tool_call_id"] == call.call_id:
                event.update(raw_result_ref=None, canonical_result_ref=None,
                             result_ref_reason="Capability raised before agent trajectory commit")
                break

    @passive
    def result(self, call, result, memory, call_index=0):
        pending = self.pending[call.call_id]
        active = self.active.pop(call.call_id, None)
        if active is None:
            if not pending["rejection_reasons"]:
                self.state.budget.rejected_proposals += 1
            code = (result.error or {}).get("code", "not_dispatched")
            pending.update(validation_status="rejected", eligible_for_dispatch=False,
                           rejection_reasons=list(dict.fromkeys(pending["rejection_reasons"] + [code])))
            return
        dispatch = active["event"]
        action = dispatch["logical_action_id"]
        observation = f"observation_{self.state.budget.successful_tool_calls+self.state.budget.failed_tool_calls+1:04d}"
        if result.ok:
            self.state.budget.successful_tool_calls += 1
        else:
            self.state.budget.failed_tool_calls += 1
        ref_base = f"extra_records.trajectory.chat_history[{self.iteration-1}]"
        error_type = active.get("exception_type")
        error_category = (("transport_timeout" if error_type and "Timeout" in error_type else
                           (result.error or {}).get("code", "backend_failure")) if not result.ok else None)
        item = self.event("tool_observation", iteration=self.iteration, logical_action_id=action,
                          observation_id=observation, provider_tool_call_id=call.call_id, capability=call.name,
                          backend=dispatch["backend"], success=result.ok, error_category=error_category,
                          error=copy.deepcopy(result.error), exception_type=error_type,
                          ended_at=utc_now(), latency_ms=(time.monotonic()-active["start"])*1000,
                          canonical_result_type=type(result.data).__name__,
                          canonical_result_ref=f"{ref_base}.memory_outputs[{call_index}].canonical_result",
                          raw_result_ref=f"{ref_base}.tool_responses[{call_index}]",
                          image_inputs=copy.deepcopy(dispatch["image_inputs"]),
                          artifact_refs=[{"kind": a.kind, "id": a.id} for a in result.artifact_refs],
                          physical_attempts=None)
        self.graph.node(observation, "tool_observation", logical_action_id=action)
        self.graph.edge(action, observation, "produces_observation")
        self.graph.edge(observation, dispatch["backend_node_id"], "uses_backend")
        source = dispatch["image_inputs"][0] if len(dispatch["image_inputs"]) == 1 else None
        if result.ok and call.name == "Visual_Grounding_Tool":
            self._grounding(item, result.data or {}, source, ref_base, call_index)
        for artifact in result.artifact_refs:
            if artifact.kind != "image":
                artifact_id = "binding:" + artifact.id
                self.graph.node(artifact_id, "binding")
                self.state.artifacts.setdefault(artifact_id, {"artifact_id": artifact_id, "kind": "binding", "id": artifact.id,
                                                             "canonical_result_ref": item["canonical_result_ref"]})
                self.graph.edge(action, artifact_id, "produces_artifact")
                self.graph.producers.setdefault(artifact_id, set()).add(observation)
                continue
            metadata = self.graph.image(artifact.id, memory)
            self.graph.edge(action, "image:" + artifact.id, "produces_image")
            self.graph.producers.setdefault(artifact.id, set()).add(observation)
            if source and artifact.id != source["resolved_image_id"]:
                self.graph.edge("image:" + artifact.id, "image:"+source["resolved_image_id"], "derived_from_image")
            if call.name == "Zoom_In_Tool" and source and result.ok:
                self._crop(item, call, artifact.id, metadata, source)
            elif call.name == "Visual_Grounding_Tool" and source and source["frame"] and (
                    metadata["width"], metadata["height"]) == (source["width"], source["height"]):
                self.graph.add_frame(artifact.id, copy.deepcopy(source["frame"]))
            else:
                self.graph.add_frame(artifact.id, {"root_image_id": None, "child_to_root_transform": None})

    def _grounding(self, item, canonical, source, ref_base, call_index):
        frame = source["frame"] if source else None
        transform = frame.get("child_to_root_transform") if frame else None
        scores = canonical.get("scores")
        labels = canonical.get("labels")
        masks = canonical.get("masks")
        boxes = canonical.get("boxes")
        detections = []
        for rank, box in enumerate(boxes if isinstance(boxes, list) else []):
            mask = masks[rank] if isinstance(masks, list) and rank < len(masks) else None
            detection_id = item["observation_id"] + f":detection_{rank:04d}"
            record = {"detection_id": detection_id, "detection_rank": rank,
                      "label": labels[rank] if isinstance(labels, list) and rank < len(labels) else None,
                      "bbox_local_xyxy": copy.deepcopy(box), "bbox_root_xyxy": transform_box(box, transform),
                      "root_frame_reason": None if transform is not None else (source or {}).get("frame_reason", "unknown_source_frame"),
                      "score": scores[rank] if isinstance(scores, list) and rank < len(scores) else None,
                      "score_reason": None if isinstance(scores, list) and rank < len(scores) else "missing_or_malformed_optional_scores",
                      "mask": {"sha256": digest(mask), "encoding": "COCO_RLE_counts",
                               "size_height_width": canonical.get("size"),
                               "canonical_ref": f"{ref_base}.memory_outputs[{call_index}].canonical_result.masks[{rank}]"}
                      if isinstance(mask, str) else None}
            detections.append(record)
            self.graph.node(detection_id, "detection", observation_id=item["observation_id"])
            self.graph.edge(item["observation_id"], detection_id, "produces_detection")
        item["grounding"] = {"query": canonical.get("query"), "model_id": canonical.get("model_id"),
                             "size_height_width": canonical.get("size"), "detections": detections,
                             "boxes_reason": None if isinstance(boxes, list) else "missing_or_malformed_boxes",
                             "masks_available": isinstance(masks, list) and bool(masks),
                             "masks_reason": None if isinstance(masks, list) else "missing_or_malformed_optional_masks",
                             "score_semantics": "retained_detector_score_not_posterior",
                             "empty_detection": isinstance(boxes, list) and len(boxes) == 0}
        backend_node = self.state.nodes.get("backend:" + str(item.get("backend")))
        if backend_node is not None:
            backend_node["reported_model_id"] = canonical.get("model_id")

    def _crop(self, item, call, child_id, child, source):
        rectangle = crop_rectangle(call.arguments["coords"], call.arguments.get("padding", 50),
                                   source["width"], source["height"])
        left, top, right, bottom = rectangle
        if (right-left, bottom-top) != (child["width"], child["height"]):
            raise ValueError("Crop pixels disagree with reconstructed integer geometry")
        parent = source["frame"]
        child_to_parent = translation(left, top)
        transform = compose(parent["child_to_root_transform"], child_to_parent) if parent and parent.get("child_to_root_transform") else None
        root = parent["root_image_id"] if parent else None
        item["crop"] = {"parent_image_id": source["resolved_image_id"], "child_image_id": child_id,
                        "parent_width": source["width"], "parent_height": source["height"],
                        "child_width": child["width"], "child_height": child["height"],
                        "crop_rectangle_parent_xyxy": list(rectangle),
                        "child_to_parent_transform": child_to_parent, "child_to_root_transform": transform,
                        "root_image_id": root, "geometry_version": "zoom_padding_before_sort_round_v1",
                        "root_frame_reason": source["frame_reason"], "selection_dependency": "unknown"}
        self.graph.add_frame(child_id, {"root_image_id": root, "child_to_root_transform": transform})

    @passive
    def finalize(self, prediction, usage, error=None):
        if self.model_event and self.model_event["status"] == "requesting":
            self.model_event["status"] = "request_failed"
        valid = bool(prediction) and not str(prediction).startswith("Error:") and not error
        self.event("finalization", final_model_iteration=self.iteration,
                   logical_tool_calls=self.state.budget.logical_tool_calls,
                   original_agent_final_response_valid=valid, validity_semantics="nonempty_nonfailure_sentinel_not_task_JSON_validation",
                   final_output_sha256=digest(str(prediction)), remaining_budget=self.state.budget.export()["remaining_budget"],
                   model_token_usage=copy.deepcopy(usage), agent_error_present=bool(error))
        return self.export()

    def export(self):
        return self.serializer.clean({"schema_version": SCHEMA_VERSION, "run_id": self.state.run_id,
            "sample_id": self.state.sample_id, "question_id": self.state.question_id,
            "budget": self.state.budget.export(), "events": self.state.events,
            "artifacts": list(self.state.artifacts.values()), "provenance_nodes": list(self.state.nodes.values()),
            "provenance_edges": self.state.provenance_edges, "capture_complete": not self.state.errors,
            "capture_errors": self.state.errors})
