#!/usr/bin/env python3
"""Execute the frozen semantic_region_inspect_v1 pilot (mock dry run by default).

Live mode issues real VLM requests and therefore requires a researcher-written
authorization JSON bound to the manifest, prompt and ontology digests, the model
alias and id, the exact endpoint, the run directory and a cumulative dispatch cap
(see outputs/bite/phase04c1f/authorization/authorization_requirements.json).
Live semantic inference has not been authorized as of Phase 4C-1F preflight.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from evaluation_kit.bite_calibration.semantic_pilot_protocol import (
    CANARY_MAX_CASES,
    mock_requester,
    run_pilot,
    validate_live_binding,
    verify_manifest,
)
from evaluation_kit.bite_calibration.semantic_region_action import build_adapter
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
MOCK_TEXT = json.dumps({
    "region_content": "unclear", "object_visible": "uncertain", "region_localization": "uncertain",
    "multiple_objects": "uncertain", "evidence_status": "insufficient",
    "short_visual_description": "mock dry-run response; no model was called",
})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path,
                        default=ROOT / "outputs/bite/phase04c1e/semantic_pilot_manifest/manifest.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("mock_dry_run", "live"), default="mock_dry_run")
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--base-url", default=os.environ.get("MODEL_BASE_URL", ""))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--canary", type=int, metavar="N",
                        help=f"dispatch at most N (<= {CANARY_MAX_CASES}) pending cases in manifest order, then stop; "
                             "counts toward the cumulative cap")
    args = parser.parse_args()
    manifest = verify_manifest(json.loads(args.manifest.read_text()))
    if args.mode == "live":
        if args.authorization is None:
            raise SystemExit("Live mode requires --authorization; none was given")
        authorization = json.loads(args.authorization.read_text())
        adapter = build_adapter(args.base_url, key=os.environ.get("MODEL_API_KEY", ""))
        validate_live_binding(authorization, manifest, adapter, args.output, root=ROOT)
    else:
        authorization = None
        adapter = build_adapter("http://mock.invalid/v1", requester=mock_requester(lambda i, p: MOCK_TEXT))
    summary = run_pilot(manifest, adapter, args.output, root=ROOT, mode=args.mode,
                        authorization=authorization, resume=args.resume,
                        max_new_dispatches=args.canary, run_phase="canary" if args.canary else "main")
    if authorization is not None:
        atomic_json(args.output / "authorization_used.json", authorization)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
