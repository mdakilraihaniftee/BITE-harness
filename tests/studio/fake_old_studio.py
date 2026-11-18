"""Stand-in for a pre-v2 Studio backend, for compatibility tests.

It reproduces the observed failure mode: an old server process that serves the
current static frontend from disk, answers the legacy ``/health`` shape, accepts
a token on ``/api/runs``, but has no ``/api/info``, topology, or architecture API.

Usage: python tests/studio/fake_old_studio.py PORT TOKEN
"""

from __future__ import annotations

import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "openvlharness/studio/static"


def make_handler(token: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/health":
                return self._send(
                    200,
                    json.dumps(
                        {"status": "ok", "runs_directory": "/legacy/runs"}
                    ).encode(),
                    "application/json",
                )
            if path == "/api/runs":
                if self.headers.get("X-Studio-Token") != token:
                    return self._send(
                        401,
                        b'{"detail":"Invalid Studio viewer token"}',
                        "application/json",
                    )
                return self._send(200, b'{"runs":[]}', "application/json")
            if path in {"/", "/index.html"}:
                return self._send(
                    200, (STATIC / "index.html").read_bytes(), "text/html"
                )
            if path.startswith("/static/"):
                target = (STATIC / path[len("/static/") :]).resolve()
                if target.parent == STATIC and target.is_file():
                    return self._send(
                        200,
                        target.read_bytes(),
                        mimetypes.guess_type(target.name)[0] or "text/plain",
                    )
            return self._send(404, b'{"detail":"Not Found"}', "application/json")

        def log_message(self, *args):
            pass

    return Handler


def serve(port: int, token: str) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(token))


if __name__ == "__main__":
    serve(int(sys.argv[1]), sys.argv[2]).serve_forever()
