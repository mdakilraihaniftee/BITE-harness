"""Ground-truth release policy, evaluator authorization, and label-leakage checks."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from openvlharness.multi_agent.testing import FIXTURE_TASK, ScriptedAgentBuilder, create_scene
from openvlharness.studio.reference import ReferenceResolver, evaluate
from openvlharness.studio.server import create_app

ROOT = Path(__file__).resolve().parents[2]
VIEWER, EVALUATOR = "viewer-token-1234567890", "evaluator-token-0987654321"
LABEL = "8675309"  # distinctive: must never appear anywhere an agent can see


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FSC147Dataset:
    """Stand-in with the real loader's class name (selects the count rule)."""

    def __init__(self, image: Path, answer: str = LABEL) -> None:
        self.data = pd.DataFrame(
            [
                {"index": 0, "image_path": str(image), "question": "Other row?", "answer": "1"},
                {"index": 41, "image_path": str(image), "question": FIXTURE_TASK, "answer": answer},
            ]
        )

    def build_prompt(self, row: int):
        line = self.data.iloc[row]
        return [{"type": "image", "value": line["image_path"]}, {"type": "text", "value": line["question"]}]


def _client(root: Path, loader=None, evaluator: str | None = EVALUATOR) -> TestClient:
    return TestClient(create_app(root, viewer_token=VIEWER, evaluator_token=evaluator, dataset_loader=loader))


def _run_dataset_task(tmp_path: Path, answer: str = LABEL):
    image = create_scene(tmp_path / "scene.png")
    runner = _load("run_studio_dataset_task", "scripts/run_studio_dataset_task.py")
    builder = ScriptedAgentBuilder(image)
    loaded = []

    def loader(name: str):
        dataset = FSC147Dataset(image, answer)
        loaded.append(dataset)
        return dataset

    runs = tmp_path / "runs"
    code = runner.main(
        ["--dataset", "FSC147_val", "--row", "1", "--num-agents", "2", "--output-dir", str(runs), "--run-id", "row41",
         "--config", str(ROOT / "configs/multi_agent.yaml"), "--estimate-updates", "--follow-up-rounds", "1",
         "--mode", "cooperative"],
        factory=builder.factory(), dataset_loader=loader,
    )
    return code, runs, builder, loaded, image


def test_reference_is_never_visible_to_agents_and_released_post_run(tmp_path: Path) -> None:
    code, runs, builder, loaded, image = _run_dataset_task(tmp_path)
    assert code == 0
    # The inference process dropped the label column before any inference.
    assert "answer" not in loaded[0].data.columns
    run = runs / "row41"
    # 1-4: no label in any agent-visible request, prompt, tool argument, peer message, or memory.
    requests = builder.all_requests_text()
    assert LABEL not in requests
    for path in run.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".jsonl", ".yaml", ".txt"}:
            assert LABEL not in path.read_text(encoding="utf-8", errors="ignore"), path
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    assert all(LABEL not in json.dumps(e["payload"]) for e in events)
    task = json.loads((run / "inputs/dataset_task.json").read_text())
    assert task["dataset_index"] == "41" and "answer" not in task
    # 5-8: the evaluator resolves the official row separately after the run.
    viewer = _client(runs, loader=lambda name: FSC147Dataset(image))
    plain = viewer.get("/api/runs/row41/reference", headers={"X-Studio-Token": VIEWER}).json()
    assert plain["state"] == "ACCESS_DENIED" and "value" not in plain and LABEL not in json.dumps(plain)
    released = viewer.get("/api/runs/row41/reference", headers={"X-Studio-Token": VIEWER, "X-Studio-Evaluator-Token": EVALUATOR}).json()
    assert released["state"] == "AVAILABLE" and released["value"] == LABEL
    assert released["provenance"]["dataset_index"] == "41" and released["provenance"]["normalization_rule"] == "fsc147_parse_count_exact_match"
    # The fixture answer is 5: nothing becomes correct because a label was visible.
    assert released["evaluation"]["correct"] is False and released["evaluation"]["parsed_prediction"] == 5
    # The ordinary snapshot never carries the reference.
    snapshot = viewer.get("/api/runs/row41/snapshot", headers={"X-Studio-Token": VIEWER}).text
    assert LABEL not in snapshot


