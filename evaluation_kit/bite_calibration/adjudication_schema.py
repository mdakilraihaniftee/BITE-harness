"""Versioned schemas for human Task V visual adjudication."""

from __future__ import annotations

from datetime import datetime

CASE_VERSION = "bite.task_v_review_case.v1"
REVIEW_VERSION = "bite.task_v_visual_adjudication.v1"
PROTOCOL_VERSION = "bite.task_v_adjudication_protocol.v1"

VISUAL_LABELS = {
    "visually_supported_positive",
    "visually_supported_negative",
    "possible_annotation_omission",
    "class_identity_ambiguous",
    "localization_ambiguous",
    "insufficient_image_evidence",
    "not_reviewed",
}
TRISTATE = {"yes", "no", "uncertain"}
CORRECTION_STATUSES = {
    "no_correction_proposed",
    "visual_only_not_benchmark_correction",
    "correction_potentially_defensible_requires_annotation_amendment",
    "indeterminate",
}


def _required(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def validate_case(case):
    if case.get("schema_version") != CASE_VERSION:
        raise ValueError("Unsupported review-case schema")
    for key in ("case_id", "state_id", "cohort_id", "source_group_id", "query"):
        _required(case.get(key), key)
    if case.get("partition") != "calibration_fit":
        raise ValueError("Review cases must remain calibration_fit only")
    annotation = case.get("H_annotation")
    if not isinstance(annotation, dict) or set(annotation) != {"0.5", "0.75"}:
        raise ValueError("H_annotation must preserve both declared thresholds")
    if any(value not in {"positive", "negative", "unknown"} for value in annotation.values()):
        raise ValueError("Invalid annotation label")
    if case.get("H_visual_review") != "not_reviewed":
        raise ValueError("Generated queues cannot fabricate visual adjudications")
    if not case.get("source_image_sha256") or not case.get("annotation_sha256"):
        raise ValueError("Frozen image and annotation identities are required")
    return case


def validate_review(review, *, expected_case=None):
    if review.get("schema_version") != REVIEW_VERSION:
        raise ValueError("Unsupported adjudication schema")
    for key in ("case_id", "reviewer_id", "reviewed_at", "protocol_version", "annotation_sha256"):
        _required(review.get(key), key)
    if review["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("Review protocol version mismatch")
    try:
        timestamp = datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("reviewed_at must be ISO-8601") from error
    if timestamp.tzinfo is None:
        raise ValueError("reviewed_at must include a timezone")
    visual = review.get("H_visual_review")
    if visual not in VISUAL_LABELS - {"not_reviewed"}:
        raise ValueError("A completed review needs a human visual judgment")
    controls = review.get("controls")
    expected_controls = {
        "object_present_in_proposed_region", "class_appears_correct",
        "box_reasonably_localizes_object", "relevant_annotation_appears_missing",
        "nearby_competing_instance", "image_evidence_inconclusive",
    }
    if not isinstance(controls, dict) or set(controls) != expected_controls:
        raise ValueError("Review controls are incomplete")
    if any(value not in TRISTATE for value in controls.values()):
        raise ValueError("Review controls must use yes/no/uncertain")
    if review.get("reviewer_type") != "human":
        raise ValueError("Only an explicitly human review can be completed")
    thresholds = review.get("applicable_iou_thresholds")
    if not isinstance(thresholds, list) or not thresholds or not set(thresholds) <= {"0.5", "0.75"}:
        raise ValueError("applicable_iou_thresholds must name at least one declared threshold")
    if review.get("corrected_label_status") not in CORRECTION_STATUSES:
        raise ValueError("Invalid corrected-label defensibility status")
    _required(review.get("corrected_label_reason"), "corrected_label_reason")
    if expected_case is not None:
        if review["case_id"] != expected_case["case_id"]:
            raise ValueError("Review case identity mismatch")
        if review["annotation_sha256"] != expected_case["annotation_sha256"]:
            raise ValueError("Annotation identity mismatch")
    return review


def pending_review(case_id, annotation_sha256):
    return {
        "schema_version": REVIEW_VERSION,
        "case_id": case_id,
        "status": "pending_human_review",
        "H_visual_review": "not_reviewed",
        "annotation_sha256": annotation_sha256,
        "human_judgments": [],
        "resolution": None,
    }
