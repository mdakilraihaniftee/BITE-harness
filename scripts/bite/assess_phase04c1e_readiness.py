#!/usr/bin/env python3
"""Classify Phase 4C-1E from its frozen utility screen and semantic-pilot artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.semantic_pilot_protocol import verify_manifest
from evaluation_kit.bite_collection.persistence import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("outputs/bite/phase04c1e"))
    args = parser.parse_args()
    root = args.root
    utility = json.loads((root / "utility_screening/summary.json").read_text())
    manifest = verify_manifest(json.loads((root / "semantic_pilot_manifest/manifest.json").read_text()))
    design = json.loads((root / "semantic_pilot_manifest/paired_comparison_design.json").read_text())
    mock = json.loads((root / "semantic_observation_contract/mock_contract_report.json").read_text())
    plan = json.loads((root / "execution_readiness/semantic_pilot_execution_plan.json").read_text())
    contract_ok = (
        mock["resume_idempotent"] and mock["payload_text_identical_across_cases"]
        and not mock["redacted_payload_mentions_score"] and mock["network_requests"] == 0
        and mock["mock_requests_issued"] == manifest["case_count"]
    )
    zoom_decision = utility["zoom_collection_decision"]["decision"]
    readiness = {
        "schema_version": "bite.phase04c1e_readiness.v1",
        "overall_status": (
            "ENGINEERING_SUCCESS / ZOOM_ONLY_COLLECTION_NOT_JUSTIFIED / "
            "SEMANTIC_PILOT_PREPARED_PENDING_AUTHORIZATION"
            if contract_ok and zoom_decision.startswith("ZOOM_ONLY_COLLECTION_NOT_JUSTIFIED")
            else "REQUIRES_REVIEW"
        ),
        "zoom_utility_screen": {
            "decision": zoom_decision,
            "reasons": utility["zoom_collection_decision"]["reasons"],
            "zoom_declared_universally_useless": False,
        },
        "semantic_action": {
            "name": manifest["action_name"],
            "contract_frozen": True,
            "prompt_sha256": manifest["frozen_contract"]["prompt_sha256"],
            "ontology_sha256": manifest["frozen_contract"]["ontology_sha256"],
            "mock_contract_validation": "PASS" if contract_ok else "FAIL",
            "real_inference_executed": False,
        },
        "semantic_pilot": {
            "manifest_sha256": manifest["manifest_sha256"],
            "source_groups": len(manifest["selected_source_groups"]),
            "cases": manifest["case_count"],
            "dispatch_cap": manifest["dispatch_cap"],
            "execution_status": plan["status"],
            "validation_or_internal_test_cases": manifest["validation_or_internal_test_cases"],
        },
        "paired_comparison_design": {
            "design_sha256": design["design_sha256"],
            "primary_estimand": design["primary_estimand"],
            "status": design["status"],
        },
        "not_ready_or_not_implemented": {
            "conditional_observation_kernel": "NOT_READY",
            "posterior_update": "NOT_IMPLEMENTED",
            "budgeted_planner": "NOT_IMPLEMENTED",
            "robust_action_value_bound": "THEORY_NOTE_ONLY",
            "task_level_extension": "PROPOSAL_ONLY",
            "held_out_validation": "NOT_AUTHORIZED",
            "matched_worker_bridge": "PREPARED_NOT_AUTHORIZED_NOT_EXECUTED",
        },
        "research_decision": "PIVOT_TO_COMPLEMENTARY_SEMANTIC_EVIDENCE_PILOT_PENDING_AUTHORIZATION",
        "next_authorization_required": [
            "live semantic VLM inference for the frozen 101-case fit-only pilot",
        ],
    }
    atomic_json(root / "readiness/readiness.json", readiness)
    print(json.dumps(readiness, indent=2))


if __name__ == "__main__":
    main()
