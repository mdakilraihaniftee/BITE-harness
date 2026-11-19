from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from openvlharness.multi_agent.events import EventLog
from openvlharness.studio.artifacts import ArtifactStore
from openvlharness.studio.geometry import map_box_to_source
from openvlharness.studio.replay import authorized_memory, public_snapshot
from openvlharness.studio.server import create_app


def make_run(root: Path, run_id: str = "run_001") -> tuple[Path, str]:
    run = root / run_id
    run.mkdir(parents=True)
    image = root / "input.png"
    Image.new("RGB", (200, 100), "green").save(image)
    artifacts = ArtifactStore(run)
    source_id = artifacts.register_file(
        image, source_event_id="evt_task", alias="input_image_1"
    )
    events = EventLog(run_id, "task_001", run / "events.jsonl", artifacts)
    started = events.emit("orchestrator", "RUN_STARTED", {}, status="running")
    events.emit(
        "worker_01",
        "TOOL_CALL_COMPLETED",
        {"canonical_result": {"boxes": [[10, 20, 80, 70]]}},
        parent_event_id=started["event_id"],
        tool_name="Visual_Grounding_Tool",
    )
    (run / "run_manifest.json").write_text(
        json.dumps({"original_task": "Count the marked objects", "worker_count": 1})
    )
    (run / "run_state.json").write_text(json.dumps({"status": "RUNNING"}))
    worker = run / "workers" / "worker_01"
    worker.mkdir(parents=True)
    (worker / "private_memory.json").write_text(
        json.dumps(
            [
                {
                    "agent_id": "worker_01",
                    "candidate_answer": "3",
                    "evidence_references": [source_id],
                    "trajectory": {"thinking": "must remain private"},
                }
            ]
        )
    )
    return run, source_id


def route_for(app, path: str):
    return next(route for route in app.routes if getattr(route, "path", None) == path)


def test_event_contract_is_ordered_and_concurrency_safe(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    log = EventLog("run", "task", run / "events.jsonl")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda index: log.emit(
                    f"worker_{index % 2:02d}", "TEST", {"index": index}
                ),
                range(100),
            )
        )
    persisted = [
        json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()
    ]
    assert [event["sequence"] for event in persisted] == list(range(100))
    assert len({event["event_id"] for event in persisted}) == 100
    assert all(event["schema_version"] == "studio.event.v1" for event in persisted)


