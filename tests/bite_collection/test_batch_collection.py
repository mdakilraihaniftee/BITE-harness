import base64
import hashlib
import json
from pathlib import Path

import pytest

from evaluation_kit.bite_calibration.matching import GroundTruth
from evaluation_kit.bite_collection.batch_runner import (
    TaskVBatchRunner,
    _best_candidate,
)
from evaluation_kit.bite_collection.dataset_adapter import (
    MANIFEST_DIGEST,
    AquariumDatasetAdapter,
    AquariumEntry,
)
from evaluation_kit.bite_collection.manifest_iterator import select_states
from evaluation_kit.bite_collection.resume import ResumeLedger
from evaluation_kit.bite_collection.synthetic import (
    synthetic_capabilities,
    synthetic_image_data_url,
)


def _raw_image():
    return base64.b64decode(synthetic_image_data_url().split(",", 1)[1])


class FakeAdapter:
    def __init__(self, root, *, queries=("person",), groups=1):
        Path(root).mkdir(parents=True, exist_ok=True)
        self.preflight = {"source_id": "synthetic:task-v"}
        self.allowed_partition = "calibration_fit"
        self.manifest = {"manifest_sha256": "a" * 64}
        self._entries = []
        raw = _raw_image()
        sha = hashlib.sha256(raw).hexdigest()
        for index in range(groups):
            path = Path(root) / f"image_{index}.png"
            path.write_bytes(raw)
            self._entries.append(AquariumEntry(
                entry_id=f"entry:{index}", source_group_id=f"group:{index}", image_sha256=sha,
                image_path=str(path), annotation_image_id=index + 1, width=200, height=120,
                partition="calibration_fit", queries=tuple(queries),
            ))
        self.gt_calls = 0

    def entries(self):
        return list(self._entries)

    def load_offline_ground_truth(self, entry):
        self.gt_calls += 1
        return GroundTruth(
            image={"id": entry.annotation_image_id, "width": 200, "height": 120},
            categories=[{"id": 1, "name": "person"}, {"id": 2, "name": "horse"}],
            annotations=[{"id": 1, "image_id": entry.annotation_image_id, "category_id": 1,
                          "bbox": [40, 20, 50, 80], "bbox_xyxy": [40, 20, 90, 100],
                          "area": 4000, "iscrowd": 0, "ignore": 0}],
            provenance={"source": "synthetic", "sample_id": entry.entry_id,
                        "source_image_sha256": entry.image_sha256}, dropped_annotation_ids=[],
        )


MEMORY = {"modules": [{"name": "image"}, {"name": "tool_context"}, {"name": "url"}],
          "emit_policy": "always"}


def test_real_manifest_adapter_validates_frozen_identity_without_opening_gt():
    adapter = AquariumDatasetAdapter()
    assert adapter.preflight["manifest_sha256"] == MANIFEST_DIGEST
    assert adapter.preflight["partition_image_counts"]["calibration_fit"] == 277
    assert len(adapter.entries()) == 277
    assert not adapter.runtime_gt_opened
    assert all(not hasattr(entry, "classes_present") for entry in adapter.entries())


def test_manifest_iterator_is_deterministic_fit_only_and_gt_free(tmp_path):
    adapter = FakeAdapter(tmp_path, queries=("person", "horse"), groups=25)
    one = select_states(adapter, seed=417, max_groups=20)
    two = select_states(adapter, seed=417, max_groups=20)
    assert one == two
    assert one["source_group_count"] == one["image_count"] == 20
    assert one["scheduled_query_count"] == 40
    assert one["maximum_public_dispatches"] == 160
    assert one["selection_uses_ground_truth"] is False
    assert {row["entry"]["partition"] for row in one["states"]} == {"calibration_fit"}


def test_iterator_rejects_caps(tmp_path):
    adapter = FakeAdapter(tmp_path)
    with pytest.raises(ValueError):
        select_states(adapter, max_groups=21)
    with pytest.raises(ValueError):
        select_states(adapter, max_queries=3)


def test_highest_score_and_stable_detector_rank_tie_break():
    candidates = [{"candidate_id": "first", "raw_scores": [.8]},
                  {"candidate_id": "second", "raw_scores": [.9]},
                  {"candidate_id": "third", "raw_scores": [.9]}]
    selected, rank = _best_candidate(candidates)
    assert selected["candidate_id"] == "second" and rank == 1


def test_resume_ledger_detects_config_mismatch_corruption_and_partial(tmp_path):
    ledger = ResumeLedger(tmp_path, {"x": 1})
    partial = ledger.state_dir("s")
    partial.mkdir(parents=True)
    (partial / "orphan.json").write_text("{}")
    assert ledger.inspect("s")["status"] == "partial_requires_explicit_new_execution"
    with pytest.raises(ValueError):
        ResumeLedger(tmp_path, {"x": 2}, resume=True)


