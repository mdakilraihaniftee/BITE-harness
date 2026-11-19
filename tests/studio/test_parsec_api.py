"""PARSEC-VL comparison endpoint: authenticated, read-only, labelled, no absolute paths."""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from openvlharness.parsec_vl.report import load_comparisons
from openvlharness.studio.server import create_app


def route_for(app, path):
    return next(route for route in app.routes if getattr(route, "path", None) == path)


def recorded(tmp_path: Path) -> Path:
    base = tmp_path / "parsec_vl"
    (base / "phase2" / "actions").mkdir(parents=True)
    (base / "phase2" / "actions" / "actions.json").write_text(json.dumps({"label": "FIXTURE", "rows": [
        {"policy": "E0", "tool_span_mean": 1.3, "tool_span_sd": 0.01, "speedup_vs_first": 1.0, "answer_wall_mean": 1.31, "overlapping_pairs_mean": 0},
        {"policy": "E2", "tool_span_mean": 1.0, "tool_span_sd": 0.01, "speedup_vs_first": 1.3, "answer_wall_mean": 1.01, "overlapping_pairs_mean": 1},
    ]}))
    return base


def test_endpoint_requires_the_viewer_token_and_serves_labelled_tables(tmp_path):
    app = create_app(tmp_path / "runs", viewer_token="secret", experiments_dir=recorded(tmp_path))
    route = route_for(app, "/api/parsec/experiments")
    authorize = route.dependant.dependencies[0].call
    with pytest.raises(HTTPException) as denied:
        authorize(None)
    assert denied.value.status_code == 401
    authorize("secret")
    body = asyncio.run(route.endpoint())
    [fixed] = [e for e in body["experiments"] if e["id"] == "fixed_plan"]
    assert fixed["evidence"] == "FIXTURE" and [r["label"] for r in fixed["rows"]] == ["E0", "E2"]
    assert fixed["source"] == "parsec_vl/phase2/actions/actions.json"  # relative, never a home path
    assert str(tmp_path) not in json.dumps(body)
    assert route.methods == {"GET"}  # read-only: there is no way to start work from this view


def test_missing_or_broken_results_are_skipped(tmp_path):
    base = tmp_path / "parsec_vl"
    (base / "phase2" / "actions").mkdir(parents=True)
    (base / "phase2" / "actions" / "actions.json").write_text("{not json")
    assert load_comparisons(base) == []
    assert load_comparisons(tmp_path / "nowhere") == []


def test_every_recorded_experiment_has_an_evidence_label():
    for experiment in load_comparisons("outputs/parsec_vl"):
        assert experiment["evidence"] in ("REAL", "FIXTURE", "SYNTHETIC")
        assert experiment["rows"] and experiment["primary_metric"] in experiment["metrics"]
        assert not experiment["source"].startswith("/")
