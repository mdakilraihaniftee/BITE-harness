import json
import math
from copy import deepcopy
from pathlib import Path

import pytest

from evaluation_kit.bite_calibration.adjudication_sampling import (
    statistical_quality_sample,
    targeted_failure_sample,
)
from evaluation_kit.bite_calibration.adjudication_schema import (
    CASE_VERSION,
    PROTOCOL_VERSION,
    REVIEW_VERSION,
    pending_review,
    validate_case,
    validate_review,
)
from evaluation_kit.bite_calibration.adjudication_validation import (
    validate_adjudications,
)
from evaluation_kit.bite_calibration.conditional_features import (
    FEATURE_VERSION,
    extract_runtime_features,
    join_offline_labels,
    runtime_projection,
)
from evaluation_kit.bite_calibration.evidence_diagnostics import build_diagnostics
from evaluation_kit.bite_calibration.model_specification import (
    phase4c_model_specification,
)
from evaluation_kit.bite_calibration.statistical_readiness import assess_readiness

PILOT = "bite.task_v_pilot.seed417.g20.v1"
EXPANSION = "bite.task_v_expansion.seed418.g30.v1"
ROOT = Path(__file__).resolve().parents[2]


def _case(index=0, *, cohort=PILOT, group=None, label="negative", score=.95):
    return {
        "schema_version": CASE_VERSION,
        "case_id": f"case:{cohort}:{index}",
        "state_id": f"state:{cohort}:{index}",
        "cohort_id": cohort,
        "query_design_id": "two_classes" if cohort == PILOT else "seven_classes",
        "source_group_id": group or f"group:{cohort}:{index // 2}",
        "query": ("fish", "shark", "stingray", "jellyfish", "puffin", "penguin", "starfish")[index % 7],
        "partition": "calibration_fit",
        "source_image_sha256": "a" * 64,
        "annotation_sha256": "b" * 64,
        "H_annotation": {"0.5": label, "0.75": label},
        "H_visual_review": "not_reviewed",
        "initial_score": score,
        "candidate_size": ("small", "medium", "large")[index % 3],
        "diagnostic_primary": "positive" if label == "positive" else "no_annotated_instance",
        "focused_association_category": "target_aligned_supporting_proposal",
    }


def _review(case, reviewer="reviewer-a", label="possible_annotation_omission"):
    return {
        "schema_version": REVIEW_VERSION,
        "case_id": case["case_id"],
        "reviewer_id": reviewer,
        "reviewer_type": "human",
        "reviewed_at": "2026-11-01T10:00:00-04:00",
        "protocol_version": PROTOCOL_VERSION,
        "annotation_sha256": case["annotation_sha256"],
        "H_visual_review": label,
        "controls": {
            "object_present_in_proposed_region": "yes",
            "class_appears_correct": "yes",
            "box_reasonably_localizes_object": "yes",
            "relevant_annotation_appears_missing": "yes",
            "nearby_competing_instance": "no",
            "image_evidence_inconclusive": "no",
        },
        "applicable_iou_thresholds": ["0.5", "0.75"],
        "corrected_label_status": "correction_potentially_defensible_requires_annotation_amendment",
        "corrected_label_reason": "Visible object, but benchmark annotation remains unchanged.",
        "comments": "independent visual review",
    }


def _pair(category="target_aligned_supporting_proposal"):
    focused = None if category == "no_target_aligned_proposal" else {
        "candidate_id": "focused:0",
        "bbox_root_xyxy": [12, 8, 32, 28],
        "bbox_local_xyxy": [2, 3, 22, 23],
        "raw_scores": [.9],
        "source_backend": "sam3_segment",
    }
    return {
        "state_id": "state:1",
        "source_group_id": "group:1",
        "query": "fish",
        "original_candidate_id": "candidate:0",
        "original_bbox_root_xyxy": [10, 10, 30, 30],
        "original_score": .8,
        "focused_aligned_candidate": focused,
        "focused_observation_id": "observation:focus",
        "focused_association_category": category,
        "focused_candidate_count": 0 if focused is None else 2,
        "incremental_logical_cost": 2,
        "zoom_crop": {
            "child_image_id": "crop:1",
            "child_width": 50,
            "child_height": 40,
        },
    }