def test_batch_collection_raw_first_isolated_branches_and_resume(tmp_path):
    adapter = FakeAdapter(tmp_path / "source")
    selection = select_states(adapter, max_groups=1, max_queries=1)
    run = tmp_path / "run"
    runner = TaskVBatchRunner(
        adapter=adapter, selection=selection, capabilities=synthetic_capabilities(), memory_config=MEMORY,
        run_dir=run, collection_run_id="synthetic_batch", dispatch_cap=4,
    )
    first = runner.run(canary_only=True)
    assert first["actual_dispatches_after_run"] == 4
    assert adapter.gt_calls == 1
    state = selection["states"][0]
    state_dir = run / "states" / state["state_id"].replace(":", "_")
    assert (state_dir / "raw_completion.json").is_file()
    initial = json.loads((state_dir / "initial_raw_state.json").read_text())
    assert initial["selected_detector_rank"] == 0
    assert initial["offline_gt_used"] is False
    branches = [json.loads(path.read_text()) for path in (state_dir / "raw_collection" / "branches").glob("*.json")]
    assert len(branches) == 2
    assert {branch["parent_snapshot_id"] for branch in branches} == {initial["parent_snapshot_id"]}
    assert sorted(branch["branch_cost"] for branch in branches) == [1, 2]
    runtime_text = json.dumps({"initial": initial, "branches": branches,
                               "operational": json.loads((state_dir / "operational_state.json").read_text())}).lower()
    assert "official_tp" not in runtime_text and "ground_truth" not in runtime_text
    mtimes = {path: path.stat().st_mtime_ns for path in state_dir.rglob("*") if path.is_file()}
    second_runner = TaskVBatchRunner(
        adapter=adapter, selection=selection, capabilities=synthetic_capabilities(), memory_config=MEMORY,
        run_dir=run, collection_run_id="synthetic_batch", resume=True, dispatch_cap=4,
    )
    second = second_runner.run(canary_only=True)
    assert second["newly_completed"] == 0 and second["resumed_complete"] == 1
    assert second["actual_dispatches_after_run"] == 4
    assert adapter.gt_calls == 1
    assert mtimes == {path: path.stat().st_mtime_ns for path in mtimes}


def test_successful_empty_initial_state_is_retained_without_branches(tmp_path):
    adapter = FakeAdapter(tmp_path / "source", queries=("nothing",))
    selection = select_states(adapter, max_groups=1, max_queries=1)
    runner = TaskVBatchRunner(
        adapter=adapter, selection=selection, capabilities=synthetic_capabilities(), memory_config=MEMORY,
        run_dir=tmp_path / "run", collection_run_id="empty", dispatch_cap=4,
    )
    result = runner.run(canary_only=True)
    assert result["actual_dispatches_after_run"] == 1
    state = selection["states"][0]
    state_dir = tmp_path / "run" / "states" / state["state_id"].replace(":", "_")
    initial = json.loads((state_dir / "initial_raw_state.json").read_text())
    assert initial["no_candidate_state"] and initial["selected_candidate"] is None
    assert list((state_dir / "raw_collection" / "branches").glob("*.json")) == []
    labels = json.loads((state_dir / "offline_labels" / "initial_candidate_labels.json").read_text())
    assert labels["labels"] == [] and labels["reason"]


def test_pilot_cannot_continue_before_canary(tmp_path):
    adapter = FakeAdapter(tmp_path / "source", groups=3)
    selection = select_states(adapter, max_groups=3, max_queries=1)
    runner = TaskVBatchRunner(
        adapter=adapter, selection=selection, capabilities=synthetic_capabilities(), memory_config=MEMORY,
        run_dir=tmp_path / "run", collection_run_id="gate", dispatch_cap=12,
    )
    with pytest.raises(RuntimeError, match="Canary"):
        runner.run(canary_only=False)


def test_resume_detects_completed_artifact_corruption(tmp_path):
    adapter = FakeAdapter(tmp_path / "source")
    selection = select_states(adapter, max_groups=1, max_queries=1)
    run = tmp_path / "run"
    runner = TaskVBatchRunner(adapter=adapter, selection=selection, capabilities=synthetic_capabilities(),
                              memory_config=MEMORY, run_dir=run, collection_run_id="corrupt", dispatch_cap=4)
    runner.run(canary_only=True)
    state = selection["states"][0]
    state_dir = run / "states" / state["state_id"].replace(":", "_")
    target = state_dir / "initial_raw_state.json"
    target.write_text("{}")
    resumed = TaskVBatchRunner(adapter=adapter, selection=selection, capabilities=synthetic_capabilities(),
                               memory_config=MEMORY, run_dir=run, collection_run_id="corrupt",
                               resume=True, dispatch_cap=4)
    with pytest.raises(RuntimeError, match="corrupt"):
        resumed.run(canary_only=True)

