"""Public JSON envelope schema; event payload fields are documented separately."""
SCHEMA_VERSION = "bite.observation.v1"
EVENT_TYPES = ["model_turn", "context_change", "tool_proposal", "tool_dispatch",
               "tool_observation", "finalization", "observer_error"]
OBSERVATION_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["schema_version", "run_id", "sample_id", "question_id", "budget",
                 "events", "artifacts", "provenance_nodes", "provenance_edges", "capture_complete"],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "run_id": {"type": "string"}, "sample_id": {"type": ["string", "null"]},
        "question_id": {"type": "string"}, "budget": {"type": "object"},
        "capture_complete": {"type": "boolean"},
        "events": {"type": "array", "items": {"type": "object", "required": ["event_id", "type"],
                   "properties": {"event_id": {"type": "string"}, "type": {"enum": EVENT_TYPES}}}},
        "artifacts": {"type": "array"}, "provenance_nodes": {"type": "array"},
        "provenance_edges": {"type": "array"},
    },
}

_EVENT_REQUIRED = {
    "model_turn": ["iteration", "model", "phase", "status", "tools_proposed", "final_response", "parsing_failed"],
    "context_change": ["iteration", "reason", "before_digest", "after_digest", "tools_enabled"],
    "tool_proposal": ["iteration", "provider_tool_call_id", "capability", "raw_arguments", "parsed_arguments",
                      "validation_status", "eligible_for_dispatch", "rejection_reasons", "logical_action_id"],
    "tool_dispatch": ["iteration", "logical_action_id", "provider_tool_call_id", "capability", "backend",
                      "image_inputs", "started_at", "logical_tool_cost", "physical_attempts"],
    "tool_observation": ["iteration", "logical_action_id", "observation_id", "provider_tool_call_id", "success",
                         "error_category", "canonical_result_ref", "raw_result_ref", "artifact_refs", "ended_at", "latency_ms"],
    "finalization": ["final_model_iteration", "logical_tool_calls", "original_agent_final_response_valid",
                     "final_output_sha256", "remaining_budget", "model_token_usage"],
    "observer_error": ["hook", "exception_type"],
}
OBSERVATION_SCHEMA["properties"]["events"]["items"]["allOf"] = [
    {"if": {"properties": {"type": {"const": kind}}}, "then": {"required": required}}
    for kind, required in _EVENT_REQUIRED.items()
]
OBSERVATION_SCHEMA["properties"]["budget"] = {
    "type": "object", "required": ["reference_limit", "remaining_budget", "model_iterations", "logical_tool_calls",
                                    "successful_tool_calls", "failed_tool_calls", "rejected_proposals", "enforced", "physical_backend_attempts"],
    "properties": {
        **{k: {"type": "integer", "minimum": 0} for k in
           ["model_iterations", "logical_tool_calls", "successful_tool_calls", "failed_tool_calls", "rejected_proposals"]},
        "enforced": {"const": False}, "physical_backend_attempts": {"type": ["integer", "null"]},
        "reference_limit": {"type": ["integer", "null"]}, "remaining_budget": {"type": ["integer", "null"]},
    },
}
