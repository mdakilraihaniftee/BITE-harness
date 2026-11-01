import ast
import json
from pathlib import Path

import pytest

from evaluation_kit.bite_collection.dataset_adapter import (
    CLASSES,
    MANIFEST_DIGEST,
    AquariumDatasetAdapter,
)
from evaluation_kit.bite_collection.expansion_protocol import freeze_expansion_protocol
from evaluation_kit.bite_collection.expansion_runner import TaskVExpansionRunner
from evaluation_kit.bite_collection.integrity import (
    StageEventLedger,
    validate_canary,
    validate_run_directory,
    validate_stage_events,
)
from evaluation_kit.bite_collection.negative_audit import reference_iou_xyxy
from evaluation_kit.bite_collection.support_analysis import build_support_summary
from evaluation_kit.bite_collection.synthetic import synthetic_capabilities
from tests.bite_collection.test_batch_collection import MEMORY, FakeAdapter


def _synthetic_expansion(adapter, *, repeat=True, query="person"):
    entry = adapter.entries()[0]
    return {
        "schema_version": "bite.task_v_expansion.v1", "protocol_sha256": "b" * 64,
        "manifest_sha256": adapter.manifest["manifest_sha256"], "partition": "calibration_fit",
        "selection_seed": 418, "seed": 418, "repeat_control_seed": 419,
        "selected_source_groups": [entry.source_group_id], "source_groups": [entry.source_group_id],
        "repeat_control_groups": [entry.source_group_id] if repeat else [],
        "maximum_public_dispatches": 4 if repeat else 3,
        "states": [{"state_id": "expansion:test", "group_index": 0, "query_index": 0,
                    "entry": entry.__dict__, "query": query, "permitted_classes": ["person", "horse", "nothing"],
                    "is_canary_group": True, "repeat_control_group": repeat}],
    }


def test_independent_reference_iou_geometry():
    assert reference_iou_xyxy([0, 0, 10, 10], [0, 0, 10, 10]) == 1
    assert reference_iou_xyxy([0, 0, 10, 10], [10, 10, 20, 20]) == 0
    assert reference_iou_xyxy([0, 0, 10, 10], [5, 0, 15, 10]) == pytest.approx(1 / 3)


def test_historical_labels_reconstructed_and_diagnosed():
    summary = json.loads(Path("outputs/bite/phase04b2b3/audit_existing/negative_audit_summary.json").read_text())
    assert summary["candidate_states"] == 38
    assert summary["positive_iou_0_50"] == 4 and summary["negative_iou_0_50"] == 34
    assert summary["negative_primary_diagnoses"] == {"no_annotated_instance": 32,
                                                       "insufficient_localization": 2}
    assert summary["reconstructed_exactly"] and summary["independent_geometry_all_passed"]
    assert not summary["systematic_defect_found"]


def test_historical_class_maps_and_review_uncertainty_are_explicit():
    path = Path("outputs/bite/phase04b2b3/audit_existing/negative_diagnostics.jsonl")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 38
    assert all(row["independent_geometry"]["class_mapping_id"] is not None for row in rows)
    negatives = [row for row in rows if not row["label_iou_0_50"]["official_tp"]]
    assert sum(row["primary_diagnosis_iou_0_50"] == "no_annotated_instance" for row in negatives) == 32
    assert sum(row["primary_diagnosis_iou_0_50"] == "insufficient_localization" for row in negatives) == 2
    assert sum(row["manual_review_status"] == "pending_visual_review" for row in rows) == 33


def test_historical_focused_outcomes_keep_runtime_and_offline_separate():
    summary = json.loads(Path("outputs/bite/phase04b2b3/analysis/focused_analysis_summary.json").read_text())
    assert summary["paired_states"] == 38
    assert summary["contingency"]["0.5"]["correct"] == {"focused_target_support": 4}
    assert summary["contingency"]["0.5"]["incorrect"] == {
        "focused_target_support": 28, "ambiguous": 5, "no_alignment": 1}
    assert summary["repeat_full_precision"] == {"count": 38, "boxes": 38, "scores": 38, "masks": 38}
    assert not summary["probability_model_fitted"]


