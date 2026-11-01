"""Versioned visual-plausibility endpoint and optional human reference boxes."""

from __future__ import annotations

import math

VISUAL_ENDPOINT_VERSION = "bite.visual_plausibility.v1"
VISUAL_VERIFICATION_VERSION = "bite.visual_verification.v2"
PLAUSIBILITY = {"supported", "unsupported", "ambiguous", "insufficient_evidence"}
LOCALIZATION = {"adequate", "inadequate", "ambiguous", "insufficient_evidence"}


def validate_reference_box(box, *, width, height):
    if not isinstance(box, dict):
        raise TypeError("Reference box must be a mapping")
    coords = box.get("pixel_xyxy")
    if not isinstance(coords, list) or len(coords) != 4:
        raise ValueError("Reference box requires four pixel xyxy coordinates")
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in coords):
        raise ValueError("Reference coordinates must be finite numbers")
    x1, y1, x2, y2 = coords
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("Reference box is outside the declared image dimensions")
    if box.get("image_width") != width or box.get("image_height") != height:
        raise ValueError("Reference box image dimensions mismatch")
    for key in ("object_class", "object_identity_note", "reviewer_id", "created_at"):
        if not isinstance(box.get(key), str) or not box[key].strip():
            raise ValueError(f"Reference box requires {key}")
    for key in ("occluded", "truncated"):
        if not isinstance(box.get(key), bool):
            raise TypeError(f"Reference box requires boolean {key}")
    return box


def visual_endpoint(*, plausibility, localization, ambiguity_controls, reference_boxes=()):
    if plausibility not in PLAUSIBILITY:
        raise ValueError("Invalid visual plausibility category")
    if localization not in LOCALIZATION:
        raise ValueError("Invalid visual localization category")
    required = {"class_identity_ambiguous", "localization_ambiguous", "insufficient_image_evidence"}
    if not isinstance(ambiguity_controls, dict) or set(ambiguity_controls) != required:
        raise ValueError("Visual endpoint ambiguity controls are incomplete")
    if any(value not in {"yes", "no", "uncertain"} for value in ambiguity_controls.values()):
        raise ValueError("Ambiguity controls must use yes/no/uncertain")
    binary = None
    if plausibility == "supported" and localization == "adequate" and all(
        value == "no" for value in ambiguity_controls.values()
    ):
        binary = 1
    elif plausibility == "unsupported" and all(
        value == "no" for value in ambiguity_controls.values()
    ):
        binary = 0
    return {
        "schema_version": VISUAL_ENDPOINT_VERSION,
        "visual_plausibility": plausibility,
        "visual_localization": localization,
        "binary_visual_endpoint": binary,
        "H_annotation_0.50": "separate_external_endpoint",
        "H_annotation_0.75": "separate_external_endpoint",
        "threshold_specific_corrected_visual_labels": {"0.5": "unknown", "0.75": "unknown"},
        "reference_box_count": len(reference_boxes),
        "single_reference_box_is_authoritative_gt": False,
        "subjective_localization_converted_to_iou": False,
        "ambiguity_controls": ambiguity_controls,
    }


def visual_verification_v2(*, object_presence, class_correctness, localization_adequacy,
                           evidence_ambiguous, localization_evidence_insufficient,
                           reference_boxes=()):
    """Composite visual verification with wrong localization represented explicitly.

    This is deliberately not an IoU endpoint. V1 remains available unchanged for
    historical records.
    """
    allowed = {"supported", "unsupported", "ambiguous", "insufficient_evidence"}
    localization_allowed = {"adequate", "inadequate", "ambiguous", "insufficient_evidence"}
    if object_presence not in allowed:
        raise ValueError("Invalid object-presence judgment")
    if class_correctness not in allowed:
        raise ValueError("Invalid class-correctness judgment")
    if localization_adequacy not in localization_allowed:
        raise ValueError("Invalid localization-adequacy judgment")
    if not isinstance(evidence_ambiguous, bool):
        raise TypeError("evidence_ambiguous must be boolean")
    if not isinstance(localization_evidence_insufficient, bool):
        raise TypeError("localization_evidence_insufficient must be boolean")
    uncertain = (
        evidence_ambiguous
        or localization_evidence_insufficient
        or object_presence in {"ambiguous", "insufficient_evidence"}
        or class_correctness in {"ambiguous", "insufficient_evidence"}
        or localization_adequacy in {"ambiguous", "insufficient_evidence"}
    )
    if uncertain:
        binary = None
        reason = "ambiguous_or_insufficient_evidence"
    elif (
        object_presence == "supported"
        and class_correctness == "supported"
        and localization_adequacy == "adequate"
    ):
        binary = 1
        reason = "presence_class_and_localization_supported"
    elif object_presence == "unsupported":
        binary = 0
        reason = "queried_object_not_visibly_present"
    elif class_correctness == "unsupported":
        binary = 0
        reason = "proposed_class_incorrect"
    elif localization_adequacy == "inadequate":
        binary = 0
        reason = "clearly_inadequate_localization"
    else:
        binary = None
        reason = "unsupported_combination"
    return {
        "schema_version": VISUAL_VERIFICATION_VERSION,
        "object_presence": object_presence,
        "class_correctness": class_correctness,
        "localization_adequacy": localization_adequacy,
        "evidence_ambiguous": evidence_ambiguous,
        "localization_evidence_insufficient": localization_evidence_insufficient,
        "binary_visual_endpoint": binary,
        "binary_reason": reason,
        "threshold_specific_corrected_visual_labels": {"0.5": "unknown", "0.75": "unknown"},
        "subjective_localization_converted_to_iou": False,
        "reference_box_count": len(reference_boxes),
        "single_reference_box_is_authoritative_gt": False,
        "supersedes_v1_for_new_reviews_only": True,
    }
