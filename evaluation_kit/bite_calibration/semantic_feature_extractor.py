"""GT-free runtime features from validated semantic observations.

Features are categorical indicators with explicit missingness. No value is
imputed into a probability, and no offline label can enter the table: rows are
checked against the GT marker set, the table is finalized with a digest, and a
later label join must present that digest.
"""

from __future__ import annotations

from .semantic_observation_schema import (
    FIELD_VALUES,
    OBSERVATION_SCHEMA_VERSION,
    ONTOLOGY_SHA256,
    PROMPT_SHA256,
    canonical_sha256,
    query_compatibility,
)
from .zoom_conditional_protocol import GT_MARKERS

FEATURE_VERSION = "bite.semantic_runtime_features.v1"
TABLE_VERSION = "bite.semantic_runtime_feature_table.v1"
COMPATIBILITY_VALUES = (
    "match", "taxonomic_overlap", "conflict_dataset_category", "conflict_other_object",
    "background", "unclear", "unavailable",
)
NONSUPPORT_COMPATIBILITY = ("conflict_dataset_category", "conflict_other_object", "background")
FORBIDDEN_FEATURE_MARKERS = GT_MARKERS | {
    "best_gt_iou", "gt_iou", "correct", "correctness", "human_review", "probability", "confidence",
}


def _keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).lower()
            yield from _keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _keys(child)


def extract_features(observation, *, allow_mock=False):
    if observation.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
        raise ValueError("Unexpected semantic observation schema")
    if observation.get("mock") and not allow_mock:
        raise ValueError("Mock observations cannot enter a research feature table")
    if observation["prompt"]["sha256"] != PROMPT_SHA256 or observation["ontology"]["sha256"] != ONTOLOGY_SHA256:
        raise ValueError("Observation was produced under a different prompt or ontology")
    if observation.get("offline_labels_accessed") or observation.get("query_sent_to_model"):
        raise ValueError("Observation violates the runtime evidence boundary")
    parsed = observation["parsed_observation"] if observation["response_status"] == "valid" else None
    status = observation["response_status"]
    compatibility = query_compatibility(observation["query"], parsed)
    row = {
        "schema_version": FEATURE_VERSION,
        "state_id": observation["state_id"],
        "original_candidate_id": observation["lineage"]["original_candidate_id"],
        "source_group_id": observation["source_group_id"],
        "query": observation["query"],
        "semantic_observation_id": observation["observation_id"],
        "mock": bool(observation.get("mock")),
        "semantic_response_status": status,
        "semantic_observation_available": parsed is not None,
        "semantic_parse_failure": status in {"empty_response", "malformed_json", "schema_violation"},
        "semantic_execution_failure": status == "execution_failure",
        "semantic_timeout": status == "timeout",
        "semantic_compatibility": compatibility,
        "semantic_region_content": parsed["region_content"] if parsed else None,
        "semantic_consistency_flag_count": len(observation["consistency_flags"]) if parsed else None,
        "semantic_logical_cost": observation["execution"]["logical_cost"],
    }
    for value in COMPATIBILITY_VALUES:
        row[f"semantic_compat_{value}"] = compatibility == value
    row["semantic_nonsupport"] = compatibility in NONSUPPORT_COMPATIBILITY
    for field in ("object_visible", "region_localization", "multiple_objects", "evidence_status"):
        row[f"semantic_{field}"] = parsed[field] if parsed else None
        for value in FIELD_VALUES[field]:
            row[f"semantic_{field}_{value}"] = bool(parsed) and parsed[field] == value
        row[f"semantic_{field}_missing"] = parsed is None
    leaked = FORBIDDEN_FEATURE_MARKERS & set(_keys(row))
    if leaked:
        raise AssertionError(f"Forbidden marker reached semantic features: {sorted(leaked)}")
    return row


def finalize_feature_table(observations, *, allow_mock=False):
    rows = sorted(
        (extract_features(row, allow_mock=allow_mock) for row in observations),
        key=lambda row: row["state_id"],
    )
    if len({row["state_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate semantic observation for a state")
    return {
        "schema_version": TABLE_VERSION,
        "status": "RUNTIME_FINALIZED_BEFORE_OFFLINE_JOIN",
        "row_count": len(rows),
        "rows": rows,
        "rows_sha256": canonical_sha256(rows),
        "offline_labels_joined": False,
    }


def join_offline_labels(table, labels, *, finalized_rows_sha256):
    """Join labels only to a table whose finalized digest is presented unchanged."""
    if canonical_sha256(table["rows"]) != finalized_rows_sha256 or table["rows_sha256"] != finalized_rows_sha256:
        raise ValueError("Runtime feature table changed after finalization")
    by_state = {}
    for label in labels:
        if label["state_id"] in by_state:
            raise ValueError("Duplicate offline label for a state")
        by_state[label["state_id"]] = label
    joined = []
    for row in table["rows"]:
        label = by_state.get(row["state_id"])
        if label is None:
            raise ValueError("Missing offline label for a semantic state")
        if label["candidate_id"] != row["original_candidate_id"]:
            raise ValueError("Offline label refers to a different candidate hypothesis")
        joined.append({**row, "label": int(label["label"]), "endpoint": label["endpoint"]})
    return joined
