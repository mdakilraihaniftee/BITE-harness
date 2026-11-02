"""Versioned Task V protocol for benchmark-defined annotation-proxy correctness."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

PROTOCOL_VERSION = "bite.task_v_annotation_proxy_protocol.v2"
ENDPOINTS = ("H_annotation_0.50", "H_annotation_0.75")
THRESHOLDS = (0.50, 0.75)


def annotation_proxy_label(candidate_box, eligible_boxes, threshold):
    """Return the closed-world COCO label for a valid candidate-present state."""
    if threshold not in THRESHOLDS:
        raise ValueError("Task V annotation endpoint supports only IoU 0.50 or 0.75")
    if candidate_box is None:
        return {"status": "no_candidate", "label": None, "best_iou": None}
    if len(candidate_box) != 4 or any(not isinstance(value, (int, float)) for value in candidate_box):
        raise ValueError("Candidate box must be a numeric xyxy box")
    x1, y1, x2, y2 = map(float, candidate_box)
    if x2 <= x1 or y2 <= y1:
        raise ValueError("Candidate box must have positive area")

    def iou(other):
        if len(other) != 4:
            raise ValueError("Eligible GT boxes must be xyxy boxes")
        gx1, gy1, gx2, gy2 = map(float, other)
        if gx2 <= gx1 or gy2 <= gy1:
            raise ValueError("Eligible GT boxes must have positive area")
        intersection = max(0.0, min(x2, gx2) - max(x1, gx1)) * max(
            0.0, min(y2, gy2) - max(y1, gy1),
        )
        union = (x2 - x1) * (y2 - y1) + (gx2 - gx1) * (gy2 - gy1) - intersection
        return intersection / union

    best = max((iou(box) for box in eligible_boxes), default=0.0)
    return {
        "status": "candidate_present",
        "label": int(best >= threshold),
        "best_iou": best,
        "empty_queried_class_is_annotation_negative": not eligible_boxes,
    }


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_protocol(*, partition_manifest_path, expansion_records_path, review_cases_path):
    partition = json.loads(Path(partition_manifest_path).read_text())
    expansion = [
        json.loads(line) for line in Path(expansion_records_path).read_text().splitlines()
        if line.strip()
    ]
    cases = [
        json.loads(line) for line in Path(review_cases_path).read_text().splitlines()
        if line.strip()
    ]
    by_state = {row["state_id"]: row for row in cases}
    selected = [by_state[row["runtime_features"]["state_id"]] for row in expansion]
    groups = {row["source_group_id"] for row in selected}
    source_hashes = {row["source_image_sha256"] for row in selected}
    annotation_hashes = {row["annotation_sha256"] for row in selected}
    if len(expansion) != 203 or len(groups) != 30 or len(source_hashes) != 30:
        raise ValueError("Unexpected seven-query expansion identity")
    if len(annotation_hashes) != 1:
        raise ValueError("Expansion records must share one frozen annotation identity")
    labels = {
        endpoint: [int(row["H_annotation"][str(threshold)] == "positive") for row in selected]
        for endpoint, threshold in zip(ENDPOINTS, ("0.5", "0.75"), strict=True)
    }
    expected = {
        "H_annotation_0.50": (31, 172),
        "H_annotation_0.75": (23, 180),
    }
    for endpoint, values in labels.items():
        observed = (sum(values), len(values) - sum(values))
        if observed != expected[endpoint]:
            raise ValueError(f"Frozen endpoint count changed for {endpoint}: {observed}")
    return {
        "schema_version": PROTOCOL_VERSION,
        "status": "ACTIVE_REVISED_PROTOCOL",
        "chronology": [
            "Human review was introduced as a label-quality safeguard.",
            "The project subsequently adopted a narrower COCO-defined benchmark endpoint.",
            "The researcher made additional human review optional for annotation-proxy work.",
            "All prior human-review artifacts remain preserved.",
            "The numerical COCO endpoint is unchanged; only its scientific interpretation changed.",
        ],
        "primary_endpoint": "H_annotation_0.50",
        "companion_endpoint": "H_annotation_0.75",
        "definition": (
            "For a valid candidate-present state, H_tau=1 iff maximum IoU against eligible official "
            "same-class COCO boxes is at least tau; an empty eligible set is annotation-negative."
        ),
        "no_candidate": {
            "status": "no_candidate",
            "binary_label_assigned": False,
            "excluded_from_candidate-present prior fitting": True,
        },
        "identity": {
            "source_id": "odinw13:Aquarium_Aquarium_Combined.v2-raw-1024.coco",
            "source_attribution": "Aquarium Combined (Roboflow), GLIP-curated archive",
            "license": "CC BY 4.0",
            "partition_manifest_sha256": partition["manifest_sha256"],
            "partition_manifest_file_sha256": _sha(partition_manifest_path),
            "annotation_sha256": next(iter(annotation_hashes)),
            "expansion_records_sha256": _sha(expansion_records_path),
            "review_cases_sha256": _sha(review_cases_path),
            "fit_source_image_count": len(source_hashes),
            "fit_source_image_sha256": sorted(source_hashes),
            "fit_source_image_set_sha256": hashlib.sha256(
                "\n".join(sorted(source_hashes)).encode()
            ).hexdigest(),
        },
        "fit_cohort": {
            "partition": "calibration_fit",
            "cohort_id": "bite.task_v_expansion.seed418.g30.v1",
            "query_design_id": "all_seven_source_classes_per_group.v1",
            "source_group_count": len(groups),
            "candidate_present_count": len(selected),
            "endpoint_counts": {
                endpoint: {"positive": sum(values), "negative": len(values) - sum(values)}
                for endpoint, values in labels.items()
            },
            "sampling_unit": "source_group_id",
            "source_group_crossing_prohibited": True,
        },
        "human_review": {
            "required_for_annotation_proxy_calibration": False,
            "status": "OPTIONAL_SUPPLEMENTAL_ANALYSIS",
            "required_for_visual_truth_claims": True,
            "required_for_annotation_omission_prevalence": True,
            "historical_records_preserved": True,
        },
        "held_out_validation": {
            "partition": "calibration_validation",
            "source_group_disjoint": True,
            "frozen_models_only": True,
            "paired_source_group_evaluation": True,
            "no_validation_tuning": True,
            "internal_test_locked": True,
        },
        "interpretation": {
            "benchmark_defined_candidate_correctness": True,
            "closed_world_annotation_convention": True,
            "exhaustive_visual_truth_claimed": False,
            "zero_annotation_omissions_claimed": False,
            "human_verified_probability_claimed": False,
            "arbitrary_image_or_query_generalization_claimed": False,
            "deployment_probability_claimed": False,
            "annotation_omission_is_documented_threat": True,
        },
        "restrictions": {
            "original_candidate_label_fixed_after_actions": True,
            "post_action_evidence_cannot_redefine_target": True,
            "probabilities_apply_only_to_declared_dataset_query_distribution": True,
        },
    }


def validate_protocol(protocol):
    if protocol.get("schema_version") != PROTOCOL_VERSION:
        raise ValueError("Unexpected annotation-proxy protocol version")
    if protocol.get("primary_endpoint") != "H_annotation_0.50":
        raise ValueError("Primary annotation endpoint changed")
    if protocol.get("companion_endpoint") != "H_annotation_0.75":
        raise ValueError("Companion annotation endpoint changed")
    if protocol["human_review"]["required_for_annotation_proxy_calibration"]:
        raise ValueError("Human review must not block annotation-proxy calibration")
    if not protocol["human_review"]["required_for_visual_truth_claims"]:
        raise ValueError("Visual-truth claims must remain separately gated")
    if protocol["interpretation"]["exhaustive_visual_truth_claimed"]:
        raise ValueError("Annotation-proxy protocol cannot claim visual truth")
    return protocol
