import copy
import hashlib
import json
import random
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from evaluation_kit.bite_calibration.action_utility_screen import (
    candidate_utilities,
    classify_zoom_collection,
    futility_projection,
    grouped_utility_bootstrap,
    screen_action,
    squared_loss_identity_diagnostic,
)
from evaluation_kit.bite_calibration.semantic_comparison_design import (
    BASELINE,
    classify_pilot,
    design_record,
    evaluate_comparisons,
    logo_crossfit,
)
from evaluation_kit.bite_calibration.semantic_feature_extractor import (
    extract_features,
    finalize_feature_table,
    join_offline_labels,
)
from evaluation_kit.bite_calibration.semantic_observation_schema import (
    PROMPT,
    PROMPT_SHA256,
    USER_PROMPT,
    canonical_sha256,
    consistency_flags,
    parse_response,
    query_compatibility,
)
from evaluation_kit.bite_calibration.semantic_pilot_protocol import (
    _guarded_read_json,
    apply_dispatch_cap,
    mock_requester,
    run_pilot,
    select_groups,
    validate_authorization,
    verify_manifest,
)
from evaluation_kit.bite_calibration.semantic_region_action import (
    OUTLINE_RGB,
    build_adapter,
    build_messages,
    inspect_region,
    render_region,
    validate_case,
)
from evaluation_kit.bite_collection.resume import file_digest
from openvlharness.services.models import ModelAdapter

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "outputs/bite/phase04c1e"
EXPANSION = ROOT / "outputs/bite/phase04b2b3/expansion/aquarium_task_v_expansion_seed418_g30"


def _valid_text(content="fish", **overrides):
    value = {
        "region_content": content, "object_visible": "yes", "region_localization": "adequate",
        "multiple_objects": "no", "evidence_status": "supported", "short_visual_description": "a fish",
    }
    value.update(overrides)
    return json.dumps(value)


def _aligned(labels, baseline, treatment, groups):
    return [{
        "state_id": f"s{i}", "source_group_id": group, "query": "fish", "label": label,
        "probabilities": {"m0": p0, "m1": p1},
    } for i, (label, p0, p1, group) in enumerate(zip(labels, baseline, treatment, groups, strict=True))]


@pytest.fixture()
def synthetic_image(tmp_path):
    image = Image.new("RGB", (200, 160), (20, 40, 60))
    for x in range(80, 120):
        for y in range(60, 100):
            image.putpixel((x, y), (200, 180, 10))
    path = tmp_path / "source.png"
    image.save(path)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _case(path, digest, *, query="fish", state="state:a", group="sha256:g1"):
    return {
        "case_id": f"semantic_case:{state}", "state_id": state, "source_group_id": group,
        "source_entry_id": "entry", "partition": "calibration_fit", "query": query,
        "source_image_sha256": digest, "source_image_path": str(path),
        "image_width": 200, "image_height": 160,
        "original_candidate_id": "candidate:x", "candidate_bbox_root_xyxy": [80, 60, 120, 100],
        "initial_observation_id": "joint_observation:x", "initial_controlled_call_id": "controlled:prefix:0001",
        "initial_action_id": "action:x", "parent_snapshot_id": "snapshot:x",
    }


def _adapter(respond=lambda i, p: _valid_text()):
    requester = mock_requester(respond)
    return build_adapter("http://fixture.invalid/v1", requester=requester), requester


# ---------------------------------------------------------------- action utility

def test_utility_sign_convention_and_units_are_separate():
    rows = candidate_utilities(_aligned([1, 0], [.4, .2], [.7, .2], ["g1", "g2"]),
                               baseline="m0", treatment="m1", action_cost=2)
    assert rows[0]["error_utility_gross"] == 1.0
    assert rows[0]["brier_utility_gross"] == pytest.approx(.36 - .09)
    assert rows[1]["error_utility_gross"] == 0.0 and rows[1]["brier_utility_gross"] == 0.0


