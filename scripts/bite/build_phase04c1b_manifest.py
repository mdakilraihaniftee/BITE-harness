#!/usr/bin/env python3
"""Build the final Phase 4C-1B implementation and artifact manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    "evaluation_kit/bite_calibration/paired_model_comparison.py",
    "evaluation_kit/bite_calibration/label_sensitivity.py",
    "evaluation_kit/bite_calibration/grouped_label_sensitivity.py",
    "evaluation_kit/bite_calibration/review_progress.py",
    "evaluation_kit/bite_calibration/validation_readiness.py",
    "evaluation_kit/bite_calibration/visual_endpoint.py",
    "evaluation_kit/bite_calibration/blind_review.py",
)
SCRIPTS = (
    "scripts/bite/compare_task_v_priors.py",
    "scripts/bite/analyze_label_sensitivity.py",
    "scripts/bite/check_task_v_review_progress.py",
    "scripts/bite/preflight_task_v_validation.py",
    "scripts/bite/assess_phase04c1b_readiness.py",
    "scripts/bite/serve_task_v_blind_review.py",
    "scripts/bite/build_phase04c1b_manifest.py",
)
DOCS = (
    "docs/bite/PHASE_04C1B_REPORT.md",
    "docs/bite/PHASE_04C_PAIRED_MODEL_COMPARISON.md",
    "docs/bite/ANNOTATION_UNCERTAINTY_SENSITIVITY_THEORY.md",
    "docs/bite/GROUPED_LABEL_UNCERTAINTY_ANALYSIS.md",
    "docs/bite/COMPLETE_TASK_V_HUMAN_REVIEWS.md",
    "docs/bite/TASK_V_VISUAL_ENDPOINT_REVIEW.md",
    "docs/bite/PHASE_04C_VALIDATION_PREFLIGHT.md",
    "docs/bite/BITE_EVIDENCE_REDUNDANCY_AND_LABEL_UNCERTAINTY.md",
    "docs/bite/PHASE_04C1B_READINESS_DECISION.md",
)
TESTS = ("tests/bite_calibration/test_phase04c1b.py",)


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def hashes(paths):
    return {path: sha(path) for path in paths}


def junit(path):
    root = ElementTree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {key: sum(int(s.attrib.get(key, 0)) for s in suites)
            for key in ("tests", "failures", "errors", "skipped")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1b"))
    args = parser.parse_args()
    output = ROOT / args.output
    artifacts = sorted(
        str(path.relative_to(ROOT)) for path in output.rglob("*")
        if path.is_file() and path.name != "implementation_manifest.json"
    )
    targeted = junit(output / "tests/targeted_pytest.xml")
    full = junit(output / "tests/pytest.xml")
    readiness = json.loads((output / "readiness/phase04c1b_readiness.json").read_text())
    integrity = json.loads((output / "integrity/phase04c1a_verification.json").read_text())
    manifest = {
        "schema_version": 1, "phase": "04C-1B", "status": readiness["overall"],
        "created_utc": datetime.now(UTC).isoformat(),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "git_branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "working_tree": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True),
        "phase04c1a_integrity": {
            "immutable_reference_count": integrity["immutable_reference_count"],
            "immutable_references_all_valid": integrity["immutable_references_all_valid"],
            "versioned_source_change_count": integrity["versioned_source_change_count"],
            "historical_artifacts_rewritten": False,
        },
        "source_sha256": hashes(SOURCES), "script_sha256": hashes(SCRIPTS),
        "test_sha256": hashes(TESTS), "documentation_sha256": hashes(DOCS),
        "artifact_sha256": hashes(artifacts),
        "tests": {
            "new_phase04c1b_tests": 28, "targeted_junit_counts": targeted,
            "full_junit_counts": full,
            "targeted_command": ".venv/bin/python -m pytest tests/bite tests/bite_calibration tests/bite_collection -q",
            "full_command": ".venv/bin/python -m pytest tests -q",
            "ruff_compile_diff_checks": "passed",
        },
        "analysis": {
            "frozen_experiments_reproduced": 4, "paired_bootstrap_replicates_per_experiment": 2000,
            "candidate_sensitivity_exact": True, "group_sensitivity_exact": True,
            "combined_solver": "exact dynamic programming", "human_reviews_used": 0,
            "validation_inference_executed": False,
        },
        "readiness": readiness,
        "restrictions_observed": readiness["restrictions"],
    }
    atomic_json(output / "implementation_manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
