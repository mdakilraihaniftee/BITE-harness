import copy
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image

from evaluation_kit.bite_calibration.paired_zoom_evaluation import paired_difference
from evaluation_kit.bite_calibration.semantic_feature_extractor import (
    finalize_feature_table,
)
from evaluation_kit.bite_calibration.semantic_observation_schema import (
    ONTOLOGY_SHA256,
    PROMPT_SHA256,
    canonical_sha256,
)
from evaluation_kit.bite_calibration.semantic_pilot_analysis import (
    LOGICAL_COST,
    canonical_targets,
    evaluate_endpoint,
    failure_analysis,
    join_rows,
    research_decision,
    support,
    validate_observations,
)
from evaluation_kit.bite_calibration.semantic_pilot_preflight import (
    smart_resize_tokens,
    verify_frozen_pilot,
)
from evaluation_kit.bite_calibration.semantic_pilot_protocol import (
    mock_requester,
    run_pilot,
    validate_live_binding,
)
from evaluation_kit.bite_calibration.semantic_region_action import (
    build_adapter,
    inspect_region,
    render_region,
)
from evaluation_kit.bite_calibration.zoom_conditional_protocol import read_jsonl
from evaluation_kit.bite_collection.resume import file_digest
from openvlharness.services.models import ModelAdapter

ROOT = Path(__file__).resolve().parents[2]
PHASE04C1E = ROOT / "outputs/bite/phase04c1e"
OUTPUT = ROOT / "outputs/bite/phase04c1f"
ENDPOINT = "http://127.0.0.1:8222/v1"
MODEL_ID = "Qwen/Qwen3-VL-8B-Instruct"


def _valid_text(content="fish"):
    return json.dumps({
        "region_content": content, "object_visible": "yes", "region_localization": "adequate",
        "multiple_objects": "no", "evidence_status": "supported", "short_visual_description": "x",
    })


