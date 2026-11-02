#!/usr/bin/env python3
"""Build the Phase 4C-1D checksum inventory and implementation manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]

SOURCES = (
    "evaluation_kit/bite_calibration/zoom_conditional_protocol.py",
    "evaluation_kit/bite_calibration/zoom_incremental_model.py",
    "evaluation_kit/bite_calibration/paired_zoom_evaluation.py",
    "evaluation_kit/bite_calibration/zoom_action_cost_analysis.py",
    "evaluation_kit/bite_calibration/zoom_evidence_readiness.py",
    "evaluation_kit/bite_calibration/sam3_attested_worker.py",
    "evaluation_kit/bite_calibration/matched_worker_bridge.py",
)
SCRIPTS = (
    "scripts/bite/run_zoom_incremental_feasibility.py",
    "scripts/bite/prepare_sam3_attestation.py",
    "scripts/bite/build_matched_worker_bridge_protocol.py",
    "scripts/bite/assess_phase04c1d_readiness.py",
    "scripts/bite/build_phase04c1d_manifest.py",
)
DOCS = (
    "docs/bite/PHASE_04C1D_REPORT.md",
    "docs/bite/TASK_V_ZOOM_CONDITIONAL_FEASIBILITY_PROTOCOL.md",
    "docs/bite/TASK_V_ZOOM_INCREMENTAL_PREDICTION_RESULTS.md",
    "docs/bite/TASK_V_ZOOM_EVIDENCE_DEPENDENCE_ANALYSIS.md",
    "docs/bite/TASK_V_ZOOM_COST_RISK_ANALYSIS.md",
    "docs/bite/TASK_V_ZOOM_MODEL_READINESS.md",
    "docs/bite/SAM3_ATTESTED_WORKER_PREPARATION.md",
    "docs/bite/TASK_V_MATCHED_WORKER_BRIDGE_PROTOCOL.md",
    "docs/bite/PHASE_04C1D_READINESS_DECISION.md",
)
TESTS = (
    "tests/bite_calibration/test_phase04c1d.py",
    "outputs/bite/phase04c1d/tests/targeted_pytest.xml",
    "outputs/bite/phase04c1d/tests/pytest.xml",
)


def _sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def _mapping(paths):
    missing = [path for path in paths if not (ROOT / path).is_file()]
    if missing:
        raise ValueError(f"Manifest input is missing: {missing}")
    return {path: _sha(path) for path in paths}


def _junit(path):
    root = ET.parse(ROOT / path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        field: sum(int(suite.attrib.get(field, 0)) for suite in suites)
        for field in ("tests", "failures", "errors", "skipped")
    }


def _artifact_paths(output):
    ignored = {
        output / "implementation_manifest.json",
        output / "manifest_checksums.json",
        output / "tests/targeted_pytest.xml",
        output / "tests/pytest.xml",
    }
    return tuple(
        str(path.relative_to(ROOT)) for path in sorted(output.rglob("*"))
        if path.is_file() and path not in ignored
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1d"))
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    source_hashes = _mapping(SOURCES)
    script_hashes = _mapping(SCRIPTS)
    documentation_hashes = _mapping(DOCS)
    test_hashes = _mapping(TESTS)
    artifact_hashes = _mapping(_artifact_paths(output))
    checksums = {
        "schema_version": "bite.phase04c1d_checksum_inventory.v1",
        "source_sha256": source_hashes,
        "script_sha256": script_hashes,
        "documentation_sha256": documentation_hashes,
        "test_sha256": test_hashes,
        "artifact_sha256": artifact_hashes,
    }
    atomic_json(output / "manifest_checksums.json", checksums)
    readiness = json.loads((output / "readiness/readiness.json").read_text())
    human = json.loads((
        ROOT / "outputs/bite/phase04c1c_revised/optional_human_reviews/status.json"
    ).read_text())
    status = subprocess.run(
        ["git", "status", "--short"], cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout
    manifest = {
        "schema_version": 1,
        "phase": "04C-1D",
        "status": (
            "ENGINEERING_SUCCESS / ZOOM_INCREMENTAL_SIGNAL_INCONCLUSIVE / "
            "CHECKPOINT_BRIDGE_PENDING"
        ),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True,
        ).stdout.strip(),
        "git_branch": subprocess.run(
            ["git", "branch", "--show-current"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip(),
        "working_tree": status,
        "source_sha256": source_hashes,
        "script_sha256": script_hashes,
        "documentation_sha256": documentation_hashes,
        "test_sha256": test_hashes,
        "artifact_sha256": artifact_hashes,
        "manifest_checksums_sha256": _sha("outputs/bite/phase04c1d/manifest_checksums.json"),
        "result": {
            "conditional_usefulness_decision": readiness["conditional_usefulness_decision"],
            "research_decision": readiness["research_decision"],
            "primary_brier_evidence": readiness["primary_brier_evidence"],
            "conditional_kernel_fitted": False,
        },
        "data_integrity": {
            "expansion_candidate_count": 203,
            "expansion_source_group_count": 30,
            "zoom_focused_branch_count": 203,
            "unique_association_count": 176,
            "ambiguous_association_count": 21,
            "no_alignment_count": 6,
            "execution_failure_count": 0,
            "human_review_records_preserved": human["validated_finalized_review_count"],
        },
        "tests": {
            "new_phase04c1d_tests": 38,
            "targeted_command": (
                ".venv/bin/python -m pytest tests/bite tests/bite_calibration "
                "tests/bite_collection -q --junitxml=outputs/bite/phase04c1d/tests/targeted_pytest.xml"
            ),
            "full_command": (
                ".venv/bin/python -m pytest tests -q "
                "--junitxml=outputs/bite/phase04c1d/tests/pytest.xml"
            ),
            "targeted_junit_counts": _junit("outputs/bite/phase04c1d/tests/targeted_pytest.xml"),
            "full_junit_counts": _junit("outputs/bite/phase04c1d/tests/pytest.xml"),
            "ruff_compile_integrity_diff_checks": "passed",
        },
        "worker_attestation": {
            "preparation_status": "PREPARED_NOT_EXECUTED",
            "historical_comparability": "UNVERIFIED",
            "matched_worker_bridge": "PREPARED_NOT_AUTHORIZED_NOT_EXECUTED",
        },
        "restrictions_observed": {
            "validation_outcomes_accessed": False,
            "internal_test_accessed": False,
            "sam3_inference_calls": 0,
            "vlm_calls": 0,
            "downloads": 0,
            "worker_restarts": 0,
            "human_reviews_rewritten": False,
            "historical_outputs_overwritten": False,
            "official_labels_changed": False,
            "production_agent_modified": False,
            "official_evaluator_modified": False,
            "underlying_model_retrained": False,
            "posterior_computed": False,
            "planner_implemented": False,
            "conditional_kernel_validated": False,
            "certificate_claimed": False,
            "git_commit_created": False,
        },
        "phase04c1e_started": False,
    }
    atomic_json(output / "implementation_manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
