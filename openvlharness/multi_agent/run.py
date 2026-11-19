"""Command-line entry point for coordinated visual-agent execution."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .config import apply_run_options, load_multi_agent_config
from .orchestrator import MultiAgentOrchestrator


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", default="configs/multi_agent.yaml")
    result.add_argument("--num-agents", type=int)
    result.add_argument("--task", required=True)
    result.add_argument("--image", type=Path)
    result.add_argument(
        "--agent-config",
        help="Override coordinator and every worker agent-system config",
    )
    result.add_argument("--output-dir", type=Path)
    result.add_argument("--run-id")
    result.add_argument("--mode", choices=("concurrent", "cooperative"))
    result.add_argument(
        "--communication", action=argparse.BooleanOptionalAction, default=None
    )
    result.add_argument(
        "--peer-communication", action=argparse.BooleanOptionalAction, default=None
    )
    add_run_option_arguments(result, include_basic=False)
    return result


def add_run_option_arguments(
    result: argparse.ArgumentParser, *, include_basic: bool = True
) -> None:
    """Run-configuration flags shared by every multi-agent runner."""
    if include_basic:
        result.add_argument("--num-agents", type=int)
        result.add_argument("--mode", choices=("concurrent", "cooperative"))
        result.add_argument(
            "--communication", action=argparse.BooleanOptionalAction, default=None,
            help="Message bus for worker reports and peer messages (assignments are always delivered).",
        )
        result.add_argument(
            "--peer-communication", action=argparse.BooleanOptionalAction, default=None,
            help="Worker-to-worker messages; coordinator assignment/reporting stays on.",
        )
    result.add_argument(
        "--worker-memory", action=argparse.BooleanOptionalAction, default=None,
        help="Optional private cross-phase worker notebook (working context is always on).",
    )
    result.add_argument(
        "--estimate-updates", action=argparse.BooleanOptionalAction, default=None,
        help="Record coordinator provisional estimates (each is one extra, budgeted model request).",
    )
    result.add_argument("--max-reassessments", type=int, default=None)
    result.add_argument("--follow-up-rounds", type=int, default=None)
    result.add_argument(
        "--tool-scheduler", choices=("off", "e0", "e1", "e2", "e3", "e4", "e5"), default=None,
        help="PARSEC-VL: off (original), e0 sequential FIFO, e1 parallel FIFO, e2 critical path; "
             "e3-e5 add declared action plans (e3 Monte Carlo plan selection, e4 fixed-width speculation, "
             "e5 selective speculation + replanning). e3-e5 change the decision protocol.",
    )
    result.add_argument("--scheduler-workers", type=int, default=None,
                        help="Concurrent tool executions allowed by the scheduler (e1-e5).")
    result.add_argument("--planning-processes", type=int, default=None,
                        help="CPU processes for Monte Carlo plan evaluation (e3/e5; 0 = in-process).")


def apply_cli_run_options(config: dict, args: argparse.Namespace) -> dict:
    try:
        return apply_run_options(
            config,
            num_agents=args.num_agents,
            worker_memory=args.worker_memory,
            peer_communication=args.peer_communication,
            communication=args.communication,
            mode=args.mode,
            estimate_updates=args.estimate_updates,
            max_reassessments=args.max_reassessments,
            follow_up_rounds=args.follow_up_rounds,
            tool_scheduler=getattr(args, "tool_scheduler", None),
            scheduler_workers=getattr(args, "scheduler_workers", None),
            planning_processes=getattr(args, "planning_processes", None),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    os.chdir(root)
    try:
        from dotenv import load_dotenv

        load_dotenv(root / ".env")
    except ImportError:
        pass
    args = parser().parse_args(argv)
    config = apply_cli_run_options(load_multi_agent_config(args.config), args)
    if args.agent_config:
        config["coordinator"]["agent_config"] = str(Path(args.agent_config).resolve())
        config["workers"]["default"]["agent_config"] = str(
            Path(args.agent_config).resolve()
        )
        for override in config["workers"]["overrides"].values():
            override["agent_config"] = str(Path(args.agent_config).resolve())
    original_input: list[dict[str, str]] = []
    if args.image:
        if not args.image.is_file():
            raise SystemExit(f"Image does not exist: {args.image}")
        original_input.append({"type": "image", "value": str(args.image.resolve())})
    original_input.append({"type": "text", "value": args.task})
    orchestrator = MultiAgentOrchestrator(
        config, run_id=args.run_id, output_directory=args.output_dir
    )
    result = orchestrator.run(args.task, original_input)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    print(f"Run artifacts: {result['extra_records']['run_directory']}")
    return 0 if result["extra_records"]["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
