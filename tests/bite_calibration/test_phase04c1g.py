import copy
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation_kit.bite_calibration.branch_evidence_renderer import (
    RENDERER_SHA256,
    render_branch,
    renderer_contract,
)
from evaluation_kit.bite_calibration.learnable_headroom import (
    learnable_headroom,
    logo_selections,
    validate_features,
)
from evaluation_kit.bite_calibration.oracle_headroom import (
    best_fixed,
    group_bootstrap,
    headroom_statistics,
    oracle_headroom,
    oracle_value,
)
from evaluation_kit.bite_calibration.semantic_observation_schema import canonical_sha256
from evaluation_kit.bite_calibration.semantic_pilot_protocol import (
    _guarded_read_json,
    mock_requester,
    run_pilot,
)
from evaluation_kit.bite_calibration.semantic_region_action import (
    build_adapter as semantic_adapter,
)
from evaluation_kit.bite_calibration.task_level_branch_runner import (
    build_adapter,
    build_count_labels,
    finalize_outcomes,
    join_outcomes,
    load_count_labels,
    official_count,
    run_branches,
)
from evaluation_kit.bite_calibration.task_level_decision_analysis import (
    classify,
    combined_evidence,
    transitions,
)
from evaluation_kit.bite_calibration.task_level_probe_protocol import (
    BRANCHES,
    INCREMENTAL_LOGICAL_COST,
    PARSER_SHA256,
    PRECALL_FEATURES,
    PROMPT_SHA256,
    _leaked_keys,
    build_task_manifest,
    common_footer,
    common_header,
    parse_count,
    validate_branch_authorization,
    verify_task_manifest,
)
from evaluation_kit.bite_collection.resume import file_digest

ROOT = Path(__file__).resolve().parents[2]
PHASE = ROOT / "outputs/bite/phase04c1g"
RUN_DIR = "outputs/bite/phase04b2b3/expansion/aquarium_task_v_expansion_seed418_g30"
SEMANTIC_MANIFEST_PATH = "outputs/bite/phase04c1e/semantic_pilot_manifest/manifest.json"
ENDPOINT_BASE = "http://127.0.0.1:8222/v1"
MODEL_ID = "Qwen/Qwen3-VL-8B-Instruct"


@pytest.fixture(scope="module")
def semantic_manifest():
    return json.loads((ROOT / SEMANTIC_MANIFEST_PATH).read_text())


@pytest.fixture(scope="module")
def manifest():
    return verify_task_manifest(json.loads((PHASE / "task_manifest/task_manifest.json").read_text()))


def _sub_manifest(manifest, count):
    sub = copy.deepcopy(manifest)
    sub["tasks"] = sub["tasks"][:count]
    sub["manifest_sha256"] = canonical_sha256({k: v for k, v in sub.items() if k != "manifest_sha256"})
    return sub


def _sub_semantic(semantic_manifest, manifest):
    keep = {task["semantic_case_id"] for task in manifest["tasks"]}
    sub = copy.deepcopy(semantic_manifest)
    sub["cases"] = [case for case in sub["cases"] if case["case_id"] in keep]
    sub["case_count"] = len(sub["cases"])
    sub["manifest_sha256"] = canonical_sha256({k: v for k, v in sub.items() if k != "manifest_sha256"})
    return sub


def _semantic_text(content="starfish"):
    return json.dumps({"region_content": content, "object_visible": "yes", "region_localization": "adequate",
                       "multiple_objects": "no", "evidence_status": "supported",
                       "short_visual_description": "an orange sea star"})


@pytest.fixture()
def mock_semantic_run(tmp_path, manifest, semantic_manifest):
    sub = _sub_manifest(manifest, 2)
    sem = _sub_semantic(semantic_manifest, sub)
    run = tmp_path / "semantic_run"
    adapter = semantic_adapter("http://mock.invalid/v1", requester=mock_requester(lambda i, p: _semantic_text()))
    run_pilot(sem, adapter, run, root=ROOT, mode="mock_dry_run")
    return sub, sem, run


