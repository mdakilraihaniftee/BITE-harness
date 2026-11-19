"""Serve the Investigation Studio with automatic browser sign-in."""

from __future__ import annotations

import argparse
import asyncio
import errno
import json
import os
import secrets
import signal
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import lifecycle
from .reference import ReferenceResolver
from .replay import (
    annotated_events,
    artifact_file,
    authorized_memory,
    list_runs,
    memory_policy,
    public_snapshot,
)


def create_app(
    runs_directory: str | Path,
    *,
    viewer_token: str,
    allow_private_memory: bool = True,
    multi_agent_config: str | Path | None = None,
    agent_config: str | Path | None = None,
    instance_id: str | None = None,
    evaluator_token: str | None = None,
    reference_dir: str | Path | None = None,
    dataset_loader=None,
    experiments_dir: str | Path | None = None,
) -> FastAPI:
    root = Path(runs_directory).resolve()
    # Recorded PARSEC-VL benchmark summaries (read-only; never executed from the UI).
    experiments_root = Path(experiments_dir or os.getenv("STUDIO_EXPERIMENTS_DIR")
                            or Path(__file__).resolve().parents[2] / "results/reference").resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not viewer_token:
        raise ValueError("A nonempty Studio viewer token is required")
    if evaluator_token is not None and (
        not evaluator_token or secrets.compare_digest(evaluator_token, viewer_token)
    ):
        raise ValueError("The evaluator token must be nonempty and differ from the viewer token")
    instance = instance_id or secrets.token_hex(8)
    # Evaluator-only label store; outside any run directory and never listed as a run.
    references = ReferenceResolver(
        Path(reference_dir).resolve() if reference_dir else root / ".references",
        dataset_loader=dataset_loader,
    )
    tickets: dict[str, tuple[float, tuple[str, ...]]] = {}
    tickets_lock = threading.Lock()
    static = Path(__file__).with_name("static")
    app = FastAPI(
        title="OpenVLHarness Investigation Studio",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def authorize(
        x_studio_token: Annotated[str | None, Header()] = None,
        request: Request = None,
    ) -> None:
        credential = x_studio_token or (request.cookies.get(f"studio_viewer_{instance}") if request else None)
        if credential is None or not secrets.compare_digest(
            credential, viewer_token
        ):
            raise HTTPException(status_code=401, detail="Invalid Studio viewer token")

    def is_evaluator(value: str | None, request: Request = None) -> bool:
        value = value or (request.cookies.get(f"studio_evaluator_{instance}") if request else None)
        return bool(
            evaluator_token
            and value is not None
            and secrets.compare_digest(value, evaluator_token)
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'"
        )
        return response

    @app.get("/health")
    async def health():
        # No filesystem path: identity is the non-secret runs_root_id in /api/info.
        return {"status": "ok", "api_version": lifecycle.API_VERSION}

    @app.get("/api/info")
    async def info():
        """Unauthenticated, non-sensitive compatibility handshake."""
        return {
            "application": lifecycle.APPLICATION,
            "api_version": lifecycle.API_VERSION,
            "ui_compatibility": lifecycle.UI_COMPATIBILITY,
            "features": list(lifecycle.FEATURES),
            "auth_required": True,
            "runs_root_id": lifecycle.runs_root_id(root),
            "instance_id": instance,
            "private_memory": allow_private_memory,
            "evaluator_access_configured": bool(evaluator_token),
        }

    @app.post("/api/launch-tickets", dependencies=[Depends(authorize)])
    async def mint_ticket(
        payload: Annotated[dict[str, Any] | None, Body()] = None,
        x_studio_evaluator_token: Annotated[str | None, Header()] = None,
        request: Request = None,
    ):
        ttl = 600
        if isinstance(payload, dict) and isinstance(payload.get("ttl_seconds"), int):
            ttl = max(10, min(900, payload["ttl_seconds"]))
        scopes: tuple[str, ...] = ()
        if isinstance(payload, dict) and "evaluator" in (payload.get("scopes") or []):
            # Only an evaluator can delegate evaluator access to a browser.
            if not is_evaluator(x_studio_evaluator_token, request):
                raise HTTPException(status_code=403, detail="Evaluator scope requires the evaluator token")
            scopes = ("evaluator",)
        ticket = secrets.token_urlsafe(24)
        now = time.monotonic()
        with tickets_lock:
            for key in [key for key, (expiry, _) in tickets.items() if expiry < now]:
                tickets.pop(key, None)
            if len(tickets) >= 256:
                tickets.pop(next(iter(tickets)))
            tickets[ticket] = (now + ttl, scopes)
        return {"ticket": ticket, "expires_in": ttl, "scopes": list(scopes)}

    @app.post("/api/launch-tickets/redeem")
    async def redeem_ticket(
        payload: Annotated[dict[str, Any], Body()],
        response: Response = None,
        request: Request = None,
    ):
        """Sign in automatically when a script's launch link opens in a browser."""
        ticket = payload.get("ticket") if isinstance(payload, dict) else None
        with tickets_lock:
            entry = tickets.pop(ticket, None) if isinstance(ticket, str) else None
        if entry is None or entry[0] < time.monotonic():
            raise HTTPException(
                status_code=401, detail="Launch link expired or already used"
            )
        result: dict[str, Any] = {"token": viewer_token}
        if "evaluator" in entry[1] and evaluator_token:
            result["evaluator_token"] = evaluator_token
        if response is not None:
            options = {
                "httponly": True,
                "samesite": "strict",
                "secure": bool(request and request.url.scheme == "https"),
            }
            response.set_cookie(f"studio_viewer_{instance}", viewer_token, **options)
            if "evaluator_token" in result:
                response.set_cookie(f"studio_evaluator_{instance}", evaluator_token, **options)
            else:
                response.delete_cookie(f"studio_evaluator_{instance}", **options)
        return result

    @app.get("/api/session", dependencies=[Depends(authorize)])
    async def browser_session(
        x_studio_evaluator_token: Annotated[str | None, Header()] = None,
        request: Request = None,
    ):
        return {"authenticated": True, "evaluator": is_evaluator(x_studio_evaluator_token, request)}

    @app.get("/api/architecture", dependencies=[Depends(authorize)])
    async def architecture():
        """Configured architecture for the no-run state (never observed activity)."""
        if not multi_agent_config:
            return {
                "available": False,
                "reason": "No multi-agent configuration was provided to this Studio.",
            }
        try:
            from ..multi_agent import load_multi_agent_config
            from .topology import build_configured_topology

            config = load_multi_agent_config(multi_agent_config)
            topology = build_configured_topology(
                config, agent_config=agent_config, source=Path(multi_agent_config).name
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {
                "available": False,
                "reason": f"Configuration could not be read: {type(exc).__name__}",
            }
        return {"available": True, "topology": topology}

    @app.get("/api/parsec/experiments", dependencies=[Depends(authorize)])
    async def parsec_experiments():
        from ..parsec_vl.report import load_comparisons

        return {"experiments": load_comparisons(experiments_root), "directory": experiments_root.name}

    @app.get("/api/runs", dependencies=[Depends(authorize)])
    async def runs():
        return {"runs": list_runs(root)}

    @app.get("/api/runs/{run_id}/snapshot", dependencies=[Depends(authorize)])
    async def snapshot(run_id: str):
        try:
            return public_snapshot(root, run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

    @app.get("/api/runs/{run_id}/topology", dependencies=[Depends(authorize)])
    async def topology(run_id: str):
        try:
            _, value = annotated_events(root, run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        return value

    @app.get("/api/runs/{run_id}/events", dependencies=[Depends(authorize)])
    async def events(run_id: str, after: int = Query(-1, ge=-1)):
        try:
            values, _ = annotated_events(root, run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        return {"events": [item for item in values if item["sequence"] > after]}

    @app.get("/api/runs/{run_id}/stream", dependencies=[Depends(authorize)])
    async def stream(
        request: Request,
        run_id: str,
        cursor: int = Query(-1, ge=-1),
        follow: bool = Query(True),
    ):
        try:
            annotated_events(root, run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

        if not follow:
            values, _ = annotated_events(root, run_id)
            pending = [item for item in values if item["sequence"] > cursor][:200]
            body = "".join(
                f"id: {event['sequence']}\nevent: investigation\ndata: "
                f"{json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
                for event in pending
            )
            return Response(body, media_type="text/event-stream")

        async def generate():
            nonlocal cursor
            last_heartbeat = time.monotonic()
            while True:
                try:
                    values, _ = annotated_events(root, run_id)
                except KeyError:
                    return
                pending = [item for item in values if item["sequence"] > cursor]
                for event in pending[:200]:
                    cursor = max(cursor, event["sequence"])
                    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    yield f"id: {event['sequence']}\nevent: investigation\ndata: {data}\n\n"
                if not follow:
                    return
                if await request.is_disconnected():
                    return
                now = time.monotonic()
                if now - last_heartbeat >= 10:
                    yield f": heartbeat {cursor}\n\n"
                    last_heartbeat = now
                await asyncio.sleep(0.4 if pending else 0.8)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    @app.get(
        "/api/runs/{run_id}/artifacts/{artifact_id}", dependencies=[Depends(authorize)]
    )
    async def artifact(run_id: str, artifact_id: str):
        try:
            path, record = artifact_file(root, run_id, artifact_id)
        except (KeyError, OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=404, detail="Artifact not found") from exc
        return FileResponse(
            path,
            media_type=record.get("mime_type", "application/octet-stream"),
            headers={"Content-Disposition": "inline"},
        )

    @app.get("/api/runs/{run_id}/reference", dependencies=[Depends(authorize)])
    async def reference(
        run_id: str,
        x_studio_evaluator_token: Annotated[str | None, Header()] = None,
        request: Request = None,
    ):
        """Ground-truth status; the value is released only post-run to evaluators."""
        try:
            return await asyncio.to_thread(
                references.status,
                root,
                run_id,
                evaluator=is_evaluator(x_studio_evaluator_token, request),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

    @app.get("/api/evaluator/check", dependencies=[Depends(authorize)])
    async def evaluator_check(
        x_studio_evaluator_token: Annotated[str | None, Header()] = None,
        request: Request = None,
    ):
        if not is_evaluator(x_studio_evaluator_token, request):
            raise HTTPException(status_code=403, detail="Evaluator token not accepted")
        return {"evaluator": True}

    @app.get("/api/runs/{run_id}/memory/{agent_id}", dependencies=[Depends(authorize)])
    async def memory(run_id: str, agent_id: str):
        if not allow_private_memory:
            raise HTTPException(
                status_code=403, detail="Private memory viewing is disabled"
            )
        try:
            return {
                "agent_id": agent_id,
                "scope": "private",
                "policy": memory_policy(root, run_id, agent_id),
                "records": authorized_memory(root, run_id, agent_id),
            }
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Agent memory not found"
            ) from exc

    @app.get("/favicon.ico")
    async def favicon():
        return Response(status_code=204)

    @app.get("/")
    async def index():
        return FileResponse(static / "index.html")

    app.mount("/static", StaticFiles(directory=static), name="static")
    return app


def _bind(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        sock.listen(2048)
    except OSError:
        sock.close()
        raise
    sock.set_inheritable(True)
    return sock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", default="outputs/multi_agent")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--token",
        default=None,
        help="Discouraged: command-line tokens are visible in the process list. "
        "Prefer the STUDIO_VIEWER_TOKEN environment variable.",
    )
    parser.add_argument("--disable-private-memory", action="store_true")
    parser.add_argument(
        "--disable-evaluator",
        action="store_true",
        help="Do not release ground-truth references to anyone (no evaluator token).",
    )
    parser.add_argument(
        "--reference-dir",
        default=os.getenv("STUDIO_REFERENCE_DIR"),
        help="Evaluator-only reference artifacts (default: <runs-dir>/.references).",
    )
    parser.add_argument(
        "--experiments-dir",
        default=os.getenv("STUDIO_EXPERIMENTS_DIR"),
        help="Recorded PARSEC-VL benchmark results for the comparison view (default: outputs/parsec_vl).",
    )
    parser.add_argument(
        "--multi-agent-config",
        default=os.getenv("STUDIO_MULTI_AGENT_CONFIG", "configs/multi_agent.yaml"),
        help="Configuration drawn as the configured architecture when no run is selected.",
    )
    parser.add_argument(
        "--agent-config",
        default=os.getenv("AGENT_CONFIG"),
        help="Agent configuration used by the runners (defaults to $AGENT_CONFIG).",
    )
    parser.add_argument(
        "--print-token",
        action="store_true",
        help="Also print the long-lived viewer token (otherwise only a single-use link).",
    )
    args = parser.parse_args(argv)
    if not 0 < args.port < 65536:
        parser.error("--port must be in 1..65535")
    supplied = os.getenv("STUDIO_VIEWER_TOKEN") or args.token
    if args.token:
        print(
            "Warning: --token is visible in the process list; prefer STUDIO_VIEWER_TOKEN.",
            file=sys.stderr,
        )
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not supplied:
        parser.error("Non-loopback hosting requires an explicit STUDIO_VIEWER_TOKEN")
    token = supplied or lifecycle.new_token()
    evaluator = (
        None
        if args.disable_evaluator
        else (os.getenv("STUDIO_EVALUATOR_TOKEN") or lifecycle.new_token())
    )
    if evaluator is not None and secrets.compare_digest(evaluator, token):
        parser.error("STUDIO_EVALUATOR_TOKEN must differ from the viewer token")
    multi_config = (
        args.multi_agent_config
        if args.multi_agent_config and Path(args.multi_agent_config).is_file()
        else None
    )

    try:
        sock = _bind(args.host, args.port)
    except OSError as exc:
        reason = (
            lifecycle.describe_listener(args.host, args.port)
            if exc.errno == errno.EADDRINUSE
            else str(exc)
        )
        print(
            f"Studio NOT started: cannot bind {args.host}:{args.port}. {reason}",
            file=sys.stderr,
            flush=True,
        )
        return 2

    import uvicorn

    instance = secrets.token_hex(8)
    root = Path(args.runs_dir).resolve()
    app = create_app(
        root,
        viewer_token=token,
        allow_private_memory=not args.disable_private_memory,
        multi_agent_config=multi_config,
        agent_config=args.agent_config,
        instance_id=instance,
        evaluator_token=evaluator,
        reference_dir=args.reference_dir,
        experiments_dir=args.experiments_dir,
    )
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="warning"))
    session = lifecycle.Session(
        host=args.host,
        port=args.port,
        token=token,
        pid=os.getpid(),
        instance_id=instance,
        api_version=lifecycle.API_VERSION,
        started_at=datetime.now(timezone.utc).isoformat(),
        evaluator_token=evaluator or "",
    )

    def announce() -> None:
        # Report readiness only after the API answers on the bound socket.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not server.should_exit:
            result = lifecycle.probe(session.base_url, timeout=0.5)
            if (
                result.kind == "compatible"
                and result.info.get("instance_id") == instance
            ):
                lifecycle.write_session(root, session)
                try:
                    link, ttl = lifecycle.launch_link(session)
                except OSError:
                    link, ttl = session.base_url, 0
                print(
                    f"Studio ready: {session.base_url}  (pid {os.getpid()}, {lifecycle.API_VERSION})",
                    flush=True,
                )
                label = f"Open (single-use link, valid {ttl // 60} min)" if ttl else "Open visualization"
                print(f"{label}: {link}", flush=True)
                if args.print_token:
                    print(f"Viewer token: {token}", flush=True)
                return
            time.sleep(0.1)
        print("Studio did not become ready within 30 s.", file=sys.stderr, flush=True)

    def cleanup() -> None:
        lifecycle.remove_session(root, args.port, instance)

    def on_signal(signum, _frame) -> None:
        # uvicorn shuts down gracefully, restores these handlers, then re-raises
        # the signal; remove the session record before exiting.
        cleanup()
        raise SystemExit(0)

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, on_signal)
    threading.Thread(target=announce, daemon=True).start()
    try:
        server.run(sockets=[sock])
    finally:
        cleanup()
        sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
