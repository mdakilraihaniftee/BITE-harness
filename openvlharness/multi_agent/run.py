"""Command-line entry point for coordinated visual-agent execution."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .config import load_multi_agent_config
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
    return result


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    os.chdir(root)
    try:
        from dotenv import load_dotenv

        load_dotenv(root / ".env")
    except ImportError:
        pass
    args = parser().parse_args(argv)
    config = load_multi_agent_config(args.config)
    if args.num_agents is not None:
        if args.num_agents < 1 or args.num_agents > config["max_agents"]:
            raise SystemExit(f"--num-agents must be in 1..{config['max_agents']}")
        config["num_agents"] = args.num_agents
    if args.agent_config:
        config["coordinator"]["agent_config"] = str(Path(args.agent_config).resolve())
        config["workers"]["default"]["agent_config"] = str(
            Path(args.agent_config).resolve()
        )
        for override in config["workers"]["overrides"].values():
            override["agent_config"] = str(Path(args.agent_config).resolve())
    if args.mode:
        config["execution"]["mode"] = args.mode
    if args.communication is not None:
        config["communication"]["enabled"] = args.communication
    if args.peer_communication is not None:
        config["communication"]["peer_to_peer"] = args.peer_communication
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