# ----------------------------------------------------------------- task construction

def test_task_manifest_reproduces_from_stored_states(manifest, semantic_manifest):
    rebuilt = build_task_manifest(semantic_manifest, root=ROOT, run_dir=RUN_DIR,
                                  semantic_manifest_path=SEMANTIC_MANIFEST_PATH, renderer_contract=renderer_contract())
    assert rebuilt["manifest_sha256"] == manifest["manifest_sha256"]
    tasks = manifest["tasks"]
    assert len(tasks) == 101
    assert len({t["source_group_id"] for t in tasks}) == 15
    assert len({t["task_id"] for t in tasks}) == 101
    assert {t["partition"] for t in tasks} == {"calibration_fit"}
    assert manifest["population"]["in_group_initial_states"] == 105
    assert len(manifest["population"]["excluded_no_candidate_state_ids"]) == 4
    assert manifest["genuine_agent_continuation"] is False


def test_stable_task_ids_and_questions(manifest):
    task = manifest["tasks"][0]
    assert task["task_id"] == "count_task:" + canonical_sha256(
        ["bite.task_level_count_probe.v1", task["state_id"], task["query"]])
    assert task["question"] == f"How many {task['query']} objects are visible in this image?"


def test_no_label_leakage_in_manifest_or_features(manifest):
    assert _leaked_keys(manifest) == set()
    assert _leaked_keys({"a": [{"label": 1}]}) == {"label"}
    for task in manifest["tasks"]:
        assert set(task["precall_features"]) == set(PRECALL_FEATURES)
    with pytest.raises(PermissionError):
        _guarded_read_json(ROOT / RUN_DIR / "states/x/offline_labels/initial_candidate_labels.json")


@pytest.mark.parametrize("text,expected", [
    ('{"count": 3}', ("valid", 3)), ("```json\n{\"count\": 0}\n```", ("valid", 0)), (" 7 ", ("valid", 7)),
    ('{"count": -1}', ("schema_violation", None)), ('{"count": 2.0}', ("schema_violation", None)),
    ('{"count": true}', ("schema_violation", None)), ('{"count": 2, "why": "x"}', ("schema_violation", None)),
    ("There are 3 starfish.", ("malformed", None)), ("", ("empty_response", None)), (None, ("empty_response", None)),
    ("[3]", ("schema_violation", None)),
])
def test_count_parser(text, expected):
    status, count, _ = parse_count(text)
    assert (status, count) == expected


def test_official_count_and_zero_handling():
    gt = SimpleNamespace(categories=[{"id": 0, "name": "creatures"}, {"id": 1, "name": "fish"},
                                     {"id": 2, "name": "Starfish"}],
                         annotations=[{"category_id": 1}, {"category_id": 1}, {"category_id": 0}], dropped=[])
    assert official_count(gt, "fish")["official_count"] == 2
    assert official_count(gt, "starfish")["official_count"] == 0
    with pytest.raises(ValueError):
        official_count(gt, "penguin")


# ----------------------------------------------------------------- branch construction

def _observation_for(task, status="valid"):
    return {
        "action_name": "semantic_region_inspect_v1", "case_id": task["semantic_case_id"], "state_id": task["state_id"],
        "lineage": {"original_candidate_id": task["initial_grounding"]["selected_candidate_id"],
                    "source_image_sha256": task["source_image_sha256"],
                    "region_render": {"render_sha256": task["semantic_region_render_sha256"]}},
        "offline_labels_accessed": False, "backend": {"model_id": MODEL_ID}, "response_status": status,
        "parsed_observation": json.loads(_semantic_text()) if status == "valid" else None,
    }


