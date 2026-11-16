#!/usr/bin/env python3
"""Execute the Phase 4C-1G Protocol A final-answer branches (mock dry run by default).

Live mode issues real Qwen3-VL requests. It therefore requires a researcher-written
authorization JSON bound to the task manifest, the prompt/parser/renderer digests,
the frozen semantic manifest, the model alias and id, the exact endpoint, the
branch set, the output and semantic-run directories, a cumulative final-answer cap,
a cumulative phase-total cap (semantic + final answers <= 505) and an expiry (see
outputs/bite/phase04c1g/authorization/authorization_requirements.json).

The coding agent does not write or approve this authorization.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from evaluation_kit.bite_calibration.semantic_pilot_protocol import mock_requester
from evaluation_kit.bite_calibration.task_level_branch_runner import (
    CANARY_MAX_TASKS,
    build_adapter,
    run_branches,
)
from evaluation_kit.bite_calibration.task_level_probe_protocol import (
    BRANCHES,
    verify_task_manifest,
)
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
PHASE = ROOT / "outputs/bite/phase04c1g"
DEFAULT_RUN = PHASE / "raw_continuations/branch_run"
SEMANTIC_RUN = ROOT / "outputs/bite/phase04c1f/raw_observations/semantic_pilot_run"
SEMANTIC_MANIFEST = ROOT / "outputs/bite/phase04c1e/semantic_pilot_manifest/manifest.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=PHASE / "task_manifest/task_manifest.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--mode", choices=("mock_dry_run", "live"), default="mock_dry_run")
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--semantic-run", type=Path, default=SEMANTIC_RUN)
    parser.add_argument("--branches", nargs="+", choices=BRANCHES, default=list(BRANCHES))
    parser.add_argument("--base-url", default=os.environ.get("MODEL_BASE_URL", ""))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--canary", type=int, metavar="N",
                        help=f"run all requested branches for at most N (<= {CANARY_MAX_TASKS}) pending tasks; "
                             "counts toward the cumulative caps")
    args = parser.parse_args()
    manifest = verify_task_manifest(json.loads(args.manifest.read_text()))
    semantic_manifest = json.loads(SEMANTIC_MANIFEST.read_text())
    semantic_run = args.semantic_run if args.semantic_run.is_dir() else None
    if args.mode == "live":
        if args.authorization is None:
            raise SystemExit("Live mode requires --authorization; none was given")
        authorization = json.loads(args.authorization.read_text())
        adapter = build_adapter(args.base_url, key=os.environ.get("MODEL_API_KEY", ""))
        semantic_run = args.semantic_run
    else:
        if args.output.resolve().is_relative_to((PHASE / "raw_continuations").resolve()):
            raise SystemExit("Mock dry runs may not write into the live raw_continuations directory")
        authorization = None
        adapter = build_adapter("http://mock.invalid/v1",
                                requester=mock_requester(lambda i, p: json.dumps({"count": 0})))
    summary = run_branches(manifest, adapter, args.output, root=ROOT, mode=args.mode, branches=args.branches,
                           semantic_run_dir=semantic_run, semantic_manifest=semantic_manifest,
                           authorization=authorization, resume=args.resume, canary_tasks=args.canary)
    if authorization is not None:
        atomic_json(args.output / "authorization_used.json", authorization)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
