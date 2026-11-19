#!/usr/bin/env python3
"""Start missing local demo services and wait for readiness (uses GPU resources)."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKERS = {
    "sam3_segment": ("sam3", 8086),
    "ocr": ("ocr", 8085),
    "depth_estimation": ("depth", 8087),
    "camera_trajectory": ("depth", 8087),
}


def ready(url: str) -> bool:
    try:
        with urlopen(url, timeout=2) as response:
            payload = json.load(response)
            if not isinstance(payload, dict):
                return False
            if url.endswith("/models"):
                return bool(payload.get("data"))
            return isinstance(payload, dict) and payload.get("status") not in {"error", "failed", "unhealthy"}
    except (OSError, HTTPError, URLError, ValueError):
        return False


def occupied(url: str) -> bool:
    address = urlsplit(url)
    try:
        with socket.create_connection((address.hostname, address.port or 80), timeout=1):
            return True
    except OSError:
        return False


def required_services(config: Path) -> list[tuple[str, str, int]]:
    settings = yaml.safe_load(config.read_text())
    model = os.path.expandvars(settings["services"]["models"]["orchestrator"]["base"]).rstrip("/")
    router = os.path.expandvars(settings["services"]["client"]["base_url"]).rstrip("/")
    result = [("qwen", model + "/models", 8222)]
    seen = set()
    for name, tool in settings["services"]["tools"].items():
        if "server_url" not in tool:
            continue
        if name not in WORKERS:
            raise ValueError(f"No local launcher for {name}; start it manually")
        service, port = WORKERS[name]
        base = os.path.expandvars(tool["server_url"]).rstrip("/")
        url = base + ("/v1/models" if service == "ocr" else "/health")
        if service not in seen:
            seen.add(service)
            result.append((service, url, port))
    # The router launcher reads its port from TOOL_SERVER_URL.
    result.append(("router", router + "/health", urlsplit(router).port or 8101))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-config", type=Path, default=Path("examples/local_grounding_tools.yaml"))
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--qwen-context-length", type=int, default=32768)
    args = parser.parse_args()
    if args.timeout <= 0 or args.qwen_context_length <= 0:
        parser.error("timeout and context length must be positive")
    os.chdir(ROOT)
    try:
        services = required_services(args.agent_config)
        # Validate all launch targets before starting any process.
        for service, url, port in services:
            endpoint = urlsplit(url)
            if endpoint.hostname not in {"localhost", "127.0.0.1", "::1"} or endpoint.scheme != "http" or endpoint.port != port:
                raise ValueError(f"{service}: automatic startup requires its configured local HTTP port {port}; start remote/custom services manually")
    except (ValueError, KeyError, OSError) as exc:
        print(f"Service setup failed: {exc}", flush=True)
        return 3
    folder = ROOT / "outputs/services"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    children = {}
    pending = []
    for service, url, _port in services:
        if ready(url):
            print(f"READY {service} (reusing)", flush=True)
            continue
        pending.append((service, url))
        if occupied(url):
            print(f"WAIT {service}: port occupied; waiting for existing service, without restarting it", flush=True)
            continue
        command = ["bash", "scripts/service.sh", service]
        if service == "qwen":
            command += ["--max-model-len", str(args.qwen_context_length)]
        if service == "router":
            command += ["--config", str(args.agent_config.resolve())]
        log = folder / f"{service}_{stamp}_{os.getpid()}.log"
        with log.open("xb") as output:
            child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                     stdout=output, stderr=subprocess.STDOUT,
                                     start_new_session=True, close_fds=True)
        children[service] = (child, log)
        print(f"START {service}: pid {child.pid}; log {log.relative_to(ROOT)}", flush=True)
    deadline = time.monotonic() + args.timeout
    last_update = 0.0
    while pending:
        for service, url in pending[:]:
            child, log = children.get(service, (None, None))
            if child is not None and child.poll() is not None:
                print(f"FAILED {service}: exit {child.returncode}; inspect {log}", flush=True)
                return 3
            if ready(url):
                print(f"READY {service}", flush=True)
                pending.remove((service, url))
        now = time.monotonic()
        if pending and now >= deadline:
            print("Timed out waiting for: " + ", ".join(name for name, _ in pending)
                  + ". Inspect outputs/services logs. No inference started; loading services were left running.", flush=True)
            return 3
        if pending and now - last_update >= 10:
            print("Loading: " + ", ".join(name for name, _ in pending), flush=True)
            last_update = now
        if pending:
            time.sleep(1)
    print("All required services are ready. Services stay running after this terminal closes.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
