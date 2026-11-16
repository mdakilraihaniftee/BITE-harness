#!/usr/bin/env python3
"""Run a retained, CPU-only end-to-end inference and scoring smoke test.

The script creates three tiny FSC147-style image/counting rows and serves fixed
OpenAI-compatible model responses from a loopback HTTP server. It exercises the
real agent, evaluator, passive BITE observer, trajectory writer, and count
metric without downloading a checkpoint or requiring a GPU.
"""

from __future__ import annotations

import base64
import io
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pandas as pd
import yaml
from PIL import Image, ImageDraw

from evaluation_kit import cli
from evaluation_kit.dataset import hf_release

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "outputs" / "offline-smoke"
DATA_ROOT = OUTPUT_ROOT / "data"
RUN_ROOT = OUTPUT_ROOT / "runs"
CONFIG_PATH = OUTPUT_ROOT / "offline_agent.yaml"
DATASET = "FSC147_val"
ANSWERS = {"red": 3, "blue": 5, "green": 7}


def make_dataset() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, (color, count) in enumerate(ANSWERS.items()):
        image = Image.new("RGB", (256, 160), "white")
        draw = ImageDraw.Draw(image)
        for item in range(count):
            x = 18 + (item % 4) * 58
            y = 20 + (item // 4) * 70
            draw.ellipse((x, y, x + 34, y + 34), fill=color)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        rows.append(
            {
                "index": index,
                "image": base64.b64encode(buffer.getvalue()).decode("ascii"),
                "image_path": f"{index}.png",
                "question": f"How many {color} circles are visible? smoke-color {color}",
                "answer": count,
            }
        )
    pd.DataFrame(rows).to_csv(DATA_ROOT / f"{DATASET}.tsv", sep="\t", index=False)


def make_config(model_base: str) -> None:
    config = {
        "agent_name": "MainAgent",
        "agent_config_version": "offline_smoke_v1",
        "agent": {"model_service": "orchestrator", "max_iterations": 3},
        "memory": {"emit_policy": "always", "modules": [{"name": "image"}]},
        "capabilities": {"registries": ["paper"], "tools": {}},
        "services": {
            "client": {"base_url": model_base, "retry": 0},
            "server": {},
            "tools": {},
            "models": {
                "orchestrator": {
                    "alias": "qwen3-vl-8b-instruct",
                    "base": model_base + "/v1",
                    "key": "offline-smoke",
                    "max_tokens": 64,
                    "retry": 0,
                }
            },
        },
    }
    CONFIG_PATH.write_text(yaml.safe_dump(config), encoding="utf-8")


def find_latest_run() -> Path:
    manifests = sorted(
        RUN_ROOT.glob("*/*/*/run_manifest.json"), key=lambda path: path.stat().st_mtime
    )
    if not manifests:
        raise RuntimeError("Smoke run completed without writing a run manifest")
    return manifests[-1].parent


def main() -> None:
    os.chdir(ROOT)
    make_dataset()
    state = {"requests": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            size = int(self.headers["Content-Length"])
            body = self.rfile.read(size).decode("utf-8")
            color = next(
                (name for name in ANSWERS if f"smoke-color {name}" in body), None
            )
            if color is None:
                self.send_error(400, "Unknown smoke question")
                return
            state["requests"] += 1
            payload = {
                "id": f"offline-smoke-{state['requests']}",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": f"<answer>{ANSWERS[color]}</answer>",
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            self.send_response(404)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        model_base = f"http://127.0.0.1:{server.server_port}"
        make_config(model_base)
        os.environ.update(
            {
                "LMUData": str(DATA_ROOT),
                "MODEL_BASE_URL": model_base + "/v1",
                "TOOL_SERVER_URL": model_base,
                "WORLD_SIZE": "1",
                "BITE_OBSERVER_ENABLED": "true",
                "BITE_OBSERVER_REFERENCE_BUDGET": "15",
            }
        )
        # The smoke TSV is generated locally, so it intentionally does not use
        # the published FSC147 checksum.
        hf_release.HF_DATASET_MD5.pop(DATASET, None)
        try:
            cli.main(
                [
                    "--data",
                    DATASET,
                    "--config",
                    str(CONFIG_PATH),
                    "--judge-config",
                    str(ROOT / "configs" / "judge_no_judge.yaml"),
                    "--work-dir",
                    str(RUN_ROOT),
                    "--num-proc",
                    "1",
                    "--save-html",
                    "all",
                    "--run-tag",
                    "offline-smoke",
                ]
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)

    run_dir = find_latest_run()
    dataset_dir = run_dir / DATASET
    metric_path = dataset_dir / "Qwen3-VL-8B-Instruct_acc.csv"
    metrics = pd.read_csv(metric_path).iloc[0].to_dict()
    trajectories = sorted((dataset_dir / "full_trajectories").glob("*.json"))
    observations = sorted((dataset_dir / "bite_observations").glob("*.json"))
    if state["requests"] != 3 or metrics.get("acc") != 100.0:
        raise RuntimeError(
            f"Unexpected smoke result: requests={state['requests']}, metrics={metrics}"
        )
    if len(trajectories) != 3 or len(observations) != 3:
        raise RuntimeError(
            f"Missing retained artifacts: trajectories={len(trajectories)}, observations={len(observations)}"
        )
    print("Offline smoke passed: 3/3 examples, count accuracy 100.0%")
    print(f"Run artifacts: {run_dir}")
    print(f"Metrics: {metric_path}")


if __name__ == "__main__":
    main()