def test_historical_parent_and_content_integrity_is_disk_derived():
    report = validate_run_directory("outputs/bite/phase04b2b2/observations/aquarium_task_v_seed417_g20")
    assert report["valid"] and report["state_count"] == 40
    assert report["all_branches_same_parent"] and report["all_content_hashes_valid"]
    assert report["sibling_contamination_count"] == 0
    assert report["stage_order_independently_reconstructible_states"] == 0
    assert report["historical_stage_order_limitation"]


def test_stage_event_chain_proves_raw_before_label(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    raw = state / "raw_completion.json"
    raw.write_text("{}")
    import hashlib
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    ledger = StageEventLedger(state / "stage_events.jsonl")
    ledger.append("runtime_started", {"offline_gt_opened": False})
    ledger.append("raw_finalized", {"raw_completion_sha256": digest})
    ledger.append("offline_gt_open_authorized", {"raw_completion_sha256": digest})
    ledger.append("labels_finalized", {"labels": "done"})
    result = validate_stage_events(ledger.path, state_dir=state)
    assert result["valid"] and result["raw_before_gt"]
    lines = ledger.path.read_text().splitlines()
    lines[2] = lines[2].replace("authorized", "tampered")
    ledger.path.write_text("\n".join(lines) + "\n")
    assert not validate_stage_events(ledger.path, state_dir=state)["valid"]


def test_hardcoded_integrity_claims_removed():
    paths = [Path("scripts/bite/collect_calibration_pilot.py"),
             Path("evaluation_kit/bite_collection/batch_runner.py")]
    text = "\n".join(path.read_text() for path in paths)
    for forbidden in ('"raw_first_labels_present": True', '"raw_before_labels": True',
                      '"all_branches_same_parent": True'):
        assert forbidden not in text
    for path in paths:
        ast.parse(path.read_text())


def test_expansion_sampling_is_frozen_uniform_fit_only_and_excludes_pilot():
    adapter = AquariumDatasetAdapter()
    one = freeze_expansion_protocol(adapter)
    two = freeze_expansion_protocol(adapter)
    pilot = json.loads(Path("outputs/bite/phase04b2b2/preflight/sample_selection_manifest.json").read_text())
    assert one == two
    assert one["eligible_source_group_count"] == 257 and one["source_group_count"] == 30
    assert not set(one["selected_source_groups"]) & set(pilot["source_groups"])
    assert one["group_inclusion_probability"] == pytest.approx(30 / 257)
    assert all(state["entry"]["partition"] == "calibration_fit" for state in one["states"])


def test_expansion_has_seven_gt_free_queries_repeat_subset_and_cap():
    protocol = freeze_expansion_protocol(AquariumDatasetAdapter())
    assert protocol["source_classes"] == list(CLASSES)
    assert protocol["scheduled_query_count"] == 210
    assert len(protocol["repeat_control_groups"]) == 5
    assert protocol["repeat_control_group_inclusion_probability"] == pytest.approx(5 / 30)
    assert protocol["maximum_public_dispatches"] == 665
    assert not protocol["selection_uses_ground_truth"] and not protocol["selection_uses_tool_outcomes"]
    assert protocol["branch_budget"] == 3
    assert all({state["query"] for state in protocol["states"]
                if state["entry"]["source_group_id"] == group}
               == set(CLASSES) for group in protocol["selected_source_groups"])


def test_frozen_protocol_preserves_manifest_and_source_group_identity():
    adapter = AquariumDatasetAdapter()
    protocol = freeze_expansion_protocol(adapter)
    persisted = json.loads(
        Path("outputs/bite/phase04b2b3/protocol/task_v_expansion_protocol.json").read_text())
    assert protocol["protocol_sha256"] == persisted["protocol_sha256"]
    assert protocol["manifest_sha256"] == MANIFEST_DIGEST
    assert [state["entry"]["source_group_id"] for state in protocol["states"]] == [
        state["entry"]["source_group_id"] for state in persisted["states"]]


def test_offline_audit_path_precedes_any_live_preflight():
    source = Path("scripts/bite/collect_task_v_expansion.py").read_text()
    audit_gate = source.index('if args.stage == "audit":')
    live_preflight = source.index("preflight = _preflight", audit_gate)
    assert audit_gate < live_preflight


def test_expansion_runner_repeat_control_cost_and_canary_integrity(tmp_path):
    adapter = FakeAdapter(tmp_path / "source")
    selection = _synthetic_expansion(adapter, repeat=True)
    run = tmp_path / "run"
    runner = TaskVExpansionRunner(adapter=adapter, selection=selection, capabilities=synthetic_capabilities(),
                                  memory_config=MEMORY, run_dir=run, collection_run_id="expansion")
    result = runner.run(canary_only=True)
    assert result["actual_dispatches_after_run"] == 4
    gate = validate_canary(run, selection, dispatch_cap=665)
    assert gate["pass"] and gate["states"][0]["raw_before_label"]["valid"]
    assert gate["states"][0]["zoom_executed"] and gate["states"][0]["repeat_executed"]


def test_expansion_missing_candidate_retains_one_cost_and_no_branches(tmp_path):
    adapter = FakeAdapter(tmp_path / "source", queries=("nothing",))
    selection = _synthetic_expansion(adapter, repeat=False, query="nothing")
    run = tmp_path / "run"
    runner = TaskVExpansionRunner(adapter=adapter, selection=selection, capabilities=synthetic_capabilities(),
                                  memory_config=MEMORY, run_dir=run, collection_run_id="empty-expansion")
    result = runner.run(canary_only=True)
    assert result["actual_dispatches_after_run"] == 1
    gate = validate_canary(run, selection, dispatch_cap=665)
    assert gate["pass"] and not gate["states"][0]["zoom_executed"]


def test_expansion_resume_is_idempotent_and_corruption_rejected(tmp_path):
    adapter = FakeAdapter(tmp_path / "source")
    selection = _synthetic_expansion(adapter, repeat=False)
    run = tmp_path / "run"
    TaskVExpansionRunner(adapter=adapter, selection=selection, capabilities=synthetic_capabilities(),
                         memory_config=MEMORY, run_dir=run, collection_run_id="resume").run(canary_only=True)
    resumed = TaskVExpansionRunner(adapter=adapter, selection=selection, capabilities=synthetic_capabilities(),
                                   memory_config=MEMORY, run_dir=run, collection_run_id="resume", resume=True)
    result = resumed.run(canary_only=True)
    assert result["newly_completed"] == 0 and result["actual_dispatches_after_run"] == 3
    state_dir = next((run / "states").iterdir())
    (state_dir / "initial_raw_state.json").write_text("{}")
    corrupt = TaskVExpansionRunner(adapter=adapter, selection=selection, capabilities=synthetic_capabilities(),
                                   memory_config=MEMORY, run_dir=run, collection_run_id="resume", resume=True)
    with pytest.raises(RuntimeError, match="corrupt"):
        corrupt.run(canary_only=True)


def test_support_summary_keeps_cohorts_separate_and_fits_nothing(tmp_path):
    result = build_support_summary(
        pilot_audit_path="outputs/bite/phase04b2b2/audits/pilot_audit.json",
        expansion_audit_path="outputs/bite/phase04b2b3/analysis/expansion_collection_audit.json",
        pilot_diagnostics_path="outputs/bite/phase04b2b3/audit_existing/negative_diagnostics.jsonl",
        expansion_diagnostics_path=(
            "outputs/bite/phase04b2b3/offline_labels/expansion_diagnostics/negative_diagnostics.jsonl"
        ),
        pilot_focused_path="outputs/bite/phase04b2b3/analysis/focused_analysis_summary.json",
        expansion_focused_path=(
            "outputs/bite/phase04b2b3/analysis/expansion_focused/focused_analysis_summary.json"
        ),
        output_path=tmp_path / "support.json",
    )
    assert set(result["cohorts"]) == {"original_pilot", "expansion"}
    assert result["pooled_descriptive"]["offline_labels"]["0.5"] == {
        "positive": 35, "negative": 206, "unknown": 0,
    }
    assert result["cohorts"]["expansion"]["high_score_invalid_count"] == 27
    assert result["support_assessment"]["negative_only_expansion_query_cells_iou_0_50"] == ["jellyfish"]
    assert not result["support_assessment"]["probability_model_fitted"]

