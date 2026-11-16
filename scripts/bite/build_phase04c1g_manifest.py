#!/usr/bin/env python3
"""Build the Phase 4C-1G checksum inventory and implementation manifest."""

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
PHASE = "outputs/bite/phase04c1g"

SOURCES = (
    "evaluation_kit/bite_calibration/task_level_probe_protocol.py",
    "evaluation_kit/bite_calibration/branch_evidence_renderer.py",
    "evaluation_kit/bite_calibration/task_level_branch_runner.py",
    "evaluation_kit/bite_calibration/oracle_headroom.py",
    "evaluation_kit/bite_calibration/learnable_headroom.py",
    "evaluation_kit/bite_calibration/task_level_decision_analysis.py",
)
SCRIPTS = (
    "scripts/bite/prepare_oracle_headroom_pilot.py",
    "scripts/bite/preflight_oracle_headroom.py",
    "scripts/bite/run_oracle_headroom_branches.py",
    "scripts/bite/analyze_oracle_headroom.py",
    "scripts/bite/assess_phase04c1g_readiness.py",
    "scripts/bite/build_phase04c1g_manifest.py",
)
DOCS = (
    "docs/bite/PHASE_04C1G_REPORT.md",
    "docs/bite/TASK_LEVEL_PROBE_PROTOCOL.md",
    "docs/bite/ORACLE_HEADROOM_RESULTS.md",
    "docs/bite/LEARNABLE_HEADROOM_RESULTS.md",
    "docs/bite/COMBINED_EVIDENCE_ANALYSIS.md",
    "docs/bite/TASK_LEVEL_ACTION_COSTS.md",
    "docs/bite/PHASE_04C1G_RESEARCH_DECISION.md",
)
MODIFIED_EARLIER_FILES = ("docs/bite/BITE_CLAUDE_DEVELOPER_HANDOFF.md",)
TESTS = (
    "tests/bite_calibration/test_phase04c1g.py",
    f"{PHASE}/tests/targeted_pytest.xml",
    f"{PHASE}/tests/pytest.xml",
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
    parser.parse_args()
    output = (ROOT / PHASE).resolve()
    ignored = {output / name for name in (
        "implementation_manifest.json", "manifest_checksums.json", "tests/targeted_pytest.xml", "tests/pytest.xml")}
    artifacts = tuple(str(p.relative_to(ROOT)) for p in sorted(output.rglob("*")) if p.is_file() and p not in ignored)
    previous = json.loads((ROOT / "outputs/bite/phase04c1f/implementation_manifest.json").read_text())
    previous_hashes = {**previous["source_sha256"], **previous["script_sha256"], **previous["documentation_sha256"],
                       **previous.get("modified_phase04c1e_files", {})}
    checksums = {
        "schema_version": "bite.phase04c1g_checksum_inventory.v1",
        "source_sha256": _mapping(SOURCES),
        "script_sha256": _mapping(SCRIPTS),
        "documentation_sha256": _mapping(DOCS),
        "test_sha256": _mapping(TESTS),
        "artifact_sha256": _mapping(artifacts),
        "modified_earlier_files": {
            path: {"previous_recorded": previous_hashes.get(path), "phase04c1g_sha256": _sha(path)}
            for path in MODIFIED_EARLIER_FILES},
    }
    atomic_json(output / "manifest_checksums.json", checksums)
    readiness = json.loads((output / "readiness/readiness.json").read_text())

    def git(*command):
        return subprocess.run(["git", *command], cwd=ROOT, check=True, capture_output=True, text=True).stdout

    manifest = {
        "schema_version": 1,
        "phase": "04C-1G",
        "status": readiness["phase_status"],
        "research_outcome": readiness["research_outcome"],
        "protocol": readiness["protocol"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git("rev-parse", "HEAD").strip(),
        "git_branch": git("branch", "--show-current").strip(),
        "working_tree": git("status", "--short"),
        **{key: checksums[key] for key in ("source_sha256", "script_sha256", "documentation_sha256", "test_sha256",
                                           "artifact_sha256", "modified_earlier_files")},
        "manifest_checksums_sha256": _sha(f"{PHASE}/manifest_checksums.json"),
        "result": readiness,
        "tests": {
            "targeted_command": (".venv/bin/python -m pytest tests/bite tests/bite_calibration tests/bite_collection "
                                 f"-q --junitxml={PHASE}/tests/targeted_pytest.xml"),
            "full_command": f".venv/bin/python -m pytest tests -q --junitxml={PHASE}/tests/pytest.xml",
            "targeted_junit_counts": _junit(f"{PHASE}/tests/targeted_pytest.xml"),
            "full_junit_counts": _junit(f"{PHASE}/tests/pytest.xml"),
        },
        "restrictions_observed": {
            "real_model_calls": readiness["real_model_calls_this_phase"],
            "sam3_inference_calls": 0,
            "inference_services_started": 0,
            "authorization_created_by_agent": False,
            "count_labels_opened": readiness["offline_labels_opened"],
            "validation_outcomes_accessed": False,
            "internal_test_accessed": False,
            "historical_outputs_overwritten": False,
            "production_agent_modified": False,
            "official_evaluator_modified": False,
            "model_weights_or_serving_parameters_changed": False,
            "planner_implemented": False,
            "git_commit_created": False,
        },
    }
    atomic_json(output / "implementation_manifest.json", manifest)
    print(json.dumps({k: manifest[k] for k in ("status", "research_outcome", "protocol")} | {"tests": manifest["tests"]},
                     indent=2))


if __name__ == "__main__":
    main()