def test_break_even_and_net_grid_shift_exactly_by_cost():
    aligned = _aligned([1, 0, 1, 0], [.4, .2, .6, .1], [.7, .2, .6, .1], ["g1", "g1", "g2", "g3"])
    screen = screen_action(aligned, baseline="m0", treatment="m1", action_cost=2, endpoint="0.5",
                           replicates=200, unused_fit_groups=10)
    gross = screen["error_loss"]["gross_utility"]["case_level"]["observed"]
    assert gross == pytest.approx(.25)
    assert screen["error_loss"]["break_even_lambda_per_logical_call"] == pytest.approx(.125)
    for entry in screen["error_loss"]["lambda_grid"]:
        assert entry["mean_net_error_utility"]["observed"] == pytest.approx(
            gross - 2 * entry["lambda_error_units_per_logical_call"])
    assert screen["additional_logical_calls"] == 8
    assert screen["brier_loss"]["not_comparable_to_error_lambda"] is True


def test_negative_utility_has_no_break_even_and_no_projection():
    aligned = _aligned([1, 0], [.7, .2], [.4, .2], ["g1", "g2"])
    screen = screen_action(aligned, baseline="m0", treatment="m1", action_cost=2, endpoint="0.5",
                           replicates=100, unused_fit_groups=10)
    assert screen["error_loss"]["break_even_lambda_per_logical_call"] is None
    assert futility_projection(-0.01, 0.01, 30)["projected_groups_for_interval_excluding_zero"] is None
    decision = classify_zoom_collection({"0.5": screen})
    assert decision["decision"] == "ZOOM_ONLY_COLLECTION_NOT_JUSTIFIED_FOR_TASK_V_VERIFICATION"
    assert decision["statistical_action_dominance_claimed"] is False


def test_bootstrap_resamples_whole_groups_not_candidate_rows():
    rows = candidate_utilities(_aligned([1, 1, 1, 1], [.4, .4, .4, .7], [.7, .7, .7, .7],
                                        ["A", "A", "A", "B"]),
                               baseline="m0", treatment="m1", action_cost=1)
    boot = grouped_utility_bootstrap(rows, replicates=300, seed=1)
    interval = boot["gross_utility"]["error_utility_gross"]["case_level"]
    # Group draws can only give means 1 (AA), 0.75 (AB) or 0 (BB); iid rows would give 0.25/0.5.
    assert {interval["lower_2_5"], interval["upper_97_5"]} <= {0.0, 0.75, 1.0}
    assert boot["candidate_rows_resampled_iid"] is False
    assert boot["replicate_fraction_is_posterior_probability"] is False


def test_squared_loss_identity_decomposition_is_exact():
    aligned = _aligned([1, 0, 1, 0, 1], [.3, .4, .6, .2, .5], [.5, .1, .7, .3, .2], list("abcde"))
    result = squared_loss_identity_diagnostic(aligned, baseline="m0", treatment="m1")
    gain = np.mean([(r["probabilities"]["m0"] - r["label"]) ** 2 - (r["probabilities"]["m1"] - r["label"]) ** 2
                    for r in aligned])
    assert result["observed_brier_gain"] == pytest.approx(gain)
    assert result["mean_squared_probability_movement"] + result["calibration_cross_term"] == pytest.approx(gain)
    assert result["correct_specification_assumed"] is False


def test_stage_a_artifacts_reproduce_phase04c1d_and_make_no_guarantee():
    summary = json.loads((OUTPUT / "utility_screening/summary.json").read_text())
    expansion = summary["endpoints"]["expansion"]
    assert expansion["0.5"]["errors_introduced"] == 2 and expansion["0.5"]["errors_avoided"] == 0
    assert expansion["0.5"]["break_even_lambda_error"] is None
    assert expansion["0.75"]["break_even_lambda_error"] == pytest.approx(0.0024630541871921183)
    assert expansion["0.75"]["additional_logical_calls"] == 406
    assert summary["status"].endswith("NOT_A_POLICY_OR_GUARANTEE")
    assert summary["zoom_collection_decision"]["zoom_declared_universally_useless"] is False


# ---------------------------------------------------------------- semantic contract

