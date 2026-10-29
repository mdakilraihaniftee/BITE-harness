"""Run a real image question and retain its complete trajectory."""
import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from openvlharness.bootstrap import build_agent


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    load_dotenv(root / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--question", default="How many bottles are visible?")
    parser.add_argument("--config", default=os.getenv("AGENT_CONFIG", "configs/local_qwen.yaml"))
    parser.add_argument("--output", type=Path, default=Path("outputs/inference.json"))
    args = parser.parse_args()
    if not args.image.is_file():
        parser.error(f"Image does not exist: {args.image}")
    result = build_agent(args.config).generate([
        {"type": "image", "value": str(args.image.resolve())},
        {"type": "text", "value": args.question},
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(result["prediction"])
    print(f"Saved result and trajectory: {args.output}")
    if str(result["prediction"]).startswith("Error:"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
