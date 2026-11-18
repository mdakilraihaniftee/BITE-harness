#!/usr/bin/env python3
"""Run one real dataset row through the instrumented multi-agent runtime."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from evaluation_kit.dataset import build_dataset
from openvlharness.multi_agent import MultiAgentOrchestrator, load_multi_agent_config
from openvlharness.multi_agent.run import add_run_option_arguments, apply_cli_run_options

# Columns that carry benchmark labels. They are dropped from the inference
# process immediately after loading; only the evaluator resolves them post-run.
LABEL_COLUMNS = ("answer",)

ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--dataset", default="FSC147_val")
    result.add_argument(
        "--row",
        type=int,
        default=0,
        help="Zero-based row position in the prepared dataset (default: 0).",
    )
    result.add_argument("--config", default="configs/multi_agent.yaml")
    result.add_argument(
        "--agent-config",
        default=os.getenv("AGENT_CONFIG", "examples/local_grounding_tools.yaml"),
        help="Agent/tool profile used by coordinator and workers.",
    )
    result.add_argument("--num-agents", type=int, default=2)
    result.add_argument(
        "--mode", choices=("concurrent", "cooperative"), default="concurrent"
    )
    result.add_argument(
        "--communication", action=argparse.BooleanOptionalAction, default=None,
        help="Message bus for reports and peer messages (assignments always delivered).",
    )
    result.add_argument(
        "--peer-communication", action=argparse.BooleanOptionalAction, default=None,
        help="Worker-to-worker messages; coordinator assignment/reporting stays on.",
    )
    add_run_option_arguments(result, include_basic=False)
    result.add_argument("--output-dir", type=Path, default=Path("outputs/multi_agent"))
    result.add_argument("--run-id")
    result.add_argument(
        "--inspect-only",
        action="store_true",
        help="Resolve and print the label-sealed dataset input without inference.",
    )
    return result


def public_row_metadata(
    row: Any, position: int, prompt: list[dict[str, Any]]
) -> dict[str, Any]:
    """Describe the selected task without reading or persisting its answer field."""
    return {
        "row_position": position,
        "dataset_index": str(row.get("index", position)),
        "question": "\n".join(
            str(item["value"]) for item in prompt if item.get("type") == "text"
        ),
        "images": [
            str(Path(item["value"]).resolve())
            for item in prompt
            if item.get("type") == "image"
        ],
        "ground_truth_policy": "sealed_not_passed_to_runtime_or_persisted_run",
    }


def seal_labels(dataset: Any) -> None:
    """Remove label columns from the in-process dataset before any inference."""
    present = [column for column in LABEL_COLUMNS if column in dataset.data.columns]
    if present:
        dataset.data = dataset.data.drop(columns=present)


def main(argv: list[str] | None = None, *, factory: Any = None, dataset_loader: Any = None) -> int:
    os.chdir(ROOT)
    load_dotenv(ROOT / ".env")
    args = parser().parse_args(argv)
    if args.row < 0:
        raise SystemExit("--row must be nonnegative")

    dataset = (dataset_loader or build_dataset)(args.dataset)
    if dataset is None:
        raise SystemExit(
            f"Dataset {args.dataset!r} is unavailable. Prepare it with the repository dataset scripts first."
        )
    if args.row >= len(dataset.data):
        raise SystemExit(
            f"--row {args.row} is outside {args.dataset} (available positions: 0..{len(dataset.data) - 1})"
        )

    seal_labels(dataset)
    row = dataset.data.iloc[args.row]
    prompt = dataset.build_prompt(args.row)
    if not isinstance(prompt, list) or not prompt:
        raise SystemExit("The dataset loader returned an empty or unsupported prompt")
    image_items = [item for item in prompt if item.get("type") == "image"]
    text_items = [item for item in prompt if item.get("type") == "text"]
    if not image_items or not text_items:
        raise SystemExit(
            "This runner requires at least one image and one text question"
        )
    missing = [
        item["value"] for item in image_items if not Path(item["value"]).is_file()
    ]
    if missing:
        raise SystemExit(f"Dataset image is missing: {missing[0]}")

    config = apply_cli_run_options(load_multi_agent_config(args.config), args)
    config["coordinator"]["agent_config"] = str(Path(args.agent_config).resolve())
    config["workers"]["default"]["agent_config"] = str(
        Path(args.agent_config).resolve()
    )
    for override in config["workers"]["overrides"].values():
        override["agent_config"] = str(Path(args.agent_config).resolve())

    run_id = args.run_id or (
        f"{args.dataset.lower()}_row_{args.row:04d}_"
        f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    )
    task = "\n".join(str(item["value"]) for item in text_items)
    metadata = {
        "schema_version": "studio.dataset-task.v1",
        "dataset": args.dataset,
        **public_row_metadata(row, args.row, prompt),
    }

    print(f"Dataset: {args.dataset}", flush=True)
    print(f"Row position: {args.row}", flush=True)
    print(f"Dataset index: {metadata['dataset_index']}", flush=True)
    print(f"Image: {metadata['images'][0]}", flush=True)
    print(f"Question: {task}", flush=True)
    print("Ground truth: sealed and not passed to the runtime", flush=True)
    print(f"Run ID: {run_id}", flush=True)
    if args.inspect_only:
        print("Inspect-only preflight completed; no model or tool call was made.")
        return 0

    orchestrator = MultiAgentOrchestrator(
        config,
        factory=factory,
        run_id=run_id,
        output_directory=args.output_dir,
    )
    # Label-free row identity, written before inference so the Studio can show
    # the reference as sealed; the evaluator resolves the label after the run.
    metadata_path = orchestrator.run_dir / "inputs" / "dataset_task.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    effective = orchestrator.effective_config
    print(
        f"Configuration: {effective['num_workers']} worker(s), optional memory "
        f"{'on' if effective['optional_worker_memory_enabled'] else 'off'}, peer communication "
        f"{'on' if effective['peer_communication_enabled'] else 'off'}, coordinator estimates "
        f"{'on' if effective['coordinator_estimate_updates']['enabled'] else 'off'}",
        flush=True,
    )
    result = orchestrator.run(task, prompt)

    print(f"Final answer: {result.get('prediction')}")
    print(f"Status: {result['extra_records']['status']}")
    print(f"Run directory: {orchestrator.run_dir.resolve()}")
    print(f"Dataset metadata: {metadata_path.resolve()}")
    return 0 if result["extra_records"]["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
