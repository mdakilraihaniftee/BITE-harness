"""Validate and summarize optional Task V human evidence without changing it."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from .adjudication_validation import validate_adjudications
from .blind_review import load_event_chain
from .review_progress import review_progress

SUMMARY_VERSION = "bite.task_v_optional_human_review_status.v1"


def _json(path):
    return json.loads(Path(path).read_text())


def _jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def summarize_optional_reviews(*, review_cases_path, statistical_sample_path,
                               targeted_sample_path, completed_dir, event_root,
                               second_review_sample_path=None):
    cases = _jsonl(review_cases_path)
    case_map = {row["case_id"]: row for row in cases}
    statistical = _json(statistical_sample_path)
    targeted = _json(targeted_sample_path)
    completed_paths = sorted(Path(completed_dir).glob("*.json"))
    completed = [_json(path) for path in completed_paths]
    validation = validate_adjudications(
        cases, completed, statistical_case_ids=statistical["case_ids"],
    )
    second = _json(second_review_sample_path) if second_review_sample_path else None
    progress = review_progress(
        cases, statistical, targeted, completed, event_roots=[event_root],
        second_review_sample=second,
    )
    chains = []
    incomplete = []
    completed_pairs = {(row["case_id"], row["reviewer_id"]): row for row in completed}
    seen_pairs = set()
    for directory in sorted(Path(event_root).glob("*")):
        first_path = directory / "0001_blind_first_pass.json"
        if not first_path.is_file():
            incomplete.append({"directory": str(directory), "reason": "missing_blind_first_pass"})
            continue
        first = _json(first_path)
        case = case_map.get(first.get("case_id"))
        if case is None:
            raise ValueError("Human-review event references an unknown case")
        chain = load_event_chain(event_root, case, first["reviewer_id"])
        pair = (case["case_id"], first["reviewer_id"])
        review = completed_pairs.get(pair)
        finalized = review is not None
        if finalized:
            seen_pairs.add(pair)
            if review["blind_event_identity"] != chain["first_pass"]["event_identity"]:
                raise ValueError("Final review does not point to its immutable blind event")
            if review["annotation_sha256"] != case["annotation_sha256"]:
                raise ValueError("Final review annotation identity mismatch")
        else:
            incomplete.append({
                "case_id": case["case_id"], "reviewer_id": first["reviewer_id"],
                "reason": "event_chain_not_finalized",
            })
        chains.append({
            "case_id": case["case_id"],
            "reviewer_id": first["reviewer_id"],
            "blind_first_pass": True,
            "gt_revealed": chain["reveal"] is not None,
            "post_reveal": chain["post_reveal"] is not None,
            "finalized": finalized,
            "blind_protocol_version": first["protocol_version"],
            "source_image_sha256": case["source_image_sha256"],
            "candidate_digest": first["candidate_digest"],
        })
    if seen_pairs != set(completed_pairs):
        raise ValueError("A finalized review has no matching validated blind event chain")

    cross = defaultdict(Counter)
    possible_missing = clearly_bad_localization = ambiguous = 0
    for review in completed:
        case = case_map[review["case_id"]]
        annotation = case["H_annotation"]["0.5"]
        visual = review["H_visual_review"]
        cross[annotation][visual] += 1
        controls = review["controls"]
        possible_missing += int(
            annotation == "negative" and controls["relevant_annotation_appears_missing"] == "yes"
        )
        clearly_bad_localization += int(controls["box_reasonably_localizes_object"] == "no")
        ambiguous += int(visual in {
            "class_identity_ambiguous", "localization_ambiguous", "insufficient_image_evidence",
        })
    return {
        "schema_version": SUMMARY_VERSION,
        "status": "OPTIONAL_SUPPLEMENTAL_REVIEW_PARTIAL",
        "validated_finalized_review_count": len(completed),
        "validated_finalized_case_count": len({row["case_id"] for row in completed}),
        "queue_union_case_count": progress["queue_union_case_count"],
        "queue_union_pending_case_count": (
            progress["queue_union_case_count"] - progress["completed_case_count"]
        ),
        "all_review_cases_count": len(cases),
        "all_review_cases_pending_count": len(cases) - validation["reviewed_case_count"],
        "set_a": progress["set_a"],
        "set_b": progress["set_b"],
        "event_progress": progress["event_progress"],
        "reviewer_ids": sorted({row["reviewer_id"] for row in completed}),
        "review_protocol_versions": sorted({row["protocol_version"] for row in completed}),
        "blind_protocol_versions": sorted({row["blind_protocol_version"] for row in completed}),
        "descriptive_only": {
            "annotation_0_50_by_visual_label": {
                annotation: dict(sorted(counts.items()))
                for annotation, counts in sorted(cross.items())
            },
            "possible_missing_annotation_case_count": possible_missing,
            "ambiguous_visual_label_count": ambiguous,
            "clearly_inadequate_localization_control_count": clearly_bad_localization,
            "incomplete_event_chain_count": len(incomplete),
            "incomplete_event_chains": incomplete,
        },
        "probability_sample_complete": progress["set_a"]["remaining"] == 0,
        "dataset_wide_omission_prevalence_estimated": False,
        "reason_no_prevalence_estimate": (
            "The frozen probability sample is incomplete; targeted and partial reviews cannot support "
            "a dataset-wide omission estimate."
        ),
        "training_labels_modified": False,
        "prior_refit_from_human_labels": False,
        "human_review_required_for_annotation_proxy": False,
        "human_review_required_for_visual_truth_claims": True,
        "source_artifact_hashes": {
            "review_cases": _sha(review_cases_path),
            "statistical_sample": _sha(statistical_sample_path),
            "targeted_sample": _sha(targeted_sample_path),
            "completed_records": {str(path): _sha(path) for path in completed_paths},
            "event_records": {
                str(path): _sha(path)
                for path in sorted(Path(event_root).glob("*/*.json"))
            },
        },
        "historical_records_rewritten": False,
        "fabricated_reviews": False,
        "authoritative_validation": validation,
        "validated_event_chains": chains,
    }


def validate_optional_review_summary(summary):
    if summary.get("schema_version") != SUMMARY_VERSION:
        raise ValueError("Unexpected optional-review summary schema")
    if summary["fabricated_reviews"] or summary["historical_records_rewritten"]:
        raise ValueError("Review preservation guarantee failed")
    if summary["validated_finalized_review_count"] != summary[
        "authoritative_validation"
    ]["completed_human_judgments"]:
        raise ValueError("Finalized review counts disagree")
    return summary