def test_common_prompt_identical_and_only_evidence_differs(manifest):
    task = manifest["tasks"][3]
    observation = _observation_for(task)
    rendered = {b: render_branch(task, b, root=ROOT, semantic_observation=observation) for b in BRANCHES}
    records = {b: r for b, (_, r) in rendered.items()}
    assert len({r["common_header_sha256"] for r in records.values()}) == 1
    assert len({r["common_footer_sha256"] for r in records.values()}) == 1
    assert len({r["system_prompt_sha256"] for r in records.values()}) == 1
    assert {r["image_sha256"][0] for r in records.values()} == {task["source_image_sha256"]}
    assert [records[b]["image_count"] for b in BRANCHES] == [1, 2, 1, 2]
    assert [records[b]["tool_calls_rendered"] for b in BRANCHES] == [1, 3, 2, 4]
    for branch, (messages, record) in rendered.items():
        text = messages[1]["content"][-1]["text"]
        assert text.startswith(common_header(task["query"]))
        assert text.endswith(common_footer(task["query"]))
        assert text.count("[Tool call 1]") == 1
        assert ("Zoom_In_Tool" in text) == (branch in {"B1", "B3"})
        assert ("semantic_region_inspect_v1" in text) == (branch in {"B2", "B3"})
        assert "official" not in text.lower() and "ground truth" not in text.lower()
    b3 = rendered["B3"][0][1]["content"][-1]["text"]
    assert b3.index("Zoom_In_Tool") < b3.index("semantic_region_inspect_v1")
    assert INCREMENTAL_LOGICAL_COST == {"B0": 0, "B1": 2, "B2": 1, "B3": 3}


def test_failed_semantic_observation_is_not_fabricated(manifest):
    task = manifest["tasks"][0]
    messages, _ = render_branch(task, "B2", root=ROOT, semantic_observation=_observation_for(task, "malformed_json"))
    text = messages[1]["content"][-1]["text"]
    assert "Status: failed (malformed_json)" in text
    assert "region_content" not in text
    with pytest.raises(ValueError):
        render_branch(task, "B2", root=ROOT, semantic_observation=None)


def test_semantic_lineage_mismatch_rejected(manifest):
    task = manifest["tasks"][0]
    wrong = _observation_for(manifest["tasks"][1])
    with pytest.raises(ValueError):
        render_branch(task, "B2", root=ROOT, semantic_observation=wrong)


def test_failed_zoom_is_reported_absent(manifest):
    task = copy.deepcopy(manifest["tasks"][0])
    task["zoom"]["crop"]["success"] = False
    messages, record = render_branch(task, "B1", root=ROOT)
    text = messages[1]["content"][-1]["text"]
    assert record["image_count"] == 1
    assert "no Image 2" in text and "Not executed" in text


def test_focused_boxes_mapped_with_recorded_crop_offset(manifest):
    for task in manifest["tasks"]:
        x0, y0 = task["zoom"]["crop"]["crop_rectangle_root_xyxy"][:2]
        for crop_box, root_box in zip(task["zoom"]["focused"]["proposals_crop_frame"],
                                      task["zoom"]["focused"]["proposals_root_frame"]):
            assert root_box["box_xyxy"] == pytest.approx([crop_box["box_xyxy"][0] + x0, crop_box["box_xyxy"][1] + y0,
                                                          crop_box["box_xyxy"][2] + x0, crop_box["box_xyxy"][3] + y0])


# ----------------------------------------------------------------------- inference

