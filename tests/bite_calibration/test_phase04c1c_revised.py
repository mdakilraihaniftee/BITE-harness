import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from evaluation_kit.bite_calibration.annotation_proxy_protocol import (
    PROTOCOL_VERSION,
    annotation_proxy_label,
    validate_protocol,
)
from evaluation_kit.bite_calibration.endpoint_readiness import READINESS_VERSION
from evaluation_kit.bite_calibration.frozen_prior_export import (
    EXPORT_VERSION,
    canonical_sha,
    validate_frozen_artifact,
)
from evaluation_kit.bite_calibration.optional_human_review import (
    SUMMARY_VERSION,
    validate_optional_review_summary,
)
from evaluation_kit.bite_calibration.prior_model import predict
from evaluation_kit.bite_calibration.sam3_provenance import (
    CACHED_REVISION,
    PROVENANCE_VERSION,
    audit_sam3_provenance,
    validate_provenance,
)
from evaluation_kit.bite_calibration.validation_model_contract import (
    CONTRACT_VERSION,
    validate_contract,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "outputs/bite/phase04c1c_revised"


def _json(path):
    return json.loads(Path(path).read_text())


def _priors():
    return [_json(path) for path in sorted((OUTPUT / "frozen_priors").glob("0_*_*.json"))]


@pytest.mark.parametrize(
    ("threshold", "expected"),
    [(0.50, 1), (0.75, 0)],
)
def test_annotation_proxy_endpoint_thresholds(threshold, expected):
    outcome = annotation_proxy_label([0, 0, 10, 10], [[0, 0, 8, 8]], threshold)
    assert outcome["status"] == "candidate_present"
    assert outcome["label"] == expected
    assert outcome["best_iou"] == pytest.approx(0.64)


def test_annotation_proxy_empty_same_class_is_closed_world_negative():
    outcome = annotation_proxy_label([0, 0, 10, 10], [], 0.50)
    assert outcome["label"] == 0
    assert outcome["empty_queried_class_is_annotation_negative"]


def test_annotation_proxy_no_candidate_is_separate_not_negative():
    assert annotation_proxy_label(None, [], 0.50) == {
        "status": "no_candidate", "label": None, "best_iou": None,
    }


@pytest.mark.parametrize("threshold", [0.0, 0.6, 1.0])
def test_annotation_proxy_rejects_unregistered_thresholds(threshold):
    with pytest.raises(ValueError, match="only IoU"):
        annotation_proxy_label([0, 0, 10, 10], [], threshold)


def test_protocol_v2_freezes_identity_counts_and_human_optionality():
    protocol = validate_protocol(_json(OUTPUT / "protocol/task_v_annotation_proxy_protocol_v2.json"))
    assert protocol["schema_version"] == PROTOCOL_VERSION
    assert protocol["identity"]["annotation_sha256"] == "5ca593fb53fc482790b51677fdd81b0e497d44e8bcdce00f8ec4275937ed097c"
    assert len(protocol["identity"]["fit_source_image_sha256"]) == 30
    assert len(set(protocol["identity"]["fit_source_image_sha256"])) == 30
    assert protocol["fit_cohort"]["source_group_count"] == 30
    assert protocol["fit_cohort"]["candidate_present_count"] == 203
    assert protocol["fit_cohort"]["endpoint_counts"]["H_annotation_0.50"] == {
        "positive": 31, "negative": 172,
    }
    assert not protocol["human_review"]["required_for_annotation_proxy_calibration"]
    assert protocol["human_review"]["required_for_visual_truth_claims"]


def test_protocol_migration_preserves_chronology_and_rejects_visual_truth_claim():
    protocol = _json(OUTPUT / "protocol/task_v_annotation_proxy_protocol_v2.json")
    assert len(protocol["chronology"]) == 5
    assert "mandatory" in (ROOT / "docs/bite/PHASE_04C1B_READINESS_DECISION.md").read_text().lower() or (
        "human" in (ROOT / "docs/bite/PHASE_04C1B_READINESS_DECISION.md").read_text().lower()
    )
    bad = deepcopy(protocol)
    bad["interpretation"]["exhaustive_visual_truth_claimed"] = True
    with pytest.raises(ValueError, match="visual truth"):
        validate_protocol(bad)


def test_frozen_prior_set_is_complete_and_primary_is_score_only():
    priors = _priors()
    assert len(priors) == 6
    assert {row["schema_version"] for row in priors} == {EXPORT_VERSION}
    assert {row["endpoint"] for row in priors} == {"H_annotation_0.5", "H_annotation_0.75"}
    assert {row["model_name"] for row in priors} == {
        "constant_prevalence", "score_only_logistic", "compact_initial_logistic",
    }
    assert {
        row["model_name"] for row in priors if row["model_role"] == "primary"
    } == {"score_only_logistic"}


@pytest.mark.parametrize("endpoint,positive,negative", [("0.5", 31, 172), ("0.75", 23, 180)])
def test_frozen_priors_are_fit_only_and_endpoint_specific(endpoint, positive, negative):
    rows = [row for row in _priors() if row["endpoint"] == f"H_annotation_{endpoint}"]
    assert len(rows) == 3
    for row in rows:
        validate_frozen_artifact(row)
        training = row["training"]
        assert training["partition"] == "calibration_fit"
        assert training["source_group_count"] == 30
        assert training["candidate_count"] == 203
        assert (training["positive_count"], training["negative_count"]) == (positive, negative)
        assert not training["pilot_included"]
        assert not training["calibration_validation_accessed"]
        assert not training["internal_test_accessed"]


def test_frozen_score_preprocessing_regularization_and_compact_area_transform():
    priors = _priors()
    score = next(row for row in priors if row["endpoint"] == "H_annotation_0.5" and row["model_name"] == "score_only_logistic")
    compact = next(row for row in priors if row["endpoint"] == "H_annotation_0.5" and row["model_name"] == "compact_initial_logistic")
    assert score["fit"]["preprocessing"]["score_transform"] == "identity_on_[0,1]"
    assert score["regularization"] == {"type": "L2", "lambda": 1.0, "intercept_penalized": False}
    assert compact["fit"]["preprocessing"]["relative_area_transform"] == "natural_log"


def test_serialized_model_hashes_and_predictions_are_reproducible():
    for artifact in _priors():
        assert artifact["serialized_model_payload_sha256"] == canonical_sha(artifact["fit"])
        contract = artifact["prediction_reproducibility"]
        outputs = predict(artifact["fit"], contract["synthetic_inputs"])
        assert canonical_sha(outputs) == contract["synthetic_predictions_sha256"]
        assert contract["fit_prediction_count"] == 203
        assert contract["all_fit_predictions_supported"]


def test_frozen_models_exclude_gt_and_future_action_features():
    for artifact in _priors():
        feature = artifact["feature_contract"]
        assert not feature["gt_derived_predictors"]
        assert not feature["zoom_or_focused_predictors"]
        assert not feature["post_action_predictors"]
        assert not ({"root_box_iou", "focused_score", "H_annotation"} & set(feature["features"]))


def test_optional_human_reviews_are_genuine_finalized_and_preserved():
    summary = validate_optional_review_summary(_json(OUTPUT / "optional_human_reviews/status.json"))
    assert summary["schema_version"] == SUMMARY_VERSION
    assert summary["validated_finalized_review_count"] == 20
    assert summary["validated_finalized_case_count"] == 20
    assert summary["event_progress"] == {
        "blind_first_pass_count": 20,
        "gt_reveal_count": 20,
        "post_reveal_count": 1,
        "first_to_post_change_count": 1,
    }
    assert all(row["finalized"] for row in summary["validated_event_chains"])
    assert not summary["fabricated_reviews"]


def test_optional_reviews_do_not_estimate_prevalence_or_change_training():
    summary = _json(OUTPUT / "optional_human_reviews/status.json")
    assert summary["queue_union_pending_case_count"] == 215
    assert summary["set_a"] == {"total": 120, "completed": 20, "remaining": 100}
    assert not summary["probability_sample_complete"]
    assert not summary["dataset_wide_omission_prevalence_estimated"]
    assert not summary["training_labels_modified"]
    assert not summary["prior_refit_from_human_labels"]
    assert not summary["human_review_required_for_annotation_proxy"]
    assert summary["human_review_required_for_visual_truth_claims"]


def test_all_human_source_hashes_still_match_persisted_files():
    summary = _json(OUTPUT / "optional_human_reviews/status.json")
    for path, expected in summary["source_artifact_hashes"]["completed_records"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
    for path, expected in summary["source_artifact_hashes"]["event_records"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected


def test_checkpoint_provenance_distinguishes_cache_from_loaded_worker():
    report = validate_provenance(_json(OUTPUT / "worker_provenance/sam3_provenance.json"))
    assert report["schema_version"] == PROVENANCE_VERSION
    assert report["status"] == "CACHE_CONFIG_VERIFIED_ONLY"
    assert report["cached_checkpoint"]["refs_main"] == CACHED_REVISION
    assert report["cached_checkpoint"]["ref_matches_expected"]
    assert not report["running_process"]["active"]
    assert not report["historical_worker"]["load_event_revision_attested"]
    assert not report["historical_worker"]["historical_process_to_cache_link_proven"]
    assert not report["cross_run_comparability"]["future_worker_equivalent_to_historical_claim_permitted"]


def test_checkpoint_weight_hashes_cover_both_cached_weight_formats():
    files = _json(OUTPUT / "worker_provenance/sam3_provenance.json")["cached_checkpoint"]["files"]
    assert files["sam3.pt"]["sha256"] == "9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e"
    assert files["model.safetensors"]["sha256"] == "6d06f0a5f84e435071fe6603e61d0b4cc7b40e0d39d487cfd4d67d8cc11cc14a"


def test_provenance_audit_does_not_promote_cache_to_load_attestation(tmp_path):
    cache = tmp_path / "cache"
    snapshot = cache / "snapshots" / CACHED_REVISION
    snapshot.mkdir(parents=True)
    (cache / "refs").mkdir()
    (cache / "refs/main").write_text(CACHED_REVISION)
    for name in ("sam3.pt", "model.safetensors", "config.json", "processor_config.json"):
        (snapshot / name).write_bytes(name.encode())
    site = tmp_path / "site"
    info = site / "sam3-0.1.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text("Name: sam3\nVersion: 0.1\n")
    (info / "direct_url.json").write_text(json.dumps({
        "vcs_info": {"commit_id": "abc"}, "url": "https://example.invalid/sam3",
    }))
    source = tmp_path / "server.py"
    config = tmp_path / "config.yaml"
    source.write_text("loader")
    config.write_text("model: facebook/sam3")
    report = audit_sam3_provenance(
        cache_root=cache, site_packages=site, worker_source=source, worker_config=config,
        active_process_lines=["123 python sam3 worker"],
    )
    assert report["running_process"]["active"]
    assert report["status"] == "CACHE_CONFIG_VERIFIED_ONLY"
    assert not report["running_process"]["identity_attested"]


def test_loaded_model_status_requires_load_event_weight_hash():
    report = _json(OUTPUT / "worker_provenance/sam3_provenance.json")
    report["status"] = "LOADED_MODEL_ATTESTED"
    with pytest.raises(ValueError, match="weight hashes"):
        validate_provenance(report)


def test_validation_contract_preserves_72_groups_504_states_and_1512_calls():
    contract = validate_contract(_json(OUTPUT / "validation_preflight/preflight_v2.json"))
    assert contract["schema_version"] == CONTRACT_VERSION
    assert contract["collection"]["source_group_count"] == 72
    assert contract["collection"]["maximum_query_states"] == 504
    assert contract["collection"]["maximum_logical_dispatches"] == 1512
    assert len(contract["collection"]["queries"]) == 7
    assert contract["source_and_split"]["cross_partition_group_overlaps"] == {
        "fit_validation": [], "fit_internal_test": [], "validation_internal_test": [],
    }
    assert contract["source_and_split"]["quarantined_validation_image_count"] == 0


def test_validation_order_applies_model_before_gt_and_preserves_zoom_separately():
    contract = _json(OUTPUT / "validation_preflight/preflight_v2.json")
    order = contract["runtime_ordering"]
    assert order.index("apply frozen prior before any additional action or GT access") < order.index(
        "open GT and derive official COCO annotation labels",
    )
    assert contract["model_contract"]["initial_probability_never_modified_by_zoom"]
    assert contract["collection"]["action_policy"]["raw_before_label_persistence"]
    assert contract["collection"]["branch_isolation_required"]
    assert contract["collection"]["resume_and_corruption_detection_required"]


def test_validation_is_no_go_for_authorization_and_checkpoint_not_human_review():
    contract = _json(OUTPUT / "validation_preflight/preflight_v2.json")
    assert contract["authorization"]["go_no_go"] == "NO_GO"
    assert not contract["authorization"]["human_review_is_gate"]
    assert contract["checkpoint"]["provenance_status"] == "CACHE_CONFIG_VERIFIED_ONLY"
    assert not contract["checkpoint"]["historical_future_comparability_verified"]
    assert not contract["authorization"]["researcher_execution_authorization_present"]
    assert not contract["collection"]["executed"]


def test_endpoint_readiness_separates_annotation_visual_zoom_and_planning():
    readiness = _json(OUTPUT / "readiness/readiness.json")
    assert readiness["schema_version"] == READINESS_VERSION
    assert "ANNOTATION_PROXY_READY" in readiness["overall"]
    assert "CHECKPOINT_COMPARABILITY_UNVERIFIED" in readiness["overall"]
    assert readiness["annotation_proxy_prior"]["human_review_required"] is False
    assert readiness["visual_truth_prior"]["human_review_required"] is True
    assert readiness["restricted_zoom_observation_model"]["fit_executed"] is False
    assert readiness["budgeted_planning"]["status"] == "NOT_READY"
    assert readiness["identifiability_theory"]["status"] == "NOT_READY"
    assert readiness["end_to_end_evaluation"]["status"] == "NOT_READY"


def test_conditional_evidence_design_is_unfitted_grouped_and_cost_explicit():
    design = _json(OUTPUT / "conditional_evidence_design/conditional_evidence_experiment.json")
    assert design["status"] == "DESIGN_ONLY_NOT_FITTED"
    assert "raw_sam3_score" in design["models"]
    assert design["development"]["allowed_partition"] == "calibration_fit"
    assert design["evaluation"]["partition"] == "calibration_validation"
    assert design["evaluation"]["paired_source_group_comparisons"]
    assert not design["dependence"]["repeated_outputs_multiplied_as_independent"]
    assert design["costs"] == {"stop": 0, "exact_repeat": 1, "zoom_then_focused_grounding": 2}
    assert not design["likelihood_fitted"] and not design["posterior_computed"]


def test_agent_selected_query_proposal_retains_unmappable_queries_without_execution():
    proposal = _json(OUTPUT / "conditional_evidence_design/agent_selected_query_proposal.json")
    assert proposal["status"] == "FUTURE_ONLY_NOT_EXECUTED"
    assert proposal["agent_selected_regime"]["query_generated_before_gt_access"]
    assert proposal["agent_selected_regime"]["unmappable_or_ambiguous_queries_retained"]
    assert proposal["separate_population"]
    assert not proposal["same_prevalence_or_calibration_curve_assumed"]
    assert proposal["vlm_calls"] == 0
    assert not proposal["agent_loop_modified"]


def test_phase_safeguards_record_no_inference_posterior_planner_or_certificate():
    readiness = _json(OUTPUT / "readiness/readiness.json")["restrictions"]
    assert not readiness["validation_inference_executed"]
    assert not readiness["conditional_zoom_likelihood_fitted"]
    assert not readiness["posterior_computed"]
    assert not readiness["planner_implemented"]
    assert not readiness["bellman_optimization_implemented"]
    assert not readiness["certificate_claimed"]


def test_original_agent_and_evaluator_do_not_import_phase04c1c_modules():
    markers = (
        "annotation_proxy_protocol", "frozen_prior_export", "sam3_provenance",
        "validation_model_contract", "endpoint_readiness",
    )
    paths = [
        ROOT / "openvlharness/agent/agent.py",
        ROOT / "evaluation_kit/runner.py",
    ]
    for path in paths:
        text = path.read_text()
        assert not any(marker in text for marker in markers)