def _context():
    return {
        "cohort_id": PILOT,
        "query_design_id": "two_classes",
        "root_width": 100,
        "root_height": 100,
        "initial_observation_id": "observation:initial",
        "parent_snapshot_id": "snapshot:0",
        "source_image_sha256": "a" * 64,
        "initial_backend": "sam3_segment",
        "coordinate_transform_valid": True,
        "initial_candidate_count": 3,
        "focused_candidate_ranks": {"focused:0": 1},
    }


def _labeled_pair(category="target_aligned_supporting_proposal", positive=False):
    pair = _pair(category)
    pair.update({
        "original_labels": [
            {"iou_threshold": .5, "official_tp": positive, "max_eligible_iou": .7 if positive else 0},
            {"iou_threshold": .75, "official_tp": False, "max_eligible_iou": .7 if positive else 0},
        ],
        "focused_aligned_labels": [] if pair["focused_aligned_candidate"] is None else [
            {"iou_threshold": .5, "official_tp": positive, "max_eligible_iou": .8 if positive else 0},
            {"iou_threshold": .75, "official_tp": positive, "max_eligible_iou": .8 if positive else 0},
        ],
        "same_assigned_gt": {"0.5": True if positive else None, "0.75": None},
        "new_valid_object_localized": {"0.5": False, "0.75": False},
    })
    return pair


def test_annotation_and_visual_labels_remain_separate():
    case = validate_case(_case())
    assert case["H_annotation"]["0.5"] == "negative"
    assert case["H_visual_review"] == "not_reviewed"
    altered = deepcopy(case)
    altered["H_visual_review"] = "visually_supported_positive"
    with pytest.raises(ValueError, match="fabricate"):
        validate_case(altered)


def test_pending_record_is_not_a_completed_human_judgment():
    row = pending_review("case:1", "a" * 64)
    assert row["status"] == "pending_human_review"
    assert row["human_judgments"] == []
    with pytest.raises(ValueError):
        validate_review(row)


def test_human_identity_timestamp_threshold_and_reason_are_validated():
    case = _case()
    validate_review(_review(case), expected_case=case)
    for key, value in (
        ("reviewer_id", ""),
        ("reviewed_at", "2026-11-01T10:00:00"),
        ("applicable_iou_thresholds", []),
        ("corrected_label_reason", ""),
    ):
        row = _review(case)
        row[key] = value
        with pytest.raises(ValueError):
            validate_review(row, expected_case=case)


def test_duplicate_reviewer_is_rejected_and_independent_disagreement_is_retained():
    case = _case()
    review = _review(case)
    with pytest.raises(ValueError, match="at most one"):
        validate_adjudications([case], [review, review])
    other = _review(case, reviewer="reviewer-b", label="visually_supported_negative")
    result = validate_adjudications([case], [review, other], statistical_case_ids=[case["case_id"]])
    assert result["double_review_disagreement_count"] == 1
    assert result["visual_label_reliability_established"] is False


def test_omission_rate_uses_statistical_sample_not_targeted_queue():
    cases = [_case(0), _case(1)]
    reviews = [_review(cases[0]), _review(cases[1], label="visually_supported_negative")]
    result = validate_adjudications(cases, reviews, statistical_case_ids=[cases[1]["case_id"]])
    assert result["suspected_omission_rate"] == 0
    assert result["targeted_queue_excluded_from_prevalence_estimate"]


def test_source_group_sampling_is_reproducible_and_cohort_stratified():
    cases = []
    for cohort in (PILOT, EXPANSION):
        cases.extend(_case(i, cohort=cohort) for i in range(28))
    one = statistical_quality_sample(cases, seed=17, pilot_groups=5, expansion_groups=6)
    two = statistical_quality_sample(cases, seed=17, pilot_groups=5, expansion_groups=6)
    assert one == two
    assert one["source_group_count"] == 11
    assert set(one["group_inclusion_probabilities"]) == {PILOT, EXPANSION}
    assert one["sampling_frame"].startswith("candidate-bearing")