def test_prompt_is_neutral_and_case_independent():
    assert PROMPT["contains_query_class"] is False and PROMPT["case_specific_text"] is False
    lowered = USER_PROMPT.lower()
    for forbidden in ("score", "correct", "annotation", "ground truth", "probability", "definitely"):
        assert forbidden not in lowered
    assert canonical_sha256(PROMPT) == PROMPT_SHA256


def test_payload_is_identical_across_queries_and_scores(synthetic_image):
    path, digest = synthetic_image
    adapter, requester = _adapter()
    inspect_region(_case(path, digest, query="fish"), adapter, mock=True)
    inspect_region(_case(path, digest, query="shark", state="state:b"), adapter, mock=True)
    assert len(requester.calls) == 2
    assert json.dumps(requester.calls[0], sort_keys=True) == json.dumps(requester.calls[1], sort_keys=True)


@pytest.mark.parametrize("text,status", [
    (_valid_text(), "valid"),
    ("```json\n" + _valid_text() + "\n```", "valid"),
    ("Here you go: " + _valid_text(), "malformed_json"),
    (_valid_text()[:-1] + ', "confidence": 0.9}', "schema_violation"),
    (_valid_text(region_content="dolphin"), "schema_violation"),
    (_valid_text(short_visual_description="x" * 400), "schema_violation"),
    ("[1, 2]", "schema_violation"),
    ("", "empty_response"),
    (None, "empty_response"),
])
def test_response_parser_classifies_without_repair(text, status):
    assert parse_response(text)[0] == status


@pytest.mark.parametrize("query,content,expected", [
    ("shark", "shark", "match"),
    ("shark", "fish", "taxonomic_overlap"),
    ("fish", "stingray", "taxonomic_overlap"),
    ("penguin", "puffin", "conflict_dataset_category"),
    ("fish", "other_object", "conflict_other_object"),
    ("fish", "background", "background"),
    ("fish", "unclear", "unclear"),
])
def test_ontology_keeps_dataset_categories_distinct_from_biology(query, content, expected):
    parsed = json.loads(_valid_text(content))
    assert query_compatibility(query, parsed) == expected


def test_ontology_unavailable_and_out_of_vocabulary():
    assert query_compatibility("fish", None) == "unavailable"
    with pytest.raises(ValueError, match="vocabulary"):
        query_compatibility("dolphin", None)


def test_consistency_flags_are_descriptive_only():
    parsed = json.loads(_valid_text("background", object_visible="yes"))
    assert "background_with_visible_object" in consistency_flags(parsed)
    assert parsed["region_content"] == "background"


def test_render_is_deterministic_outline_outside_box_and_identity_checked(synthetic_image):
    path, digest = synthetic_image
    first, meta = render_region(path, [80, 60, 120, 100], expected_sha256=digest)
    _, meta2 = render_region(path, [80, 60, 120, 100], expected_sha256=digest)
    assert meta["render_sha256"] == meta2["render_sha256"]
    full = Image.open(__import__("io").BytesIO(first["full_frame_with_outline"]["png"]))
    assert full.getpixel((100, 80)) == (200, 180, 10)
    assert full.getpixel((80, 80)) == (200, 180, 10)
    assert full.getpixel((79, 80)) == OUTLINE_RGB
    x0, y0, x1, y1 = meta["context_crop_xyxy"]
    assert x0 <= 80 and y0 <= 60 and x1 >= 120 and y1 >= 100
    assert meta["upsampling"] is False
    with pytest.raises(ValueError, match="digest"):
        render_region(path, [80, 60, 120, 100], expected_sha256="0" * 64)


@pytest.mark.parametrize("field", ["label", "initial_score", "best_gt_iou", "annotation_scope_audit"])
def test_case_whitelist_rejects_gt_and_detector_score(synthetic_image, field):
    path, digest = synthetic_image
    case = _case(path, digest)
    case[field] = 1
    with pytest.raises(ValueError, match="whitelist"):
        validate_case(case)


def test_case_rejects_non_fit_partition(synthetic_image):
    path, digest = synthetic_image
    case = _case(path, digest)
    case["partition"] = "calibration_validation"
    with pytest.raises(ValueError, match="calibration-fit"):
        validate_case(case)


