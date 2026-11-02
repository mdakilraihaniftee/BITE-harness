import json
from copy import deepcopy
from itertools import pairwise
from pathlib import Path

import pytest

from evaluation_kit.bite_calibration.blind_review import (
    BLIND_EVENT_VERSION,
    BLIND_PROTOCOL_VERSION_V3,
    candidate_digest,
    validate_blind_first_pass,
)
from evaluation_kit.bite_calibration.grouped_label_sensitivity import (
    exact_combined_bounds,
    exact_group_budget_bounds,
)
from evaluation_kit.bite_calibration.label_sensitivity import (
    brier_difference,
    brute_force_bounds,
    exact_cardinality_bounds,
    flip_effect,
    minimal_ranking_reversal,
    with_group_balanced_weights,
)
from evaluation_kit.bite_calibration.paired_model_comparison import (
    align_predictions,
    load_frozen_predictions,
    paired_difference,
    paired_group_bootstrap,
    reproduce_metrics,
)
from evaluation_kit.bite_calibration.review_progress import (
    build_second_review_sample,
    load_review_inputs,
    review_progress,
)
from evaluation_kit.bite_calibration.validation_readiness import preflight_validation
from evaluation_kit.bite_calibration.visual_endpoint import (
    VISUAL_ENDPOINT_VERSION,
    VISUAL_VERIFICATION_VERSION,
    visual_endpoint,
    visual_verification_v2,
)

ROOT = Path(__file__).resolve().parents[2]


def _aligned():
    return [
        {"state_id": "a", "candidate_id": "ca", "source_group_id": "g1", "fold_index": 0,
         "label": 0, "query": "fish", "annotation_scope_audit": "no_annotated_queried_class_instance",
         "probabilities": {"constant_prevalence": .2, "score_only_logistic": .8,
                           "compact_initial_logistic": .7}},
        {"state_id": "b", "candidate_id": "cb", "source_group_id": "g1", "fold_index": 0,
         "label": 1, "query": "fish", "annotation_scope_audit": "annotated_or_other_diagnostic",
         "probabilities": {"constant_prevalence": .3, "score_only_logistic": .7,
                           "compact_initial_logistic": .6}},
        {"state_id": "c", "candidate_id": "cc", "source_group_id": "g2", "fold_index": 1,
         "label": 0, "query": "shark", "annotation_scope_audit": "no_annotated_queried_class_instance",
         "probabilities": {"constant_prevalence": .4, "score_only_logistic": .1,
                           "compact_initial_logistic": .2}},
    ]


def _case():
    return {
        "case_id": "case", "source_group_id": "g", "initial_candidate_id": "candidate",
        "source_image_sha256": "a" * 64, "annotation_sha256": "b" * 64,
        "initial_box_root_xyxy": [1, 2, 10, 20], "image_width": 30, "image_height": 40,
    }


def _v3_event():
    case = _case()
    return {
        "schema_version": BLIND_EVENT_VERSION, "event_type": "blind_first_pass_submitted",
        "protocol_version": BLIND_PROTOCOL_VERSION_V3, "case_id": case["case_id"],
        "reviewer_id": "researcher", "reviewer_type": "human",
        "submitted_at": "2026-11-01T12:00:00Z", "source_group_id": case["source_group_id"],
        "initial_candidate_id": case["initial_candidate_id"],
        "source_image_sha256": case["source_image_sha256"],
        "annotation_sha256": case["annotation_sha256"], "candidate_digest": candidate_digest(case),
        "visual_verification": {
            "object_presence": "supported", "class_correctness": "supported",
            "localization_adequacy": "inadequate", "evidence_ambiguous": False,
            "localization_evidence_insufficient": False,
        },
        "legacy_evidence_controls": {
            "object_present_in_proposed_region": "yes", "class_appears_correct": "yes",
            "box_reasonably_localizes_object": "no", "relevant_annotation_appears_missing": "no",
            "nearby_competing_instance": "no", "image_evidence_inconclusive": "no",
        },
        "reference_boxes": [],
    }


def test_signed_paired_brier_difference():
    observed = paired_difference(_aligned(), "score_only_logistic", "constant_prevalence", "brier_score")
    expected = sum(
        brier_difference(r["label"], r["probabilities"]["score_only_logistic"],
                         r["probabilities"]["constant_prevalence"])
        for r in _aligned()
    ) / 3
    assert observed == pytest.approx(expected)


def test_paired_logloss_and_error_differences_have_declared_sign():
    for metric in ("log_loss", "decision_error"):
        assert isinstance(paired_difference(
            _aligned(), "score_only_logistic", "constant_prevalence", metric,
        ), float)


def test_alignment_rejects_missing_model_and_duplicate_prediction():
    rows = []
    for model, probability in (("constant_prevalence", .2), ("score_only_logistic", .3)):
        rows.append({"state_id": "x", "model_name": model, "probability": probability,
                     "label": 0, "source_group_id": "g", "fold_index": 0})
    with pytest.raises(ValueError, match="all frozen"):
        align_predictions(rows)
    rows.append(deepcopy(rows[0]))
    with pytest.raises(ValueError, match="unique"):
        align_predictions(rows)


