import hashlib
import json
import uuid
from copy import deepcopy
from pathlib import Path

import pytest

from evaluation_kit.bite_calibration.matched_worker_bridge import build_bridge_protocol
from evaluation_kit.bite_calibration.paired_zoom_evaluation import (
    align_predictions,
    evaluate_predictions,
    paired_difference,
    paired_group_bootstrap,
)
from evaluation_kit.bite_calibration.sam3_attested_worker import (
    prepare_attested_worker,
    validate_initialization_event,
    validate_revision,
)
from evaluation_kit.bite_calibration.zoom_action_cost_analysis import analyze_cost_risk
from evaluation_kit.bite_calibration.zoom_conditional_protocol import (
    freeze_runtime_rows,
    join_frozen_target,
    read_jsonl,
    runtime_integrity_report,
    validate_paired_labels,
    validate_runtime_row,
)
from evaluation_kit.bite_calibration.zoom_evidence_readiness import (
    assess_zoom_readiness,
)
from evaluation_kit.bite_calibration.zoom_incremental_model import (
    BASELINE_MODEL,
    GEOMETRY_MODEL,
    PRIMARY_MODEL,
    crossfit_zoom,
    deterministic_shuffled_rows,
    fit_zoom_logistic,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "outputs/bite/phase04c1d"


def _rows(path):
    return read_jsonl(ROOT / path)


@pytest.fixture(scope="module")
def runtime_rows():
    return freeze_runtime_rows(
        _rows("outputs/bite/phase04b2b4/conditional_features/expansion_runtime_features.jsonl"),
        cohort_name="expansion", expected_count=203, expected_groups=30,
    )


@pytest.fixture(scope="module")
def joined_50(runtime_rows):
    predictions = _rows("outputs/bite/phase04c1a/crossfit/expansion_iou_0_5_predictions.jsonl")
    return join_frozen_target(runtime_rows, predictions, endpoint="0.5")


@pytest.fixture(scope="module")
def crossfit_50(joined_50):
    return crossfit_zoom(joined_50)


def test_actual_runtime_table_is_complete_gt_free_and_retains_missingness(runtime_rows):
    assert len(runtime_rows) == 203
    assert len({row["source_group_id"] for row in runtime_rows}) == 30
    categories = {name: sum(row["association_category"] == name for row in runtime_rows) for name in (
        "target_aligned_supporting_proposal", "ambiguous_target_association",
        "no_target_aligned_proposal", "execution_failure",
    )}
    assert categories == {
        "target_aligned_supporting_proposal": 176,
        "ambiguous_target_association": 21,
        "no_target_aligned_proposal": 6,
        "execution_failure": 0,
    }
    assert sum(not row["score_change_observed"] for row in runtime_rows) == 27
    assert all(row["incremental_logical_cost"] == 2 for row in runtime_rows)


@pytest.mark.parametrize("field", ["label", "official_tp", "ground_truth", "H_annotation"])
def test_runtime_validator_rejects_gt_predictors(runtime_rows, field):
    row = deepcopy(runtime_rows[0])
    row["schema_version"] = "bite.focused_evidence_features.v1"
    row[field] = 1
    with pytest.raises(ValueError, match="GT-derived"):
        validate_runtime_row(row)


def test_runtime_validator_rejects_invented_missing_score(runtime_rows):
    row = deepcopy(next(row for row in runtime_rows if not row["score_change_observed"]))
    row["schema_version"] = "bite.focused_evidence_features.v1"
    row["focused_score"] = row["initial_score"]
    with pytest.raises(ValueError, match="synthetic"):
        validate_runtime_row(row)


def test_runtime_validator_rejects_invalid_transform_and_cost(runtime_rows):
    row = deepcopy(runtime_rows[0])
    row["schema_version"] = "bite.focused_evidence_features.v1"
    row["coordinate_transform_valid"] = False
    with pytest.raises(ValueError, match="coordinate"):
        validate_runtime_row(row)
    row = deepcopy(runtime_rows[0])
    row["schema_version"] = "bite.focused_evidence_features.v1"
    row["incremental_logical_cost"] = 1
    with pytest.raises(ValueError, match="two logical"):
        validate_runtime_row(row)


def test_runtime_integrity_matches_frozen_image_identities(runtime_rows):
    protocol = json.loads((
        ROOT / "outputs/bite/phase04c1c_revised/protocol/task_v_annotation_proxy_protocol_v2.json"
    ).read_text())
    report = runtime_integrity_report(
        runtime_rows,
        source_path=ROOT / "outputs/bite/phase04b2b4/conditional_features/expansion_runtime_features.jsonl",
        expected_image_hashes=protocol["identity"]["fit_source_image_sha256"],
    )
    assert report["status"] == "PASS"
    assert report["source_image_count"] == 30
    assert report["gt_derived_predictor_count"] == 0


@pytest.mark.parametrize("endpoint,positive", [("0.5", 31), ("0.75", 23)])
def test_all_203_candidates_join_original_labels_and_folds(runtime_rows, endpoint, positive):
    path = f"outputs/bite/phase04c1a/crossfit/expansion_iou_{endpoint.replace('.', '_')}_predictions.jsonl"
    joined = join_frozen_target(runtime_rows, _rows(path), endpoint=endpoint)
    assert len(joined) == 203 and sum(row["label"] for row in joined) == positive
    assert all(row["target_joined_after_runtime_freeze"] for row in joined)
    assert all(len({row["fold_index"] for row in joined if row["source_group_id"] == group}) == 1
               for group in {row["source_group_id"] for row in joined})


def test_original_hypothesis_reproduces_paired_diagnostic(joined_50):
    paired = _rows("outputs/bite/phase04b2b4/diagnostics/expansion_paired_diagnostics.jsonl")
    assert validate_paired_labels(joined_50, paired, endpoint="0.5")


def test_candidate_mismatch_blocks_join(runtime_rows):
    predictions = _rows("outputs/bite/phase04c1a/crossfit/expansion_iou_0_5_predictions.jsonl")
    changed = deepcopy(predictions)
    next(row for row in changed if row["model_name"] == "score_only_logistic")["candidate_id"] = "wrong"
    with pytest.raises(ValueError, match="candidate_id"):
        join_frozen_target(runtime_rows, changed, endpoint="0.5")


def test_primary_encoding_uses_explicit_missingness(joined_50):
    model = fit_zoom_logistic(joined_50, PRIMARY_MODEL)
    assert "score_change_observed" in model["feature_names"]
    assert model["preprocessing"]["score_difference"]["fit_value_count"] == 176
    assert model["missing_continuous_values_imputed_to_observed_training_mean"]


def test_optional_geometry_adds_exactly_one_continuous_feature(joined_50):
    primary = fit_zoom_logistic(joined_50, PRIMARY_MODEL)
    geometry = fit_zoom_logistic(joined_50, GEOMETRY_MODEL)
    assert set(geometry["feature_names"]) - set(primary["feature_names"]) == {"z_root_box_iou"}


def test_crossfit_reuses_m0_and_original_folds_without_group_leakage(joined_50, crossfit_50):
    baseline = {row["state_id"]: row for row in crossfit_50["predictions"] if row["model_name"] == BASELINE_MODEL}
    assert len(baseline) == 203
    assert all(baseline[row["state_id"]]["probability"] == row["m0_probability"] for row in joined_50)
    assert all(baseline[row["state_id"]]["fold_index"] == row["fold_index"] for row in joined_50)
    for fit in crossfit_50["fitted_models"]:
        assert not set(fit["training_groups"]) & set(fit["evaluation_groups"])
    assert crossfit_50["full_fit_prior_used_as_baseline"] is False


def test_fold_preprocessing_is_training_local(joined_50, crossfit_50):
    for fit in crossfit_50["fitted_models"]:
        if fit["model_name"] != PRIMARY_MODEL:
            continue
        train = [row for row in joined_50 if row["fold_index"] != fit["fold_index"]]
        expected = sum(row["initial_score"] for row in train) / len(train)
        assert fit["model"]["preprocessing"]["initial_score"]["mean"] == pytest.approx(expected)


def test_crossfit_predictions_are_reproducible_and_finite(joined_50, crossfit_50):
    again = crossfit_zoom(joined_50)
    assert again == crossfit_50
    assert len(crossfit_50["predictions"]) == 609
    assert all(0 <= row["probability"] <= 1 for row in crossfit_50["predictions"])


def test_primary_analysis_retains_ambiguous_and_missing(crossfit_50):
    aligned = align_predictions(crossfit_50["predictions"])
    assert len(aligned) == 203
    assert sum(not row["score_change_observed"] for row in aligned) == 27


def test_paired_difference_sign_and_bootstrap_are_correct(crossfit_50):
    aligned = align_predictions(crossfit_50["predictions"])
    observed = paired_difference(aligned, PRIMARY_MODEL, BASELINE_MODEL, "brier_score")
    assert observed == pytest.approx(0.0002348354973904231)
    one = paired_group_bootstrap(aligned, replicates=40, seed=461)
    two = paired_group_bootstrap(aligned, replicates=40, seed=461)
    assert one == two
    assert one["source_group_count"] == 30
    assert one["candidate_rows_resampled_iid"] is False


def test_actual_evaluation_reports_group_balanced_metrics_and_coverage(crossfit_50):
    result = evaluate_predictions(crossfit_50["predictions"], bootstrap_replicates=20)
    assert result["models"][PRIMARY_MODEL]["prediction_coverage"] == 1
    assert result["models"][PRIMARY_MODEL]["group_balanced"]["group_count"] == 30
    assert result["evidence_diagnostics"]["aligned_only_selection_biased_sensitivity"]["primary_analysis"] is False


def test_cost_analysis_is_offline_and_counts_two_calls(crossfit_50):
    cost = analyze_cost_risk(align_predictions(crossfit_50["predictions"]))
    assert cost["always_zoom"]["incremental_logical_calls"] == 406
    assert cost["paired_decision_changes"] == {
        "errors_avoided": 0, "new_errors_introduced": 2, "net_error_change": 2,
    }
    assert cost["status"] == "OFFLINE_OBSERVED_DECISION_DIAGNOSTIC_NOT_A_POLICY"


def test_shuffled_control_is_deterministic_and_breaks_pairing(joined_50):
    one = deterministic_shuffled_rows(joined_50)
    two = deterministic_shuffled_rows(joined_50)
    assert one == two
    assert all(row["shuffled_zoom_donor_state_id"] != row["state_id"] for row in one)
    assert [row["label"] for row in one] == [row["label"] for row in joined_50]


def _synthetic_rows():
    rows = []
    for group_index in range(30):
        for case_index in range(4):
            label = case_index % 2
            rows.append({
                "state_id": f"s:{group_index}:{case_index}",
                "original_candidate_id": f"c:{group_index}:{case_index}",
                "source_group_id": f"g:{group_index}",
                "root_image_sha256": hashlib.sha256(f"g:{group_index}".encode()).hexdigest(),
                "query": "synthetic", "endpoint": "0.5", "fold_index": group_index % 3,
                "label": label, "m0_probability": .5, "initial_score": .5,
                "score_difference": .4 if label else -.4, "root_box_iou": .9,
                "score_change_observed": True, "root_box_iou_observed": True,
                "association_ambiguous": False, "association_no_alignment": False,
                "association_execution_failure": False,
                "association_category": "target_aligned_supporting_proposal",
                "annotation_scope_audit": "synthetic",
            })
    return rows


def test_synthetic_informative_zoom_feature_is_detected():
    result = crossfit_zoom(_synthetic_rows())
    aligned = align_predictions(result["predictions"])
    assert paired_difference(aligned, PRIMARY_MODEL, BASELINE_MODEL, "brier_score") < -.1


@pytest.mark.parametrize("revision", ["main", "ABC", "3c879f", "g" * 40])
def test_immutable_revision_parser_rejects_movable_or_invalid_values(revision):
    with pytest.raises(ValueError):
        validate_revision(revision)


def test_immutable_revision_parser_accepts_cached_commit():
    assert validate_revision("3c879f39826c281e95690f02c7821c4de09afae7")


def _attestation():
    return json.loads((OUTPUT / "worker_attestation/preparation.json").read_text())


def test_attestation_preparation_uses_verified_sam3_pt_without_loading_or_download():
    plan = _attestation()
    assert plan["load_plan"]["actual_expected_loader_artifact"] == "sam3.pt"
    assert plan["load_plan"]["arguments"]["load_from_HF"] is False
    assert plan["cached_artifacts"]["sam3.pt"]["sha256"] == "9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e"
    assert not plan["model_loaded"] and not plan["download_performed"]


def test_attestation_digest_mismatch_is_rejected(tmp_path):
    snapshot = tmp_path / "snapshots" / ("a" * 40)
    snapshot.mkdir(parents=True)
    for name in ("sam3.pt", "config.json", "processor_config.json"):
        (snapshot / name).write_bytes(name.encode())
    with pytest.raises(ValueError, match="digest mismatch"):
        prepare_attested_worker(
            model_id="facebook/sam3", revision="a" * 40, cache_root=tmp_path,
            expected_weight_sha256="0" * 64,
            expected_config_sha256=hashlib.sha256(b"config.json").hexdigest(),
            expected_processor_sha256=hashlib.sha256(b"processor_config.json").hexdigest(),
            worker_source=__file__, worker_config=__file__, environment={"mock": "1"},
        )


def test_mock_initialization_event_validates_process_session_and_actual_artifact():
    plan = _attestation()
    event = {
        "schema_version": "bite.sam3_worker_initialization_attestation.v1",
        "session_id": str(uuid.uuid4()), "process_id": 123,
        "process_start_time_utc": "2026-11-02T00:00:00+00:00",
        "model_load_time_utc": "2026-11-02T00:01:00+00:00",
        "model_id": plan["intended_configuration"]["model_id"],
        "immutable_revision": plan["intended_configuration"]["immutable_revision"],
        "resolved_weight_path": plan["cached_artifacts"]["sam3.pt"]["resolved_path"],
        "weight_sha256": plan["cached_artifacts"]["sam3.pt"]["sha256"],
        "processor_config_sha256": plan["cached_artifacts"]["processor_config.json"]["sha256"],
        "worker_source_sha256": plan["worker_identity"]["worker_source_sha256"],
        "worker_config_sha256": plan["worker_identity"]["worker_config_sha256"],
        "library_versions": {"sam3": "0.1.0"},
        "preprocessing": {"presence": False}, "load_succeeded": True,
    }
    assert validate_initialization_event(event, plan)
    event["weight_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="weight_sha256"):
        validate_initialization_event(event, plan)


def test_matched_worker_bridge_is_fit_only_capped_and_unexecuted():
    protocol = json.loads((OUTPUT / "matched_worker_bridge/protocol.json").read_text())
    assert protocol["source_group_count"] == 30
    assert protocol["query_schedule"]["state_count"] == 210
    assert protocol["dispatch_caps"]["initial_grounding_only"] == 210
    assert protocol["dispatch_caps"]["initial_plus_zoom_focused_if_separately_authorized"] == 630
    assert protocol["status"] == "PREPARED_NOT_AUTHORIZED_NOT_EXECUTED"


def test_bridge_rejects_wrong_source_group_count():
    expansion = json.loads((
        ROOT / "outputs/bite/phase04b2b3/protocol/task_v_expansion_protocol.json"
    ).read_text())
    annotation = json.loads((
        ROOT / "outputs/bite/phase04c1c_revised/protocol/task_v_annotation_proxy_protocol_v2.json"
    ).read_text())
    changed = deepcopy(expansion)
    changed["source_group_count"] = 29
    with pytest.raises(ValueError, match="30"):
        build_bridge_protocol(changed, annotation, _attestation())


def test_actual_readiness_is_inconclusive_and_does_not_promote_validation():
    readiness = json.loads((OUTPUT / "readiness/readiness.json").read_text())
    assert readiness["conditional_usefulness_decision"] == "INCONCLUSIVE_INSUFFICIENT_SUPPORT"
    assert readiness["research_decision"] == "ZOOM_INCONCLUSIVE_MORE_FIT_EVIDENCE_NEEDED"
    assert readiness["validation"]["authorized"] is False
    assert readiness["conditional_kernel"]["fit_justified_now"] is False


def test_readiness_decision_rules_cover_positive_negative_and_inconclusive():
    def result(delta, low, high):
        return {"paired_uncertainty": {"comparisons": {
            f"{PRIMARY_MODEL}_minus_{BASELINE_MODEL}": {"case_level": {"brier_score": {
                "observed_difference": delta, "lower_2_5": low, "upper_97_5": high,
            }}}
        }}}
    positive = assess_zoom_readiness({"a": result(-.1, -.2, -.01), "b": result(-.1, -.2, -.01)}, checkpoint_status="x")
    negative = assess_zoom_readiness({"a": result(.1, .01, .2), "b": result(.1, .01, .2)}, checkpoint_status="x")
    mixed = assess_zoom_readiness({"a": result(-.1, -.2, .1), "b": result(.1, -.1, .2)}, checkpoint_status="x")
    assert positive["research_decision"] == "ZOOM_PROMISING_CONTINUE_TO_VALIDATION"
    assert negative["research_decision"] == "ZOOM_UNHELPFUL_REVISE_ACTION_SPACE"
    assert mixed["research_decision"] == "ZOOM_INCONCLUSIVE_MORE_FIT_EVIDENCE_NEEDED"


def test_historical_human_reviews_are_preserved():
    status = json.loads((
        ROOT / "outputs/bite/phase04c1c_revised/optional_human_reviews/status.json"
    ).read_text())
    assert status["validated_finalized_review_count"] == 20
    assert status["historical_records_rewritten"] is False


def test_phase_inputs_exclude_validation_internal_test_and_model_inference():
    summary = json.loads((OUTPUT / "paired_metrics/summary.json").read_text())
    restrictions = summary["restrictions"]
    assert restrictions["validation_accessed"] is False
    assert restrictions["internal_test_accessed"] is False
    assert restrictions["new_model_inference"] is False
    assert restrictions["planner_implemented"] is False


def test_original_agent_and_evaluator_do_not_import_zoom_modules():
    for path in (
        ROOT / "openvlharness/agent/agent.py",
        ROOT / "evaluation_kit/runner.py",
    ):
        text = path.read_text()
        assert "zoom_incremental_model" not in text
        assert "paired_zoom_evaluation" not in text
        assert "sam3_attested_worker" not in text
