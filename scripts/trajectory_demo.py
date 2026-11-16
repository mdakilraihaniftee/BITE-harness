#!/usr/bin/env python3
"""Run one real agent task and show its complete recorded trajectory."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from evaluation_kit.utils.reporting_utils import render_html_report
from openvlharness.bootstrap import build_agent

ROOT = Path(__file__).resolve().parents[1]


def compact(value: Any) -> Any:
    """Keep trajectory structure readable while replacing embedded image bytes."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if "base64" in lowered or lowered.endswith("_b64"):
                size = len(item) if isinstance(item, str) else "unknown"
                cleaned[key] = f"<embedded image/data: {size} characters>"
            else:
                cleaned[key] = compact(item)
        return cleaned
    if isinstance(value, list):
        return [compact(item) for item in value]
    if isinstance(value, str) and value.startswith("data:image/"):
        return f"<embedded image: {len(value)} characters>"
    return value


def json_block(value: Any) -> str:
    return json.dumps(compact(value), indent=2, ensure_ascii=False, default=str)


def build_markdown(image: Path, question: str, result: dict[str, Any]) -> str:
    trajectory = result.get("extra_records", {}).get("trajectory", {})
    lines = [
        "# Agent trajectory",
        "",
        f"- Image: `{image}`",
        f"- Question: {question}",
        "",
    ]
    for position, turn in enumerate(trajectory.get("chat_history", []), start=1):
        turn_id = turn.get("turn", position)
        assistant = turn.get("assistant") or {}
        lines.extend([f"## Turn {turn_id}", ""])
        content = assistant.get("content")
        if content:
            lines.extend(["### Assistant", "", str(content).strip(), ""])
        tool_calls = assistant.get("tool_calls") or []
        if tool_calls:
            lines.extend(
                ["### Tool calls", "", "```json", json_block(tool_calls), "```", ""]
            )
        tool_responses = turn.get("tool_responses") or []
        if tool_responses:
            lines.extend(
                [
                    "### Tool responses",
                    "",
                    "```json",
                    json_block(tool_responses),
                    "```",
                    "",
                ]
            )
        memory_outputs = turn.get("memory_outputs") or []
        if memory_outputs:
            lines.extend(
                [
                    "### Memory updates",
                    "",
                    "```json",
                    json_block(memory_outputs),
                    "```",
                    "",
                ]
            )
        if "final_answer" in turn:
            lines.extend(["### Turn answer", "", str(turn["final_answer"]), ""])

    lines.extend(["## Final answer", "", str(result.get("prediction")), ""])
    observer = result.get("extra_records", {}).get("bite_observer")
    if observer:
        lines.extend(
            [
                "## BITE observer summary",
                "",
                "```json",
                json_block(
                    {
                        "schema_version": observer.get("schema_version"),
                        "run_id": observer.get("run_id"),
                        "budget": observer.get("budget"),
                        "event_count": len(observer.get("events", [])),
                    }
                ),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    os.chdir(ROOT)
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "image",
        nargs="?",
        type=Path,
        default=Path("data/images/FSC147/190.jpg"),
        help="Image to inspect (default: first prepared FSC147 example)",
    )
    parser.add_argument(
        "--question",
        default="How many seagulls are in this image? Use the available visual tools and explain the evidence.",
    )
    parser.add_argument(
        "--config", default=os.getenv("AGENT_CONFIG", "configs/local_qwen.yaml")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/trajectory-demo")
    )
    args = parser.parse_args()

    if not args.image.is_file():
        parser.error(f"Image does not exist: {args.image}")

    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    run_dir = args.output_dir / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    os.environ.update(
        {
            "BITE_OBSERVER_ENABLED": "true",
            "BITE_OBSERVER_REFERENCE_BUDGET": "15",
            "BITE_OBSERVER_RUN_ID": f"trajectory-demo-{stamp}",
        }
    )

    agent = build_agent(args.config)
    result = agent.generate(
        [
            {"type": "image", "value": str(args.image.resolve())},
            {"type": "text", "value": args.question},
        ]
    )

    json_path = run_dir / "trajectory.json"
    markdown_path = run_dir / "trajectory.md"
    html_path = run_dir / "trajectory.html"
    json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n"
    )
    markdown = build_markdown(args.image.resolve(), args.question, result)
    markdown_path.write_text(markdown + "\n")
    record = {
        "task_id": stamp,
        "dataset": "single-image-demo",
        "model_name": agent.model,
        "agent_class": agent.__class__.__name__,
        "prediction": result.get("prediction"),
        "trajectory": result.get("extra_records", {}).get("trajectory", {}),
    }
    html_path.write_text(render_html_report(record, max_chars=20_000), encoding="utf-8")

    print(markdown)
    print("\nSaved complete trajectory:")
    print(f"  Markdown: {markdown_path.resolve()}")
    print(f"  HTML:     {html_path.resolve()}")
    print(f"  Raw JSON: {json_path.resolve()}")
    if str(result.get("prediction", "")).startswith("Error:"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
