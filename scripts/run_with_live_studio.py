#!/usr/bin/env python3
"""Run a command while an Investigation Studio follows its run live.

Selection rules (see ``openvlharness/studio/lifecycle.py``): reuse a recorded
Studio only when ``/api/info`` reports the current API version, the same runs
directory, and the recorded token is accepted; otherwise start a new Studio on
the first free port at or after ``--port``. Outdated Studios and unrelated
listeners are reported and never killed. The browser opens the exact chosen
instance with a launch link that signs in and selects the run automatically,
before or after the run directory exists. Browser sessions survive reloads.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openvlharness.studio import lifecycle


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--runs-dir", type=Path, default=Path("outputs/multi_agent"))
    parser.add_argument("--host", default=os.getenv("STUDIO_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("STUDIO_PORT", "8787"))
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        default=os.getenv("STUDIO_OPEN_BROWSER", "1").lower() in {"0", "false", "no"},
    )
    parser.add_argument(
        "--stop-server-on-exit",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("a command is required after --")
    if not 0 < args.port < 65536:
        parser.error("--port must be in 1..65535")
    return args


def port_is_available(host: str, port: int) -> bool:
    bind_host = "127.0.0.1" if host in {"localhost", "0.0.0.0", "::"} else host
    family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.bind((bind_host, port))
        return True
    except OSError:
        return False


def find_compatible(
    runs_directory: Path, host: str, requested_port: int, notes: list[str]
) -> lifecycle.Session | None:
    """Reuse only a compatible Studio for this runs directory with a valid token."""
    candidates = lifecycle.read_sessions(runs_directory)
    supplied = os.getenv("STUDIO_VIEWER_TOKEN")
    if supplied and not any(item.port == requested_port for item in candidates):
        candidates.append(
            lifecycle.Session(
                host, requested_port, supplied, source="STUDIO_VIEWER_TOKEN"
            )
        )
    seen: set[int] = set()
    for session in candidates:
        if session.port in seen:
            continue
        seen.add(session.port)
        ok, result = lifecycle.usable(session, runs_directory)
        if ok:
            return session
        where = f"Studio record on :{session.port}"
        if result.kind == "unreachable":
            if session.source.startswith("studio-"):
                lifecycle.remove_session(
                    runs_directory, session.port, session.instance_id
                )
            notes.append(f"{where}: not running (stale record ignored).")
        elif result.kind in {"outdated_studio", "incompatible_version"}:
            notes.append(
                f"{where}: outdated Studio backend ({result.detail}); not reused. "
                f"Stop it with: python scripts/studio_ctl.py stop --port {session.port}"
            )
        else:
            notes.append(f"{where}: not reused ({result.detail or result.kind}).")
    if requested_port not in seen and not port_is_available(host, requested_port):
        notes.append(lifecycle.describe_listener(host, requested_port))
    return None


def start_studio(
    runs_directory: Path, host: str, requested_port: int
) -> tuple[lifecycle.Session, subprocess.Popen[bytes]]:
    support = lifecycle.support_dir(runs_directory)
    token = os.getenv("STUDIO_VIEWER_TOKEN") or lifecycle.new_token()
    evaluator_token = os.getenv("STUDIO_EVALUATOR_TOKEN") or lifecycle.new_token()
    port = requested_port
    for _attempt in range(5):
        while port < 65536 and not port_is_available(host, port):
            port += 1
        log_path = support / f"studio-{port}.log"
        log_handle = log_path.open("ab", buffering=0)
        environment = {
            **os.environ,
            "STUDIO_VIEWER_TOKEN": token,
            "STUDIO_EVALUATOR_TOKEN": evaluator_token,
        }
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "openvlharness.studio.server",
                "--host",
                host,
                "--port",
                str(port),
                "--runs-dir",
                str(runs_directory),
            ],
            cwd=ROOT,
            env=environment,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
        session = lifecycle.Session(
            host, port, token, process.pid, evaluator_token=evaluator_token
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break  # bind race or startup error: try the next port
            ok, result = lifecycle.usable(session, runs_directory)
            if ok:
                session.instance_id = result.info.get("instance_id")
                log_handle.close()
                return session, process
            time.sleep(0.15)
        log_handle.close()
        if process.poll() is None:
            process.terminate()
            raise RuntimeError(f"Studio did not become ready; inspect {log_path}")
        port += 1
    raise RuntimeError(f"Studio could not start; inspect logs in {support}")


def ensure_studio(
    runs_directory: Path, host: str, requested_port: int
) -> tuple[lifecycle.Session, subprocess.Popen[bytes] | None, list[str]]:
    runs_directory = runs_directory.resolve()
    runs_directory.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    session = find_compatible(runs_directory, host, requested_port, notes)
    if session is not None:
        return session, None, notes
    session, process = start_studio(runs_directory, host, requested_port)
    return session, process, notes


def open_browser(url: str) -> bool:
    return lifecycle.open_in_browser(url)


def show_run(session: lifecycle.Session, run_id: str, *, no_browser: bool, runs_dir: Path | None = None) -> None:
    """Open the exact Studio instance with a URL that selects the run.

    The viewer waits for the run to appear, so the browser may open before the
    run's manifest exists. The browser signs in automatically from the launch link.
    """
    try:
        link, _ttl = lifecycle.launch_link(session, run_id)
    except OSError as exc:
        print(f"Could not create a Studio link: {exc}", file=sys.stderr)
        return
    opened = False if no_browser else open_browser(link)
    state = "opened in your browser" if opened else "open this link"
    print(f"Live visualization ({state}):", flush=True)
    print(f"  {link}", flush=True)
    hint = None if opened else lifecycle.remote_access_hint(session.port)
    if hint:
        print(hint, flush=True)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    os.chdir(ROOT)
    try:
        session, started_server, notes = ensure_studio(
            args.runs_dir, args.host, args.port
        )
    except RuntimeError as exc:
        print(f"Investigation Studio unavailable: {exc}", file=sys.stderr, flush=True)
        print("The task was not started.", file=sys.stderr, flush=True)
        return 3
    for note in notes:
        print(f"Studio note: {note}", flush=True)
    origin = (
        f"started (pid {started_server.pid})"
        if started_server
        else "reused existing instance"
    )
    print(f"Live Studio: {session.base_url} — {origin}", flush=True)
    print(f"Live run: {args.run_id}", flush=True)

    task = subprocess.Popen(args.command, cwd=ROOT)
    # Open immediately: the viewer waits for the requested run to appear.
    show_run(session, args.run_id, no_browser=args.no_browser, runs_dir=args.runs_dir)
    try:
        return task.wait()
    except KeyboardInterrupt:
        task.terminate()
        return task.wait()
    finally:
        if args.stop_server_on_exit and started_server is not None:
            started_server.terminate()
            try:
                started_server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                started_server.kill()


if __name__ == "__main__":
    raise SystemExit(run())
