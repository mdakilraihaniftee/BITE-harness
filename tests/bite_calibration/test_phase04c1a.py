import json
import math
from copy import deepcopy
from pathlib import Path

import pytest

from evaluation_kit.bite_calibration.blind_review import (
    BLIND_EVENT_VERSION,
    BLIND_PROTOCOL_VERSION,
    append_event,
    candidate_digest,
    load_event_chain,
    validate_blind_first_pass,
    validate_post_reveal_event,
    validate_reveal_event,
)
from evaluation_kit.bite_calibration.calibration_metrics import (
    calibration_metrics,
    reliability_summary,
)
from evaluation_kit.bite_calibration.grouped_crossfit import crossfit, make_group_folds
from evaluation_kit.bite_calibration.grouped_uncertainty import grouped_bootstrap
from evaluation_kit.bite_calibration.prior_model import (
    fit_constant,
    fit_logistic,
    predict,
)
from evaluation_kit.bite_calibration.proxy_calibration import (
    load_proxy_records,
    validate_prediction_artifacts,
)
from evaluation_kit.bite_calibration.validation_protocol import (
    build_validation_protocol,
    validate_validation_protocol,
)
from evaluation_kit.bite_calibration.visual_endpoint import (
    VISUAL_ENDPOINT_VERSION,
    validate_reference_box,
    visual_endpoint,
)

ROOT = Path(__file__).resolve().parents[2]


def _case():
    return {
        "case_id": "case:1",
        "source_group_id": "group:1",
        "initial_candidate_id": "candidate:1",
        "source_image_sha256": "a" * 64,
        "annotation_sha256": "b" * 64,
        "initial_box_root_xyxy": [10, 20, 40, 60],
        "image_width": 100,
        "image_height": 80,
    }


def _controls(value="yes"):
    return {
        "object_present_in_proposed_region": value,
        "class_appears_correct": value,
        "box_reasonably_localizes_object": value,
        "relevant_annotation_appears_missing": "no",
        "nearby_competing_instance": "no",
        "image_evidence_inconclusive": "no",
    }


def _event(event_type="blind_first_pass_submitted", timestamp="2026-11-01T09:00:00-04:00"):
    case = _case()
    return {
        "schema_version": BLIND_EVENT_VERSION,
        "event_type": event_type,
        "protocol_version": BLIND_PROTOCOL_VERSION,
        "case_id": case["case_id"],
        "reviewer_id": "human-a",
        "reviewer_type": "human",
        "submitted_at": timestamp,
        "source_group_id": case["source_group_id"],
        "initial_candidate_id": case["initial_candidate_id"],
        "source_image_sha256": case["source_image_sha256"],
        "annotation_sha256": case["annotation_sha256"],
        "candidate_digest": candidate_digest(case),
        "visual_plausibility": "supported",
        "visual_localization": "adequate",
        "ambiguity_controls": {
            "class_identity_ambiguous": "no",
            "localization_ambiguous": "no",
            "insufficient_image_evidence": "no",
        },
        "legacy_evidence_controls": _controls(),
        "reference_boxes": [],
    }


def _records(groups=9):
    rows = []
    for group in range(groups):
        for index in range(3):
            label = int(index == 0 and group % 2 == 0)
            rows.append({
                "partition": "calibration_fit",
                "cohort_name": "synthetic",
                "cohort_id": "cohort",
                "query_design_id": "design",
                "state_id": f"state:{group}:{index}",
                "candidate_id": f"candidate:{group}:{index}",
                "source_group_id": f"group:{group}",
                "query": "fish" if index % 2 else "shark",
                "candidate_size": "small" if index == 0 else "medium",
                "initial_score": .8 if label else .2 + index / 10,
                "original_relative_area": .02 + .01 * index,
                "label": label,
                "endpoint": "H_annotation_0.5",
                "annotation_scope_audit": "audit_only",
                "predictive_feature_names": ["initial_score", "original_relative_area"],
            })
    return rows


