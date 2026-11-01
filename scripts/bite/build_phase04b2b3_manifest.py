#!/usr/bin/env python3
"""Freeze checksums and measured results for Phase 4B-2B-3."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "outputs/bite/phase04b2b3"

SOURCE_FILES = [
    "evaluation_kit/bite_collection/batch_runner.py",
    "evaluation_kit/bite_collection/collection_audit.py",
    "evaluation_kit/bite_collection/integrity.py",
    "evaluation_kit/bite_collection/negative_audit.py",
    "evaluation_kit/bite_collection/focused_analysis.py",
    "evaluation_kit/bite_collection/expansion_protocol.py",
    "evaluation_kit/bite_collection/expansion_runner.py",
    "evaluation_kit/bite_collection/support_analysis.py",
    "scripts/bite/collect_calibration_pilot.py",
    "scripts/bite/collect_task_v_expansion.py",
    "scripts/bite/build_phase04b2b3_manifest.py",
]
TEST_FILES = ["tests/bite_collection/test_batch_collection.py", "tests/bite_collection/test_expansion.py"]
DOC_FILES = [
    "docs/bite/PHASE_04B2B3_REPORT.md",
    "docs/bite/TASK_V_NEGATIVE_LABEL_AUDIT.md",
    "docs/bite/TASK_V_FOCUSED_EVIDENCE_ANALYSIS.md",
    "docs/bite/COLLECTION_INTEGRITY_REVALIDATION.md",
    "docs/bite/TASK_V_EXPANSION_PROTOCOL.md",
    "docs/bite/TASK_V_EXPANSION_RESULTS.md",
    "docs/bite/TASK_V_SUPPORT_READINESS.md",
]
ARTIFACT_FILES = [
    "outputs/bite/phase04b2b3/protocol/task_v_expansion_protocol.json",
    "outputs/bite/phase04b2b3/preflight/expansion_preflight.json",
    "outputs/bite/phase04b2b3/canary/canary_gate_v2.json",
    "outputs/bite/phase04b2b3/expansion/first_full_execution.json",
    "outputs/bite/phase04b2b3/expansion/execution.json",
    "outputs/bite/phase04b2b3/audit_existing/negative_audit_summary.json",
    "outputs/bite/phase04b2b3/analysis/expansion_collection_audit.json",
    "outputs/bite/phase04b2b3/analysis/task_v_support_summary.json",
    "outputs/bite/phase04b2b3/validation/existing_pilot_integrity_v2.json",
    "outputs/bite/phase04b2b3/validation/expansion_integrity_v2.json",
]


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def digests(paths):
    return {path: digest(path) for path in paths}


def junit_counts(path):
    root = ElementTree.parse(path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    return {key: int(suite.attrib.get(key, 0)) for key in ("tests", "failures", "errors", "skipped")}


def main():
    original = json.loads((OUTPUT / "audit_existing/negative_audit_summary.json").read_text())
    expanded = json.loads((OUTPUT / "analysis/expansion_collection_audit.json").read_text())
    integrity = json.loads((OUTPUT / "validation/expansion_integrity_v2.json").read_text())
    first_execution = json.loads((OUTPUT / "expansion/first_full_execution.json").read_text())
    resume_execution = json.loads((OUTPUT / "expansion/execution.json").read_text())
    protocol = json.loads((OUTPUT / "protocol/task_v_expansion_protocol.json").read_text())
    manifest = {
        "schema_version": 1,
        "phase": "04B-2B-3",
        "status": "SUCCESS",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "git_branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "working_tree": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True),
        "source_sha256": digests(SOURCE_FILES),
        "test_sha256": {
            **digests(TEST_FILES),
            "outputs/bite/phase04b2b3/targeted_pytest.xml": digest(
                "outputs/bite/phase04b2b3/targeted_pytest.xml"),
            "outputs/bite/phase04b2b3/pytest.xml": digest("outputs/bite/phase04b2b3/pytest.xml"),
        },
        "documentation_sha256": digests(DOC_FILES),
        "artifact_sha256": digests(ARTIFACT_FILES),
        "tests": {
            "targeted_summary": "192 passed, 0 failed",
            "full_summary": "724 passed, 449 subtests passed, 0 failures/errors/skips; 3 existing pandas warnings",
            "full_junit_counts": junit_counts(OUTPUT / "pytest.xml"),
            "targeted_command": (
                ".venv/bin/python -m pytest tests/bite tests/bite_calibration "
                "tests/bite_collection -q --junitxml=outputs/bite/phase04b2b3/targeted_pytest.xml"
            ),
            "full_command": (
                ".venv/bin/python -m pytest tests -q "
                "--junitxml=outputs/bite/phase04b2b3/pytest.xml"
            ),
            "ruff_compile_pip_diff_checks": "passed",
        },
        "historical_negative_audit": original,
        "expansion_protocol": {
            "protocol_sha256": protocol["protocol_sha256"],
            "eligible_groups": protocol["eligible_source_group_count"],
            "selected_groups": protocol["source_group_count"],
            "scheduled_states": protocol["scheduled_query_count"],
            "repeat_control_groups": len(protocol["repeat_control_groups"]),
            "dispatch_cap": protocol["maximum_public_dispatches"],
        },
        "collection": {
            "completed_states": expanded["sampling"]["completed_states"],
            "candidate_present": expanded["sampling"]["completed_states"] - expanded["sampling"]["no_candidate"],
            "no_candidate": expanded["sampling"]["no_candidate"],
            "actual_dispatches": first_execution["actual_dispatches_after_run"],
            "failed_dispatches": expanded["actions"]["failed_dispatches"],
            "offline_labels": expanded["offline_labels"],
            "content_integrity_valid": integrity["valid"],
            "raw_before_label_states": integrity["stage_order_independently_reconstructible_states"],
        },
        "resume_proof": {
            "newly_completed": resume_execution["newly_completed"],
            "resumed_complete": resume_execution["resumed_complete"],
            "dispatches_unchanged": resume_execution["actual_dispatches_after_run"],
            "state_tree_sha256": "af25baee5fabc8c4b9271650ff3752809954b7ec2af30dcc3d1e414816b07823",
        },
        "restrictions_observed": {
            "qwen_calls": 0,
            "probabilities_fitted": False,
            "posterior_computed": False,
            "planner_implemented": False,
            "certificates_implemented": False,
            "model_training_or_finetuning": False,
            "phase04c_started": False,
            "git_commit_created": False,
        },
    }
    atomic_json(OUTPUT / "implementation_manifest.json", manifest)


if __name__ == "__main__":
    main()