def test_alignment_rejects_group_crossing_folds():
    rows = []
    for state, fold in (("a", 0), ("b", 1)):
        for model in ("constant_prevalence", "score_only_logistic", "compact_initial_logistic"):
            rows.append({"state_id": state, "model_name": model, "probability": .2,
                         "label": 0, "source_group_id": "same", "fold_index": fold})
    with pytest.raises(ValueError, match="cross"):
        align_predictions(rows)


def test_paired_group_bootstrap_is_deterministic_and_not_row_iid():
    one = paired_group_bootstrap(_aligned(), replicates=100, seed=9)
    two = paired_group_bootstrap(_aligned(), replicates=100, seed=9)
    assert one == two
    assert one["same_group_draw_used_for_every_model_pair"]
    assert one["candidate_rows_resampled_iid"] is False
    assert one["refit_inside_bootstrap"] is False


def test_real_frozen_metrics_reproduce_exactly_and_cohorts_stay_separate():
    summary = json.loads((ROOT / "outputs/bite/phase04c1a/proxy_models/prior_experiment_summary.json").read_text())
    for experiment, frozen in summary["experiments"].items():
        _, aligned = load_frozen_predictions(
            ROOT / f"outputs/bite/phase04c1a/crossfit/{experiment}_predictions.jsonl",
        )
        report = reproduce_metrics(aligned, frozen)
        assert report["all_metrics_match"]
        assert {row["cohort_name"] for row in aligned} == {frozen["cohort"]}


@pytest.mark.parametrize("label", [0, 1])
def test_brier_flip_identity_for_positive_and_negative(label):
    p_model, p_base = .8, .2
    direct = brier_difference(1 - label, p_model, p_base) - brier_difference(
        label, p_model, p_base,
    )
    assert flip_effect(label, p_model, p_base) == pytest.approx(direct)


@pytest.mark.parametrize("budget", [0, 1, 2, 99])
def test_exact_cardinality_extrema_match_bruteforce(budget):
    exact = exact_cardinality_bounds(
        _aligned(), "score_only_logistic", "constant_prevalence", budget=budget,
    )
    brute = brute_force_bounds(
        _aligned(), "score_only_logistic", "constant_prevalence", budget=budget,
    )
    assert (exact["minimum_difference"], exact["maximum_difference"]) == pytest.approx(brute)


def test_empty_uncertainty_set_and_budget_zero_leave_difference_unchanged():
    none = exact_cardinality_bounds(
        _aligned(), "score_only_logistic", "constant_prevalence",
        eligible=lambda _: False, budget=20,
    )
    zero = exact_cardinality_bounds(
        _aligned(), "score_only_logistic", "constant_prevalence", budget=0,
    )
    assert none["eligible_count"] == 0
    assert none["minimum_difference"] == none["maximum_difference"]
    assert zero["minimum_difference"] == zero["maximum_difference"]


def test_sensitivity_bounds_widen_monotonically():
    bounds = [exact_cardinality_bounds(
        _aligned(), "score_only_logistic", "constant_prevalence", budget=b,
    ) for b in range(4)]
    assert all(a["minimum_difference"] >= b["minimum_difference"] for a, b in pairwise(bounds))
    assert all(a["maximum_difference"] <= b["maximum_difference"] for a, b in pairwise(bounds))


def test_minimal_ranking_reversal_is_exact():
    result = minimal_ranking_reversal(
        _aligned(), "score_only_logistic", "constant_prevalence",
    )
    if result["possible"] and result["minimum_flips"]:
        smaller = exact_cardinality_bounds(
            _aligned(), "score_only_logistic", "constant_prevalence",
            budget=result["minimum_flips"] - 1,
        )
        observed = smaller["observed_difference"]
        assert not smaller["includes_zero"] or observed == 0


def test_group_balanced_weights_equalize_total_group_mass():
    weighted = with_group_balanced_weights(_aligned())
    totals = {}
    for row in weighted:
        totals[row["source_group_id"]] = totals.get(row["source_group_id"], 0) + row["weight"]
    assert totals == pytest.approx({"g1": 1, "g2": 1})
    exact_cardinality_bounds(weighted, "score_only_logistic", "constant_prevalence", budget=1)


def test_group_budget_selects_whole_dependency_groups_exactly():
    result = exact_group_budget_bounds(
        _aligned(), "score_only_logistic", "constant_prevalence", group_budget=1,
    )
    assert len(result["minimum_selected_groups"]) <= 1
    assert len(result["maximum_selected_groups"]) <= 1


def test_combined_group_candidate_dp_respects_both_caps():
    result = exact_combined_bounds(
        _aligned(), "score_only_logistic", "constant_prevalence",
        candidate_budget=1, group_budget=1,
    )
    assert len(result["minimum_selected_state_ids"]) <= 1
    assert len(result["maximum_selected_groups"]) <= 1
    assert result["heuristic"] is False


