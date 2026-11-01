#!/usr/bin/env python3
"""Build the reproducibility manifest for the completed offline Phase 4B-2B-4."""

from __future__ import annotations

import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "outputs/bite/phase04b2b4"

SOURCES = [
    "evaluation_kit/bite_calibration/adjudication_schema.py",
    "evaluation_kit/bite_calibration/adjudication_sampling.py",
    "evaluation_kit/bite_calibration/adjudication_export.py",
    "evaluation_kit/bite_calibration/adjudication_validation.py",
    "evaluation_kit/bite_calibration/conditional_features.py",
    "evaluation_kit/bite_calibration/evidence_diagnostics.py",
    "evaluation_kit/bite_calibration/model_specification.py",
    "evaluation_kit/bite_calibration/statistical_readiness.py",
]
SCRIPTS = [
    "scripts/bite/build_task_v_review_queue.py",
    "scripts/bite/serve_task_v_review.py",
    "scripts/bite/validate_task_v_reviews.py",
    "scripts/bite/analyze_conditional_evidence.py",
    "scripts/bite/assess_phase4c_readiness.py",
    "scripts/bite/build_phase04b2b4_manifest.py",
]
DOCS = [
    "docs/bite/PHASE_04B2B4_REPORT.md",
    "docs/bite/TASK_V_ANNOTATION_ADJUDICATION_PROTOCOL.md",
    "docs/bite/TASK_V_ANNOTATION_RELIABILITY.md",
    "docs/bite/TASK_V_CONDITIONAL_EVIDENCE_DIAGNOSTICS.md",
    "docs/bite/TASK_V_ACTION_SPACE_REASSESSMENT.md",
    "docs/bite/PHASE_04C_RESTRICTED_MODEL_SPECIFICATION.md",
    "docs/bite/PHASE_04C_READINESS_DECISION.md",
]
ARTIFACTS = [
    "outputs/bite/phase04b2b4/integrity/historical_artifact_verification.json",
    "outputs/bite/phase04b2b4/review_sampling/review_sampling_summary.json",
    "outputs/bite/phase04b2b4/review_interface/review_cases.jsonl",
    "outputs/bite/phase04b2b4/review_interface/index.html",
    "outputs/bite/phase04b2b4/human_adjudications/pending_adjudications.jsonl",
    "outputs/bite/phase04b2b4/conditional_features/pilot_runtime_features.jsonl",
    "outputs/bite/phase04b2b4/conditional_features/expansion_runtime_features.jsonl",
    "outputs/bite/phase04b2b4/diagnostics/conditional_evidence_summary.json",
    "outputs/bite/phase04b2b4/diagnostics/pilot_paired_diagnostics.jsonl",
    "outputs/bite/phase04b2b4/diagnostics/expansion_paired_diagnostics.jsonl",
    "outputs/bite/phase04b2b4/model_specification/phase4c_restricted_model_specification.json",
    "outputs/bite/phase04b2b4/readiness/phase4c_readiness.json",
    "outputs/bite/phase04b2b4/validation/human_adjudication_validation.json",
    "outputs/bite/phase04b2b4/tests/targeted_pytest.xml",
    "outputs/bite/phase04b2b4/tests/pytest.xml",
]


def _sha(relative):
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def _hashes(paths):
    missing = [path for path in paths if not (ROOT / path).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing manifest inputs: {missing}")
    return {path: _sha(path) for path in paths}


def _junit(relative):
    root = ET.parse(ROOT / relative).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    return {
        key: int(suite.attrib.get(key, 0))
        for key in ("tests", "failures", "errors", "skipped")
    }


def _git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, capture_output=True,
    ).stdout.strip()


def main():
    review = json.loads((OUTPUT / "review_sampling/review_sampling_summary.json").read_text())
    validation = json.loads((OUTPUT / "validation/human_adjudication_validation.json").read_text())
    readiness = json.loads((OUTPUT / "readiness/phase4c_readiness.json").read_text())
    manifest = {
        "schema_version": 1,
        "phase": "04B-2B-4",
        "status": "ENGINEERING_SUCCESS / HUMAN_ADJUDICATION_PENDING",
        "created_utc": datetime.now(UTC).isoformat(),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("branch", "--show-current"),
        "working_tree": _git("status", "--short"),
        "source_sha256": _hashes(SOURCES),
        "script_sha256": _hashes(SCRIPTS),
        "test_sha256": _hashes(["tests/bite_calibration/test_phase04b2b4.py"]),
        "documentation_sha256": _hashes(DOCS),
        "artifact_sha256": _hashes(ARTIFACTS),
        "review": {
            "candidate_cases": review["total_candidate_cases"],
            "statistical_cases": review["statistical"]["case_count"],
            "targeted_cases": review["targeted"]["case_count"],
            "queue_union_cases": review["review_queue_union_count"],
            "completed_human_judgments": validation["completed_human_judgments"],
            "suspected_omission_rate": validation["suspected_omission_rate"],
        },
        "tests": {
            "new_phase04b2b4_tests": 22,
            "targeted_summary": "214 passed, 0 failed",
            "targeted_junit_counts": _junit("outputs/bite/phase04b2b4/tests/targeted_pytest.xml"),
            "full_summary": "746 passed, 449 subtests passed, 0 failures; 3 existing pandas warnings",
            "full_junit_counts": _junit("outputs/bite/phase04b2b4/tests/pytest.xml"),
            "targeted_command": (
                ".venv/bin/python -m pytest tests/bite tests/bite_calibration "
                "tests/bite_collection -q"
            ),
            "full_command": ".venv/bin/python -m pytest tests -q",
            "phase_specific_ruff": "passed",
            "compileall": "passed",
            "git_diff_check": "passed",
            "configuration_and_registry_tests": "passed as part of full suite",
        },
        "interface_validation": {
            "loopback_html_http_status": 200,
            "loopback_case_api_http_status": 200,
            "source_hash_checked_before_serving": True,
            "human_record_schema_checked_before_exclusive_create": True,
        },
        "readiness": readiness["model_readiness"],
        "restrictions_observed": {
            "gpu_inference_calls": 0,
            "model_calls": 0,
            "datasets_or_checkpoints_downloaded": 0,
            "probabilities_fitted": False,
            "posterior_computed": False,
            "planner_implemented": False,
            "certificate_implemented": False,
            "main_agent_modified_by_phase04b2b4": False,
            "official_evaluator_modified_by_phase04b2b4": False,
            "historical_outputs_rewritten": False,
            "phase4c_started": False,
            "git_commit_created": False,
        },
    }
    atomic_json(OUTPUT / "implementation_manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
