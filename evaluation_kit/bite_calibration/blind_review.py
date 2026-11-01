"""Server-enforced blind-first review transitions with immutable event files."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from .adjudication_schema import validate_review
from .visual_endpoint import (
    validate_reference_box,
    visual_endpoint,
    visual_verification_v2,
)

BLIND_PROTOCOL_VERSION = "bite.task_v_blind_adjudication_protocol.v2"
BLIND_PROTOCOL_VERSION_V3 = "bite.task_v_blind_adjudication_protocol.v3"
BLIND_EVENT_VERSION = "bite.task_v_blind_review_event.v1"
EVIDENCE_CONTROL_NAMES = {
    "object_present_in_proposed_region", "class_appears_correct",
    "box_reasonably_localizes_object", "relevant_annotation_appears_missing",
    "nearby_competing_instance", "image_evidence_inconclusive",
}


def candidate_digest(case):
    value = {
        "candidate_id": case["initial_candidate_id"],
        "bbox": case["initial_box_root_xyxy"],
        "source_image_sha256": case["source_image_sha256"],
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _timestamp(value, name):
    if not isinstance(value, str):
        raise TypeError(f"{name} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed


def _identity(event):
    return hashlib.sha256(
        f"{event['case_id']}:{event['reviewer_id']}".encode(),
    ).hexdigest()


def review_directory(root, case_id, reviewer_id):
    token = hashlib.sha256(f"{case_id}:{reviewer_id}".encode()).hexdigest()
    return Path(root) / token


def _base(event, case):
    for key in (
        "case_id", "reviewer_id", "submitted_at", "source_group_id", "initial_candidate_id",
        "source_image_sha256", "annotation_sha256", "candidate_digest",
    ):
        if not isinstance(event.get(key), str) or not event[key].strip():
            raise ValueError(f"Blind review event requires {key}")
    if event["case_id"] != case["case_id"]:
        raise ValueError("Review case identity mismatch")
    if event["source_image_sha256"] != case["source_image_sha256"]:
        raise ValueError("Source digest mismatch")
    if event["annotation_sha256"] != case["annotation_sha256"]:
        raise ValueError("Annotation digest mismatch")
    if event["source_group_id"] != case["source_group_id"]:
        raise ValueError("Source-group identity mismatch")
    if event["initial_candidate_id"] != case["initial_candidate_id"]:
        raise ValueError("Candidate identity mismatch")
    if event["candidate_digest"] != candidate_digest(case):
        raise ValueError("Candidate digest mismatch")
    if event.get("reviewer_type") != "human":
        raise ValueError("Blind review events require a human reviewer")
    _timestamp(event["submitted_at"], "submitted_at")


def validate_blind_first_pass(event, case):
    _base(event, case)
    if event.get("schema_version") != BLIND_EVENT_VERSION or event.get("event_type") != "blind_first_pass_submitted":
        raise ValueError("Invalid blind first-pass event")
    if event.get("protocol_version") not in {BLIND_PROTOCOL_VERSION, BLIND_PROTOCOL_VERSION_V3}:
        raise ValueError("Blind-review protocol mismatch")
    endpoint = _endpoint_for_event(event)
    for box in event.get("reference_boxes", []):
        validate_reference_box(box, width=case["image_width"], height=case["image_height"])
    controls = event.get("legacy_evidence_controls")
    if not isinstance(controls, dict) or set(controls) != EVIDENCE_CONTROL_NAMES:
        raise ValueError("Blind first pass requires all legacy evidence controls")
    if any(value not in {"yes", "no", "uncertain"} for value in controls.values()):
        raise ValueError("Blind evidence controls must use yes/no/uncertain")
    return {**event, "derived_visual_endpoint": endpoint, "event_identity": _identity(event)}


def validate_reveal_event(event, case, first_pass):
    _base(event, case)
    if event.get("schema_version") != BLIND_EVENT_VERSION or event.get("event_type") != "gt_revealed":
        raise ValueError("Invalid reveal event")
    if event["reviewer_id"] != first_pass["reviewer_id"]:
        raise ValueError("Reveal reviewer mismatch")
    if _timestamp(event["submitted_at"], "submitted_at") < _timestamp(
        first_pass["submitted_at"], "first_pass_submitted_at",
    ):
        raise ValueError("GT reveal cannot precede the blind first pass")
    if event.get("blind_event_identity") != first_pass["event_identity"]:
        raise ValueError("Reveal does not reference the immutable blind event")
    return {**event, "event_identity": _identity(event) + ":reveal"}


def validate_post_reveal_event(event, case, first_pass, reveal):
    _base(event, case)
    if event.get("schema_version") != BLIND_EVENT_VERSION or event.get("event_type") != "post_reveal_judgment":
        raise ValueError("Invalid post-reveal event")
    if event["reviewer_id"] != first_pass["reviewer_id"]:
        raise ValueError("Post-reveal reviewer mismatch")
    if _timestamp(event["submitted_at"], "submitted_at") < _timestamp(
        reveal["submitted_at"], "gt_revealed_at",
    ):
        raise ValueError("Post-reveal judgment cannot precede reveal")
    if event.get("protocol_version") != first_pass.get("protocol_version"):
        raise ValueError("Post-reveal protocol must match the blind first pass")
    endpoint = _endpoint_for_event(event)
    for box in event.get("reference_boxes", []):
        validate_reference_box(box, width=case["image_width"], height=case["image_height"])
    controls = event.get("legacy_evidence_controls")
    if not isinstance(controls, dict) or set(controls) != EVIDENCE_CONTROL_NAMES:
        raise ValueError("Post-reveal judgment requires all legacy evidence controls")
    if any(value not in {"yes", "no", "uncertain"} for value in controls.values()):
        raise ValueError("Post-reveal evidence controls must use yes/no/uncertain")
    changed = (
        event.get("visual_plausibility") != first_pass.get("visual_plausibility")
        or event.get("visual_localization") != first_pass.get("visual_localization")
        or event.get("ambiguity_controls") != first_pass.get("ambiguity_controls")
        or event.get("legacy_evidence_controls") != first_pass.get("legacy_evidence_controls")
        or event.get("reference_boxes", []) != first_pass.get("reference_boxes", [])
        or event.get("visual_verification") != first_pass.get("visual_verification")
    )
    if changed and not isinstance(event.get("reason_for_change"), str):
        raise ValueError("Changed post-reveal judgment requires a reason")
    if changed and not event["reason_for_change"].strip():
        raise ValueError("Changed post-reveal judgment requires a reason")
    return {**event, "derived_visual_endpoint": endpoint, "changed_from_blind": changed,
            "event_identity": _identity(event) + ":post"}


def _endpoint_for_event(event):
    if event.get("protocol_version") == BLIND_PROTOCOL_VERSION:
        return visual_endpoint(
            plausibility=event.get("visual_plausibility"),
            localization=event.get("visual_localization"),
            ambiguity_controls=event.get("ambiguity_controls"),
            reference_boxes=event.get("reference_boxes", []),
        )
    verification = event.get("visual_verification")
    if not isinstance(verification, dict):
        raise TypeError("Blind-review v3 requires visual_verification")
    return visual_verification_v2(
        object_presence=verification.get("object_presence"),
        class_correctness=verification.get("class_correctness"),
        localization_adequacy=verification.get("localization_adequacy"),
        evidence_ambiguous=verification.get("evidence_ambiguous"),
        localization_evidence_insufficient=verification.get(
            "localization_evidence_insufficient",
        ),
        reference_boxes=event.get("reference_boxes", []),
    )


def load_event_chain(root, case, reviewer_id):
    directory = review_directory(root, case["case_id"], reviewer_id)
    first_path = directory / "0001_blind_first_pass.json"
    reveal_path = directory / "0002_gt_revealed.json"
    post_path = directory / "0003_post_reveal.json"
    first = validate_blind_first_pass(json.loads(first_path.read_text()), case) if first_path.is_file() else None
    reveal = (
        validate_reveal_event(json.loads(reveal_path.read_text()), case, first)
        if reveal_path.is_file() and first else None
    )
    post = (
        validate_post_reveal_event(json.loads(post_path.read_text()), case, first, reveal)
        if post_path.is_file() and first and reveal else None
    )
    if reveal_path.is_file() and first is None:
        raise ValueError("Orphan reveal event")
    if post_path.is_file() and reveal is None:
        raise ValueError("Orphan post-reveal event")
    return {"first_pass": first, "reveal": reveal, "post_reveal": post}


def append_event(root, case, event):
    directory = review_directory(root, case["case_id"], event["reviewer_id"])
    directory.mkdir(parents=True, exist_ok=True)
    chain = load_event_chain(root, case, event["reviewer_id"])
    event_type = event.get("event_type")
    if event_type == "blind_first_pass_submitted":
        if chain["first_pass"] is not None:
            raise ValueError("Blind first-pass judgment is immutable and already exists")
        validated = validate_blind_first_pass(event, case)
        path = directory / "0001_blind_first_pass.json"
    elif event_type == "gt_revealed":
        if chain["first_pass"] is None:
            raise ValueError("Blind first pass must be submitted before reveal")
        if chain["reveal"] is not None:
            raise ValueError("GT reveal event already exists")
        validated = validate_reveal_event(event, case, chain["first_pass"])
        path = directory / "0002_gt_revealed.json"
    elif event_type == "post_reveal_judgment":
        if chain["reveal"] is None:
            raise ValueError("GT must be revealed before a post-reveal judgment")
        if chain["post_reveal"] is not None:
            raise ValueError("Post-reveal adjustment already exists; explicit new protocol revision required")
        validated = validate_post_reveal_event(event, case, chain["first_pass"], chain["reveal"])
        path = directory / "0003_post_reveal.json"
    else:
        raise ValueError("Unknown blind review event type")
    with path.open("x") as stream:
        stream.write(json.dumps(validated, indent=2, sort_keys=True) + "\n")
    return validated


def validate_final_completion(review, case, chain):
    if chain["first_pass"] is None or chain["reveal"] is None:
        raise ValueError("Final completion requires blind first pass followed by reveal")
    validate_review(review, expected_case=case)
    if review["reviewer_id"] != chain["first_pass"]["reviewer_id"]:
        raise ValueError("Final completion reviewer does not match blind event chain")
    return review


def progress_summary(cases, queue_ids, event_root, completed_reviews):
    completed_pairs = {(row["case_id"], row["reviewer_id"]) for row in completed_reviews}
    first = reveal = post = 0
    reviewed_cases = set()
    for case in cases:
        case_dir_prefix = None
        for directory in Path(event_root).glob("*") if Path(event_root).is_dir() else ():
            first_path = directory / "0001_blind_first_pass.json"
            if not first_path.is_file():
                continue
            event = json.loads(first_path.read_text())
            if event.get("case_id") != case["case_id"]:
                continue
            case_dir_prefix = directory
            first += 1
            reviewed_cases.add(case["case_id"])
            reveal += int((directory / "0002_gt_revealed.json").is_file())
            post += int((directory / "0003_post_reveal.json").is_file())
        del case_dir_prefix
    completed_case_ids = {case_id for case_id, _ in completed_pairs}
    return {
        "schema_version": "bite.task_v_blind_review_progress.v1",
        "queue_case_count": len(queue_ids),
        "blind_first_pass_count": first,
        "gt_reveal_count": reveal,
        "post_reveal_judgment_count": post,
        "completed_human_judgment_count": len(completed_pairs),
        "completed_case_count": len(completed_case_ids),
        "outstanding_queue_case_count": len(set(queue_ids) - completed_case_ids),
        "viewing_marks_complete": False,
        "human_review_status": "COMPLETE" if set(queue_ids) <= completed_case_ids else "PENDING",
    }
