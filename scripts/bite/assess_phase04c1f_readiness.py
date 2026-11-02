#!/usr/bin/env python3
"""Classify Phase 4C-1F from what exists on disk: preflight, authorization status,
and (only if an authorized run was analyzed) the pilot research decision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.action_utility_screen import (
    sample_size_sensitivity,
)
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "outputs/bite/phase04c1f")
    args = parser.parse_args()
    root = args.root
    screen = json.loads((ROOT / "outputs/bite/phase04c1e/utility_screening/expansion_iou_0_75.json").read_text())
    groups = [c["error_utility_sum"] / c["candidate_count"] for c in screen["group_contributions"]]
    sensitivity = {
        "schema_version": "bite.sample_size_sensitivity.v1",
        "source": "Phase 4C-1E Zoom IoU .75 group-mean gross error utility (30 groups)",
        **sample_size_sensitivity(groups),
    }
    atomic_json(root / "research_decision/sample_size_sensitivity.json", sensitivity)

    preflight = json.loads((root / "preflight/pilot_integrity.json").read_text())
    backend = json.loads((root / "preflight/backend_readiness.json").read_text())
    authorization = json.loads((root / "authorization/status.json").read_text())
    decision_path = root / "research_decision/decision.json"
    executed = (root / "raw_observations/semantic_pilot_run/run_configuration.json").is_file()
    if executed and decision_path.is_file():
        pilot = json.loads(decision_path.read_text())["decision"]
        overall = f"PILOT_EXECUTED / {pilot}"
    else:
        pilot = "NOT_EXECUTED"
        overall = (
            "OFFLINE_PREFLIGHT_PASS / AUTHORIZATION_ABSENT / PILOT_NOT_EXECUTED"
            if preflight["status"] == "PASS" and authorization["status"] == "AUTHORIZATION_ABSENT"
            else "REQUIRES_REVIEW"
        )
    readiness = {
        "schema_version": "bite.phase04c1f_readiness.v1",
        "overall_status": overall,
        "pilot_integrity": preflight["status"],
        "frozen_artifacts_unchanged": preflight["frozen_artifacts_unchanged"],
        "authorization": authorization["status"],
        "live_vlm_calls": 0 if not executed else "see raw_observations run_summary",
        "inference_service_running": backend["service_running"],
        "weights_cache_status": backend["weights"]["status"],
        "load_time_model_identity": "UNVERIFIED",
        "semantic_pilot_research_decision": pilot,
        "frozen_decision_rule_applicable": executed,
        "theory_corrections": [
            "fitted probability displacement is not an information ceiling",
            "Hoeffding sample sizes are worst-case, not universal",
            "exact offline replay requires coverage of the policy's actions and observations",
        ],
        "next_authorization_required": None if executed else (
            "researcher-written authorization JSON per authorization/authorization_requirements.json, "
            "plus a researcher-started local vLLM service"),
    }
    atomic_json(root / "research_decision/readiness.json", readiness)
    print(json.dumps(readiness, indent=2))


if __name__ == "__main__":
    main()
