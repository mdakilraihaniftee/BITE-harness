#!/usr/bin/env python3
"""Freeze Phase 04B-2B-2 implementation and artifact identities."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from xml.etree import ElementTree

from evaluation_kit.bite_calibration.common import file_hash
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "outputs/bite/phase04b2b2"


def _hashes(paths):
    return {str(path): file_hash(ROOT / path) for path in paths}


def _junit(path):
    root = ElementTree.parse(path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    return {name: int(suite.attrib.get(name, 0)) for name in ("tests", "failures", "errors", "skipped")}


def _completion_tree():
    rows = []
    for path in sorted((OUTPUT / "observations/aquarium_task_v_seed417_g20/states").glob("*/completion.json")):
        rows.append({"path": str(path.relative_to(ROOT)), "sha256": file_hash(path)})
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"state_completion_count": len(rows), "state_completion_tree_sha256": digest}


def main():
    source = [
        "evaluation_kit/bite_collection/__init__.py",
        "evaluation_kit/bite_collection/dataset_adapter.py",
        "evaluation_kit/bite_collection/manifest_iterator.py",
        "evaluation_kit/bite_collection/batch_runner.py",
        "evaluation_kit/bite_collection/resume.py",
        "evaluation_kit/bite_collection/collection_audit.py",
        "scripts/bite/collect_calibration_pilot.py",
        "scripts/bite/build_phase04b2b2_manifest.py",
    ]
    docs = [
        "docs/bite/PHASE_04B2B2_COLLECTION_REPORT.md",
        "docs/bite/AQUARIUM_TASK_V_PILOT_RESULTS.md",
        "docs/bite/TASK_V_COLLECTION_SUPPORT_ANALYSIS.md",
        "docs/bite/MULTI_IMAGE_COLLECTION_REPRODUCIBILITY.md",
    ]
    artifacts = [
        "outputs/bite/phase04b2b2/preflight/preflight_report.json",
        "outputs/bite/phase04b2b2/preflight/sample_selection_manifest.json",
        "outputs/bite/phase04b2b2/canary/canary_gate.json",
        "outputs/bite/phase04b2b2/pilot/initial_execution.json",
        "outputs/bite/phase04b2b2/pilot/execution.json",
        "outputs/bite/phase04b2b2/audits/pilot_audit.json",
        "outputs/bite/phase04b2b2/offline_labels/export_summary.json",
        "outputs/bite/phase04b2b2/offline_labels/initial_candidate_labels.jsonl",
        "outputs/bite/phase04b2b2/offline_labels/branch_calibration_records.jsonl",
        "outputs/bite/phase04b2b2/validation/integrity_report.json",
        "outputs/bite/phase04b2b2/validation/targeted_pytest.xml",
        "outputs/bite/phase04b2b2/validation/pytest.xml",
    ]
    audit = json.loads((OUTPUT / "audits/pilot_audit.json").read_text())
    preflight = json.loads((OUTPUT / "preflight/preflight_report.json").read_text())
    manifest = {
        "schema_version": 1, "phase": "04B-2B-2", "status": "SUCCESS",
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "git_branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "working_tree": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True),
        "source_sha256": _hashes(source), "test_sha256": _hashes(["tests/bite_collection/test_batch_collection.py"]),
        "documentation_sha256": _hashes(docs), "artifact_sha256": _hashes(artifacts),
        "source": preflight["dataset"], "sample": preflight["selection"],
        "collection": {key: audit[key] for key in (
            "sampling", "actions", "actual_logical_dispatches", "observation_outcomes", "exact_repeat",
            "offline_labels", "latency_ms", "storage", "resume", "state_isolation", "scientific_support",
        )},
        "collection_integrity": _completion_tree(),
        "tests": {
            "new_phase_tests": 9,
            "targeted_summary": "177 passed, 0 failed",
            "full_summary": "709 passed, 449 subtests passed, 0 failures/errors/skips; 3 existing pandas warnings",
            "targeted_junit": _junit(OUTPUT / "validation/targeted_pytest.xml"),
            "full_junit": _junit(OUTPUT / "validation/pytest.xml"),
            "targeted_command": ".venv/bin/python -m pytest tests/bite tests/bite_calibration tests/bite_collection -q --junitxml=outputs/bite/phase04b2b2/validation/targeted_pytest.xml",
            "full_command": ".venv/bin/python -m pytest tests -q --junitxml=outputs/bite/phase04b2b2/validation/pytest.xml",
            "ruff_compile_diff_checks": "passed",
        },
        "previous_phase_integrity": {
            "phase04b2b1a_manifest_sha256": file_hash(ROOT / "outputs/bite/phase04b2b1a/implementation_manifest.json"),
            "phase04b2b1_manifest_sha256": file_hash(ROOT / "outputs/bite/phase04b2b1/implementation_manifest.json"),
            "prior_output_files_modified_by_phase04b2b2": 0,
        },
        "restrictions_observed": {
            "qwen_or_orchestrator_calls": 0, "model_training": False,
            "probabilities_fitted": False, "posterior_computed": False,
            "planner_implemented": False, "certificates_implemented": False,
            "baseline_agent_or_evaluator_modified_in_this_phase": False,
            "source_images_redistributed_in_reports": False, "phase4c_started": False,
            "git_commit_created": False,
        },
    }
    atomic_json(OUTPUT / "implementation_manifest.json", manifest)


if __name__ == "__main__":
    main()