def test_statistical_and_targeted_sets_have_distinct_inference_semantics():
    cases = [_case(i, cohort=PILOT if i < 14 else EXPANSION) for i in range(28)]
    targeted = targeted_failure_sample(cases)
    assert targeted["prevalence_estimation_permitted"] is False
    assert targeted["inclusion_probability"] is None
    assert all("high_score_invalid_at_iou_0_50" in reasons for reasons in targeted["selection_reasons"].values())


def test_review_cases_are_fit_only_and_frozen_by_hash():
    case = _case()
    assert validate_case(case)["source_image_sha256"] == "a" * 64
    case["partition"] = "calibration_validation"
    with pytest.raises(ValueError, match="calibration_fit"):
        validate_case(case)


def test_runtime_geometry_score_area_and_rank_features_are_exact():
    features = extract_runtime_features(_pair(), _context())
    assert features["schema_version"] == FEATURE_VERSION
    assert features["root_box_iou"] == pytest.approx(18 * 18 / (400 + 400 - 18 * 18))
    assert features["score_difference"] == pytest.approx(.1)
    assert features["absolute_score_difference"] == pytest.approx(.1)
    assert features["log_area_ratio"] == pytest.approx(0)
    assert features["focused_detector_rank"] == 1
    assert features["proposal_count_change"] == -1


@pytest.mark.parametrize(
    ("category", "ambiguous", "no_alignment"),
    [("ambiguous_target_association", True, False), ("no_target_aligned_proposal", False, True)],
)
def test_ambiguous_and_successful_empty_focus_are_explicit(category, ambiguous, no_alignment):
    features = extract_runtime_features(_pair(category), _context())
    assert features["association_is_ambiguous"] is ambiguous
    assert features["no_alignment"] is no_alignment
    if no_alignment:
        assert features["focused_score"] is None
        assert features["root_box_iou"] is None


def test_mask_geometry_is_honestly_unavailable():
    features = extract_runtime_features(_pair(), _context())
    assert features["mask_geometry_available"] is False
    assert features["mask_geometry_iou"] is None
    assert "not_implemented" in features["mask_unavailable_reason"]


def test_runtime_extractor_rejects_ground_truth_and_offline_fields():
    context = _context()
    context["H_annotation"] = "positive"
    with pytest.raises(ValueError, match="offline-only"):
        extract_runtime_features(_pair(), context)
    pair = _pair()
    pair["official_tp"] = True
    with pytest.raises(ValueError, match="offline-only"):
        extract_runtime_features(pair, _context())


def test_offline_labels_are_joined_only_after_runtime_projection():
    pair = _labeled_pair(positive=True)
    runtime = runtime_projection(pair)
    assert not {"original_labels", "focused_aligned_labels", "same_assigned_gt"} & set(runtime)
    features = extract_runtime_features(runtime, _context())
    joined = join_offline_labels(features, pair)
    assert "H_annotation" not in joined["runtime_features"]
    assert joined["offline_outcomes"]["H_annotation"]["0.5"] == "positive"


def test_no_future_branch_label_leaks_into_runtime_vector():
    pair = _labeled_pair(positive=True)
    before = extract_runtime_features(runtime_projection(pair), _context())
    pair["original_labels"][0]["official_tp"] = False
    pair["same_assigned_gt"]["0.5"] = False
    after = extract_runtime_features(runtime_projection(pair), _context())
    assert before == after


def test_diagnostics_preserve_source_clusters_cohorts_and_missing_categories():
    positive = _labeled_pair(positive=True)
    negative = _labeled_pair("no_target_aligned_proposal", positive=False)
    rows = [
        join_offline_labels(extract_runtime_features(runtime_projection(pair), _context()), pair)
        for pair in (positive, negative)
    ]
    report = build_diagnostics({"pilot": rows, "expansion": rows})
    assert set(report["cohorts"]) == {"pilot", "expansion"}
    assert report["cohorts"]["pilot"]["source_group_count"] == 1
    assert report["cohorts"]["pilot"]["no_alignment_cases_retained"] == 1
    assert report["separability_assessment"]["statistical_significance_claimed"] is False


