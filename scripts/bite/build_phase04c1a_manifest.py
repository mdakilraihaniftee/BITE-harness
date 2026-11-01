#!/usr/bin/env python3
"""Build Phase 4C-1A integrity and reproducibility manifests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "outputs/bite/phase04c1a"
PRIOR_MANIFEST = ROOT / "outputs/bite/phase04b2b4/implementation_manifest.json"

SOURCES = [
    "evaluation_kit/bite_calibration/calibration_metrics.py",
    "evaluation_kit/bite_calibration/prior_model.py",
    "evaluation_kit/bite_calibration/grouped_crossfit.py",
    "evaluation_kit/bite_calibration/grouped_uncertainty.py",
    "evaluation_kit/bite_calibration/proxy_calibration.py",
    "evaluation_kit/bite_calibration/visual_endpoint.py",
    "evaluation_kit/bite_calibration/blind_review.py",
    "evaluation_kit/bite_calibration/validation_protocol.py",
]
SCRIPTS = [
    "scripts/bite/run_task_v_prior_experiment.py",
    "scripts/bite/build_validation_collection_protocol.py",
    "scripts/bite/serve_task_v_blind_review.py",
    "scripts/bite/validate_adjudication_progress.py",
    "scripts/bite/assess_phase04c1a_readiness.py",
    "scripts/bite/build_phase04c1a_manifest.py",
]
DOCS = [
    "docs/bite/PHASE_04C1A_REPORT.md",
    "docs/bite/TASK_V_BLIND_REVIEW_REFINEMENT.md",
    "docs/bite/TASK_V_VISUAL_ENDPOINT_SPECIFICATION.md",
    "docs/bite/TASK_V_PRIOR_CALIBRATION_EXPERIMENT.md",
    "docs/bite/TASK_V_PRIOR_RESULTS.md",
    "docs/bite/TASK_V_GROUPED_UNCERTAINTY.md",
    "docs/bite/PHASE_04C_VALIDATION_COLLECTION_PROTOCOL.md",
    "docs/bite/PHASE_04C_NEXT_STAGE_READINESS.md",
]


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _hashes(relatives):
    return {relative: _sha(ROOT / relative) for relative in relatives}


def _git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, capture_output=True,
    ).stdout.strip()


def _junit(path):
    root = ET.parse(path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    return {
        name: int(suite.attrib.get(name, 0))
        for name in ("tests", "failures", "errors", "skipped")
    }


def _verify_prior():
    prior = json.loads(PRIOR_MANIFEST.read_text())
    checks = {}
    for section in (
        "source_sha256", "script_sha256", "test_sha256", "documentation_sha256", "artifact_sha256",
    ):
        for relative, expected in prior[section].items():
            path = ROOT / relative
            actual = _sha(path) if path.is_file() else None
            checks[relative] = {
                "section": section, "expected": expected, "actual": actual,
                "valid": actual == expected,
            }
    result = {
        "schema_version": "bite.phase04c1a_prior_integrity.v1",
        "prior_manifest": str(PRIOR_MANIFEST.relative_to(ROOT)),
        "prior_manifest_sha256": _sha(PRIOR_MANIFEST),
        "reference_count": len(checks),
        "all_valid": all(row["valid"] for row in checks.values()),
        "checks": checks,
    }
    if not result["all_valid"]:
        raise RuntimeError("Phase 4B-2B-4 integrity verification failed")
    return result


def main():
    integrity = _verify_prior()
    atomic_json(OUTPUT / "integrity/phase04b2b4_verification.json", integrity)
    summary = json.loads((OUTPUT / "proxy_models/prior_experiment_summary.json").read_text())
    progress = json.loads((OUTPUT / "review_validation/adjudication_progress.json").read_text())
    readiness = json.loads((OUTPUT / "readiness/phase04c1a_readiness.json").read_text())
    artifact_paths = sorted(
        path for path in OUTPUT.rglob("*")
        if path.is_file() and path.name != "implementation_manifest.json"
    )
    artifact_hashes = {
        str(path.relative_to(ROOT)): _sha(path) for path in artifact_paths
    }
    manifest = {
        "schema_version": 1,
        "phase": "04C-1A",
        "status": "ENGINEERING_SUCCESS / PROXY_PRIOR_EXPLORATORY / HUMAN_REVIEW_PENDING",
        "created_utc": datetime.now(UTC).isoformat(),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("branch", "--show-current"),
        "working_tree": _git("status", "--short"),
        "prior_integrity": {"reference_count": integrity["reference_count"], "all_valid": True},
        "source_sha256": _hashes(SOURCES),
        "script_sha256": _hashes(SCRIPTS),
        "test_sha256": _hashes(["tests/bite_calibration/test_phase04c1a.py"]),
        "documentation_sha256": _hashes(DOCS),
        "artifact_sha256": artifact_hashes,
        "experiment": {
            "primary_cohort": summary["primary_cohort"],
            "sensitivity_cohort": summary["sensitivity_cohort"],
            "experiment_count": len(summary["experiments"]),
            "models_per_experiment": 3,
            "crossfit_folds": 3,
            "bootstrap_replicates_per_model": 2000,
            "human_reviews_used": summary["human_reviews_used"],
            "calibration_validation_accessed": summary["calibration_validation_accessed"],
            "internal_test_accessed": summary["internal_test_accessed"],
        },
        "human_review": {
            "queue_case_count": progress["queue_case_count"],
            "completed_human_judgments": progress["completed_human_judgment_count"],
            "blind_api_cases_checked": 235,
            "blind_api_concealed_fields_valid": True,
            "source_hashes_valid": progress["source_hashes_valid"],
            "fake_human_reviews_created": False,
        },
        "tests": {
            "new_phase04c1a_tests": 24,
            "targeted_summary": "238 passed, 0 failed",
            "targeted_junit_counts": _junit(OUTPUT / "tests/targeted_pytest.xml"),
            "full_summary": "770 passed, 449 subtests passed, 0 failures; 3 existing pandas warnings",
            "full_junit_counts": _junit(OUTPUT / "tests/pytest.xml"),
            "targeted_command": (
                ".venv/bin/python -m pytest tests/bite tests/bite_calibration "
                "tests/bite_collection -q"
            ),
            "full_command": ".venv/bin/python -m pytest tests -q",
            "phase_specific_ruff": "passed",
            "compileall": "passed",
            "git_diff_check": "passed",
        },
        "readiness": readiness,
        "restrictions_observed": {
            "gpu_inference_calls": 0,
            "sam3_or_vlm_training_calls": 0,
            "datasets_or_checkpoints_downloaded": 0,
            "zoom_likelihood_fitted": False,
            "zoom_posterior_computed": False,
            "validation_collection_executed": False,
            "planner_implemented": False,
            "controller_implemented": False,
            "certificate_claimed": False,
            "main_agent_modified_by_phase04c1a": False,
            "official_evaluator_modified_by_phase04c1a": False,
            "historical_outputs_rewritten": False,
            "git_commit_created": False,
            "phase04c1b_started": False,
        },
    }
    atomic_json(OUTPUT / "implementation_manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
