#!/usr/bin/env python3
"""Serve the internal Task V review UI and persist validated human judgments."""

from __future__ import annotations

import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from evaluation_kit.bite_calibration.adjudication_schema import validate_review


def serve(output, host, port):
    interface = output / "review_interface"
    cases = {row["case_id"]: row for row in (
        json.loads(line) for line in (interface / "review_cases.jsonl").read_text().splitlines())}
    queue = json.loads((interface / "review_queue.json").read_text())["case_ids"]
    completed = output / "human_adjudications/completed"
    completed.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body, content_type="application/json"):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(status); self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def do_GET(self):
            if self.path == "/":
                return self._send(200, (interface / "index.html").read_bytes(), "text/html; charset=utf-8")
            if self.path == "/api/cases":
                return self._send(200, json.dumps([cases[case_id] for case_id in queue]))
            if self.path.startswith("/source/"):
                case_id = unquote(self.path[len("/source/"):])
                case = cases.get(case_id)
                if case is None:
                    return self._send(404, "not found", "text/plain")
                source = Path(case["source_image_path"])
                if hashlib.sha256(source.read_bytes()).hexdigest() != case["source_image_sha256"]:
                    return self._send(409, "source identity mismatch", "text/plain")
                return self._send(200, source.read_bytes(), "image/jpeg")
            return self._send(404, "not found", "text/plain")

        def do_POST(self):
            if self.path != "/api/reviews":
                return self._send(404, "not found", "text/plain")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                review = json.loads(self.rfile.read(length))
                case = cases[review["case_id"]]
                validate_review(review, expected_case=case)
                name = hashlib.sha256(
                    f"{review['case_id']}:{review['reviewer_id']}".encode()).hexdigest() + ".json"
                path = completed / name
                try:
                    with path.open("x") as stream:
                        stream.write(json.dumps(review, indent=2, sort_keys=True) + "\n")
                except FileExistsError as error:
                    raise ValueError("This reviewer already submitted this case") from error
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                return self._send(400, json.dumps({"status": "INVALID", "error": str(error)}))
            return self._send(201, json.dumps({"status": "SAVED", "path": str(path)}))

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Review interface: http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04b2b4"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8114)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("The internal review server is loopback-only")
    serve(args.output.resolve(), args.host, args.port)


if __name__ == "__main__":
    main()