def test_blind_first_pass_is_validated_and_keeps_visual_endpoint_separate():
    event = validate_blind_first_pass(_event(), _case())
    assert event["derived_visual_endpoint"]["schema_version"] == VISUAL_ENDPOINT_VERSION
    assert event["derived_visual_endpoint"]["binary_visual_endpoint"] == 1
    assert event["derived_visual_endpoint"]["threshold_specific_corrected_visual_labels"] == {
        "0.5": "unknown", "0.75": "unknown",
    }


def test_blind_event_rejects_source_annotation_and_candidate_mismatch():
    for key, value in (
        ("source_image_sha256", "c" * 64),
        ("annotation_sha256", "c" * 64),
        ("candidate_digest", "c" * 64),
        ("initial_candidate_id", "candidate:other"),
    ):
        event = _event()
        event[key] = value
        with pytest.raises(ValueError):
            validate_blind_first_pass(event, _case())


def test_reveal_requires_blind_event_and_cannot_precede_it():
    first = validate_blind_first_pass(_event(), _case())
    reveal = _event("gt_revealed", "2026-11-01T08:59:00-04:00")
    reveal["blind_event_identity"] = first["event_identity"]
    with pytest.raises(ValueError, match="precede"):
        validate_reveal_event(reveal, _case(), first)


def test_append_only_chain_prevents_blind_overwrite_and_out_of_order_reveal(tmp_path):
    with pytest.raises(ValueError, match="before reveal"):
        append_event(tmp_path, _case(), _event("gt_revealed"))
    append_event(tmp_path, _case(), _event())
    with pytest.raises(ValueError, match="immutable"):
        append_event(tmp_path, _case(), _event())
    chain = load_event_chain(tmp_path, _case(), "human-a")
    assert chain["first_pass"] is not None and chain["reveal"] is None


def test_post_reveal_change_is_separate_and_requires_reason():
    first = validate_blind_first_pass(_event(), _case())
    reveal = _event("gt_revealed", "2026-11-01T09:01:00-04:00")
    reveal["blind_event_identity"] = first["event_identity"]
    reveal = validate_reveal_event(reveal, _case(), first)
    post = _event("post_reveal_judgment", "2026-11-01T09:02:00-04:00")
    post["visual_plausibility"] = "unsupported"
    post["legacy_evidence_controls"] = _controls("no")
    post["reason_for_change"] = ""
    with pytest.raises(ValueError, match="reason"):
        validate_post_reveal_event(post, _case(), first, reveal)
    post["reason_for_change"] = "GT reveal changed interpretation"
    validated = validate_post_reveal_event(post, _case(), first, reveal)
    assert validated["changed_from_blind"]
    assert first["visual_plausibility"] == "supported"


def test_reference_box_is_optional_research_geometry_not_authoritative_gt():
    box = {
        "pixel_xyxy": [1, 2, 20, 30], "image_width": 100, "image_height": 80,
        "object_class": "fish", "object_identity_note": "left fish", "occluded": False,
        "truncated": True, "reviewer_id": "human-a", "created_at": "2026-11-01T09:00:00Z",
    }
    validate_reference_box(box, width=100, height=80)
    endpoint = visual_endpoint(
        plausibility="supported", localization="adequate",
        ambiguity_controls={
            "class_identity_ambiguous": "no", "localization_ambiguous": "no",
            "insufficient_image_evidence": "no",
        }, reference_boxes=[box],
    )
    assert endpoint["single_reference_box_is_authoritative_gt"] is False
    assert endpoint["subjective_localization_converted_to_iou"] is False


def test_reference_box_rejects_invalid_or_out_of_frame_coordinates():
    with pytest.raises(ValueError):
        validate_reference_box({"pixel_xyxy": [10, 10, 101, 20]}, width=100, height=80)


