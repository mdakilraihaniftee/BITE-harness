#!/usr/bin/env python3
"""Rerun all six Studio browser suites with fresh offline fixtures and recorded real runs.

No inference: real runs are copied from disk. Credentials are passed only in the
environment. Output and screenshots go to a fresh verification directory.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys

from parsec_audit import ROOT, Runner, fixture_suite, read, require, write


def prepare(out):
    from studio_config_matrix import run_fixture, run_visual

    fixture = fixture_suite(out, trials=1, delay=0.3)
    runs = out / "runs"
    for n, memory, peer in ((1, False, False), (2, True, True), (3, True, False), (4, False, True)):
        run_fixture(runs, workers=n, memory=memory, peer=peer,
                    run_id=f"fixture_w{n}_mem{'on' if memory else 'off'}_peer{'on' if peer else 'off'}")
    run_visual(runs, workers=2, run_id="visual_chain_fixture", tool_scheduler="e2", tool_delay=0.05)
    copies = {}
    for name, source in {
        "real_fsc147_row0_studio": ROOT / "outputs/multi_agent/real_fsc147_row0_studio",
        "real_two_worker_smoke_v3": ROOT / "outputs/multi_agent/real_two_worker_smoke_v3",
        "example_fsc147_row25": ROOT / "outputs/multi_agent/example_fsc147_row25",
        "fsc147_val_row_24_20261118_095252": ROOT / "outputs/multi_agent/fsc147_val_row_24_20261118_095252",
        "legacy_demo": ROOT / "outputs/studio_validation/legacy_demo",
    }.items():
        require((source / "events.jsonl").exists(), f"Required recorded run missing: {source}")
        shutil.copytree(source, runs / name)
        copies[name] = str(source.relative_to(ROOT))
    write(out / "recorded_run_sources.json", copies)
    return fixture


def main():
    os.chdir(ROOT)
    r = Runner("verify")
    require(shutil.which("node") and shutil.which("google-chrome"), "Node and Chrome are required")
    fixture = None
    with (r.out / "browser_fixture_preparation.log").open("w") as log, contextlib.redirect_stdout(log):
        fixture = r.function("Browser fixture preparation", lambda: prepare(r.out))
    print("Prepared fresh browser fixtures and copied recorded real runs.", flush=True)
    if not fixture:
        return r.finish()
    runs = r.out / "runs"
    r.env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + r.env.get("PATH", "")
    for script, name in (("studio_protocol_fixture.py", "studio_protocol_fixture"),
                         ("multi_agent_smoke.py", "studio_demo_architecture")):
        if not r.command(f"Prepare {name}", [sys.executable, f"scripts/{script}", "--output-dir", str(runs), "--run-id", name]):
            return r.finish()
    from run_with_live_studio import ensure_studio

    session, started, _ = ensure_studio(runs, "127.0.0.1", 9190)
    r.env.update(STUDIO_VIEWER_TOKEN=session.token, STUDIO_EVALUATOR_TOKEN=session.evaluator_token)
    base = ["node", "scripts/studio_browser_matrix.mjs", "--base", session.base_url, "--runs-dir", str(runs)]
    ids = fixture["run_ids"]
    try:
        for suite, flags in (
            ("parsec", ["--parsec", ",".join(ids[k] for k in ("legacy", "sequential", "parallel", "adopted", "pruned", "four_workers"))]),
            ("simple", ["--simple", "fixture_w1_memoff_peeroff,fixture_w4_memoff_peeron,example_fsc147_row25"]),
            ("story", ["--story", "example_fsc147_row25,fixture_w1_memoff_peeroff,studio_protocol_fixture,fixture_w2_memon_peeron"]),
            ("visual", ["--visual", "visual_chain_fixture,fsc147_val_row_24_20261118_095252"]),
            ("matrix", []),
        ):
            r.command(f"Browser {suite}", base + ["--out", str(r.out / suite)] + flags, timeout=600)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            old_port = sock.getsockname()[1]
        r.command("Browser original", ["node", "scripts/studio_browser_check.mjs", "--base", session.base_url,
                  "--runs-dir", str(runs), "--out", str(r.out / "original"), "--old-port", str(old_port)], timeout=600)
    finally:
        if started is not None:
            started.terminate()
            started.wait(timeout=15)
    reports = {}
    for path in r.out.glob("*/*.json"):
        if path.name.startswith("browser-"):
            data = read(path)
            if isinstance(data, dict) and "checks" in data:
                reports[path.parent.name] = {"passed": sum(bool(c["ok"]) for c in data["checks"]),
                                            "total": len(data["checks"]), "failures": [c for c in data["checks"] if not c["ok"]]}
    write(r.out / "browser_counts.json", reports)
    print(json.dumps(reports, indent=2), flush=True)
    return r.finish()


if __name__ == "__main__":
    raise SystemExit(main())
