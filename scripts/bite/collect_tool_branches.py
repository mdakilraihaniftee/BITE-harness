#!/usr/bin/env python3
"""Run the CPU-only controlled branch demonstration."""

import argparse
import json

from evaluation_kit.bite_collection.synthetic import run_synthetic_demo


def main():
    parser = argparse.ArgumentParser(description="Collect isolated BITE tool branches without reading GT")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--synthetic-demo", action="store_true",
                      help="Run the mandatory deterministic CPU-only demonstration")
    mode.add_argument("--live-pilot", action="store_true",
                      help="Run the explicit PascalVOC development-only router pilot")
    parser.add_argument("--output-dir", default="outputs/bite/phase04b1/synthetic")
    parser.add_argument("--config", default="configs/agent/qwen3_8b_paper.yaml")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--dataset", default="ODinW13_bbox_val_qwen3")
    parser.add_argument("--sample-id", default="PascalVOC_val_262")
    args = parser.parse_args()
    if args.synthetic_demo:
        result = run_synthetic_demo(args.output_dir)
        records = result["calibration_rows"]
        validation = result["validation"]
    else:
        from evaluation_kit.bite_collection.live import run_live_pilot
        result = run_live_pilot(config=args.config, data_root=args.data_root, dataset=args.dataset,
                                sample_id=args.sample_id, output_dir=args.output_dir)
        records = result["rows"]
        validation = result["report"]
    print(json.dumps({"status": "SUCCESS", "branches": len(result["branches"]),
                      "calibration_records": len(records),
                      "actual_continuation_expenditure": validation["actual_continuation_expenditure"],
                      "output": args.output_dir}, indent=2))


if __name__ == "__main__":
    main()