def test_visual_v2_marks_decisive_wrong_localization_negative():
    result = visual_verification_v2(
        object_presence="supported", class_correctness="supported",
        localization_adequacy="inadequate", evidence_ambiguous=False,
        localization_evidence_insufficient=False,
    )
    assert result["schema_version"] == VISUAL_VERIFICATION_VERSION
    assert result["binary_visual_endpoint"] == 0
    assert result["subjective_localization_converted_to_iou"] is False


def test_visual_v2_keeps_ambiguous_or_insufficient_localization_unknown():
    for location, insufficient in (("ambiguous", False), ("inadequate", True)):
        result = visual_verification_v2(
            object_presence="supported", class_correctness="supported",
            localization_adequacy=location, evidence_ambiguous=False,
            localization_evidence_insufficient=insufficient,
        )
        assert result["binary_visual_endpoint"] is None


def test_visual_v1_history_is_unchanged():
    result = visual_endpoint(
        plausibility="supported", localization="inadequate",
        ambiguity_controls={
            "class_identity_ambiguous": "no", "localization_ambiguous": "no",
            "insufficient_image_evidence": "no",
        },
    )
    assert result["schema_version"] == VISUAL_ENDPOINT_VERSION
    assert result["binary_visual_endpoint"] is None


def test_blind_protocol_v3_derives_wrong_localization_without_reveal():
    result = validate_blind_first_pass(_v3_event(), _case())
    assert result["derived_visual_endpoint"]["binary_visual_endpoint"] == 0
    assert "initial_score" not in result
    assert "H_annotation" not in result


def test_review_progress_preserves_set_separation_and_no_fabrication():
    cases, statistical, targeted, completed = load_review_inputs(ROOT)
    second = build_second_review_sample(cases, statistical)
    progress = review_progress(cases, statistical, targeted, completed,
                               second_review_sample=second)
    assert progress["set_a"]["total"] == 120
    assert progress["set_b"]["total"] == 228
    expected_pairs = {(row["case_id"], row["reviewer_id"]) for row in completed}
    assert progress["genuine_completed_review_count"] == len(expected_pairs)
    assert progress["fake_human_reviews_created"] is False
    assert progress["visual_label_reliability"] == (
        "REQUIRES_ANALYSIS" if expected_pairs else "UNKNOWN"
    )


def test_second_review_sample_is_group_aware_deterministic_and_blind():
    cases, statistical, _, _ = load_review_inputs(ROOT)
    one = build_second_review_sample(cases, statistical)
    two = build_second_review_sample(cases, statistical)
    assert one == two
    assert one["source_group_count"] == 5
    assert one["second_reviewer_blinded_to_first_reviewer"]
    assert set(one["case_ids"]) <= set(statistical["case_ids"])


def test_validation_preflight_is_gt_free_disjoint_and_unexecuted():
    result = preflight_validation(
        ROOT / "outputs/bite/phase04c1a/validation_protocol/task_v_validation_collection_v1.json",
        ROOT / "outputs/bite/phase04b2b1a/manifests/calibration_partition_manifest.json",
        ROOT / "outputs/bite/phase04b2b1a/manifests/development_debug_exclusions.json",
        ROOT / "outputs/bite/phase04c1a/implementation_manifest.json",
        ROOT / "outputs/bite/reference_baseline/attempt_20261029T210515Z/checkpoint_refs.json",
        ROOT / "outputs/bite/phase04b2b3/preflight/preflight_report.json",
    )
    assert result["source_and_split"]["validation_group_count"] == 72
    assert not any(result["source_and_split"]["cross_partition_group_overlaps"].values())
    assert result["source_and_split"]["validation_labels_or_outcomes_accessed"] is False
    assert result["authorization"]["network_inference_calls"] == 0
    assert result["authorization"]["new_inference_authorized"] is False
    assert result["checkpoint_provenance"]["checkpoint_verified_by_worker"] is False


def test_frozen_validation_model_schema_and_internal_test_lock():
    result = json.loads((ROOT / "outputs/bite/phase04c1b/validation_preflight/preflight.json").read_text())
    assert result["frozen_model_evaluation"]["features"]["score_only_logistic"] == ["initial_score"]
    assert result["frozen_model_evaluation"]["l2_lambda"] == 1.0
    assert result["source_and_split"]["internal_test_accessed"] is False


def test_phase04c1a_immutable_artifacts_remain_verified():
    result = json.loads((ROOT / "outputs/bite/phase04c1b/integrity/phase04c1a_verification.json").read_text())
    assert result["immutable_references_all_valid"]
    assert result["historical_artifacts_rewritten"] is False


def test_new_offline_modules_are_not_imported_by_agent_or_evaluator():
    names = ("paired_model_comparison", "label_sensitivity", "validation_readiness")
    text = "\n".join((ROOT / path).read_text() for path in (
        "openvlharness/agent/agent.py", "evaluation_kit/runner.py", "evaluation_kit/cli.py",
    ))
    assert not any(name in text for name in names)