def _authorization(manifest, run_dir, semantic_run, **overrides):
    record = {
        "live_final_answer_inference_authorized": True, "authorized_by": "Test Researcher",
        "task_manifest_sha256": manifest["manifest_sha256"], "prompt_sha256": PROMPT_SHA256,
        "parser_sha256": PARSER_SHA256, "renderer_sha256": RENDERER_SHA256,
        "semantic_manifest_sha256": manifest["population"]["semantic_manifest_sha256"],
        "model_alias": "qwen3-vl-8b-instruct", "model_id": MODEL_ID,
        "endpoint": ENDPOINT_BASE + "/chat/completions", "branches": list(BRANCHES),
        "output_dir": str(run_dir), "semantic_run_dir": str(semantic_run), "dispatch_cap": 8,
        "phase_total_dispatch_cap": 10,
        "valid_until_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    record.update(overrides)
    return record


def _live_adapter(text='{"count": 1}', model=MODEL_ID):
    def respond(payload):
        return {"model": model, "choices": [{"message": {"role": "assistant", "content": text},
                                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}}
    return build_adapter(ENDPOINT_BASE, requester=respond)


@pytest.mark.parametrize("override", [
    {"live_final_answer_inference_authorized": False}, {"authorized_by": "Claude Code"}, {"authorized_by": " "},
    {"task_manifest_sha256": "0" * 64}, {"prompt_sha256": "0" * 64}, {"renderer_sha256": "0" * 64},
    {"model_id": "other"}, {"endpoint": "http://127.0.0.1:9999/v1/chat/completions"}, {"branches": ["B9"]},
    {"dispatch_cap": 9}, {"dispatch_cap": 0}, {"phase_total_dispatch_cap": 506}, {"phase_total_dispatch_cap": 7},
    {"valid_until_utc": "2020-01-01T00:00:00+00:00"}, {"valid_until_utc": "2099-01-01T00:00:00"},
    {"output_dir": "elsewhere"},
])
def test_authorization_enforced(tmp_path, mock_semantic_run, override):
    sub, _, semantic_run = mock_semantic_run
    run = tmp_path / "run"
    authorization = _authorization(sub, run, semantic_run, **override)
    with pytest.raises(PermissionError):
        validate_branch_authorization(authorization, sub, _live_adapter(), run, root=ROOT)


def test_missing_authorization_and_network_client_refused(tmp_path, manifest):
    sub = _sub_manifest(manifest, 1)
    with pytest.raises(PermissionError):
        run_branches(sub, _live_adapter(), tmp_path / "r", root=ROOT, mode="live", branches=["B0"])
    with pytest.raises(PermissionError):
        run_branches(sub, build_adapter(ENDPOINT_BASE), tmp_path / "r2", root=ROOT, mode="mock_dry_run",
                     branches=["B0"])
    with pytest.raises(PermissionError):
        validate_branch_authorization(_authorization(sub, tmp_path, tmp_path), sub,
                                      build_adapter("http://10.0.0.5:8222/v1"), tmp_path, root=ROOT)


def test_live_run_caps_canary_resume_and_raw_before_gt(tmp_path, mock_semantic_run):
    sub, sem, semantic_run = mock_semantic_run
    run = tmp_path / "run"
    authorization = _authorization(sub, run, semantic_run)
    # mock semantic observations are refused in live mode
    with pytest.raises(ValueError):
        run_branches(sub, _live_adapter(), run, root=ROOT, mode="live", branches=list(BRANCHES),
                     semantic_run_dir=semantic_run, semantic_manifest=sem, authorization=authorization)
    run = tmp_path / "run_b01"
    authorization = _authorization(sub, run, semantic_run, branches=["B0", "B1"], dispatch_cap=4,
                                   phase_total_dispatch_cap=5)
    first = run_branches(sub, _live_adapter(), run, root=ROOT, mode="live", branches=["B0", "B1"],
                         semantic_run_dir=semantic_run, semantic_manifest=sem, authorization=authorization,
                         canary_tasks=1)
    assert first["dispatched"] == 2 and first["semantic_dispatches_counted"] == 2
    second = run_branches(sub, _live_adapter(), run, root=ROOT, mode="live", branches=["B0", "B1"],
                          semantic_run_dir=semantic_run, semantic_manifest=sem, authorization=authorization,
                          resume=True)
    # phase total 5 - 2 semantic = 3 final answers allowed; 2 already used
    assert second["dispatched"] == 1 and second["skipped_cap"] == 1
    third = run_branches(sub, _live_adapter(), run, root=ROOT, mode="live", branches=["B0", "B1"],
                         semantic_run_dir=semantic_run, semantic_manifest=sem, authorization=authorization,
                         resume=True)
    assert third["dispatched"] == 0
    with pytest.raises(ValueError):
        finalize_outcomes(sub, run, tmp_path / "final", branches=["B0", "B1"])
    inputs = sorted(run.glob("states/*/branch_input.json"))
    assert len(inputs) == 3
    for path in inputs:
        events = [json.loads(line)["event"] for line in (path.parent / "stage_events.jsonl").read_text().splitlines()]
        assert events == ["branch_input_persisted", "raw_finalized"]
        assert "label" not in path.read_text().lower().replace("labels", "")


def test_mock_full_pipeline_finalize_then_labels(tmp_path, mock_semantic_run):
    sub, sem, semantic_run = mock_semantic_run
    run = tmp_path / "run"
    adapter = build_adapter("http://mock.invalid/v1", requester=mock_requester(lambda i, p: '{"count": 1}'))
    summary = run_branches(sub, adapter, run, root=ROOT, mode="mock_dry_run", branches=list(BRANCHES),
                           semantic_run_dir=semantic_run, semantic_manifest=sem)
    assert summary["dispatched"] == 8
    with pytest.raises(ValueError):
        finalize_outcomes(sub, run, tmp_path / "final_live")
    final = tmp_path / "final"
    labels = tmp_path / "labels"
    gt = SimpleNamespace(categories=[{"id": i, "name": n} for i, n in enumerate(
        ("fish", "jellyfish", "penguin", "puffin", "shark", "starfish", "stingray"))],
        annotations=[{"category_id": 5}], dropped=[])
    with pytest.raises(FileNotFoundError):
        build_count_labels(sub, final, labels, load_ground_truth=lambda entry: gt)
    record, rows = finalize_outcomes(sub, run, final, require_live=False)
    assert record["row_count"] == 8 and _leaked_keys(rows) == set()
    with pytest.raises(FileExistsError):
        finalize_outcomes(sub, run, final, require_live=False)
    label_rows = build_count_labels(sub, final, labels, load_ground_truth=lambda entry: gt)
    assert load_count_labels(labels, final) == label_rows
    joined = join_outcomes(sub, rows, label_rows)
    assert [r["branches"]["B0"]["correct"] for r in joined] == [
        int(r["official_count"] == 1) for r in joined]
    (final / "raw_outcome_table.jsonl").write_text("tampered\n")
    with pytest.raises(ValueError):
        load_count_labels(labels, final)


def test_consecutive_failures_halt_and_preserve(tmp_path, manifest):
    sub = _sub_manifest(manifest, 3)

    def failing(payload):
        raise TimeoutError("simulated")
    adapter = build_adapter("http://mock.invalid/v1", requester=failing)
    with pytest.raises(RuntimeError):
        run_branches(sub, adapter, tmp_path / "run", root=ROOT, mode="mock_dry_run", branches=["B0"])
    answers = sorted((tmp_path / "run").glob("states/*/final_answer.json"))
    assert len(answers) == 3
    assert {json.loads(p.read_text())["response_status"] for p in answers} == {"timeout"}


def test_served_model_mismatch_halts(tmp_path, mock_semantic_run):
    sub, sem, semantic_run = mock_semantic_run
    run = tmp_path / "run"
    authorization = _authorization(sub, run, semantic_run, branches=["B0"], dispatch_cap=2,
                                   phase_total_dispatch_cap=4)
    with pytest.raises(RuntimeError):
        run_branches(sub, _live_adapter(model="other/model"), run, root=ROOT, mode="live", branches=["B0"],
                     semantic_run_dir=semantic_run, semantic_manifest=sem, authorization=authorization)


# ------------------------------------------------------------- synthetic analysis rows

def _rows(seed=0, groups=15, per_group=7, rule=None):
    rng = random.Random(seed)
    rows = []
    for g in range(groups):
        for k in range(per_group):
            score = rng.random()
            features = {"initial_score": score, "log_proposal_count": rng.random(),
                        "top_box_relative_area": rng.random(), "score_gap": rng.random()}
            correct = rule(score, rng) if rule else {b: int(rng.random() < 0.5) for b in BRANCHES}
            count = rng.choice([0, 0, 1, 3])
            rows.append({"task_id": f"t{g}_{k}", "source_group_id": f"g{g:02d}", "query": rng.choice(["fish", "shark"]),
                         "official_count": count, "features": features,
                         "branches": {b: {"correct": correct[b], "valid": True, "presence_correct": correct[b]}
                                      for b in BRANCHES}})
    return rows


def _row(task, group, correct, count=0):
    return {"task_id": task, "source_group_id": group, "query": "fish", "official_count": count,
            "features": dict.fromkeys(PRECALL_FEATURES, 0.5),
            "branches": {b: {"correct": c, "valid": True, "presence_correct": c} for b, c in zip(BRANCHES, correct)}}


def test_oracle_best_fixed_and_combined_gap_exact():
    rows = [_row("a", "g1", (1, 0, 0, 0)), _row("b", "g1", (0, 1, 0, 0)), _row("c", "g2", (0, 0, 0, 1)),
            _row("d", "g2", (1, 1, 1, 1))]
    stats = headroom_statistics(rows)
    assert best_fixed(rows)[0] == "B0"            # B0 and B1 tie at 0.5; B0 is cheaper
    assert stats["best_fixed_value"] == pytest.approx(-0.5)
    assert stats["oracle_value"] == pytest.approx(0.0)
    assert stats["oracle_adaptivity_gap"] == pytest.approx(0.5)
    assert stats["single_action_oracle_value"] == pytest.approx(-0.25)
    assert stats["combined_evidence_oracle_gap"] == pytest.approx(0.25)
    # cost-adjusted: with lambda=0.1 the case solved only by B3 costs 0.3
    assert oracle_value(rows, 0.1) == pytest.approx((0 + -0.2 + -0.3 + 0) / 4)
    summary = combined_evidence(rows)["counts"]
    assert summary["B3_only_successful_branch"] == 1
    tr = transitions(rows)
    assert tr["relative_to_B0"]["B1"]["incorrect_to_correct"] == 1
    assert tr["relative_to_B0"]["B1"]["correct_to_incorrect"] == 1
    assert tr["cross_branch"]["all_branches_fail"] == 0


def test_selector_detects_known_signal():
    rows = _rows(1, rule=lambda s, rng: {"B0": int(s >= .5), "B1": int(s < .5), "B2": 0, "B3": 0})
    result = learnable_headroom(rows, replicates=200)
    zero = result["by_penalty"]["0.0"]
    assert zero["hindsight_oracle_utility"] == pytest.approx(0.0)
    for policy in ("P2_score_threshold", "P3_action_value"):
        assert zero["policies"][policy]["recovery_fraction"]["value"] > 0.85
        assert zero["bootstrap"]["statistics"][f"{policy}_minus_P1"]["lower_2_5"] > 0
    decision = classify(oracle_headroom(rows, replicates=200), result, rows)
    assert decision["outcome"] == "SIMPLE_POLICY_SUFFICIENT"


def test_null_signal_is_not_rewarded():
    rows = _rows(2)
    result = learnable_headroom(rows, replicates=300)
    zero = result["by_penalty"]["0.0"]
    interval = zero["bootstrap"]["statistics"]["P3_action_value_minus_P1"]
    assert interval["lower_2_5"] <= 0
    decision = classify(oracle_headroom(rows, replicates=300), result, rows)
    assert decision["outcome"] in {"ORACLE_HEADROOM_NOT_LEARNABLE", "SIMPLE_POLICY_SUFFICIENT"}
    assert decision["outcome"] != "PROMISING_PREDICTABLE_HEADROOM"


def test_low_headroom_and_invalid_outcomes():
    rows = _rows(3, rule=lambda s, rng: dict.fromkeys(BRANCHES, 1))
    oracle = oracle_headroom(rows, replicates=50)
    assert classify(oracle, learnable_headroom(rows, replicates=50), rows)["outcome"] == "LOW_OBSERVED_ORACLE_HEADROOM"
    for row in rows[:40]:
        row["branches"]["B2"]["valid"] = False
    assert classify(oracle, None, rows)["outcome"] == "EXPERIMENT_INSUFFICIENT_OR_INVALID"
    assert classify(oracle, None, rows, executed=False)["outcome"] == "EXPERIMENT_INSUFFICIENT_OR_INVALID"


def test_logo_selection_is_group_disjoint():
    rows = _rows(4)
    base, folds = logo_selections(rows, 0.0)
    assert len(folds) == 15 and {f["training_groups"] for f in folds} == {14}
    perturbed = copy.deepcopy(rows)
    for row in perturbed:
        if row["source_group_id"] == "g03":
            row["branches"] = {b: {**v, "correct": 1 - v["correct"]} for b, v in row["branches"].items()}
    changed, _ = logo_selections(perturbed, 0.0)
    for row in rows:
        if row["source_group_id"] == "g03":
            assert changed[row["task_id"]] == base[row["task_id"]]


def test_features_reject_identifiers_and_future_information():
    rows = _rows(5)
    validate_features(rows)
    bad = copy.deepcopy(rows)
    bad[0]["features"]["source_group_id"] = 1.0
    with pytest.raises(ValueError):
        validate_features(bad)
    bad = copy.deepcopy(rows)
    bad[0]["features"]["focused_score"] = 0.5
    with pytest.raises(ValueError):
        validate_features(bad)


def test_group_bootstrap_resamples_groups_and_preserves_negative_gains():
    rows = [_row(f"t{g}_{k}", f"g{g}", (1, 0, 0, 0)) for g in range(6) for k in range(3)]
    stats = {"b1_minus_b0": lambda rs: sum(r["branches"]["B1"]["correct"] - r["branches"]["B0"]["correct"]
                                           for r in rs) / len(rs),
             "invalid": lambda rs: None}
    first = group_bootstrap(rows, stats, replicates=100, seed=467)
    second = group_bootstrap(rows, stats, replicates=100, seed=467)
    assert first == second
    assert first["statistics"]["b1_minus_b0"]["observed"] == -1.0
    assert first["statistics"]["b1_minus_b0"]["upper_97_5"] == -1.0
    assert first["statistics"]["invalid"]["invalid_replicates"] == 100
    assert first["candidate_rows_resampled_iid"] is False and first["source_group_count"] == 6


# ---------------------------------------------------------------------- regression

def test_historical_phase_artifacts_unchanged():
    for phase in ("phase04c1d", "phase04c1e", "phase04c1f"):
        inventory = json.loads((ROOT / f"outputs/bite/{phase}/manifest_checksums.json").read_text())["artifact_sha256"]
        assert [p for p, d in inventory.items() if file_digest(ROOT / p) != d] == [], phase


def test_prepared_artifacts_consistent(manifest):
    summary = json.loads((PHASE / "task_manifest/preparation_summary.json").read_text())
    assert summary["task_manifest_sha256"] == manifest["manifest_sha256"]
    assert summary["model_calls"] == 0 and summary["offline_labels_accessed"] is False
    assert summary["common_header_and_footer_identical_across_b0_b1"] is True
    for name in ("finalized_outputs", "offline_labels", "oracle_headroom", "learnable_headroom"):
        if not (PHASE / "raw_continuations/branch_run/run_configuration.json").exists():
            assert not (PHASE / name).exists(), name
