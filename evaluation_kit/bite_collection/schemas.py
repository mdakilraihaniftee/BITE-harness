"""Versioned machine contracts for executable snapshots and branch records."""

from jsonschema import validate

SNAPSHOT_VERSION = "bite.collection_state.v1"
COLLECTION_VERSION = "bite.collection.v1"

SNAPSHOT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version", "snapshot_id", "state_digest", "snapshot_completeness",
        "task", "source_group_id", "source_image_sha256", "prefix_action_count",
        "prefix_logical_cost", "allowed_action_types", "memory", "execution_context",
        "previous_actions", "previous_observations", "candidate_history", "provenance",
        "native_history", "history_mode", "capture_complete", "limitations",
    ],
    "properties": {
        "schema_version": {"const": SNAPSHOT_VERSION},
        "snapshot_id": {"type": "string"},
        "state_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "snapshot_completeness": {"enum": ["tool_execution_complete", "incomplete"]},
        "task": {"type": "object"},
        "source_group_id": {"type": "string"},
        "source_image_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "prefix_action_count": {"type": "integer", "minimum": 0},
        "prefix_logical_cost": {"type": "integer", "minimum": 0},
        "allowed_action_types": {"type": "array", "items": {"type": "string"}},
        "memory": {"type": "object"},
        "execution_context": {"type": "object"},
        "previous_actions": {"type": "array"},
        "previous_observations": {"type": "array"},
        "candidate_history": {"type": "array"},
        "provenance": {"type": "object"},
        "native_history": {"type": ["array", "null"]},
        "history_mode": {"enum": ["preserved_not_extended", "unavailable"]},
        "capture_complete": {"type": "boolean"},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
}

COLLECTION_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version", "collection_run_id", "source_group_id", "parent_snapshot_id",
        "parent_state_digest", "branch_id", "selection_design", "eligible_actions",
        "ineligible_actions", "selection_probability", "path_draw_probability",
        "selection_steps", "selection_seed", "rng", "selected_path", "prefix_cost", "branch_cost",
        "hypothetical_path_cost", "experimental_expenditure_contribution", "observations",
        "candidate_rows", "resulting_artifacts", "terminal_state_digest", "status", "capture_complete",
        "offline_gt_used", "native_history_extended", "errors",
    ],
    "properties": {
        "schema_version": {"const": COLLECTION_VERSION},
        **{key: {"type": "string"} for key in [
            "collection_run_id", "source_group_id", "parent_snapshot_id",
            "parent_state_digest", "branch_id", "selection_design", "terminal_state_digest",
        ]},
        "eligible_actions": {"type": "array"},
        "ineligible_actions": {"type": "array"},
        "selection_probability": {"type": ["number", "null"], "exclusiveMinimum": 0, "maximum": 1},
        "path_draw_probability": {"type": ["number", "null"], "exclusiveMinimum": 0, "maximum": 1},
        "selection_steps": {"type": "array"},
        "selection_seed": {"type": ["integer", "null"]},
        "rng": {"type": ["string", "null"]},
        "selected_path": {"type": "array"},
        **{key: {"type": "integer", "minimum": 0} for key in [
            "prefix_cost", "branch_cost", "hypothetical_path_cost",
            "experimental_expenditure_contribution",
        ]},
        "observations": {"type": "array"},
        "candidate_rows": {"type": "array"},
        "resulting_artifacts": {"type": "array"},
        "status": {"enum": ["complete", "partial", "failed", "ineligible"]},
        "capture_complete": {"type": "boolean"},
        "offline_gt_used": {"const": False},
        "native_history_extended": {"const": False},
        "errors": {"type": "array"},
    },
}


def validate_snapshot(record):
    validate(record, SNAPSHOT_SCHEMA)
    return True


def validate_branch(record):
    validate(record, COLLECTION_SCHEMA)
    if record["hypothetical_path_cost"] != record["prefix_cost"] + record["branch_cost"]:
        raise ValueError("Hypothetical path cost must equal prefix plus branch cost")
    if record["experimental_expenditure_contribution"] != record["branch_cost"]:
        raise ValueError("A branch contributes only its actually dispatched continuation cost")
    joint_ids = {}
    for candidate in record["candidate_rows"]:
        observation_id = candidate["joint_observation_id"]
        joint_ids.setdefault(observation_id, set()).add(candidate["logical_cost_accounting_id"])
    if any(len(cost_ids) != 1 for cost_ids in joint_ids.values()):
        raise ValueError("Candidates from one joint observation must share one cost identity")
    return True
