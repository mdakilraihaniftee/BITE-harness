"""Visual tool-action lineage: geometry, runtime instrumentation, artifacts, and the JS model."""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from openvlharness.capabilities.zoom import Capability as ZoomCapability
from openvlharness.multi_agent.visual_fixture import VisualAgentBuilder, VisualPolicy, create_visual_scene
from openvlharness.services.tools.image_utils import coerce_xyxy
from openvlharness.studio import geometry as G
from openvlharness.studio.replay import public_snapshot

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "tests/studio/geometry_vectors.json").read_text())
NODE = shutil.which("node")


def _transform(spec):
    kind, args = next(iter(spec.items()))
    if kind == "crop":
        return G.crop_transform(args["box"], args["output"])
    if kind == "resize":
        return G.resize_transform(args["child"], args["parent"])
    if kind == "letterbox":
        return G.letterbox_transform(args["content"], args["padding"], args["parent"])
    return G.normalized_transform(args["scale"], args["frame"])


@pytest.mark.parametrize("case", VECTORS["chains"], ids=lambda c: c["name"])
def test_geometry_chains(case) -> None:
    transform = G.compose([_transform(step) for step in case["chain"]])
    assert transform.apply_box(case["box"]) == pytest.approx(tuple(case["expected"]))
    back = transform.inverse().apply_box(case["expected"])
    assert back == pytest.approx(tuple(case["box"]))


def test_clip_and_zoom_rule() -> None:
    for case in VECTORS["clip"]:
        expected = tuple(case["expected"]) if case["expected"] else None
        assert G.clip_box(case["box"], *case["size"]) == expected
    for case in VECTORS["zoom"]:
        c, p = case["coords"], case["padding"]
        assert list(coerce_xyxy([c[0] - p, c[1] - p, c[2] + p, c[3] + p], *case["input"], "normalized_xyxy")) == case["expected"]
    with pytest.raises(ValueError):
        G.crop_transform([10, 10, 5, 20], [5, 10])


def test_zoom_capability_describes_and_verifies_its_crop() -> None:
    inputs = [{"registry_id": "input_image_1", "width": 674, "height": 384}]
    outputs = [{"registry_id": "tool_generated_image_1", "width": 506, "height": 338}]
    record = ZoomCapability.visual_transform({"coords": [156, 54, 707, 781], "padding": 100}, inputs, outputs, None)
    assert record["crop_box"] == [38, 0, 544, 338] and record["verified"] is True
    mismatched = ZoomCapability.visual_transform({"coords": [156, 54, 707, 781], "padding": 100}, inputs,
                                                 [{"registry_id": "x", "width": 500, "height": 338}], None)
    assert mismatched["verified"] is False
    assert ZoomCapability.visual_transform({}, inputs, outputs, None)["verified"] is False


def _load_runner():
    spec = importlib.util.spec_from_file_location("studio_config_matrix", ROOT / "scripts/studio_config_matrix.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def visual_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("visual")
    run_dir, result = _load_runner().run_visual(out, workers=2, mode="concurrent", run_id="chain")
    assert result["extra_records"]["status"] == "COMPLETED"
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    return run_dir, events


def test_runtime_records_inputs_outputs_and_geometry(visual_run) -> None:
    run_dir, events = visual_run
    artifacts = json.loads((run_dir / "artifacts.json").read_text())["artifacts"]
    assert "data:image/" not in (run_dir / "events.jsonl").read_text(), "pixels go to the artifact store, not the event log"
    w1 = [e for e in events if e["agent_id"] == "worker_01" and e["event_type"] in ("TOOL_CALL_REQUESTED", "TOOL_CALL_COMPLETED")]
    requests = [e for e in w1 if e["event_type"] == "TOOL_CALL_REQUESTED"]
    done = [e for e in w1 if e["event_type"] == "TOOL_CALL_COMPLETED"]
    # Requests name their input before execution (live display), completions record the authoritative input.
    assert [r["payload"]["visual_inputs"][0]["registry_id"] for r in requests] == [
        "input_image_1", "input_image_1", "tool_generated_image_2", "tool_generated_image_2", "tool_generated_image_4"]
    zoom_a, detect_a, zoom_b, detect_b = done[1], done[2], done[3], done[4]
    assert zoom_a["payload"]["visual"]["transform"]["crop_box"] == [438, 230, 640, 400]
    assert zoom_a["payload"]["visual"]["transform"]["verified"] is True
    out = zoom_a["payload"]["visual"]["outputs"][0]
    stored = artifacts[out["image"]["artifact_ref"]]
    assert (stored["width"], stored["height"]) == (202, 170) == (out["width"], out["height"])
    assert detect_a["payload"]["visual"]["inputs"][0]["registry_id"] == "tool_generated_image_2"
    assert detect_a["payload"]["canonical_result"]["boxes"] == [[67.0, 55.0, 96.0, 84.0], [114.0, 92.0, 141.0, 119.0]]
    assert zoom_b["payload"]["visual"]["transform"]["crop_box"] == [104, 83, 151, 128]
    assert detect_b["payload"]["canonical_result"]["boxes"] == [[10.0, 9.0, 37.0, 36.0]]
    # Registry IDs are per-question: both workers have a tool_generated_image_1, in different scopes.
    scopes = {e["agent_id"]: e["payload"]["image_scope"] for e in events if e["event_type"] == "TOOL_CALL_COMPLETED"}
    assert scopes["worker_01"] != scopes["worker_02"]


def test_instrumentation_never_changes_what_the_model_sees(tmp_path: Path) -> None:
    image = create_visual_scene(tmp_path / "scene.png")
    task = [{"type": "image", "value": str(image)}, {"type": "text", "value": "How many marked objects?"}]
    seen = []
    for sink in (None, lambda *args, **kwargs: {"event_id": "e"}):
        builder = VisualAgentBuilder(image)
        agent = builder(None, "worker_01", True)
        agent.event_sink = sink
        agent.generate(copy.deepcopy(task), task_id="t")
        seen.append(json.dumps(builder.policies["worker_01"].requests, sort_keys=True))
    assert seen[0] == seen[1]
    assert isinstance(builder.policies["worker_01"], VisualPolicy)


@pytest.mark.skipif(NODE is None, reason="Node.js is required for frontend tests")
def test_frontend_lineage_and_geometry(visual_run, tmp_path: Path) -> None:
    run_dir, _ = visual_run
    snapshot = public_snapshot(run_dir.parent, run_dir.name)
    data = tmp_path / "visual.json"
    data.write_text(json.dumps({"run": {"events": snapshot["events"], "artifacts": snapshot["artifacts"], "aliases": snapshot["artifact_aliases"]}}))
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests/studio/js/visual_lineage.test.cjs")],
        capture_output=True, text=True, timeout=120, check=False,
        env={"STUDIO_VISUAL_DATA": str(data), "STUDIO_GEOMETRY_VECTORS": str(ROOT / "tests/studio/geometry_vectors.json"), "PATH": str(Path(NODE).parent)},
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
