"""Studio instance identity, discovery, compatibility, and launch links.

Shared by the server entry point, the task launcher, and ``scripts/studio_ctl.py``
so every tool applies the same rules:

* A listener counts as a usable Studio only if ``/api/info`` reports this
  application, the exact API version, and the same runs directory identity, and
  the recorded viewer token is accepted. A bare HTTP 200 or ``/health`` is never
  sufficient.
* Older Studio backends (``/health`` without ``/api/info``) are reported as
  outdated and never reused. Unrelated listeners are left alone.
* Viewer tokens live only in ``<runs>/.studio/studio-<port>.json`` (mode 0600)
  and in process environments, never on command lines. Browser links carry a
  single-use, short-lived launch ticket instead of the token.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

APPLICATION = "OpenVLHarness Investigation Studio"
API_VERSION = "studio.api.v3"
UI_COMPATIBILITY = "studio.ui.v3"
FEATURES = (
    "topology",
    "configured_architecture",
    "stream",
    "launch_tickets",
    "replay",
    "reference_release",
    "coordinator_estimates",
    "run_configuration",
)


def runs_root_id(path: str | Path) -> str:
    """Non-secret identity of a runs directory (no filesystem path is exposed)."""
    return hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:16]


def support_dir(root: str | Path) -> Path:
    path = Path(root).resolve() / ".studio"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


@dataclass
class Session:
    host: str
    port: int
    token: str
    pid: int | None = None
    instance_id: str | None = None
    api_version: str | None = None
    started_at: str | None = None
    # Separate credential for releasing ground-truth references (owner-only file).
    evaluator_token: str = field(default="", repr=False)
    source: str = field(default="", compare=False)

    @property
    def base_url(self) -> str:
        host = "127.0.0.1" if self.host in {"0.0.0.0", "::", "localhost"} else self.host
        if ":" in host:
            host = f"[{host}]"
        return f"http://{host}:{self.port}"


def session_path(root: str | Path, port: int) -> Path:
    return support_dir(root) / f"studio-{port}.json"


def write_session(root: str | Path, session: Session) -> Path:
    path = session_path(root, session.port)
    temporary = path.with_suffix(".tmp")
    payload = {key: value for key, value in asdict(session).items() if key != "source"}
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")
    os.replace(temporary, path)
    os.chmod(path, 0o600)
    return path


def remove_session(root: str | Path, port: int, instance_id: str | None) -> None:
    path = session_path(root, port)
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if instance_id is None or current.get("instance_id") == instance_id:
        path.unlink(missing_ok=True)


def read_sessions(root: str | Path) -> list[Session]:
    """Recorded sessions, including the pre-v2 ``session.json`` file."""
    sessions = []
    directory = support_dir(root)
    for path in sorted(directory.glob("studio-*.json")) + [directory / "session.json"]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            sessions.append(
                Session(
                    host=str(payload["host"]),
                    port=int(payload["port"]),
                    token=str(payload.get("token") or ""),
                    pid=payload.get("pid"),
                    instance_id=payload.get("instance_id"),
                    api_version=payload.get("api_version"),
                    started_at=payload.get("started_at"),
                    evaluator_token=str(payload.get("evaluator_token") or ""),
                    source=path.name,
                )
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
    return sessions


def _get(
    url: str, *, token: str | None = None, timeout: float = 1.0
) -> tuple[int, Any]:
    headers = {"X-Studio-Token": token} if token else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(65536)
            status = response.status
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (OSError, urllib.error.URLError, ValueError):
        return 0, None
    try:
        return status, json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, None


@dataclass
class Probe:
    kind: str  # compatible | incompatible_version | outdated_studio | unrelated | unreachable
    info: dict[str, Any] | None = None
    detail: str = ""


def probe(base_url: str, *, timeout: float = 1.0) -> Probe:
    """Classify whatever listens at ``base_url`` without credentials."""
    status, info = _get(f"{base_url}/api/info", timeout=timeout)
    if status == 0:
        return Probe("unreachable", detail="no HTTP response")
    if (
        status == 200
        and isinstance(info, dict)
        and info.get("application") == APPLICATION
    ):
        if info.get("api_version") == API_VERSION:
            return Probe("compatible", info)
        return Probe(
            "incompatible_version",
            info,
            f"API {info.get('api_version')!r}, expected {API_VERSION!r}",
        )
    health_status, health = _get(f"{base_url}/health", timeout=timeout)
    if (
        health_status == 200
        and isinstance(health, dict)
        and health.get("status") == "ok"
        and "runs_directory" in health
    ):
        return Probe(
            "outdated_studio",
            None,
            "Investigation Studio without the compatibility API (pre-v2 backend)",
        )
    return Probe(
        "unrelated", None, f"HTTP {status} from /api/info; not an Investigation Studio"
    )


def authorized(base_url: str, token: str, *, timeout: float = 1.0) -> bool:
    return (
        bool(token)
        and _get(f"{base_url}/api/runs", token=token, timeout=timeout)[0] == 200
    )


def usable(session: Session, root: str | Path) -> tuple[bool, Probe]:
    """Compatible version, same runs directory, and the recorded token is accepted."""
    result = probe(session.base_url)
    if result.kind != "compatible":
        return False, result
    if result.info.get("runs_root_id") != runs_root_id(root):
        return False, Probe(
            "other_runs_directory", result.info, "serves a different runs directory"
        )
    if session.instance_id and result.info.get("instance_id") != session.instance_id:
        return False, Probe(
            "replaced", result.info, "a different Studio instance now owns this port"
        )
    if not authorized(session.base_url, session.token):
        return False, Probe(
            "unauthorized", result.info, "recorded viewer token was rejected"
        )
    return True, result


def launch_link(
    session: Session,
    run_id: str | None = None,
    *,
    ttl_seconds: int = 600,
    evaluator: bool | None = None,
) -> tuple[str, int]:
    """Mint a single-use launch ticket and return a browser link carrying it.

    The local owner (who can read the 0600 session record) gets evaluator scope
    by default so post-run ground truth can be shown; pass ``evaluator=False``
    or set ``STUDIO_EVALUATOR_LINKS=0`` for a viewer-only link to share.
    """
    if evaluator is None:
        evaluator = os.getenv("STUDIO_EVALUATOR_LINKS", "1") != "0"
    body: dict[str, Any] = {"ttl_seconds": ttl_seconds}
    headers = {"X-Studio-Token": session.token, "Content-Type": "application/json"}
    if evaluator and session.evaluator_token:
        body["scopes"] = ["evaluator"]
        headers["X-Studio-Evaluator-Token"] = session.evaluator_token
    request = urllib.request.Request(
        f"{session.base_url}/api/launch-tickets",
        data=json.dumps(body).encode(),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        payload = json.loads(response.read().decode("utf-8"))
    fragment = {"ticket": payload["ticket"]}
    if run_id:
        fragment["run"] = run_id
    return f"{session.base_url}/#{urllib.parse.urlencode(fragment)}", int(
        payload["expires_in"]
    )


def listener_pid(port: int) -> int | None:
    """PID of a same-user process listening on ``port`` (Linux /proc), if any."""
    inodes = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(table).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if (
                len(parts) > 9
                and parts[3] == "0A"
                and int(parts[1].rsplit(":", 1)[1], 16) == port
            ):
                inodes.add(parts[9])
    if not inodes:
        return None
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            for fd in (proc / "fd").iterdir():
                target = os.readlink(fd)
                if target.startswith("socket:[") and target[8:-1] in inodes:
                    return int(proc.name)
        except OSError:
            continue
    return None


def is_studio_process(pid: int) -> bool:
    """True only for a Studio server process owned by the current user."""
    try:
        if os.stat(f"/proc/{pid}").st_uid != os.getuid():
            return False
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    return b"openvlharness.studio.server" in cmdline


def describe_listener(host: str, port: int) -> str:
    """Human explanation of what occupies a port, for startup errors."""
    session = Session(host=host, port=port, token="")
    result = probe(session.base_url)
    pid = listener_pid(port)
    owner = f" (pid {pid})" if pid else ""
    if result.kind == "compatible":
        return (
            f"Port {port} is already served by a compatible Investigation Studio{owner}. "
            f"Open it with: python scripts/studio_ctl.py url --port {port}"
        )
    if result.kind in {"outdated_studio", "incompatible_version"}:
        return (
            f"Port {port} is held by an outdated Investigation Studio{owner}: {result.detail}. "
            f"Stop it with: python scripts/studio_ctl.py stop --port {port}  (or choose STUDIO_PORT/--port)"
        )
    return (
        f"Port {port} is in use by another process{owner}, which is not an Investigation Studio. "
        "It was left untouched; choose another port with STUDIO_PORT or --port."
    )


def new_token() -> str:
    return secrets.token_urlsafe(24)
