#!/usr/bin/env python3
"""Summarize Phase 4C-1G status from artifacts on disk (no model calls, no labels)."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation_kit.bite_calibration.task_level_decision_analysis import DECISION_RULE
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
PHASE = ROOT / "outputs/bite/phase04c1g"
SEMANTIC_RUN = ROOT / "outputs/bite/phase04c1f/raw_observations/semantic_pilot_run"
BRANCH_RUN = PHASE / "raw_continuations/branch_run"


def _complete_units(run):
    return sum(1 for p in run.glob("states/*/raw_completion.json")) if run.is_dir() else 0


def main():
    preparation = json.loads((PHASE / "task_manifest/preparation_summary.json").read_text())
    identity = json.loads((PHASE / "preflight/input_identity.json").read_text())
    authorization = json.loads((PHASE / "authorization/status.json").read_text())
    mock = json.loads((PHASE / "preflight/mock_contract_report.json").read_text())
    semantic_complete = _complete_units(SEMANTIC_RUN)
    branch_complete = _complete_units(BRANCH_RUN)
    decision_path = PHASE / "readiness/research_decision.json"
    analyzed = (PHASE / "oracle_headroom/oracle_headroom.json").is_file()
    blockers = []
    if authorization["phase04c1f_semantic_gate"]["status"] == "AUTHORIZATION_ABSENT":
        blockers.append("no researcher-written Phase 4C-1F semantic-pilot authorization (B2/B3 evidence missing)")
    if authorization["phase04c1g_final_answer_gate"]["status"] == "AUTHORIZATION_ABSENT":
        blockers.append("no researcher-written Phase 4C-1G final-answer authorization")
    if semantic_complete < preparation["task_count"]:
        blockers.append(f"semantic observations complete: {semantic_complete}/{preparation['task_count']}")
    if branch_complete < 4 * preparation["task_count"]:
        blockers.append(f"final-answer units complete: {branch_complete}/{4 * preparation['task_count']}")
    if analyzed and decision_path.is_file():
        decision = json.loads(decision_path.read_text())
        outcome = decision["outcome"]
    else:
        outcome = "EXPERIMENT_INSUFFICIENT_OR_INVALID"
        atomic_json(decision_path, {"outcome": outcome, "executed": False, "blockers": blockers,
                                    "rule": DECISION_RULE,
                                    "note": "No final-answer data exist; no result can be inferred."})
    readiness = {
        "schema_version": "bite.phase04c1g_readiness.v1",
        "phase_status": ("ENGINEERING_SUCCESS / EXPERIMENT_EXECUTED" if analyzed
                         else "ENGINEERING_SUCCESS_WITH_BLOCKERS"),
        "protocol": preparation["protocol"],
        "genuine_agent_continuation": False,
        "research_outcome": outcome,
        "blockers": blockers,
        "task_manifest_sha256": preparation["task_manifest_sha256"],
        "tasks": preparation["task_count"],
        "source_groups": preparation["source_group_count"],
        "zoom_evidence_complete": identity["zoom_crops_present"] == preparation["task_count"],
        "mock_contract_rows": mock["finalized_rows"],
        "semantic_observations_complete": semantic_complete,
        "final_answer_units_complete": branch_complete,
        "real_model_calls_this_phase": semantic_complete + branch_complete,
        "offline_labels_opened": (PHASE / "offline_labels/count_labels.jsonl").is_file(),
    }
    atomic_json(PHASE / "readiness/readiness.json", readiness)
    print(json.dumps(readiness, indent=2))


if __name__ == "__main__":
    main()
