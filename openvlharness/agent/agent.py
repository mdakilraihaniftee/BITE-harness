"""One agent loop; capabilities own tool meaning and adapters own API syntax."""

import copy
import hashlib
import os
import re
import time
from uuid import uuid4

from ..bite import create_observer
from ..capabilities._base import BaseCapability, failure
from ..contracts import VirtualCall
from ..input import input_messages, normalize_input
from ..services.raw_trace import RawTraceExportError


def _accumulate(into, values):
    """Add numeric usage fields recursively into a mutable totals mapping."""
    for key, value in values.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            into[key] = into.get(key, 0) + value
        elif isinstance(value, dict):
            _accumulate(into.setdefault(key, {}), value)


class MainAgent:
    """Coordinate model requests and capability execution for independent questions.

    Each generate call creates fresh memory and trajectory state. Capability
    implementations own tool semantics; the adapter owns provider message formats,
    context handling and final-answer extraction.
    """

    fail_msg = "Error: Unable to get response from the server."
    # Returned when max_iterations ends a question without an answer. Digit-free so that numeric
    # answer parsers (counting, MRA) cannot read it as a prediction.
    limit_msg = "Error: Reached the iteration limit without a final answer."

    def __init__(
        self,
        model_adapter,
        capabilities,
        memory_factory,
        system_prompt,
        user_prefix,
        max_iterations=15,
        tool_choice="auto",
        paired_sampling_seed=False,
        budget_guard=None,
        event_sink=None,
    ):
        """Configure the agent and publish tool schemas to its model adapter.

        Args:
            model_adapter: Adapter for the orchestrator's registered model profile.
            capabilities: Mapping of public tool names to capability instances.
            memory_factory: Zero-argument callable creating fresh question memory.
            system_prompt: System instruction text.
            user_prefix: Format string containing the user_query placeholder.
            max_iterations: Maximum number of regular model/tool iterations.
            tool_choice: Provider tool-selection mode for regular requests.
            paired_sampling_seed: Derive request seeds from task_id when available.
        """
        self.adapter = model_adapter
        self.capabilities = dict(capabilities)
        self.memory_factory = memory_factory
        self.system_prompt = system_prompt
        self.user_prefix = user_prefix
        self.max_iterations = max_iterations
        self.tool_choice = tool_choice
        self.paired_sampling_seed = paired_sampling_seed
        # Multi-agent execution installs an actor-scoped guard. Legacy agents leave
        # this unset and retain byte-for-byte action semantics.
        self.budget_guard = budget_guard
        # Optional structured observer installed by the multi-agent Studio. It is
        # deliberately separate from model history and never changes model input.
        self.event_sink = event_sink
        self.model = model_adapter.model
        self.json_schema = [c.public_schema() for c in self.capabilities.values()]
        self.adapter.json_schema = self.json_schema

    def generate(self, message, *, dataset=None, task_id=None):
        """Answer one question and collect its trajectory, artifacts and usage.

        Args:
            message: Text, an image/text item, or a list of strings or typed items.
            dataset: Accepted for evaluator integration; not used by the agent.
            task_id: Optional sample identifier used for seeds and raw trace filenames.

        Returns:
            A mapping with prediction and extra_records. Records include trajectory
            and tool_detections, plus usage when reported. Inference failures retain
            partial records and set trajectory.error. Requested raw trace exports
            populate trajectory.raw_trace or an explicit trajectory.raw_trace_error.

        Raises:
            ValueError: Input items are malformed.
            OSError: Input image loading fails before inference begins.

        HTTP image inputs are downloaded during normalization. The caller's message
        is copied; tool results and conversation state belong to this question only.
        """
        del dataset
        original = copy.deepcopy(message)
        question, system = normalize_input(message, self.system_prompt)
        memory = self.memory_factory()
        # Each question has its own image registry; this ID scopes registry
        # names such as tool_generated_image_1 for Studio visual lineage.
        self._image_scope = f"q_{uuid4().hex[:12]}"
        self._image_sizes = {}
        history = [
            self.adapter.encode_message(m)
            for m in input_messages(question, system, self.user_prefix)
        ]
        initial = memory.start(question)
        if initial:
            history.append(self.adapter.encode_message(initial))
            self._emit(
                "MEMORY_READ",
                {
                    "memory_scope": "private",
                    "memory_kind": "working_context",
                    "read_kind": "initial_inventory",
                    "modules": list(getattr(memory, "modules", []) or []),
                    "image_scope": self._image_scope,
                },
                summary="Initial memory inventory entered the model context.",
            )
        turns, detections, usage = [], [], {}
        observer = create_observer(memory, task_id, self.model)
        if observer is not None:
            memory._bite_observer = observer
        final = self.fail_msg
        error = None
        capture = {} if self.adapter.raw_trace_enabled else None
        try:
            final = self._run(
                history,
                memory,
                turns,
                detections,
                usage,
                task_id,
                capture=capture,
                observer=observer,
            )
        except (RuntimeError, OSError) as exc:
            error = str(exc)
        trajectory = {
            "input_messages": original,
            "chat_history": turns,
            "messages": history,
            "final_answer": final,
        }
        if error:
            trajectory["error"] = error
        if capture is not None:
            try:
                if error:
                    raise RawTraceExportError(
                        "inference_failed",
                        f"Raw trace export failed because inference did not complete: {error}",
                    )
                trajectory["raw_trace"] = self.adapter.export_raw_trace(
                    capture, task_id
                )
            except RawTraceExportError as exc:
                trajectory["raw_trace_error"] = {"code": exc.code, "message": str(exc)}
                self.adapter.logger.error(
                    "Raw trace export failed for task %s: %s", task_id, exc
                )
        if final == self.limit_msg and not error:
            trajectory["error"] = (
                f"Reached max_iterations ({self.max_iterations}) without a final answer."
            )
        extra = {"trajectory": trajectory, "tool_detections": detections}
        if usage:
            extra["usage"] = {"total": usage}
        if observer is not None:
            extra["bite_observer"] = observer.finalize(
                final, usage, trajectory.get("error")
            )
        self._emit(
            "AGENT_ANSWER_RECORDED",
            {"answer": final, "error": trajectory.get("error")},
            summary=(
                "Agent returned an answer."
                if not trajectory.get("error")
                else "Agent stopped with an execution error."
            ),
            status="failed" if trajectory.get("error") else "completed",
        )
        return {"prediction": final, "extra_records": extra}

    def _run(
        self,
        history,
        memory,
        turns,
        detections,
        usage,
        task_id,
        *,
        capture=None,
        observer=None,
    ):
        """Run model/tool iterations, updating history, memory and reporting lists.

        Returns the extracted final answer or the failure message. The adapter may
        compact history or issue a text-only final request according to its profile.
        When supplied, capture holds the terminating response and its exact request.
        """
        adapter = self.adapter
        policy = adapter.profile
        tools, choice = self.json_schema, self.tool_choice
        seed_base = None
        if self.paired_sampling_seed and task_id is not None:
            base = (
                int(hashlib.md5(str(task_id).encode()).hexdigest()[:8], 16)
                % 1_000_000_000
            )
            try:
                salt = int(os.environ.get("HARNESS_SEARCH_SAMPLE_INDEX", "0") or "0")
            except ValueError:
                salt = 0
            seed_base = (base + salt * 1_000_003) % 2_000_000_000
        for index in range(self.max_iterations):
            if self.budget_guard is not None and not self.budget_guard.reserve(
                "model_requests"
            ):
                raise RuntimeError("Multi-agent model-request budget exhausted")
            if observer is not None:
                observer.model_start(index)
            if index == self.max_iterations - 1:
                history.append(
                    adapter.encode_message(
                        {
                            "role": "user",
                            "content": "Please provide your best final answer now if enough information is available.",
                        }
                    )
                )
            if policy.get("context_policy") == "qwen_tokenizer":
                before = (
                    observer.serializer.fingerprint(history)
                    if observer is not None
                    else None
                )
                tools, choice = adapter._ensure_context_fits(history, tools, choice)
                if observer is not None:
                    observer.context_change(
                        before, observer.serializer.fingerprint(history), tools
                    )
            seed = seed_base + index if seed_base is not None else None
            try:
                response = self._observed_request(
                    {
                        "iteration": index,
                        "phase": "tool_selection",
                        "tools_offered": len(tools or []),
                    },
                    adapter.request,
                    history,
                    tools,
                    choice,
                    seed=seed,
                    capture=capture,
                )
            except RuntimeError as exc:
                context_error = any(
                    text in str(exc).lower()
                    for text in ("context length", "maximum input length")
                )
                if policy.get("context_error_fallback") and context_error:
                    if observer is not None:
                        observer.context_change(
                            "context_error",
                            "vanilla_fallback",
                            False,
                            "provider_context_error_fallback",
                        )
                    response = self._observed_request(
                        {
                            "iteration": index,
                            "phase": "context_error_fallback",
                            "tools_offered": 0,
                        },
                        adapter.request,
                        adapter._build_vanilla_fallback_msgs(history),
                        None,
                        "none",
                        seed=seed,
                        capture=capture,
                    )
                else:
                    raise
            if isinstance(response, dict) and isinstance(response.get("usage"), dict):
                _accumulate(usage, response["usage"])
            text, calls, original = adapter.parse(response, index)
            if observer is not None:
                observer.model_response(calls, not calls and adapter.final_answer(text))
            turn = self._turn(index, text, calls)
            if calls:
                adapter.append_assistant_calls(history, text, calls, original)
                deferred = []
                for call in calls:
                    # Stable per-invocation identity for Studio correlation. The
                    # model-supplied call ID is not guaranteed unique across actors.
                    invocation_id = f"inv_{uuid4().hex}"
                    decision_event = self._emit(
                        "DECISION_SUMMARY_RECORDED",
                        {
                            "current_goal": "Continue the assigned visual investigation.",
                            "action_intent": f"Invoke {call['name']} with the recorded arguments.",
                            "rationale_recorded": False,
                            "public_note": "Action rationale was not explicitly recorded by the model.",
                            "tool_call_id": call["id"],
                            "invocation_id": invocation_id,
                        },
                        summary=f"Selected {call['name']}; no explicit public rationale was recorded.",
                        tool_name=call["name"],
                    )
                    request_event = self._emit(
                        "TOOL_CALL_REQUESTED",
                        {
                            "tool_call_id": call["id"],
                            "invocation_id": invocation_id,
                            "arguments": call.get("args", {}),
                            "parse_error": call.get("parse_error"),
                            **self._visual_request(call.get("args"), memory),
                        },
                        summary=f"Requested {call['name']}.",
                        status="planned",
                        parent_event_id=(decision_event or {}).get("event_id"),
                        tool_name=call["name"],
                    )
                    started_event = None
                    tool_latency = None
                    images_before = None
                    if observer is not None:
                        observer.proposal(call, self.capabilities.get(call["name"]))
                    virtual = VirtualCall(call["id"], call["name"], call["args"])
                    if call.get("parse_error"):
                        result = failure(
                            virtual,
                            call["parse_error"]["code"],
                            call["parse_error"]["message"],
                            details=call["parse_error"].get("details"),
                        )
                    elif call["name"] not in self.capabilities:
                        result = failure(
                            virtual, "tool_not_found", f"Tool not found: {call['name']}"
                        )
                    else:
                        if (
                            self.budget_guard is not None
                            and not self.budget_guard.reserve("tool_calls")
                        ):
                            result = failure(
                                virtual,
                                "budget_denied",
                                "The actor or global multi-agent tool-call budget is exhausted.",
                            )
                        else:
                            if observer is not None and not isinstance(
                                self.capabilities[call["name"]], BaseCapability
                            ):
                                observer.dispatch(
                                    virtual, self.capabilities[call["name"]], memory
                                )
                            capability = self.capabilities[call["name"]]
                            # Emitted only once the call is actually dispatched to
                            # its capability, after parsing and budget checks pass.
                            started_event = self._emit(
                                "TOOL_CALL_STARTED",
                                {
                                    "tool_call_id": call["id"],
                                    "invocation_id": invocation_id,
                                    "backend": getattr(capability, "backend", None),
                                },
                                summary=f"Started {call['name']}.",
                                status="running",
                                parent_event_id=(request_event or {}).get("event_id"),
                                tool_name=call["name"],
                            )
                            images_before = self._registry_ids(memory)
                            tool_started = time.monotonic()
                            result = (
                                observer.invoke(capability, virtual, memory)
                                if observer is not None
                                else capability.invoke(virtual, memory)
                            )
                            tool_latency = time.monotonic() - tool_started
                    if observer is not None:
                        observer.result(
                            virtual, result, memory, len(turn["tool_responses"])
                        )
                    result_event = self._emit(
                        "TOOL_CALL_COMPLETED" if result.ok else "TOOL_CALL_FAILED",
                        {
                            "tool_call_id": call["id"],
                            "invocation_id": invocation_id,
                            "latency_seconds": tool_latency,
                            "ok": result.ok,
                            "result": result.payload.get("result"),
                            "canonical_result": result.data,
                            "error": result.error,
                            "meta": result.payload.get("meta", {}),
                            **self._visual_result(
                                call, self.capabilities.get(call["name"]), result, memory, images_before
                            ),
                        },
                        summary=(
                            f"{call['name']} returned evidence."
                            if result.ok
                            else f"{call['name']} failed; no usable evidence was recorded."
                        ),
                        status="completed" if result.ok else "failed",
                        parent_event_id=(started_event or request_event or {}).get(
                            "event_id"
                        ),
                        tool_name=call["name"],
                    )
                    if result.ok:
                        self._emit(
                            "EVIDENCE_OBSERVED",
                            {
                                "tool_call_id": call["id"],
                                "invocation_id": invocation_id,
                                "evidence_refs": [
                                    ref.id for ref in result.artifact_refs
                                ],
                            },
                            summary=f"Evidence from {call['name']} entered the agent context.",
                            parent_event_id=(result_event or {}).get("event_id"),
                            tool_name=call["name"],
                        )
                    if result.detection:
                        detection = copy.deepcopy(result.detection)
                        detection["tool_call_idx"] = len(detections)
                        detection["boxes_xyxy_pixels"] = [
                            list(map(float, box[:4]))
                            for box in detection["boxes_xyxy_pixels"]
                        ]
                        detection["scores"] = [float(s) for s in detection["scores"]]
                        detections.append(detection)
                    turn["tool_responses"].append(result.payload)
                    immediate, later = adapter.result_messages(call, result)
                    start = len(history)
                    history.extend(immediate)
                    record = {
                        "tool_call_id": call["id"],
                        "tool_name": call["name"],
                        "immediate_message_indices": list(range(start, len(history))),
                        "deferred_message_indices": [],
                        "image_refs": result.prepared.get("image_refs", []),
                        "tool_output_processor": result.processor_info,
                        "canonical_result": result.data,
                    }
                    turn["memory_outputs"].append(record)
                    self._emit(
                        "MEMORY_WRITTEN",
                        {
                            "tool_call_id": call["id"],
                            "invocation_id": invocation_id,
                            "tool_name": call["name"],
                            "image_refs": record["image_refs"],
                            "memory_scope": "private",
                    "memory_kind": "working_context",
                        },
                        summary=f"Stored {call['name']} references in private agent memory.",
                        parent_event_id=(result_event or {}).get("event_id"),
                        tool_name=call["name"],
                    )
                    deferred.append((record, later))
                for record, messages in deferred:
                    start = len(history)
                    history.extend(messages)
                    record["deferred_message_indices"] = list(
                        range(start, len(history))
                    )
                update = memory.build_environment_update(
                    successful=any(p.get("ok") is True for p in turn["tool_responses"])
                )
                if update:
                    turn["memory_turn_message_indices"] = [len(history)]
                    history.append(adapter.encode_message(update))
                    self._emit(
                        "MEMORY_READ",
                        {
                            "memory_scope": "private",
                    "memory_kind": "working_context",
                            "read_kind": "environment_update",
                            "modules": list(getattr(memory, "modules", []) or []),
                        },
                        summary="Private memory inventory entered the model context.",
                    )
                turns.append(turn)
                if index == self.max_iterations - 1 and policy.get(
                    "extra_final_request"
                ):
                    if self.budget_guard is not None and not self.budget_guard.reserve(
                        "model_requests"
                    ):
                        raise RuntimeError("Multi-agent model-request budget exhausted")
                    if observer is not None:
                        observer.model_start(index + 1, "final_text_only")
                    before = (
                        observer.serializer.fingerprint(history)
                        if observer is not None
                        else None
                    )
                    final_tools, final_choice = adapter._ensure_context_fits(
                        history, tools, "none"
                    )
                    if observer is not None:
                        observer.context_change(
                            before,
                            observer.serializer.fingerprint(history),
                            final_tools,
                        )
                    response = self._observed_request(
                        {
                            "iteration": index + 1,
                            "phase": "final_text_only",
                            "tools_offered": len(final_tools or []),
                        },
                        adapter.request,
                        history,
                        final_tools,
                        final_choice,
                        seed=seed,
                        capture=capture,
                    )
                    text, calls, original = adapter.parse(
                        response, index + 1, phase="final_text_only"
                    )
                    if observer is not None:
                        observer.model_response(
                            calls, not calls and adapter.final_answer(text)
                        )
                        for call in calls:
                            observer.proposal(
                                call,
                                self.capabilities.get(call["name"]),
                                rejected_reason="final_text_only",
                            )
                    if isinstance(response.get("usage"), dict):
                        _accumulate(usage, response["usage"])
                    if calls:
                        adapter.append_assistant_calls(history, text, calls, original)
                    else:
                        history.append(
                            adapter.encode_message(
                                {"role": "assistant", "content": text}
                            )
                        )
                    final_turn = self._turn(index + 1, text, calls)
                    final_turn["final_answer"] = adapter.final_answer(text)
                    turns.append(final_turn)
                    return final_turn["final_answer"] or self.limit_msg
                continue
            answer = adapter.final_answer(text)
            turn["final_answer"] = answer
            turns.append(turn)
            if policy.get("append_final_message") and text:
                history.append(
                    adapter.encode_message({"role": "assistant", "content": text})
                )
            if answer or not policy.get("continue_empty_answer"):
                return answer or self.fail_msg
            history.append(
                adapter.encode_message({"role": "assistant", "content": text})
            )
        return self.limit_msg

    def _observed_request(self, meta, request, *args, **kwargs):
        """Run one model request, emitting public request/response boundaries.

        Only timing, phase and token counts are recorded; request and response
        text never enter the event log.
        """
        if self.event_sink is None:
            return request(*args, **kwargs)
        iteration, phase = meta["iteration"], meta["phase"]
        request_id = f"mreq_{uuid4().hex}"
        started = self._emit(
            "MODEL_REQUEST_STARTED",
            {
                "request_id": request_id,
                "iteration": iteration,
                "phase": phase,
                "tools_offered": meta["tools_offered"],
                "model_id": self.model,
            },
            summary=f"Sent inference request {iteration + 1} ({phase.replace('_', ' ')}).",
            status="running",
        )
        began = time.monotonic()
        try:
            response = request(*args, **kwargs)
        except Exception as exc:
            self._emit(
                "MODEL_REQUEST_FAILED",
                {
                    "request_id": request_id,
                    "latency_seconds": time.monotonic() - began,
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                },
                summary="Inference request failed.",
                status="failed",
                parent_event_id=(started or {}).get("event_id"),
            )
            raise
        usage = response.get("usage") if isinstance(response, dict) else None
        counts = {
            key: value
            for key, value in (usage or {}).items()
            if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
            and isinstance(value, int)
        }
        self._emit(
            "MODEL_RESPONSE_RECEIVED",
            {
                "request_id": request_id,
                "latency_seconds": time.monotonic() - began,
                "usage": counts,
            },
            summary="Model response received.",
            parent_event_id=(started or {}).get("event_id"),
        )
        return response

    def _emit(self, event_type, payload, **metadata):
        """Emit optional public observability without affecting agent execution."""
        if self.event_sink is None:
            return None
        try:
            return self.event_sink(event_type, payload, **metadata)
        except Exception as exc:  # noqa: BLE001 - observability must never stop inference
            self.adapter.logger.warning(
                "Studio event emission failed for %s: %s", event_type, exc
            )
            return None

    # ---- Studio visual lineage (observability only; never changes inference) ----
    def _registry_ids(self, memory):
        if self.event_sink is None:
            return None
        try:
            return set(memory.state.images.registry)
        except AttributeError:
            return None

    def _image_size(self, registry_id, entry):
        """Pixel size of a registered data-URL image (cached per question)."""
        key = (self._image_scope, registry_id)
        if key in self._image_sizes:
            return self._image_sizes[key]
        size = None
        data_url = entry.get("data_url") if isinstance(entry, dict) else None
        if isinstance(data_url, str) and data_url.startswith("data:image/") and "," in data_url:
            try:
                import base64
                from io import BytesIO

                from PIL import Image

                with Image.open(BytesIO(base64.b64decode(data_url.split(",", 1)[1]))) as image:
                    size = [int(image.size[0]), int(image.size[1])]
            except Exception:  # noqa: BLE001 - unknown size stays unknown
                size = None
        self._image_sizes[key] = size
        return size

    def _visual_request(self, args, memory):
        """Images a call names, resolved by registry alias only (no downloads)."""
        if self.event_sink is None or not isinstance(args, dict):
            return {}
        record = {"image_scope": getattr(self, "_image_scope", None)}
        try:
            from ..memory.images import _normalize_image_alias

            images = memory.state.images
            inputs = []
            for key, value in args.items():
                lowered = str(key).lower()
                if not (lowered.endswith("_id") and "image" in lowered and isinstance(value, str)):
                    continue
                ref = images.alias_to_ref.get(_normalize_image_alias(value))
                entry = images.registry.get(ref) if ref else None
                size = self._image_size(ref, entry) if entry else None
                inputs.append({"argument": key, "requested": value, "registry_id": ref,
                               "width": size[0] if size else None, "height": size[1] if size else None,
                               "resolved_by": "registry_alias_preview"})
            if inputs:
                record["visual_inputs"] = inputs
        except Exception:  # noqa: BLE001 - observability must never stop inference
            pass
        return record

    def _visual_result(self, call, capability, result, memory, images_before):
        """Input/output images of a finished call and capability-described geometry.

        Inputs come from the capability's own image-resolution record; outputs are
        the registry entries this call created. Output pixels are included as data
        URLs, which the Studio event log moves into its content-addressed artifact
        store before persisting or streaming the event.
        """
        if self.event_sink is None:
            return {}
        record = {"image_scope": getattr(self, "_image_scope", None)}
        try:
            images = memory.state.images
            meta = (result.payload or {}).get("meta") or {}
            inputs = []
            for rewrite in (meta.get("image_resolution") or {}).get("rewrites") or []:
                ref = rewrite.get("image_ref")
                entry = images.registry.get(ref) if ref else None
                size = self._image_size(ref, entry) if entry else None
                inputs.append({"argument": str(rewrite.get("field", "")).replace("args.", ""),
                               "requested": rewrite.get("original"), "registry_id": ref,
                               "fallback_mode": rewrite.get("fallback_mode"),
                               "width": size[0] if size else None, "height": size[1] if size else None,
                               "resolved_by": "capability"})
            outputs = []
            if images_before is not None:
                for ref in [key for key in images.registry if key not in images_before]:
                    entry = images.registry[ref]
                    size = self._image_size(ref, entry)
                    data_url = entry.get("data_url")
                    outputs.append({"registry_id": ref, "source": entry.get("source"),
                                    "width": size[0] if size else None, "height": size[1] if size else None,
                                    "image": data_url if isinstance(data_url, str) and data_url.startswith("data:image/") else None})
            visual = {"inputs": inputs, "outputs": outputs}
            describe = getattr(capability, "visual_transform", None)
            if callable(describe) and result.ok:
                try:
                    transform = describe(call.get("args") or {}, inputs, outputs, result)
                except Exception as exc:  # noqa: BLE001 - geometry is optional
                    transform = {"error": f"{type(exc).__name__}: {exc}"}
                if transform:
                    visual["transform"] = transform
            if inputs or outputs or visual.get("transform"):
                record["visual"] = visual
        except Exception:  # noqa: BLE001 - observability must never stop inference
            pass
        return record

    @staticmethod
    def _turn(index, text, calls):
        """Create a reporting record with tagged reasoning and normalized tool calls."""

        def tag(name):
            match = re.search(
                rf"<{name}>(.*?)</{name}>", text, re.DOTALL | re.IGNORECASE
            )
            return match.group(1).strip() if match else ""

        return {
            "turn": index + 1,
            "assistant": {
                "content": text,
                "perception": tag("perception"),
                "thinking": tag("thinking"),
                "tool_calls": [
                    {
                        key: call.get(key)
                        for key in (
                            "id",
                            "name",
                            "raw_arguments",
                            "args",
                            "parse_error",
                        )
                    }
                    for call in calls
                ],
            },
            "tool_responses": [],
            "memory_outputs": [],
            "memory_turn_message_indices": [],
        }