def test_observation_lineage_dependence_and_provenance(synthetic_image):
    path, digest = synthetic_image
    adapter, requester = _adapter(lambda i, p: _valid_text("fish", multiple_objects="yes"))
    observation, _ = inspect_region(_case(path, digest), adapter, mock=True)
    assert len(requester.calls) == 1
    lineage = observation["lineage"]
    assert lineage["source_image_sha256"] == digest
    assert lineage["original_candidate_id"] == "candidate:x"
    assert lineage["initial_controlled_call_id"] == "controlled:prefix:0001"
    assert observation["dependence"]["statistically_independent_of_initial_evidence_assumed"] is False
    assert observation["dependence"]["likelihood_multiplication_permitted"] is False
    assert observation["backend"]["checkpoint_attested"] is False
    assert observation["prompt"]["sha256"] == PROMPT_SHA256
    assert observation["parsed_observation"]["multiple_objects"] == "yes"
    assert observation["correctness_probability_requested"] is False
    assert "image_sha256" in json.dumps(observation["request"]["payload_redacted"])
    assert "base64" not in json.dumps(observation["request"]["payload_redacted"])


@pytest.mark.parametrize("error,status", [(TimeoutError("t"), "timeout"), (RuntimeError("500"), "execution_failure")])
def test_failures_are_recorded_not_converted(synthetic_image, error, status):
    path, digest = synthetic_image

    def respond(index, payload):
        raise error
    adapter, _ = _adapter(respond)
    observation, response = inspect_region(_case(path, digest), adapter, mock=True)
    assert observation["response_status"] == status
    assert observation["parsed_observation"] is None and response is None


def test_adapter_for_a_different_model_is_rejected(synthetic_image):
    path, digest = synthetic_image
    adapter = ModelAdapter({"alias": "qwen3-vl-2b-instruct", "base": "http://fixture.invalid/v1"},
                           requester=mock_requester(lambda i, p: _valid_text()))
    with pytest.raises(ValueError, match="frozen model"):
        inspect_region(_case(path, digest), adapter, mock=True)


def test_messages_contain_two_images_and_fixed_text(synthetic_image):
    path, digest = synthetic_image
    images, _ = render_region(path, [80, 60, 120, 100], expected_sha256=digest)
    messages = build_messages(images)
    parts = messages[1]["content"]
    assert [part["type"] for part in parts] == ["image_url", "image_url", "text"]
    assert parts[2]["text"] == USER_PROMPT


# ---------------------------------------------------------------- runtime features

def _observation(synthetic_image, respond=lambda i, p: _valid_text("shark"), query="fish", mock=False):
    path, digest = synthetic_image
    adapter, _ = _adapter(respond)
    observation, _ = inspect_region(_case(path, digest, query=query), adapter, mock=mock)
    return observation


def test_features_are_runtime_only_and_categorical(synthetic_image):
    row = extract_features(_observation(synthetic_image))
    assert row["semantic_compatibility"] == "taxonomic_overlap"
    assert row["semantic_compat_taxonomic_overlap"] is True and row["semantic_nonsupport"] is False
    assert not any(key in row for key in ("label", "probability", "confidence", "initial_score"))
    assert row["original_candidate_id"] == "candidate:x"


def test_features_preserve_missingness_on_failure(synthetic_image):
    row = extract_features(_observation(synthetic_image, respond=lambda i, p: "not json"))
    assert row["semantic_parse_failure"] is True and row["semantic_observation_available"] is False
    assert row["semantic_compatibility"] == "unavailable"
    assert row["semantic_object_visible"] is None and row["semantic_object_visible_missing"] is True
    assert row["semantic_object_visible_yes"] is False


def test_features_reject_mock_and_changed_prompt(synthetic_image):
    mock = _observation(synthetic_image, mock=True)
    with pytest.raises(ValueError, match="Mock"):
        extract_features(mock)
    changed = copy.deepcopy(_observation(synthetic_image))
    changed["prompt"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="prompt"):
        extract_features(changed)