def test_restricted_model_is_unfitted_grouped_and_keeps_holdouts_locked():
    spec = phase4c_model_specification()
    assert spec["status"] == "SPECIFICATION_ONLY_NOT_FITTED"
    assert spec["sampling_unit"] == "source_group_id"
    assert spec["bayes_update"]["executed_in_phase04b2b4"] is False
    assert "remain locked" in spec["evaluation_plan"]["internal_test"]
    assert spec["label_endpoints"]["unresolved_visual_labels_are_not_coerced"]


def test_repeat_is_costed_but_not_treated_as_independent_evidence():
    spec = phase4c_model_specification()
    assert spec["planning_link"]["logical_costs"]["repeat_grounding"] == 1
    report = json.loads(
        (ROOT / "outputs/bite/phase04b2b4/diagnostics/conditional_evidence_summary.json").read_text()
    )
    assert report["dependence"]["repeat_outputs_are_not_independent_evidence"]


def test_readiness_refuses_zoom_and_general_models_with_pending_reviews():
    diagnostics = {
        "cohorts": {
            "expansion": {
                "candidate_count": 203,
                "class_support": {"fish": {"positive": 9}, "jellyfish": {"negative": 29}},
            }
        }
    }
    result = assess_readiness(
        integrity={"historical_valid": True, "expansion_valid": True},
        review_validation={
            "reviewed_case_count": 0,
            "completed_human_judgments": 0,
            "suspected_omission_rate": None,
            "double_reviewed_case_count": 0,
            "double_review_agreement_count": 0,
            "visual_label_reliability_established": False,
        },
        diagnostics=diagnostics,
        support_summary={"schema_version": "test"},
    )
    assert result["label_readiness"]["status"] == "PENDING_HUMAN_ADJUDICATION"
    assert result["model_readiness"]["restricted_pooled_zoom_outcome_model"].startswith("REQUIRES")
    assert result["model_readiness"]["general_class_conditional_model"] == "NOT_READY"
    assert result["model_readiness"]["formal_identifiability_certificate"] == "NOT_READY"


def test_real_phase_outputs_preserve_counts_designs_and_honest_pending_status():
    output = ROOT / "outputs/bite/phase04b2b4"
    cases = [json.loads(line) for line in (output / "review_interface/review_cases.jsonl").read_text().splitlines()]
    sampling = json.loads((output / "review_sampling/review_sampling_summary.json").read_text())
    validation = json.loads((output / "validation/human_adjudication_validation.json").read_text())
    assert len(cases) == 241
    assert {case["cohort_id"] for case in cases} == {PILOT, EXPANSION}
    assert sum(case["H_annotation"]["0.5"] == "positive" for case in cases) == 35
    assert sampling["statistical"]["case_count"] == 120
    assert sampling["targeted"]["prevalence_estimation_permitted"] is False
    assert validation["completed_human_judgments"] == 0
    assert validation["suspected_omission_rate"] is None


def test_generated_runtime_feature_files_contain_no_gt_keys():
    output = ROOT / "outputs/bite/phase04b2b4/conditional_features"
    for name, expected in (("pilot_runtime_features.jsonl", 38), ("expansion_runtime_features.jsonl", 203)):
        rows = [json.loads(line) for line in (output / name).read_text().splitlines()]
        assert len(rows) == expected
        text = json.dumps(rows).lower()
        assert "official_tp" not in text
        assert "h_annotation" not in text
        assert "ground_truth" not in text


def test_feature_values_are_finite_or_explicitly_missing():
    row = extract_runtime_features(_pair(), _context())
    for key in ("root_box_iou", "normalized_center_displacement", "log_area_ratio", "score_difference"):
        assert row[key] is None or math.isfinite(row[key])
