"""Startup orchestration checks without loading models or contacting services."""
import io
import json
import subprocess
import sys

import pytest

from scripts import ensure_local_services as services


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = services.ROOT / "examples/local_grounding_tools.yaml"
    for name, port, suffix in (
        ("MODEL_BASE_URL", 8222, "/v1"), ("TOOL_SERVER_URL", 18101, ""),
        ("SAM3_SERVER_URL", 8086, ""), ("OCR_SERVER_URL", 8085, ""),
        ("DEPTH_ESTIMATION_SERVER_URL", 8087, ""),
    ):
        monkeypatch.setenv(name, f"http://127.0.0.1:{port}{suffix}")
    monkeypatch.setattr(services, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["ensure_local_services.py", "--agent-config", str(path), "--timeout", "1"])
    return path


def test_services_match_profile_and_ocr_models_route(config):
    result = services.required_services(config)
    assert [item[0] for item in result] == ["qwen", "sam3", "ocr", "depth", "router"]
    assert next(url for name, url, _ in result if name == "ocr").endswith(":8085/v1/models")
    assert next(port for name, _, port in result if name == "router") == 18101


@pytest.mark.parametrize("payload,expected", [({"data": []}, False), ({"data": [{"id": "qwen"}]}, True)])
def test_model_readiness_requires_served_models(monkeypatch, payload, expected):
    monkeypatch.setattr(services, "urlopen", lambda *_a, **_k: io.BytesIO(json.dumps(payload).encode()))
    assert services.ready("http://127.0.0.1:8222/v1/models") is expected


def forbidden_start(*_args, **_kwargs):
    pytest.fail("Should not start a process")


def test_healthy_services_reused(config, monkeypatch):
    monkeypatch.setattr(services, "ready", lambda _url: True)
    monkeypatch.setattr(subprocess, "Popen", forbidden_start)
    assert services.main() == 0


def test_occupied_unhealthy_service_times_out_without_duplicate(config, monkeypatch, capsys):
    monkeypatch.setattr(services, "ready", lambda _url: False)
    monkeypatch.setattr(services, "occupied", lambda _url: True)
    monkeypatch.setattr(subprocess, "Popen", forbidden_start)
    ticks = iter([0, 2])
    monkeypatch.setattr(services.time, "monotonic", lambda: next(ticks))
    assert services.main() == 3
    assert "No inference started" in capsys.readouterr().out


def test_remote_target_rejected_before_any_start(config, monkeypatch):
    monkeypatch.setenv("SAM3_SERVER_URL", "http://192.0.2.1:8086")
    monkeypatch.setattr(subprocess, "Popen", forbidden_start)
    assert services.main() == 3


def test_failed_child_reports_log_and_stops_before_task(config, monkeypatch, capsys):
    class Failed:
        pid = 123
        returncode = 1

        def poll(self):
            return self.returncode

    calls = []
    def start(command, **kwargs):
        calls.append((command, kwargs))
        return Failed()
    monkeypatch.setattr(services, "ready", lambda _url: False)
    monkeypatch.setattr(services, "occupied", lambda _url: False)
    monkeypatch.setattr(subprocess, "Popen", start)
    assert services.main() == 3
    assert "FAILED qwen: exit 1; inspect" in capsys.readouterr().out
    assert all(command[:2] == ["bash", "scripts/service.sh"] and kwargs["start_new_session"] for command, kwargs in calls)