def test_artifacts_are_content_addressed_deduplicated_and_run_scoped(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    image = tmp_path / "same.png"
    Image.new("RGB", (23, 17), "blue").save(image)
    store = ArtifactStore(run)
    first = store.register_file(image, source_event_id="evt_1", alias="input_image_1")
    second = store.register_file(image, source_event_id="evt_2")
    assert first == second
    path, record = store.resolve(first)
    assert path.is_file() and record["width"] == 23 and record["height"] == 17
    with pytest.raises(KeyError):
        store.resolve("../../etc/passwd")


@pytest.mark.parametrize(
    ("coordinate_system", "box", "metadata", "expected"),
    [
        ("source_pixels", [-10, 10, 250, 80], {}, (0, 10, 200, 80)),
        ("normalized_0_1", [0.1, 0.2, 0.5, 0.8], {}, (20, 20, 100, 80)),
        ("normalized_0_1000", [100, 200, 500, 800], {}, (20, 20, 100, 80)),
        (
            "resized_pixels",
            [50, 25, 100, 50],
            {"coordinate_width": 100, "coordinate_height": 50},
            (100, 50, 200, 100),
        ),
        (
            "crop_pixels",
            [0, 0, 50, 25],
            {
                "crop_bounds": [40, 20, 140, 70],
                "coordinate_width": 50,
                "coordinate_height": 25,
            },
            (40, 20, 140, 70),
        ),
        (
            "padded_resized_pixels",
            [10, 20, 110, 70],
            {
                "padding_left": 10,
                "padding_top": 20,
                "content_width": 100,
                "content_height": 50,
            },
            (0, 0, 200, 100),
        ),
    ],
)
def test_roi_coordinate_mapping(
    coordinate_system: str,
    box: list[float],
    metadata: dict[str, object],
    expected: tuple[float, float, float, float],
) -> None:
    mapped = map_box_to_source(
        box,
        source_width=200,
        source_height=100,
        coordinate_system=coordinate_system,
        transform_metadata=metadata,
    )
    assert mapped.warning is None
    assert mapped.box == pytest.approx(expected)


def test_invalid_roi_is_not_rendered_as_an_approximation() -> None:
    mapped = map_box_to_source(
        [0, 0, 10, 10],
        source_width=200,
        source_height=100,
        coordinate_system="crop_pixels",
    )
    assert mapped.box is None
    assert "require" in mapped.warning.lower()


def test_authenticated_snapshot_memory_artifact_and_stream_resume(
    tmp_path: Path,
) -> None:
    run, artifact_id = make_run(tmp_path)
    app = create_app(tmp_path, viewer_token="correct-token")
    snapshot_route = route_for(app, "/api/runs/{run_id}/snapshot")
    authorize = snapshot_route.dependant.dependencies[0].call
    with pytest.raises(HTTPException) as denied:
        authorize(None)
    assert denied.value.status_code == 401
    authorize("correct-token")

    snapshot = asyncio.run(snapshot_route.endpoint(run.name))
    assert snapshot["artifact_aliases"]["input_image_1"] == artifact_id
    memory = asyncio.run(
        route_for(app, "/api/runs/{run_id}/memory/{agent_id}").endpoint(
            run.name, "worker_01"
        )
    )
    assert memory["records"][0]["candidate_answer"] == "3"
    assert "trajectory" not in memory["records"][0]
    artifact = asyncio.run(
        route_for(app, "/api/runs/{run_id}/artifacts/{artifact_id}").endpoint(
            run.name, artifact_id
        )
    )
    assert Path(artifact.path).suffix == ".png"
    stream = asyncio.run(
        route_for(app, "/api/runs/{run_id}/stream").endpoint(
            None, run.name, cursor=0, follow=False
        )
    )
    body = stream.body.decode()
    assert "id: 1" in body
    assert "id: 0" not in body


def test_private_memory_can_be_disabled_at_backend(tmp_path: Path) -> None:
    run, _ = make_run(tmp_path)
    app = create_app(tmp_path, viewer_token="token", allow_private_memory=False)

    async def denied() -> None:
        with pytest.raises(HTTPException) as error:
            await route_for(app, "/api/runs/{run_id}/memory/{agent_id}").endpoint(
                run.name, "worker_01"
            )
        assert error.value.status_code == 403

    asyncio.run(denied())


def test_launch_link_signs_browser_in_for_evidence_memory_and_stream(tmp_path: Path) -> None:
    run, artifact_id = make_run(tmp_path)
    app = create_app(tmp_path, viewer_token="internal", instance_id="browser-test")
    with TestClient(app) as client:
        assert client.get("/api/runs").status_code == 401
        ticket = client.post("/api/launch-tickets", headers={"X-Studio-Token": "internal"}, json={}).json()["ticket"]
        sign_in = client.post("/api/launch-tickets/redeem", json={"ticket": ticket})
        assert "HttpOnly" in sign_in.headers["set-cookie"] and "SameSite=strict" in sign_in.headers["set-cookie"]
        assert client.get("/api/session").json() == {"authenticated": True, "evaluator": False}
        assert client.get("/api/runs").json()["runs"][0]["run_id"] == run.name
        assert client.get(f"/api/runs/{run.name}/snapshot").status_code == 200
        assert client.get(f"/api/runs/{run.name}/memory/worker_01").status_code == 200
        assert client.get(f"/api/runs/{run.name}/artifacts/{artifact_id}").headers["content-type"] == "image/png"
        stream = client.get(f"/api/runs/{run.name}/stream?follow=false&cursor=0")
        assert stream.status_code == 200 and "id: 1" in stream.text and "id: 0" not in stream.text
        restarted = TestClient(create_app(tmp_path, viewer_token="replacement", instance_id="restarted"))
        restarted.cookies.update(client.cookies)
        assert restarted.get("/api/runs").status_code == 401
    with TestClient(app) as stranger:
        for path in ("/api/session", "/api/runs", f"/api/runs/{run.name}/snapshot",
                     f"/api/runs/{run.name}/memory/worker_01", f"/api/runs/{run.name}/artifacts/{artifact_id}",
                     f"/api/runs/{run.name}/stream?follow=false"):
            assert stranger.get(path).status_code == 401


def test_replay_snapshot_tolerates_missing_assets_and_partial_jsonl(
    tmp_path: Path,
) -> None:
    run = tmp_path / "legacy"
    run.mkdir()
    (run / "events.jsonl").write_text(
        json.dumps({"event_type": "OLD_EVENT", "sequence": 0, "payload": {}}) + "\n{"
    )
    snapshot = public_snapshot(tmp_path, "legacy")
    assert snapshot["events"][0]["schema_version"] == "studio.event.v1"
    assert snapshot["artifacts"] == {}


def test_authorized_worker_memory_strips_trajectory_and_hidden_reasoning(
    tmp_path: Path,
) -> None:
    run, _ = make_run(tmp_path)
    payload = authorized_memory(tmp_path, run.name, "worker_01")
    serialized = json.dumps(payload)
    assert "trajectory" not in serialized
    assert "must remain private" not in serialized


def test_frontend_has_required_views_and_uses_safe_text_rendering() -> None:
    static = Path("openvlharness/studio/static")
    html = (static / "index.html").read_text()
    script = (static / "app.js").read_text()
    for component in (
        "agent-graph",
        "timeline",
        "image-stage",
        "step-details",
        "memory-content",
        "replay-slider",
        "final-answer",
    ):
        assert f'id="{component}"' in html
    assert "innerHTML" not in script
    assert "X-Studio-Token" in script
    assert (
        "EventSource(" not in script
    )  # Fetch streaming carries the required auth header.


def test_deterministic_two_worker_investigation_uses_production_replay_path(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/multi_agent_smoke.py",
            "--output-dir",
            str(tmp_path),
            "--run-id",
            "integration",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    snapshot = public_snapshot(tmp_path, "integration")
    types = {event["event_type"] for event in snapshot["events"]}
    assert {
        "COORDINATOR_PLAN_RECORDED",
        "TOOL_CALL_COMPLETED",
        "MESSAGE_SENT",
        "VERIFICATION_REQUESTED",
        "HYPOTHESIS_UPDATED",
        "FINAL_ANSWER_RECORDED",
    } <= types
    assert snapshot["artifact_aliases"]["input_image_1"]
    assert any(
        record["artifact_type"] == "tool_visual_output"
        for record in snapshot["artifacts"].values()
    )


def test_dataset_runner_resolves_local_row_without_opening_label(tmp_path: Path) -> None:
    # Exercise the actual CLI and TSV loader without a downloaded benchmark,
    # a deployment .env, or a network request.
    image = tmp_path / "input.png"
    Image.new("RGB", (32, 24), "green").save(image)
    (tmp_path / "SubmissionFixture.tsv").write_text(
        "index\timage_path\tquestion\tanswer\n"
        f"17\t{image}\tHow many marked objects are there?\t8675309\n"
    )
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_studio_dataset_task.py",
            "--dataset",
            "SubmissionFixture",
            "--row",
            "0",
            "--run-id",
            "dataset_inspect",
            "--inspect-only",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "LMUData": str(tmp_path)},
    )
    assert completed.returncode == 0, completed.stderr
    assert str(image) in completed.stdout
    assert "Dataset index: 17" in completed.stdout
    assert "How many marked objects are there?" in completed.stdout
    assert "Ground truth: sealed" in completed.stdout
    assert "Inspect-only preflight completed" in completed.stdout
    assert "Final answer:" not in completed.stdout
    assert "8675309" not in completed.stdout