def test_reference_states(tmp_path: Path) -> None:
    code, runs, _, _, image = _run_dataset_task(tmp_path, answer="5")
    assert code == 0
    resolver = ReferenceResolver(runs / ".references", dataset_loader=lambda name: FSC147Dataset(image, "5"))
    available = resolver.status(runs, "row41", evaluator=True)
    assert available["state"] == "AVAILABLE" and available["evaluation"]["correct"] is True
    assert resolver.status(runs, "row41", evaluator=False)["state"] == "ACCESS_DENIED"
    # Sealed while not terminal (copy the run and mark it running).
    running = runs / "running"
    running.mkdir()
    (running / "inputs").mkdir()
    (running / "inputs/dataset_task.json").write_text((runs / "row41/inputs/dataset_task.json").read_text())
    (running / "run_state.json").write_text(json.dumps({"status": "RUNNING"}))
    sealed = resolver.status(runs, "running", evaluator=True)
    assert sealed["state"] == "SEALED" and "value" not in sealed and sealed["provenance"]["dataset_index"] == "41"
    # Not available: no authoritative source at all.
    (runs / "plain").mkdir()
    (runs / "plain/run_state.json").write_text(json.dumps({"status": "COMPLETED"}))
    (runs / "plain/final_result.json").write_text(json.dumps({"final_answer": "3"}))
    assert resolver.status(runs, "plain", evaluator=True)["state"] == "NOT_AVAILABLE"
    # Reference error: recorded identity does not match the dataset row.
    mismatch = ReferenceResolver(None, dataset_loader=lambda name: FSC147Dataset(image, "5"))
    task = json.loads((runs / "row41/inputs/dataset_task.json").read_text())
    task["dataset_index"] = "999"
    (runs / "row41/inputs/dataset_task.json").write_text(json.dumps(task))
    error = mismatch.status(runs, "row41", evaluator=True)
    assert error["state"] == "REFERENCE_ERROR" and "value" not in error


def test_server_authorization_and_scoped_tickets(tmp_path: Path) -> None:
    code, runs, _, _, image = _run_dataset_task(tmp_path)
    assert code == 0
    client = _client(runs, loader=lambda name: FSC147Dataset(image))
    viewer = {"X-Studio-Token": VIEWER}
    assert client.get("/api/runs/row41/reference").status_code == 401
    wrong = client.get("/api/runs/row41/reference", headers={**viewer, "X-Studio-Evaluator-Token": "guess"}).json()
    assert wrong["state"] == "ACCESS_DENIED" and "value" not in wrong
    assert client.get("/api/evaluator/check", headers=viewer).status_code == 403
    assert client.get("/api/evaluator/check", headers={**viewer, "X-Studio-Evaluator-Token": EVALUATOR}).status_code == 200
    # Evaluator scope can only be delegated by an evaluator.
    denied = client.post("/api/launch-tickets", headers=viewer, json={"scopes": ["evaluator"]})
    assert denied.status_code == 403
    plain = client.post("/api/launch-tickets", headers=viewer, json={}).json()["ticket"]
    assert "evaluator_token" not in client.post("/api/launch-tickets/redeem", json={"ticket": plain}).json()
    scoped = client.post("/api/launch-tickets", headers={**viewer, "X-Studio-Evaluator-Token": EVALUATOR}, json={"scopes": ["evaluator"]}).json()
    redeemed = client.post("/api/launch-tickets/redeem", json={"ticket": scoped["ticket"]}).json()
    assert redeemed == {"token": VIEWER, "evaluator_token": EVALUATOR}
    # Studio without an evaluator token never releases references.
    closed = _client(runs, loader=lambda name: FSC147Dataset(image), evaluator=None)
    assert closed.get("/api/runs/row41/reference", headers={**viewer, "X-Studio-Evaluator-Token": EVALUATOR}).json()["state"] == "ACCESS_DENIED"
    assert closed.get("/api/info").json()["evaluator_access_configured"] is False
    with pytest.raises(ValueError):
        create_app(runs, viewer_token=VIEWER, evaluator_token=VIEWER)


def test_memory_endpoint_reports_policy(tmp_path: Path) -> None:
    code, runs, _, _, _ = _run_dataset_task(tmp_path)
    assert code == 0
    client = _client(runs)
    body = client.get("/api/runs/row41/memory/worker_01", headers={"X-Studio-Token": VIEWER}).json()
    assert body["policy"]["optional_memory"] == "on" and body["records"] and body["records"][0]["phase"] == "initial"
    snapshot = client.get("/api/runs/row41/snapshot", headers={"X-Studio-Token": VIEWER}).json()
    assert snapshot["effective_config"]["num_workers"] == 2


def test_evaluation_rule_is_the_deterministic_count_parser() -> None:
    assert evaluate("There are 13 grapes.", "13", "fsc147_parse_count_exact_match")["correct"] is True
    assert evaluate("\\boxed{12}", "13", "fsc147_parse_count_exact_match")["absolute_error"] == 1
    assert evaluate("Unable to determine", "13", "fsc147_parse_count_exact_match")["parse_failed"] is True
    assert evaluate("13", "13", None) is None  # no valid rule -> no correctness label
