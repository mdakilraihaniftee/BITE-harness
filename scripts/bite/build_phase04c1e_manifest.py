#!/usr/bin/env python3
"""Build the Phase 4C-1E checksum inventory and implementation manifest."""

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
    "evaluation_kit/bite_calibration/action_utility_screen.py",
    "evaluation_kit/bite_calibration/semantic_observation_schema.py",
    "evaluation_kit/bite_calibration/semantic_region_action.py",
    "evaluation_kit/bite_calibration/semantic_feature_extractor.py",
    "evaluation_kit/bite_calibration/semantic_pilot_protocol.py",
    "evaluation_kit/bite_calibration/semantic_comparison_design.py",
)
SCRIPTS = (
    "scripts/bite/evaluate_zoom_action_utility.py",
    "scripts/bite/prepare_semantic_verification_pilot.py",
    "scripts/bite/run_semantic_verification_pilot.py",
    "scripts/bite/assess_phase04c1e_readiness.py",
    "scripts/bite/build_phase04c1e_manifest.py",
)
DOCS = (
    "docs/bite/BITE_CLAUDE_DEVELOPER_HANDOFF.md",
    "docs/bite/PHASE_04C1E_REPORT.md",
    "docs/bite/BITE_ACTION_UTILITY_SCREENING.md",
    "docs/bite/TASK_V_SEMANTIC_VERIFICATION_ACTION.md",
    "docs/bite/TASK_V_COMPLEMENTARY_EVIDENCE_PILOT.md",
    "docs/bite/TASK_V_SEMANTIC_ONTOLOGY_AND_PROMPT.md",
    "docs/bite/BITE_DEPENDENT_EVIDENCE_VALUE_THEORY.md",
    "docs/bite/TASK_V_AGENT_TASK_EXTENSION_PROPOSAL.md",
    "docs/bite/PHASE_04C1E_READINESS_DECISION.md",
)
TESTS = (
    "tests/bite_calibration/test_phase04c1e.py",
    "outputs/bite/phase04c1e/tests/targeted_pytest.xml",
    "outputs/bite/phase04c1e/tests/pytest.xml",
)
# The mock run is a regenerable contract check; its 101 case directories are
# summarized by the mock contract report rather than inventoried file by file.
MOCK_RUN = "semantic_observation_contract/mock_run"


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
        if path.is_file() and path not in ignored and MOCK_RUN not in str(path.relative_to(output))
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1e"))
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    source_hashes = _mapping(SOURCES)
    script_hashes = _mapping(SCRIPTS)
    documentation_hashes = _mapping(DOCS)
    test_hashes = _mapping(TESTS)
    artifact_hashes = _mapping(_artifact_paths(output))
    checksums = {
        "schema_version": "bite.phase04c1e_checksum_inventory.v1",
        "source_sha256": source_hashes,
        "script_sha256": script_hashes,
        "documentation_sha256": documentation_hashes,
        "test_sha256": test_hashes,
        "artifact_sha256": artifact_hashes,
        "excluded_regenerable_directories": [f"outputs/bite/phase04c1e/{MOCK_RUN}"],
    }
    atomic_json(output / "manifest_checksums.json", checksums)
    readiness = json.loads((output / "readiness/readiness.json").read_text())
    pilot = json.loads((output / "semantic_pilot_manifest/manifest.json").read_text())
    human = json.loads((
        ROOT / "outputs/bite/phase04c1c_revised/optional_human_reviews/status.json"
    ).read_text())

    def git(*command):
        return subprocess.run(["git", *command], cwd=ROOT, check=True, capture_output=True, text=True).stdout

    manifest = {
        "schema_version": 1,
        "phase": "04C-1E",
        "status": readiness["overall_status"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git("rev-parse", "HEAD").strip(),
        "git_branch": git("branch", "--show-current").strip(),
        "working_tree": git("status", "--short"),
        "source_sha256": source_hashes,
        "script_sha256": script_hashes,
        "documentation_sha256": documentation_hashes,
        "test_sha256": test_hashes,
        "artifact_sha256": artifact_hashes,
        "manifest_checksums_sha256": _sha("outputs/bite/phase04c1e/manifest_checksums.json"),
        "result": {
            "zoom_collection_decision": readiness["zoom_utility_screen"]["decision"],
            "research_decision": readiness["research_decision"],
            "semantic_pilot_manifest_sha256": pilot["manifest_sha256"],
            "semantic_pilot_cases": pilot["case_count"],
            "semantic_pilot_groups": len(pilot["selected_source_groups"]),
            "prompt_sha256": pilot["frozen_contract"]["prompt_sha256"],
            "ontology_sha256": pilot["frozen_contract"]["ontology_sha256"],
            "paired_design_sha256": readiness["paired_comparison_design"]["design_sha256"],
        },
        "data_integrity": {
            "phase04c1d_predictions_verified_against_checksums": True,
            "models_refit_in_stage_a": False,
            "human_review_records_preserved": human["validated_finalized_review_count"],
        },
        "tests": {
            "targeted_command": (
                ".venv/bin/python -m pytest tests/bite tests/bite_calibration "
                "tests/bite_collection -q --junitxml=outputs/bite/phase04c1e/tests/targeted_pytest.xml"
            ),
            "full_command": (
                ".venv/bin/python -m pytest tests -q "
                "--junitxml=outputs/bite/phase04c1e/tests/pytest.xml"
            ),
            "targeted_junit_counts": _junit("outputs/bite/phase04c1e/tests/targeted_pytest.xml"),
            "full_junit_counts": _junit("outputs/bite/phase04c1e/tests/pytest.xml"),
        },
        "restrictions_observed": {
            "validation_outcomes_accessed": False,
            "internal_test_accessed": False,
            "pilot_selection_used_labels": False,
            "pilot_subset_label_statistics_computed": False,
            "expansion_labels_previously_opened_in_earlier_phases": True,
            "sam3_inference_calls": 0,
            "vlm_calls": 0,
            "mock_requester_calls_only": True,
            "downloads": 0,
            "worker_restarts": 0,
            "human_reviews_rewritten": False,
            "historical_outputs_overwritten": False,
            "production_agent_modified": False,
            "official_evaluator_modified": False,
            "underlying_model_retrained": False,
            "posterior_computed": False,
            "planner_implemented": False,
            "git_commit_created": False,
        },
    }
    atomic_json(output / "implementation_manifest.json", manifest)
    print(json.dumps(manifest["result"], indent=2))


if __name__ == "__main__":
    main()
