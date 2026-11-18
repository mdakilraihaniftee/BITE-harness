#!/usr/bin/env python3
"""Inspect and manage Investigation Studio instances for a runs directory.

  status                 list recorded and probed Studios with compatibility
  url [--port] [--run]   mint a fresh single-use browser link for a usable Studio
  ensure [--port]        reuse a compatible Studio or start one, then print a link
  stop --port PORT       stop the Studio server process listening on PORT

``stop`` only signals a process that is (a) owned by you and (b) running
``openvlharness.studio.server``; any other listener is refused. Tokens are never
printed; links carry a single-use ticket.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openvlharness.studio import lifecycle
from scripts.run_with_live_studio import ensure_studio


def _status(root: Path, ports: list[int]) -> int:
    rows = []
    recorded = {session.port: session for session in lifecycle.read_sessions(root)}
    for port in sorted(set(recorded) | set(ports)):
        session = recorded.get(port) or lifecycle.Session("127.0.0.1", port, "")
        result = lifecycle.probe(session.base_url, timeout=0.6)
        if result.kind == "unreachable" and port not in recorded:
            continue
        usable = False
        if port in recorded and result.kind == "compatible":
            usable, result = lifecycle.usable(session, root)
        pid = lifecycle.listener_pid(port)
        verdict = "USABLE" if usable else result.kind.upper()
        rows.append(
            (port, pid or "-", verdict, result.detail or "", session.source or "probe")
        )
    if not rows:
        print("No Investigation Studio is running for this runs directory.")
        return 1
    print(f"{'PORT':<6} {'PID':<9} {'STATE':<22} {'RECORD':<18} DETAIL")
    for port, pid, verdict, detail, source in rows:
        print(f"{port:<6} {pid!s:<9} {verdict:<22} {source:<18} {detail}")
    return 0


def _usable_session(root: Path, port: int | None) -> lifecycle.Session | None:
    for session in lifecycle.read_sessions(root):
        if port is not None and session.port != port:
            continue
        if lifecycle.usable(session, root)[0]:
            return session
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path(os.getenv("STUDIO_RUNS_DIR", "outputs/multi_agent")),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    url = sub.add_parser("url")
    url.add_argument("--port", type=int)
    url.add_argument("--run")
    url.add_argument(
        "--viewer-only",
        action="store_true",
        help="Mint a link without evaluator (ground-truth release) scope, e.g. to share.",
    )
    url.add_argument(
        "--open", action="store_true", help="also open the link in a browser"
    )
    ensure = sub.add_parser("ensure")
    ensure.add_argument(
        "--port", type=int, default=int(os.getenv("STUDIO_PORT", "8787"))
    )
    ensure.add_argument("--run")
    ensure.add_argument("--open", action="store_true")
    ensure.add_argument("--viewer-only", action="store_true")
    stop = sub.add_parser("stop")
    stop.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    root = args.runs_dir.resolve()
    os.chdir(ROOT)

    if args.command == "status":
        return _status(root, [8787, 8788])

    if args.command in {"url", "ensure"}:
        if args.command == "ensure":
            session, process, notes = ensure_studio(root, "127.0.0.1", args.port)
            for note in notes:
                print(f"Note: {note}")
            origin = f"started, pid {process.pid}" if process else "reused"
            print(f"Studio: {session.base_url} ({origin})")
        else:
            session = _usable_session(root, args.port)
            if session is None:
                print(
                    "No usable Studio found. Start one with: python scripts/studio_ctl.py ensure",
                    file=sys.stderr,
                )
                return 1
        link, ttl = lifecycle.launch_link(
            session, args.run, evaluator=not args.viewer_only
        )
        scope = "viewer only" if args.viewer_only or not session.evaluator_token else "viewer + evaluator"
        print(f"Link scope: {scope}")
        print(f"Single-use link (valid {ttl // 60} min): {link}")
        if args.open:
            webbrowser.open(link, new=2)
        return 0

    pid = lifecycle.listener_pid(args.port)
    if pid is None:
        print(f"Nothing you own is listening on port {args.port}.", file=sys.stderr)
        return 1
    if not lifecycle.is_studio_process(pid):
        print(
            f"Refusing to stop pid {pid} on port {args.port}: it is not your Investigation Studio server.",
            file=sys.stderr,
        )
        return 1
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if lifecycle.listener_pid(args.port) is None:
            break
        time.sleep(0.1)
    legacy = lifecycle.support_dir(root) / "session.json"
    for session in lifecycle.read_sessions(root):
        if session.port == args.port and session.source == "session.json":
            legacy.unlink(missing_ok=True)
    print(f"Stopped Investigation Studio pid {pid} on port {args.port}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
