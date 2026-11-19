"""Run the frontend module tests and syntax checks with Node, using real recorded runs."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from openvlharness.studio.replay import public_snapshot
from openvlharness.studio.topology import build_topology

ROOT = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(
    NODE is None, reason="Node.js is required for frontend tests"
)


def _manifest(workers: int) -> dict:
    model = {
        "model_id": "Qwen/Qwen3-VL-8B-Instruct",
        "endpoint": "http://127.0.0.1:8222/v1/chat/completions",
    }
    actors = {"coordinator": {"model_client": model, "tools": [], "tool_access": False}}
    for index in range(1, workers + 1):
        actors[f"worker_{index:02d}"] = {
            "model_client": model,
            "tool_access": True,
            "tools": [{"name": "Visual_Grounding_Tool"}, {"name": "Zoom_In_Tool"}],
        }
    return {
        "worker_count": workers,
        "topology": {"actors": actors, "budget": {"tool_calls": 1}},
    }


def test_static_javascript_parses() -> None:
    for path in sorted((ROOT / "openvlharness/studio/static").glob("*.js")):
        result = subprocess.run(
            [NODE, "--check", str(path)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, f"{path.name}: {result.stderr}"


def test_stream_status_labels() -> None:
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests/studio/js/stream_status.test.cjs")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_frontend_modules(tmp_path: Path) -> None:
    for script, run in (
        ("scripts/studio_protocol_fixture.py", "fixture"),
        ("scripts/multi_agent_smoke.py", "demo"),
    ):
        done = subprocess.run(
            [sys.executable, script, "--output-dir", str(tmp_path), "--run-id", run],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert done.returncode == 0, done.stderr
    runs = {}
    for run in ("fixture", "demo"):
        snapshot = public_snapshot(tmp_path, run)
        runs[run] = {"topology": snapshot["topology"], "events": snapshot["events"]}
    topologies = {
        str(n): build_topology(_manifest(n), [], run_id="t") for n in (1, 2, 3, 4, 6, 8)
    }
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"runs": runs, "topologies": topologies}))
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests/studio/js/studio_frontend.test.cjs")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={"STUDIO_TEST_DATA": str(data), "PATH": str(Path(NODE).parent)},
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]


def test_answer_story_and_team_modules(tmp_path: Path) -> None:
    """Answer state (tests A-G), story, and compact team model on recorded fixture runs."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "studio_config_matrix", ROOT / "scripts/studio_config_matrix.py"
    )
    matrix = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(matrix)
    plan = {
        "revision": dict(workers=1, memory=False, peer=False),
        "single_peer": dict(workers=1, memory=True, peer=True),
        "retained": dict(workers=2, memory=True, peer=True),
        "w2": dict(workers=2, memory=True, peer=True),
        "w3": dict(workers=3, memory=True, peer=False),
        "w4": dict(workers=4, memory=False, peer=True),
        "withdrawal": dict(workers=1, memory=True, peer=False, scenario="withdrawal"),
    }
    runs = {}
    for name, options in plan.items():
        matrix.run_fixture(tmp_path, run_id=name, **options)
        runs[name] = public_snapshot(tmp_path, name)
    # A legacy run: recorded before effective configuration and answer state existed.
    legacy = json.loads(json.dumps(runs["w2"]))
    new_types = {
        "RUN_CONFIGURATION_RECORDED",
        "COORDINATOR_ESTIMATE_UPDATED",
        "COORDINATOR_REASSESSMENT_RECORDED",
        "INVESTIGATION_ROUND_STARTED",
        "INVESTIGATION_ROUND_COMPLETED",
    }
    legacy["events"] = [e for e in legacy["events"] if e["event_type"] not in new_types]
    legacy["effective_config"] = None
    for node in legacy["topology"]["nodes"]:
        node["metadata"].pop("optional_notebook", None)
    runs["legacy"] = legacy
    data = tmp_path / "answer.json"
    data.write_text(json.dumps({"runs": runs}))
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests/studio/js/answer_story_team.test.cjs")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={"STUDIO_ANSWER_DATA": str(data), "PATH": str(Path(NODE).parent)},
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]


def test_story_semantics() -> None:
    """Semantic step grouping, causality, replay safety, and legacy handling."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests/studio/js/story_semantics.test.cjs")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={"PATH": str(Path(NODE).parent)},
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]


def test_simple_team() -> None:
    """Simple team picture: traffic counts and highlighted flows come from recorded events."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests/studio/js/simple_team.test.cjs")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={"PATH": str(Path(NODE).parent)},
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]


def test_parsec_view_model(tmp_path) -> None:
    """PARSEC-VL view model over real fixture event streams (legacy, parallel plan, speculation)."""
    from openvlharness.parsec_vl.fixture import run_plan_fixture

    runs = {}
    for name, policy, extra in (("legacy", "off", {"plan": "parallel"}), ("parallel", "e3", {"plan": "parallel"}),
                                ("speculative", "e4", {"plan": "fallback"})):
        _, _, _, events = run_plan_fixture(tmp_path / name, policy=policy, workers=1, tool_delay=0.05,
                                           planning_processes=0, **extra)
        runs[name] = events
    data = tmp_path / "parsec_runs.json"
    data.write_text(json.dumps(runs))
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests/studio/js/parsec_view.test.cjs")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={"PARSEC_RUNS": str(data), "PATH": str(Path(NODE).parent)},
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