def test_labels_join_only_to_unchanged_finalized_table(synthetic_image):
    table = finalize_feature_table([_observation(synthetic_image)])
    digest = table["rows_sha256"]
    labels = [{"state_id": "state:a", "candidate_id": "candidate:x", "label": 1, "endpoint": "0.5"}]
    assert join_offline_labels(table, labels, finalized_rows_sha256=digest)[0]["label"] == 1
    tampered = copy.deepcopy(table)
    tampered["rows"][0]["semantic_nonsupport"] = True
    with pytest.raises(ValueError, match="after finalization"):
        join_offline_labels(tampered, labels, finalized_rows_sha256=digest)
    with pytest.raises(ValueError, match="different candidate"):
        join_offline_labels(table, [{**labels[0], "candidate_id": "candidate:y"}], finalized_rows_sha256=digest)


# ---------------------------------------------------------------- pilot preparation

@pytest.fixture(scope="module")
def manifest():
    return verify_manifest(json.loads((OUTPUT / "semantic_pilot_manifest/manifest.json").read_text()))


def test_manifest_is_fit_only_gt_blind_and_within_cap(manifest):
    selection = json.loads((EXPANSION / "sample_selection_manifest.json").read_text())
    cohort = selection["selected_source_groups"]
    assert manifest["selected_source_groups"] == select_groups(cohort, count=15, seed=465)
    assert set(manifest["selected_source_groups"]) <= set(cohort)
    assert manifest["case_count"] == len(manifest["cases"]) <= manifest["dispatch_cap"] == 105
    assert {case["source_group_id"] for case in manifest["cases"]} <= set(manifest["selected_source_groups"])
    assert manifest["selection"]["uses_ground_truth"] is False
    assert manifest["selection"]["uses_phase04c1a_label_balanced_folds"] is False
    assert manifest["validation_or_internal_test_cases"] == 0
    for case in manifest["cases"]:
        validate_case(case)
        assert file_digest(ROOT / case["source_image_path"]) == case["source_image_sha256"]
    assert len({case["case_id"] for case in manifest["cases"]}) == manifest["case_count"]


def test_group_selection_is_deterministic_and_seed_dependent():
    groups = [f"g{i:02d}" for i in range(30)]
    assert select_groups(groups) == select_groups(list(reversed(groups)))
    assert select_groups(groups, seed=1) != select_groups(groups, seed=2)


def test_dispatch_cap_rule_is_label_free():
    cases = [{"state_id": f"state:{i}"} for i in range(10)]
    kept, dropped = apply_dispatch_cap(cases, cap=4, seed=7)
    assert len(kept) == 4 and len(dropped) == 6
    ranked = sorted(cases, key=lambda c: hashlib.sha256(f"7:{c['state_id']}".encode()).hexdigest())
    assert {c["state_id"] for c in kept} == {c["state_id"] for c in ranked[:4]}


def test_guarded_reader_refuses_offline_label_paths(tmp_path):
    path = tmp_path / "offline_labels" / "x.json"
    path.parent.mkdir()
    path.write_text("{}")
    with pytest.raises(PermissionError):
        _guarded_read_json(path)