def test_constant_prevalence_uses_frozen_beta_smoothing():
    model = fit_constant([1, 0, 0])
    assert model["probability"] == pytest.approx(2 / 5)
    assert predict(model, [{}, {}])[0]["probability"] == pytest.approx(2 / 5)


def test_logistic_requires_both_training_classes():
    with pytest.raises(ValueError, match="both target classes"):
        fit_logistic(_records()[:2], [0, 0], "score_only_logistic")


@pytest.mark.parametrize("model_name", ["score_only_logistic", "compact_initial_logistic"])
def test_logistic_predictions_are_bounded_and_training_preprocessing_is_frozen(model_name):
    rows = _records()
    model = fit_logistic(rows, [row["label"] for row in rows], model_name)
    outputs = predict(model, rows)
    assert model["preprocessing"]["fit_on_training_fold_only"]
    assert model["regularization"]["lambda"] == 1.0
    assert all(output["supported"] and 0 <= output["probability"] <= 1 for output in outputs)


def test_missing_initial_features_return_explicit_unsupported_prediction():
    rows = _records()
    model = fit_logistic(rows, [row["label"] for row in rows], "compact_initial_logistic")
    bad = deepcopy(rows[0])
    bad["original_relative_area"] = None
    output = predict(model, [bad])[0]
    assert not output["supported"]
    assert output["probability"] is None


def test_brier_logloss_decision_error_and_reliability_bins():
    metrics = calibration_metrics([0, 1], [.25, .75])
    assert metrics["brier_score"] == pytest.approx(.0625)
    assert metrics["log_loss"] == pytest.approx(-math.log(.75))
    assert metrics["decision_error"] == 0
    bins = reliability_summary([0, 1], [.25, 1.0])
    assert sum(row["count"] for row in bins) == 2
    assert bins[-1]["right_inclusive"]


def test_group_folds_are_deterministic_disjoint_and_balanced_for_positive_groups():
    rows = _records()
    one = make_group_folds(rows)
    two = make_group_folds(rows)
    assert one == two
    assert len(set().union(*map(set, one))) == 9
    assert not any(set(one[i]) & set(one[j]) for i in range(3) for j in range(i + 1, 3))


def test_crossfit_uses_one_fold_per_group_and_train_fold_preprocessing():
    result = crossfit(_records())
    assert len(result["predictions"]) == len(_records()) * 3
    for fold in result["folds"]:
        assert not set(fold["training_groups"]) & set(fold["evaluation_groups"])
        assert fold["training_positive_count"] > 0
    means = [
        tuple(row["model"]["preprocessing"]["mean"])
        for row in result["fitted_models"] if row["model_name"] == "compact_initial_logistic"
    ]
    assert len(means) == 3


def test_group_bootstrap_resamples_groups_and_reports_unsupported_replicates():
    predictions = []
    for group, label in (("g1", 1), ("g2", 0), ("g3", 0)):
        predictions.append({"source_group_id": group, "label": label, "probability": .5})
    result = grouped_bootstrap(predictions, replicates=100, seed=1)
    assert result["unique_group_count"] == 3
    assert result["positive_bearing_group_count"] == 1
    assert result["invalid_single_class_replicates"] > 0
    assert result["refit_inside_bootstrap"] is False


def test_real_proxy_records_are_fit_only_and_exclude_future_evidence():
    rows = load_proxy_records(
        ROOT / "outputs/bite/phase04b2b4/diagnostics/expansion_paired_diagnostics.jsonl",
        ROOT / "outputs/bite/phase04b2b4/review_interface/review_cases.jsonl",
        endpoint="0.5", cohort_name="expansion",
    )
    assert len(rows) == 203
    assert {row["partition"] for row in rows} == {"calibration_fit"}
    text = json.dumps(rows).lower()
    for forbidden in ("focused_score", "root_box_iou", "score_difference", "root_image_sha256"):
        assert forbidden not in text


