"""Studio server lifecycle, compatibility handshake, launch links, and launcher reuse."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import HTTPException

from openvlharness.studio import lifecycle
from openvlharness.studio.server import create_app

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
import fake_old_studio

spec = importlib.util.spec_from_file_location(
    "live_launcher", ROOT / "scripts/run_with_live_studio.py"
)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def route(app, path: str, method: str = "GET"):
    return next(
        r
        for r in app.routes
        if getattr(r, "path", None) == path
        and method in getattr(r, "methods", {method})
    )


@contextmanager
def background(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


@contextmanager
def unrelated_listener(port: int):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"hello from something else")

        def log_message(self, *args):
            pass

    with background(ThreadingHTTPServer(("127.0.0.1", port), Handler)) as server:
        yield server


# ---------------------------------------------------------------------------
# Handshake, health, tickets, configured architecture


def test_info_handshake_is_unauthenticated_and_non_sensitive(tmp_path: Path) -> None:
    app = create_app(tmp_path, viewer_token="secret-token-value", instance_id="abc123")
    info = asyncio.run(route(app, "/api/info").endpoint())
    assert info["application"] == lifecycle.APPLICATION
    assert info["api_version"] == lifecycle.API_VERSION
    assert info["ui_compatibility"] == lifecycle.UI_COMPATIBILITY
    assert info["runs_root_id"] == lifecycle.runs_root_id(tmp_path)
    assert info["instance_id"] == "abc123" and "topology" in info["features"]
    serialized = json.dumps(info)
    assert str(tmp_path) not in serialized and "secret-token-value" not in serialized
    health = asyncio.run(route(app, "/health").endpoint())
    assert "runs_directory" not in health and str(tmp_path) not in json.dumps(health)


def test_frontend_declares_the_backend_ui_contract() -> None:
    script = (ROOT / "openvlharness/studio/static/app.js").read_text()
    assert f'const UI_COMPATIBILITY = "{lifecycle.UI_COMPATIBILITY}"' in script
    assert "/api/info" in script


def test_launch_tickets_are_authenticated_single_use_and_expire(tmp_path: Path) -> None:
    app = create_app(tmp_path, viewer_token="tok")
    mint = route(app, "/api/launch-tickets", "POST")
    with pytest.raises(HTTPException):
        mint.dependant.dependencies[0].call("wrong")
    redeem = route(app, "/api/launch-tickets/redeem", "POST").endpoint
    ticket = asyncio.run(mint.endpoint({"ttl_seconds": 60}))["ticket"]
    assert asyncio.run(redeem({"ticket": ticket})) == {"token": "tok"}
    with pytest.raises(HTTPException) as reused:
        asyncio.run(redeem({"ticket": ticket}))
    assert reused.value.status_code == 401
    short = asyncio.run(mint.endpoint({"ttl_seconds": 10}))["ticket"]
    original = time.monotonic
    try:
        time.monotonic = lambda: original() + 11
        with pytest.raises(HTTPException):
            asyncio.run(redeem({"ticket": short}))
    finally:
        time.monotonic = original
    with pytest.raises(HTTPException):
        asyncio.run(redeem({"ticket": "made-up"}))


def test_configured_architecture_requires_auth_and_uses_a_worker_template(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "OPENAI_BASE_URL", "http://user:pw@10.1.2.3:9000/v1?api_key=sk-123"
    )
    agent_config = tmp_path / "agent.yaml"
    agent_config.write_text((ROOT / "examples/local_grounding_tools.yaml").read_text())
    app = create_app(
        tmp_path,
        viewer_token="tok",
        multi_agent_config=ROOT / "configs/multi_agent.yaml",
        agent_config=agent_config,
    )
    endpoint = route(app, "/api/architecture")
    with pytest.raises(HTTPException):
        endpoint.dependant.dependencies[0].call(None)
    payload = asyncio.run(endpoint.endpoint())
    topology = payload["topology"]
    assert payload["available"] and topology["scope"] == "configured"
    assert topology["agents"] == ["coordinator", "worker_template"]
    assert not any(node["id"].startswith("worker_0") for node in topology["nodes"])
    assert (
        topology["worker_template"]["default_count"] == 2
        and topology["worker_template"]["max_count"] == 4
    )
    assert {node["provenance"] for node in topology["nodes"]} == {"configured"}
    tools = sorted(
        node["label"] for node in topology["nodes"] if node["type"] == "tool"
    )
    assert "Visual_Grounding_Tool" in tools and "Zoom_In_Tool" in tools
    serialized = json.dumps(topology)
    for secret in ("pw@", "sk-123", "api_key", str(tmp_path)):
        assert secret not in serialized
    unavailable = create_app(tmp_path, viewer_token="tok")
    assert (
        asyncio.run(route(unavailable, "/api/architecture").endpoint())["available"]
        is False
    )


# ---------------------------------------------------------------------------
# Probe classification


def test_probe_classifies_compatible_outdated_unrelated_and_unreachable(
    tmp_path: Path,
) -> None:
    port = free_port()
    assert (
        lifecycle.probe(f"http://127.0.0.1:{port}", timeout=0.3).kind == "unreachable"
    )
    with background(fake_old_studio.serve(port, "old")):
        result = lifecycle.probe(f"http://127.0.0.1:{port}")
        assert result.kind == "outdated_studio"
        # The legacy readiness check (token accepted on /api/runs) would have passed.
        assert lifecycle.authorized(f"http://127.0.0.1:{port}", "old")
    with unrelated_listener(port):
        assert lifecycle.probe(f"http://127.0.0.1:{port}").kind == "unrelated"


# ---------------------------------------------------------------------------
# Server entry point


def run_server(
    port: int, runs: Path, token: str = "env-token-value-123"
) -> subprocess.Popen:
    env = {**os.environ, "STUDIO_VIEWER_TOKEN": token, "PYTHONUNBUFFERED": "1"}
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "openvlharness.studio.server",
            "--port",
            str(port),
            "--runs-dir",
            str(runs),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_server_refuses_occupied_port_without_claiming_readiness(
    tmp_path: Path,
) -> None:
    port = free_port()
    with unrelated_listener(port) as other:
        process = run_server(port, tmp_path)
        out, err = process.communicate(timeout=30)
        assert process.returncode == 2
        assert "Studio ready" not in out and "Viewer token" not in out
        assert "not an Investigation Studio" in err and "left untouched" in err
        assert other.socket.fileno() >= 0  # still serving
    with background(fake_old_studio.serve(port, "old")):
        process = run_server(port, tmp_path)
        _, err = process.communicate(timeout=30)
        assert (
            process.returncode == 2
            and "outdated Investigation Studio" in err
            and "studio_ctl.py stop" in err
        )


def test_server_announces_after_ready_keeps_token_off_argv_and_cleans_up(
    tmp_path: Path,
) -> None:
    port = free_port()
    token = "env-token-value-xyz"
    process = run_server(port, tmp_path, token)
    try:
        line = ""
        deadline = time.monotonic() + 30
        while "Studio ready" not in line and time.monotonic() < deadline:
            line = process.stdout.readline()
        assert "Studio ready" in line
        link_line = process.stdout.readline()
        assert "#ticket=" in link_line and token not in link_line
        cmdline = (
            Path(f"/proc/{process.pid}/cmdline").read_bytes().decode(errors="replace")
        )
        assert token not in cmdline
        record = lifecycle.session_path(tmp_path, port)
        assert record.is_file() and stat.S_IMODE(record.stat().st_mode) == 0o600
        session = lifecycle.read_sessions(tmp_path)[0]
        assert lifecycle.usable(session, tmp_path)[0]
        link, _ = lifecycle.launch_link(session, "some_run")
        assert (
            link.startswith(f"http://127.0.0.1:{port}/#ticket=")
            and "run=some_run" in link
            and token not in link
        )
    finally:
        process.terminate()
        process.wait(timeout=15)
    assert not lifecycle.session_path(tmp_path, port).exists()


# ---------------------------------------------------------------------------
# Launcher selection


@pytest.fixture
def started():
    processes = []
    yield processes
    for process in processes:
        process.terminate()
        process.wait(timeout=15)


def test_launcher_starts_then_reuses_a_compatible_studio(
    tmp_path: Path, started, monkeypatch
) -> None:
    monkeypatch.delenv("STUDIO_VIEWER_TOKEN", raising=False)
    port = free_port()
    first, process, _notes = launcher.ensure_studio(tmp_path, "127.0.0.1", port)
    started.append(process)
    assert process is not None and first.port == port
    assert lifecycle.probe(first.base_url).info["auth_required"] is True
    link, ttl = lifecycle.launch_link(first, "new_run")
    assert link.startswith(f"{first.base_url}/#ticket=") and "run=new_run" in link and ttl > 0
    assert lifecycle._get(f"{first.base_url}/api/runs")[0] == 401
    assert first.token not in Path(f"/proc/{process.pid}/cmdline").read_bytes().decode(
        errors="replace"
    )
    second, again, _ = launcher.ensure_studio(tmp_path, "127.0.0.1", port)
    assert (
        again is None
        and second.port == port
        and second.instance_id == first.instance_id
    )


def test_launcher_never_reuses_an_outdated_studio(
    tmp_path: Path, started, monkeypatch
) -> None:
    monkeypatch.delenv("STUDIO_VIEWER_TOKEN", raising=False)
    port = free_port()
    legacy = lifecycle.support_dir(tmp_path) / "session.json"
    legacy.write_text(
        json.dumps(
            {
                "host": "127.0.0.1",
                "port": port,
                "token": "old",
                "runs_directory": str(tmp_path),
            }
        )
    )
    with background(fake_old_studio.serve(port, "old")):
        session, process, notes = launcher.ensure_studio(tmp_path, "127.0.0.1", port)
        started.append(process)
        assert process is not None and session.port != port
        assert lifecycle.probe(session.base_url).kind == "compatible"
        assert any(
            "outdated" in note and "studio_ctl.py stop" in note for note in notes
        )
        assert (
            lifecycle.probe(f"http://127.0.0.1:{port}").kind == "outdated_studio"
        )  # untouched


def test_launcher_skips_unrelated_listener_and_stale_records(
    tmp_path: Path, started, monkeypatch
) -> None:
    monkeypatch.delenv("STUDIO_VIEWER_TOKEN", raising=False)
    port = free_port()
    stale_port = free_port()
    lifecycle.write_session(
        tmp_path, lifecycle.Session("127.0.0.1", stale_port, "t", 999999, "dead")
    )
    with unrelated_listener(port):
        session, process, notes = launcher.ensure_studio(tmp_path, "127.0.0.1", port)
        started.append(process)
        assert session.port != port and process is not None
        assert any("not an Investigation Studio" in note for note in notes)
        assert lifecycle.probe(f"http://127.0.0.1:{port}").kind == "unrelated"
    assert not lifecycle.session_path(tmp_path, stale_port).exists()


def test_launcher_does_not_reuse_a_studio_for_another_runs_directory(
    tmp_path: Path, started, monkeypatch
) -> None:
    monkeypatch.delenv("STUDIO_VIEWER_TOKEN", raising=False)
    port = free_port()
    other = tmp_path / "other"
    a, process_a, _ = launcher.ensure_studio(other, "127.0.0.1", port)
    started.append(process_a)
    # Copy the record so the second runs directory "knows" about the first server.
    lifecycle.write_session(tmp_path / "mine", a)
    b, process_b, notes = launcher.ensure_studio(tmp_path / "mine", "127.0.0.1", port)
    started.append(process_b)
    assert process_b is not None and b.port != a.port
    assert any("different runs directory" in note for note in notes)


def test_studio_ctl_refuses_to_stop_non_studio_processes(tmp_path: Path) -> None:
    port = free_port()
    with unrelated_listener(port):
        result = subprocess.run(
            [
                sys.executable,
                "scripts/studio_ctl.py",
                "--runs-dir",
                str(tmp_path),
                "stop",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 1 and "Refusing" in result.stderr
        assert lifecycle.probe(f"http://127.0.0.1:{port}").kind == "unrelated"


# ---- browser opening: never a terminal browser (it cannot run the Studio) ----------------

def test_headless_ssh_session_has_no_graphical_browser():
    ssh = {"SSH_CONNECTION": "1.2.3.4 5 6.7.8.9 22", "TERM": "xterm-256color"}
    assert not lifecycle.graphical_browser_available(ssh, "linux")
    assert not lifecycle.graphical_browser_available({**ssh, "BROWSER": "lynx"}, "linux")
    assert not lifecycle.graphical_browser_available({**ssh, "BROWSER": "/usr/bin/w3m -dump"}, "linux")
    assert "ssh -N -L 8794:127.0.0.1:8794" in lifecycle.remote_access_hint(8794, ssh)


def test_graphical_browsers_are_detected():
    assert lifecycle.graphical_browser_available({"DISPLAY": ":0"}, "linux")
    assert lifecycle.graphical_browser_available({"WAYLAND_DISPLAY": "wayland-0"}, "linux")
    assert lifecycle.graphical_browser_available({"BROWSER": "/home/u/.vscode-server/bin/helpers/browser.sh"}, "linux")
    assert lifecycle.graphical_browser_available({}, "darwin")
    assert lifecycle.remote_access_hint(8787, {}) is None


def test_open_in_browser_refuses_without_a_display(monkeypatch):
    import webbrowser

    for name in ("BROWSER", "DISPLAY", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(lifecycle.sys, "platform", "linux")
    monkeypatch.setattr(webbrowser, "get", lambda *a: (_ for _ in ()).throw(AssertionError("must not look up a browser")))
    assert lifecycle.open_in_browser("http://127.0.0.1:1/#ticket=x") is False


def test_open_in_browser_skips_a_text_browser_even_with_a_display(monkeypatch):
    import webbrowser

    class Lynx:
        name = "www-browser"

        def open(self, *a, **k):
            raise AssertionError("terminal browser must not be started")

    monkeypatch.delenv("BROWSER", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(webbrowser, "get", lambda *a: Lynx())
    assert lifecycle.open_in_browser("http://127.0.0.1:1/") is False
