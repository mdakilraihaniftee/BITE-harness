#!/usr/bin/env python3
"""Build the Phase 4C-1F checksum inventory and implementation manifest."""

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
    "evaluation_kit/bite_calibration/semantic_pilot_preflight.py",
    "evaluation_kit/bite_calibration/semantic_pilot_analysis.py",
    "evaluation_kit/bite_calibration/semantic_pilot_protocol.py",
    "evaluation_kit/bite_calibration/action_utility_screen.py",
)
SCRIPTS = (
    "scripts/bite/preflight_semantic_pilot.py",
    "scripts/bite/analyze_semantic_pilot.py",
    "scripts/bite/run_semantic_verification_pilot.py",
    "scripts/bite/assess_phase04c1f_readiness.py",
    "scripts/bite/build_phase04c1f_manifest.py",
)
DOCS = (
    "docs/bite/PHASE_04C1F_REPORT.md",
    "docs/bite/TASK_V_SEMANTIC_PILOT_EXECUTION_REPORT.md",
    "docs/bite/TASK_V_SEMANTIC_EVIDENCE_RESULTS.md",
    "docs/bite/TASK_V_SEMANTIC_INCREMENTAL_VALUE.md",
    "docs/bite/TASK_V_SEMANTIC_FAILURE_ANALYSIS.md",
    "docs/bite/BITE_ACTION_COST_COMPARISON.md",
    "docs/bite/TASK_V_SEMANTIC_PILOT_RESEARCH_DECISION.md",
    "docs/bite/PHASE_04C1F_READINESS_DECISION.md",
)
# Phase 4C-1E files changed in 4C-1F (code hardening and dated corrections).
MODIFIED_PHASE04C1E = (
    "evaluation_kit/bite_calibration/semantic_pilot_protocol.py",
    "evaluation_kit/bite_calibration/action_utility_screen.py",
    "scripts/bite/run_semantic_verification_pilot.py",
    "docs/bite/BITE_DEPENDENT_EVIDENCE_VALUE_THEORY.md",
    "docs/bite/BITE_ACTION_UTILITY_SCREENING.md",
    "docs/bite/PHASE_04C1E_REPORT.md",
    "docs/bite/TASK_V_AGENT_TASK_EXTENSION_PROPOSAL.md",
    "docs/bite/TASK_V_COMPLEMENTARY_EVIDENCE_PILOT.md",
    "docs/bite/BITE_CLAUDE_DEVELOPER_HANDOFF.md",
)
TESTS = (
    "tests/bite_calibration/test_phase04c1f.py",
    "outputs/bite/phase04c1f/tests/targeted_pytest.xml",
    "outputs/bite/phase04c1f/tests/pytest.xml",
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
    return {field: sum(int(suite.attrib.get(field, 0)) for suite in suites)
            for field in ("tests", "failures", "errors", "skipped")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1f"))
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    ignored = {output / name for name in (
        "implementation_manifest.json", "manifest_checksums.json", "tests/targeted_pytest.xml", "tests/pytest.xml")}
    artifacts = tuple(str(p.relative_to(ROOT)) for p in sorted(output.rglob("*")) if p.is_file() and p not in ignored)
    previous = json.loads((ROOT / "outputs/bite/phase04c1e/implementation_manifest.json").read_text())
    previous_hashes = {**previous["source_sha256"], **previous["script_sha256"], **previous["documentation_sha256"]}
    modified = {path: {"phase04c1e_sha256": previous_hashes.get(path), "phase04c1f_sha256": _sha(path)}
                for path in MODIFIED_PHASE04C1E}
    checksums = {
        "schema_version": "bite.phase04c1f_checksum_inventory.v1",
        "source_sha256": _mapping(SOURCES),
        "script_sha256": _mapping(SCRIPTS),
        "documentation_sha256": _mapping(DOCS),
        "test_sha256": _mapping(TESTS),
        "artifact_sha256": _mapping(artifacts),
        "modified_phase04c1e_files": modified,
    }
    atomic_json(output / "manifest_checksums.json", checksums)
    readiness = json.loads((output / "research_decision/readiness.json").read_text())
    integrity = json.loads((output / "preflight/pilot_integrity.json").read_text())

    def git(*command):
        return subprocess.run(["git", *command], cwd=ROOT, check=True, capture_output=True, text=True).stdout

    manifest = {
        "schema_version": 1,
        "phase": "04C-1F",
        "status": readiness["overall_status"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git("rev-parse", "HEAD").strip(),
        "git_branch": git("branch", "--show-current").strip(),
        "working_tree": git("status", "--short"),
        **{key: checksums[key] for key in (
            "source_sha256", "script_sha256", "documentation_sha256", "test_sha256", "artifact_sha256",
            "modified_phase04c1e_files")},
        "manifest_checksums_sha256": _sha("outputs/bite/phase04c1f/manifest_checksums.json"),
        "result": {
            "authorization": readiness["authorization"],
            "pilot_executed": False,
            "pilot_integrity": integrity["status"],
            "frozen_manifest_sha256": integrity["manifest_sha256"],
            "prompt_sha256": integrity["prompt_sha256"],
            "ontology_sha256": integrity["ontology_sha256"],
            "design_sha256": integrity["design_sha256"],
            "cases": integrity["case_count"],
            "source_groups": integrity["source_group_count"],
            "semantic_research_decision": readiness["semantic_pilot_research_decision"],
        },
        "tests": {
            "targeted_command": (".venv/bin/python -m pytest tests/bite tests/bite_calibration tests/bite_collection "
                                 "-q --junitxml=outputs/bite/phase04c1f/tests/targeted_pytest.xml"),
            "full_command": ".venv/bin/python -m pytest tests -q --junitxml=outputs/bite/phase04c1f/tests/pytest.xml",
            "targeted_junit_counts": _junit("outputs/bite/phase04c1f/tests/targeted_pytest.xml"),
            "full_junit_counts": _junit("outputs/bite/phase04c1f/tests/pytest.xml"),
        },
        "restrictions_observed": {
            "live_vlm_calls": 0,
            "sam3_inference_calls": 0,
            "inference_services_started": 0,
            "authorization_created_by_agent": False,
            "pilot_labels_opened": False,
            "validation_outcomes_accessed": False,
            "internal_test_accessed": False,
            "frozen_manifest_prompt_ontology_changed": False,
            "historical_outputs_overwritten": False,
            "production_agent_modified": False,
            "official_evaluator_modified": False,
            "model_weights_or_serving_parameters_changed": False,
            "posterior_or_planner_implemented": False,
            "git_commit_created": False,
        },
    }
    atomic_json(output / "implementation_manifest.json", manifest)
    print(json.dumps(manifest["result"], indent=2))


if __name__ == "__main__":
    main()