def test_real_crossfit_artifact_is_annotation_proxy_only_and_group_disjoint():
    experiment = json.loads(
        (ROOT / "outputs/bite/phase04c1a/crossfit/expansion_iou_0_5_summary.json").read_text()
    )
    assert experiment["status"] == "ANNOTATION_PROXY_EXPLORATORY"
    assert experiment["zoom_likelihood_fitted"] is False
    assert experiment["posterior_update_executed"] is False
    assert validate_prediction_artifacts({
        **experiment,
        "predictions": [json.loads(line) for line in (
            ROOT / "outputs/bite/phase04c1a/crossfit/expansion_iou_0_5_predictions.jsonl"
        ).read_text().splitlines()],
    })


def test_cohorts_and_annotation_thresholds_have_separate_artifacts():
    summary = json.loads(
        (ROOT / "outputs/bite/phase04c1a/proxy_models/prior_experiment_summary.json").read_text()
    )
    assert set(summary["experiments"]) == {
        "expansion_iou_0_5", "expansion_iou_0_75",
        "pilot_sensitivity_iou_0_5", "pilot_sensitivity_iou_0_75",
    }
    assert summary["primary_cohort"] == "expansion"
    assert summary["calibration_validation_accessed"] is False
    assert summary["internal_test_accessed"] is False


def test_high_score_annotation_negatives_do_not_receive_forced_near_one_probabilities():
    summary = json.loads(
        (ROOT / "outputs/bite/phase04c1a/proxy_models/prior_experiment_summary.json").read_text()
    )
    audit = summary["experiments"]["expansion_iou_0_5"]["support_audit"]
    assert audit["high_score_annotation_negative_count"] == 27
    assert audit["high_score_annotation_negative_model_probabilities"][
        "score_only_logistic"
    ]["maximum_probability"] < 1


def test_validation_protocol_uses_metadata_only_all_validation_groups_and_no_test():
    protocol = validate_validation_protocol(build_validation_protocol(
        ROOT / "outputs/bite/phase04b2b1a/manifests/calibration_partition_manifest.json",
    ))
    assert protocol["selection"]["group_count"] == 72
    assert protocol["query_design"]["maximum_query_states"] == 504
    assert protocol["action_policy"]["maximum_logical_dispatches"] == 1512
    assert protocol["source"]["validation_images_loaded"] is False
    assert protocol["source"]["validation_annotations_loaded"] is False
    assert protocol["source"]["internal_test_accessed"] is False
    assert protocol["execution"]["observed_dispatches"] == 0


def test_validation_policy_has_no_repeat_and_caps_candidate_path_at_three_calls():
    protocol = json.loads((
        ROOT / "outputs/bite/phase04c1a/validation_protocol/task_v_validation_collection_v1.json"
    ).read_text())
    assert protocol["action_policy"]["routine_exact_repeat"] is False
    assert protocol["action_policy"]["maximum_public_calls_per_candidate_present_state"] == 3
    assert protocol["action_policy"]["raw_before_label_persistence"]


def test_human_review_progress_remains_pending_and_unfabricated():
    progress = json.loads((
        ROOT / "outputs/bite/phase04c1a/review_validation/adjudication_progress.json"
    ).read_text())
    assert progress["completed_human_judgment_count"] == 0
    assert progress["human_review_status"] == "PENDING"
    assert progress["annotation_omission_prevalence_estimated"] is False
    assert progress["reviewer_agreement_reported"] is False
    assert progress["fake_human_reviews_created"] is False


def test_prior_modules_are_not_imported_by_agent_or_official_evaluator():
    sources = [
        ROOT / "openvlharness/agent/agent.py",
        ROOT / "evaluation_kit/runner.py",
        ROOT / "evaluation_kit/cli.py",
    ]
    text = "\n".join(path.read_text() for path in sources)
    assert "prior_model" not in text
    assert "proxy_calibration" not in text
    assert "grouped_crossfit" not in text