def _served(respond, model=MODEL_ID):
    calls = []

    def requester(payload):
        calls.append(payload)
        text = respond(len(calls) - 1)
        return {"model": model, "choices": [{"message": {"role": "assistant", "content": text},
                                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 60, "total_tokens": 1060}}
    requester.calls = calls
    return requester


@pytest.fixture()
def small_manifest(tmp_path):
    image = Image.new("RGB", (160, 120), (30, 60, 90))
    path = tmp_path / "image.png"
    image.save(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    cases = [{
        "case_id": f"semantic_case:{index}", "state_id": f"state:{index}", "source_group_id": f"sha256:g{index}",
        "source_entry_id": "entry", "partition": "calibration_fit", "query": "fish",
        "source_image_sha256": digest, "source_image_path": str(path), "image_width": 160, "image_height": 120,
        "original_candidate_id": "candidate:local", "candidate_bbox_root_xyxy": [40, 30, 90, 80],
        "initial_observation_id": "joint_observation:x", "initial_controlled_call_id": "controlled:prefix:0001",
        "initial_action_id": "action:x", "parent_snapshot_id": "snapshot:x",
    } for index in range(5)]
    render = render_region(path, [40, 30, 90, 80], expected_sha256=digest)[1]["render_sha256"]
    for case in cases:
        case["region_render_sha256"] = render
    manifest = {
        "schema_version": "bite.semantic_pilot_manifest.v1", "source_cohort": "cohort:test",
        "dispatch_cap": 5, "case_count": 5, "cases": cases,
        "frozen_contract": {"prompt_sha256": PROMPT_SHA256, "ontology_sha256": ONTOLOGY_SHA256},
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    return manifest


def _authorization(manifest, run_dir, **overrides):
    value = {
        "live_semantic_inference_authorized": True, "authorized_by": "Researcher",
        "manifest_sha256": manifest["manifest_sha256"], "prompt_sha256": PROMPT_SHA256,
        "ontology_sha256": ONTOLOGY_SHA256, "model_alias": "qwen3-vl-8b-instruct", "model_id": MODEL_ID,
        "endpoint": ENDPOINT + "/chat/completions", "output_dir": str(run_dir), "dispatch_cap": 5,
    }
    value.update(overrides)
    return value


def _live(manifest, run_dir, respond=lambda i: _valid_text(), authorization=None, **kwargs):
    requester = _served(respond, **kwargs)
    adapter = build_adapter(ENDPOINT, requester=requester)
    return adapter, requester, authorization or _authorization(manifest, run_dir)


# ---------------------------------------------------------------- authorization gate

def test_missing_authorization_blocks_live_calls(small_manifest, tmp_path):
    adapter, requester, _ = _live(small_manifest, tmp_path / "run")
    with pytest.raises(PermissionError):
        run_pilot(small_manifest, adapter, tmp_path / "run", root=Path("/"), mode="live")
    assert requester.calls == []


@pytest.mark.parametrize("field,value,message", [
    ("manifest_sha256", "0" * 64, "manifest"),
    ("ontology_sha256", "0" * 64, "ontology"),
    ("model_id", "Qwen/Qwen3-VL-2B-Instruct", "model id"),
    ("endpoint", "http://127.0.0.1:9999/v1/chat/completions", "endpoint"),
    ("output_dir", "/elsewhere", "output directory"),
    ("dispatch_cap", 6, "cap"),
    ("live_semantic_inference_authorized", False, "live_semantic"),
    ("valid_until_utc", (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "expired"),
])
def test_mismatched_authorization_blocks_live_calls(small_manifest, tmp_path, field, value, message):
    run = tmp_path / "run"
    adapter, requester, authorization = _live(small_manifest, run)
    authorization[field] = value
    with pytest.raises(PermissionError, match=message):
        run_pilot(small_manifest, adapter, run, root=Path("/"), mode="live", authorization=authorization)
    assert requester.calls == [] and not run.exists()


def test_wrong_backend_and_non_loopback_endpoint_are_blocked(small_manifest, tmp_path):
    run = tmp_path / "run"
    wrong = ModelAdapter({"alias": "qwen3-vl-2b-instruct", "base": ENDPOINT}, requester=_served(lambda i: ""))
    with pytest.raises(PermissionError, match="model id"):
        validate_live_binding(_authorization(small_manifest, run), small_manifest, wrong, run, root=Path("/"))
    remote = build_adapter("https://vlm.example.org/v1", requester=_served(lambda i: ""))
    authorization = _authorization(small_manifest, run, endpoint=remote.endpoint)
    with pytest.raises(PermissionError, match="Non-loopback"):
        validate_live_binding(authorization, small_manifest, remote, run, root=Path("/"))


def test_authorization_requirements_file_is_not_itself_an_authorization(small_manifest, tmp_path):
    requirements = json.loads((OUTPUT / "authorization/authorization_requirements.json").read_text())
    status = json.loads((OUTPUT / "authorization/status.json").read_text())
    assert status["status"] == "AUTHORIZATION_ABSENT" and status["vlm_calls"] == 0
    manifest = json.loads((PHASE04C1E / "semantic_pilot_manifest/manifest.json").read_text())
    template = requirements["required_fields"]
    assert template["manifest_sha256"] == manifest["manifest_sha256"] and len(template["manifest_sha256"]) == 64
    adapter = build_adapter(ENDPOINT, requester=_served(lambda i: ""))
    with pytest.raises(PermissionError):
        validate_live_binding(template, manifest, adapter, ROOT / template["output_dir"], root=ROOT)


# ---------------------------------------------------------------- execution

def test_live_run_records_authorization_identity_and_scoped_identity(small_manifest, tmp_path):
    run = tmp_path / "run"
    adapter, requester, authorization = _live(small_manifest, run)
    summary = run_pilot(small_manifest, adapter, run, root=Path("/"), mode="live", authorization=authorization)
    assert summary["dispatched"] == 5 and len(requester.calls) == 5
    configuration = json.loads((run / "run_configuration.json").read_text())["configuration"]
    assert configuration["authorization_sha256"] == canonical_sha256(authorization)
    observation = json.loads(next((run / "states").glob("*/semantic_observation.json")).read_text())
    context = observation["execution_context"]
    assert context["mode"] == "live" and context["authorization_sha256"] == canonical_sha256(authorization)
    assert context["scoped_identity"]["state_id"] == observation["state_id"]
    assert context["scoped_identity"]["action_version"] == "semantic_region_inspect_v1"
    assert observation["backend"]["served_model_reported"] == MODEL_ID


def test_canary_counts_toward_a_cumulative_cap(small_manifest, tmp_path):
    run = tmp_path / "run"
    adapter, requester, authorization = _live(small_manifest, run)
    authorization["dispatch_cap"] = 3
    canary = run_pilot(small_manifest, adapter, run, root=Path("/"), mode="live", authorization=authorization,
                       max_new_dispatches=2, run_phase="canary")
    assert canary["dispatched"] == 2
    main = run_pilot(small_manifest, adapter, run, root=Path("/"), mode="live", authorization=authorization,
                     resume=True)
    assert main["dispatched"] == 1 and main["complete_before_run"] == 2
    again = run_pilot(small_manifest, adapter, run, root=Path("/"), mode="live", authorization=authorization,
                      resume=True)
    assert again["dispatched"] == 0 and len(requester.calls) == 3


def test_canary_size_is_limited(small_manifest, tmp_path):
    adapter, _, authorization = _live(small_manifest, tmp_path / "run")
    with pytest.raises(ValueError, match="canary"):
        run_pilot(small_manifest, adapter, tmp_path / "run", root=Path("/"), mode="live",
                  authorization=authorization, max_new_dispatches=6, run_phase="canary")


def test_consecutive_failures_halt_and_are_preserved_and_counted(small_manifest, tmp_path):
    run = tmp_path / "run"

    def respond(index):
        raise TimeoutError("server down")
    adapter, requester, authorization = _live(small_manifest, run, respond=respond)
    with pytest.raises(RuntimeError, match="consecutive"):
        run_pilot(small_manifest, adapter, run, root=Path("/"), mode="live", authorization=authorization)
    observations = [json.loads(p.read_text()) for p in (run / "states").glob("*/semantic_observation.json")]
    assert len(observations) == 3 and {o["response_status"] for o in observations} == {"timeout"}
    assert json.loads((run / "run_summary.json").read_text())["halted"] is True
    adapter2, requester2, _ = _live(small_manifest, run)
    summary = run_pilot(small_manifest, adapter2, run, root=Path("/"), mode="live",
                        authorization=authorization, resume=True)
    assert summary["complete_before_run"] == 3 and summary["dispatched"] == 2
    assert len(requester.calls) + len(requester2.calls) == 5


def test_served_model_mismatch_halts_after_persisting(small_manifest, tmp_path):
    run = tmp_path / "run"
    adapter, requester, authorization = _live(small_manifest, run, model="other/model")
    with pytest.raises(RuntimeError, match="server reported model"):
        run_pilot(small_manifest, adapter, run, root=Path("/"), mode="live", authorization=authorization)
    assert len(requester.calls) == 1
    assert len(list((run / "states").glob("*/raw_completion.json"))) == 1


def test_partial_case_blocks_all_further_dispatch(small_manifest, tmp_path):
    run = tmp_path / "run"
    adapter, requester, authorization = _live(small_manifest, run)
    run_pilot(small_manifest, adapter, run, root=Path("/"), mode="live", authorization=authorization,
              max_new_dispatches=1, run_phase="canary")
    crashed = run / "states" / small_manifest["cases"][3]["case_id"].replace(":", "_")
    crashed.mkdir(parents=True)
    (crashed / "stage_events.jsonl").write_text("{}\n")
    with pytest.raises(RuntimeError, match="partial"):
        run_pilot(small_manifest, adapter, run, root=Path("/"), mode="live", authorization=authorization,
                  resume=True)
    assert len(requester.calls) == 1


# ---------------------------------------------------------------- frozen pilot integrity

def test_preflight_integrity_artifacts():
    report = json.loads((OUTPUT / "preflight/pilot_integrity.json").read_text())
    assert report["status"] == "PASS" and report["failed_checks"] == []
    assert report["source_group_count"] == 15 and report["case_count"] == 101
    assert report["in_group_initial_states"] == 105 and len(report["no_candidate_state_ids"]) == 4
    assert report["checks"]["no_candidate_state_dispatched"] is False
    assert report["identifier_safety"]["candidate_id_alone_is_a_safe_join_key"] is False
    assert report["checks"]["scoped_identities_unique"] is True
    assert report["frozen_artifacts_unchanged"] is True
    for digest in (report["manifest_sha256"], report["prompt_sha256"], report["ontology_sha256"],
                   report["design_sha256"]):
        assert len(digest) == 64
    rows = read_jsonl(OUTPUT / "preflight/case_identity.jsonl")
    assert len(rows) == 101 and not any(row["initial_score_sent_to_model"] for row in rows)
    assert len({canonical_sha256(row["scoped_identity"]) for row in rows}) == 101


def test_preflight_rejects_a_tampered_frozen_case():
    manifest = json.loads((PHASE04C1E / "semantic_pilot_manifest/manifest.json").read_text())
    tampered = copy.deepcopy(manifest)
    tampered["cases"][0]["candidate_bbox_root_xyxy"][0] += 5
    tampered["manifest_sha256"] = canonical_sha256({k: v for k, v in tampered.items() if k != "manifest_sha256"})
    selection = json.loads((ROOT / "outputs/bite/phase04b2b3/expansion/aquarium_task_v_expansion_seed418_g30/"
                                   "sample_selection_manifest.json").read_text())
    runtime = read_jsonl(ROOT / "outputs/bite/phase04c1d/runtime_features/expansion_runtime_features_v1.jsonl")
    with pytest.raises(ValueError, match="differs from its stored state"):
        verify_frozen_pilot(tampered, root=ROOT,
                            run_dir="outputs/bite/phase04b2b3/expansion/aquarium_task_v_expansion_seed418_g30",
                            selection=selection, runtime_rows=runtime)


def test_backend_readiness_records_provenance_limits_without_secrets():
    backend = json.loads((OUTPUT / "preflight/backend_readiness.json").read_text())
    assert backend["configured_model_id"] == MODEL_ID
    assert backend["endpoint"]["loopback"] is True and backend["greedy_decoding"] is True
    assert backend["adapter_transport_retries"] == 0
    assert backend["weights"]["load_time_identity"].startswith("UNVERIFIED")
    assert backend["semantic_action_uses_image_host_or_tunnel"] is False
    assert set(backend["endpoint"]) == {"source", "configured", "resolved_chat_completions_url", "host", "port",
                                        "loopback", "api_key_configured", "port_listening"}
    assert isinstance(backend["endpoint"]["api_key_configured"], bool)


def test_smart_resize_token_rule():
    assert smart_resize_tokens(768, 1024, min_pixels=65536, max_pixels=16777216) == 768
    assert smart_resize_tokens(40, 40, min_pixels=65536, max_pixels=16777216) >= 64


# ---------------------------------------------------------------- analysis (synthetic only)

def _observation(tmp_path, small_manifest, index, text, *, live=True):
    case = small_manifest["cases"][index]
    adapter = build_adapter(ENDPOINT, requester=mock_requester(lambda i, p: text))
    observation, _ = inspect_region(case, adapter, mock=not live)
    observation["execution_context"] = {"mode": "live" if live else "mock_dry_run"}
    return observation


def test_validate_observations_enforces_frozen_lineage(tmp_path, small_manifest):
    observations = [_observation(tmp_path, small_manifest, i, _valid_text()) for i in range(4)]
    report = validate_observations(observations, small_manifest)
    assert report["missing_case_ids"] == [small_manifest["cases"][4]["case_id"]] and not report["complete"]
    with pytest.raises(ValueError, match="Duplicate"):
        validate_observations(observations + observations[:1], small_manifest)
    bad = copy.deepcopy(observations[0])
    bad["lineage"]["region_render"]["render_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="lineage"):
        validate_observations([bad], small_manifest)
    with pytest.raises(ValueError, match="live"):
        validate_observations([_observation(tmp_path, small_manifest, 0, _valid_text(), live=False)], small_manifest)


def test_label_join_uses_state_scope_and_finalized_digest(tmp_path, small_manifest):
    observations = [_observation(tmp_path, small_manifest, i, _valid_text()) for i in range(5)]
    table = finalize_feature_table(observations)
    targets = {c["state_id"]: {"state_id": c["state_id"], "candidate_id": "candidate:local", "label": i % 2,
                               "endpoint": "0.5", "annotation_scope_audit": "no_annotated_queried_class_instance"}
               for i, c in enumerate(small_manifest["cases"])}
    zoom = [{"state_id": c["state_id"], "original_candidate_id": "candidate:local", "initial_score": .7,
             "score_difference": 0.0, "score_change_observed": True, "association_ambiguous": False,
             "association_no_alignment": False} for c in small_manifest["cases"]]
    rows = join_rows(table, table["rows_sha256"], targets, zoom)
    assert [r["label"] for r in rows] == [targets[r["state_id"]]["label"] for r in rows]
    zoom[0]["original_candidate_id"] = "candidate:other"
    with pytest.raises(ValueError, match="different candidate"):
        join_rows(table, table["rows_sha256"], targets, zoom)
    tampered = copy.deepcopy(table)
    tampered["rows"][0]["semantic_nonsupport"] = True
    with pytest.raises(ValueError, match="after finalization"):
        join_rows(tampered, table["rows_sha256"], targets, zoom)


def test_canonical_targets_use_one_m0_row_per_state():
    rows = [{"model_name": name, "state_id": "s", "candidate_id": "c", "label": 1, "endpoint": "0.5",
             "annotation_scope_audit": "x"} for name in ("initial_score_only_m0", "zoom_restricted_m1")]
    assert canonical_targets(rows) == {"s": {"state_id": "s", "candidate_id": "c", "label": 1,
                                             "endpoint": "0.5", "annotation_scope_audit": "x"}}
    with pytest.raises(ValueError, match="Duplicate"):
        canonical_targets(rows + rows[:1])


def _analysis_rows(signal, groups=15, per_group=7, seed=11, positive_groups=None):
    rng = random.Random(seed)
    rows = []
    for group in range(groups):
        for index in range(per_group):
            allowed = positive_groups is None or group in positive_groups
            label = int(allowed and rng.random() < .25)
            match = bool(label) if rng.random() < signal else rng.random() < .3
            rows.append({
                "state_id": f"s{group}-{index}", "source_group_id": f"g{group}", "query": "fish",
                "endpoint": "0.5", "label": label, "initial_score": min(1, max(0, .7 + .1 * label + rng.gauss(0, .1))),
                "score_difference": rng.gauss(0, .05), "score_change_observed": True,
                "association_ambiguous": False, "association_no_alignment": False,
                "semantic_compat_match": match, "semantic_nonsupport": not match,
                "semantic_observation_available": True, "semantic_region_localization_adequate": True,
                "semantic_response_status": "valid", "semantic_compatibility": "match" if match else "background",
                "semantic_object_visible": "yes", "semantic_region_localization": "adequate",
                "semantic_multiple_objects": "no", "semantic_evidence_status": "supported",
                "annotation_scope_audit": "annotated_or_other_diagnostic" if label else "no_annotated_queried_class_instance",
            })
    return rows


def test_evaluation_preserves_population_and_uses_paired_grouped_differences():
    rows = _analysis_rows(.9)
    result = evaluate_endpoint(rows, replicates=200)
    assert result["status"] == "ESTIMATED" and len(result["predictions"]) == len(rows)
    aligned = result["predictions"]
    contrast = result["paired_uncertainty"]["contrasts"]["ms_semantic_minus_m0_initial_score"]
    brier = contrast["case_level"]["brier_score"]["observed_difference"]
    assert brier == pytest.approx(result["primary_brier_difference"])
    assert contrast["case_level"]["log_loss"]["observed_difference"] == pytest.approx(
        paired_difference(aligned, "ms_semantic", "m0_initial_score", "log_loss"))
    assert result["paired_uncertainty"]["candidate_rows_resampled_iid"] is False
    assert result["paired_uncertainty"]["seed"] == 467
    assert "ms_semantic_minus_mz_zoom" in result["paired_uncertainty"]["contrasts"]
    for model, cost in LOGICAL_COST.items():
        assert result["decision_screens"][model]["additional_logical_calls"] == cost * len(rows)
    assert result["primary_brier_difference"] < 0


def test_sparse_positive_support_is_non_estimable_and_inconclusive():
    rows = _analysis_rows(.9, positive_groups={3})
    counts = support(rows)
    assert counts["groups_with_positives"] <= 1 and counts["logo_estimable"] is False
    result = evaluate_endpoint(rows, replicates=50)
    assert result["status"] == "NON_ESTIMABLE"
    decision = research_decision(1.0, {"0.5": result, "0.75": result})
    assert decision["decision"] == "INCONCLUSIVE" and decision["larger_collection_authorized"] is False


def test_guard_overlay_downgrades_fragile_proceed():
    estimated = evaluate_endpoint(_analysis_rows(.9), replicates=100)
    fragile = copy.deepcopy(estimated)
    fragile["support"]["groups_with_positives"] = 2
    decision = research_decision(1.0, {"0.5": estimated, "0.75": fragile})
    assert decision["frozen_rule_outcome"] == "PROCEED_TO_LARGER_FIT_COLLECTION"
    assert decision["decision"] == "INCONCLUSIVE" and decision["guard_overlay_failures"]
    assert research_decision(.5, {"0.5": estimated, "0.75": estimated})["decision"] == "REVISE_CONTRACT_AS_NEW_VERSION"


def test_failure_analysis_strata_distinguish_annotation_absence():
    rows = _analysis_rows(.5)
    rows[0]["label"] = 0
    rows[0]["annotation_scope_audit"] = "annotated_or_other_diagnostic"
    analysis = failure_analysis(rows)
    assert set(analysis["stratum_counts"]) <= {
        "annotation_positive", "negative_no_queried_class_annotation", "negative_queried_class_annotated_or_other"}
    assert analysis["stratum_counts"]["negative_queried_class_annotated_or_other"] >= 1
    assert analysis["annotation_absence_treated_as_visual_absence"] is False


# ---------------------------------------------------------------- regression

def test_phase04c1e_artifacts_unchanged():
    inventory = json.loads((PHASE04C1E / "manifest_checksums.json").read_text())["artifact_sha256"]
    assert [p for p, d in inventory.items() if file_digest(ROOT / p) != d] == []


def test_no_semantic_run_or_results_exist_without_authorization():
    assert not (OUTPUT / "raw_observations").exists()
    for name in ("crossfit_predictions", "paired_metrics", "grouped_uncertainty", "offline_labels"):
        assert not (OUTPUT / name).exists()


def test_sample_size_sensitivity_depends_on_assumptions():
    from evaluation_kit.bite_calibration.action_utility_screen import sample_size_sensitivity
    result = sample_size_sensitivity([0.0] * 29 + [1 / 7])
    grid = {row["epsilon"]: row for row in result["precision_grid"]}
    assert grid[0.005]["hoeffding_groups"] == 239659 and grid[0.1]["hoeffding_groups"] == 600
    assert grid[0.005]["empirical_bernstein_groups_at_observed_sd"] < grid[0.005]["hoeffding_groups"]
    assert result["normal_approximation_has_finite_sample_guarantee"] is False
    assert result["universal_requirement_claimed"] is False
    stored = json.loads((OUTPUT / "research_decision/sample_size_sensitivity.json").read_text())
    assert stored["observed_group_count"] == 30


def test_measured_zoom_costs_cover_every_branch():
    costs = json.loads((OUTPUT / "preflight/zoom_measured_costs.json").read_text())
    assert costs["all_expansion_states"]["zoom_total_two_dispatches"]["count"] == 203
    assert costs["semantic_pilot_states"]["zoom_total_two_dispatches"]["count"] == 101
    assert costs["all_expansion_states"]["initial_sam3_grounding"]["count"] == 210