def _small_manifest(synthetic_image, count=3):
    path, digest = synthetic_image
    cases = []
    for index in range(count):
        case = _case(path, digest, state=f"state:{index}")
        case["source_image_path"] = str(path)
        cases.append(case)
    manifest = {
        "schema_version": "bite.semantic_pilot_manifest.v1", "dispatch_cap": count, "cases": cases,
        "frozen_contract": json.loads((OUTPUT / "semantic_pilot_manifest/manifest.json").read_text())["frozen_contract"],
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    return manifest


def test_live_mode_requires_bound_authorization(synthetic_image, tmp_path):
    manifest = _small_manifest(synthetic_image)
    adapter, requester = _adapter()
    with pytest.raises(PermissionError):
        run_pilot(manifest, adapter, tmp_path / "run", root=Path("/"), mode="live")
    authorization = {"live_semantic_inference_authorized": True, "manifest_sha256": "0" * 64,
                     "prompt_sha256": PROMPT_SHA256, "model_alias": "qwen3-vl-8b-instruct",
                     "authorized_by": "x", "dispatch_cap": 3}
    with pytest.raises(PermissionError, match="manifest"):
        validate_authorization(authorization, manifest)
    authorization["manifest_sha256"] = manifest["manifest_sha256"]
    authorization["dispatch_cap"] = 4
    with pytest.raises(PermissionError, match="cap"):
        validate_authorization(authorization, manifest)
    assert requester.calls == []


def test_dry_run_refuses_a_network_adapter(synthetic_image, tmp_path):
    manifest = _small_manifest(synthetic_image)
    network = build_adapter("http://127.0.0.1:9/v1")
    with pytest.raises(PermissionError, match="local requester"):
        run_pilot(manifest, network, tmp_path / "run", root=Path("/"), mode="mock_dry_run")


def test_mock_run_is_resumable_idempotent_and_detects_corruption(synthetic_image, tmp_path):
    manifest = _small_manifest(synthetic_image)
    adapter, requester = _adapter()
    first = run_pilot(manifest, adapter, tmp_path / "run", root=Path("/"), mode="mock_dry_run")
    assert first["dispatched"] == 3 and len(requester.calls) == 3
    again = run_pilot(manifest, adapter, tmp_path / "run", root=Path("/"), mode="mock_dry_run", resume=True)
    assert again["dispatched"] == 0 and len(requester.calls) == 3
    with pytest.raises(FileExistsError):
        run_pilot(manifest, adapter, tmp_path / "run", root=Path("/"), mode="mock_dry_run")
    target = next((tmp_path / "run/states").glob("*/semantic_observation.json"))
    target.write_text(target.read_text().replace("scripted", "edited") + " ")
    with pytest.raises(RuntimeError, match="corrupt"):
        run_pilot(manifest, adapter, tmp_path / "run", root=Path("/"), mode="mock_dry_run", resume=True)
    events = [json.loads(line) for line in (target.parent / "stage_events.jsonl").read_text().splitlines()]
    assert [event["event"] for event in events] == ["runtime_started", "raw_finalized"]
    assert events[1]["previous_event_sha256"] == events[0]["event_sha256"]


def test_tampered_manifest_is_refused(manifest):
    tampered = copy.deepcopy(manifest)
    tampered["cases"] = tampered["cases"][:-1]
    with pytest.raises(ValueError, match="digest"):
        verify_manifest(tampered)


def test_mock_contract_report_and_execution_plan(manifest):
    report = json.loads((OUTPUT / "semantic_observation_contract/mock_contract_report.json").read_text())
    assert report["status"] == "MOCK_ONLY_NO_MODEL_CALLED" and report["network_requests"] == 0
    assert report["resume_idempotent"] and report["payload_text_identical_across_cases"]
    assert report["redacted_payload_mentions_score"] is False
    assert report["mock_requests_issued"] == manifest["case_count"]
    plan = json.loads((OUTPUT / "execution_readiness/semantic_pilot_execution_plan.json").read_text())
    assert plan["status"] == "PREPARED_LIVE_INFERENCE_NOT_AUTHORIZED"
    assert plan["manifest_sha256"] == manifest["manifest_sha256"]
    assert plan["output_location"].startswith("outputs/bite/phase04c1f/")
    assert "--output outputs/bite/phase04c1f/" in plan["live_command"]


# ---------------------------------------------------------------- comparison design

def _synthetic_comparison_rows(signal, seed=3):
    rng = random.Random(seed)
    rows = []
    for group in range(15):
        for index in range(7):
            label = int(rng.random() < .2)
            score = min(1, max(0, .7 + .1 * label + rng.gauss(0, .1)))
            informative = rng.random() < signal
            match = bool(label) if informative else rng.random() < .3
            rows.append({
                "state_id": f"s{group}-{index}", "source_group_id": f"g{group}", "query": "fish",
                "label": label, "initial_score": score, "score_difference": rng.gauss(0, .05),
                "score_change_observed": True, "association_ambiguous": False, "association_no_alignment": False,
                "semantic_compat_match": match, "semantic_nonsupport": not match,
                "semantic_observation_available": True, "semantic_region_localization_adequate": rng.random() < .5,
            })
    return rows


def test_injected_semantic_signal_is_detected_and_null_is_not_rewarded():
    strong = evaluate_comparisons(logo_crossfit(_synthetic_comparison_rows(.95)), replicates=200)
    null = evaluate_comparisons(logo_crossfit(_synthetic_comparison_rows(0.0)), replicates=200)
    key = f"ms_semantic_minus_{BASELINE}"
    assert strong[key]["brier_difference_upper_97_5"] < 0
    assert null[key]["brier_difference"] > strong[key]["brier_difference"]
    assert null[key]["brier_difference_lower_2_5"] < 0.005 < null[key]["brier_difference_upper_97_5"] + 0.005


def test_logo_predictions_never_use_the_held_out_group():
    rows = _synthetic_comparison_rows(.5)
    baseline = logo_crossfit(rows, model_names=(BASELINE,))
    perturbed = copy.deepcopy(rows)
    for row in perturbed:
        if row["source_group_id"] == "g0":
            row["label"] = 1 - row["label"]
    changed = logo_crossfit(perturbed, model_names=(BASELINE,))
    for before, after in zip(baseline, changed, strict=True):
        if before["source_group_id"] == "g0":
            assert before["probabilities"] == after["probabilities"]


def test_design_is_frozen_and_decision_rule_is_prespecified():
    stored = json.loads((OUTPUT / "semantic_pilot_manifest/paired_comparison_design.json").read_text())
    assert stored == design_record()
    assert stored["fitting"]["frozen_full_fit_prior_used_as_oof_baseline"] is False
    assert classify_pilot(.8, {"0.5": -.01, "0.75": -.01}) == "REVISE_CONTRACT_AS_NEW_VERSION"
    assert classify_pilot(.95, {"0.5": -.01, "0.75": -.01}) == "PROCEED_TO_LARGER_FIT_COLLECTION"
    assert classify_pilot(.95, {"0.5": .01, "0.75": 0.0}) == "STOP_SEMANTIC_ACTION_FOR_TASK_V"
    assert classify_pilot(.95, {"0.5": -.01, "0.75": .01}) == "INCONCLUSIVE"


# ---------------------------------------------------------------- regression

def _verify_inventory(mapping):
    mismatched = [path for path, digest in mapping.items() if file_digest(ROOT / path) != digest]
    assert mismatched == []


def test_phase04c1d_artifacts_and_frozen_priors_unchanged():
    checksums = json.loads((ROOT / "outputs/bite/phase04c1d/manifest_checksums.json").read_text())
    _verify_inventory(checksums["artifact_sha256"])
    prior_manifest = json.loads((ROOT / "outputs/bite/phase04c1c_revised/implementation_manifest.json").read_text())
    _verify_inventory({k: v for k, v in prior_manifest["artifact_sha256"].items() if "frozen_priors" in k})


def test_human_reviews_preserved():
    status = json.loads((ROOT / "outputs/bite/phase04c1c_revised/optional_human_reviews/status.json").read_text())
    assert status["validated_finalized_review_count"] == 20
    completed = list((ROOT / "outputs/bite/phase04b2b4/human_adjudications/completed").glob("*.json"))
    assert len(completed) == 20


def test_production_agent_evaluator_and_partitions_untouched():
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", "openvlharness", "evaluation_kit/runner.py",
         "evaluation_kit/cli.py", "evaluation_kit/tools.py", "evaluation_kit/dataset", "run_benchmark.py",
         "configs", "docs/bite/dataset_source_registry_v1.json"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert result.stdout == ""


def test_semantic_modules_never_open_a_network_client_at_import():
    import evaluation_kit.bite_calibration.semantic_region_action as action
    source = Path(action.__file__).read_text()
    assert "requests.post" not in source and "AuxiliaryModel" not in source
    assert np.isfinite(0.0)
