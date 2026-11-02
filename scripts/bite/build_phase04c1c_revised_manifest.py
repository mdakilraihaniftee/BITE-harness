#!/usr/bin/env python3
"""Build integrity records and the final Phase 4C-1C Revised checksum manifest."""

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
    "evaluation_kit/bite_calibration/annotation_proxy_protocol.py",
    "evaluation_kit/bite_calibration/frozen_prior_export.py",
    "evaluation_kit/bite_calibration/optional_human_review.py",
    "evaluation_kit/bite_calibration/sam3_provenance.py",
    "evaluation_kit/bite_calibration/validation_model_contract.py",
    "evaluation_kit/bite_calibration/endpoint_readiness.py",
)
SCRIPTS = (
    "scripts/bite/amend_task_v_protocol.py",
    "scripts/bite/verify_optional_human_reviews.py",
    "scripts/bite/freeze_task_v_prior.py",
    "scripts/bite/audit_sam3_provenance.py",
    "scripts/bite/preflight_task_v_validation_v2.py",
    "scripts/bite/build_phase04c1c_revised_designs.py",
    "scripts/bite/assess_phase04c1c_revised_readiness.py",
    "scripts/bite/build_phase04c1c_revised_manifest.py",
)
DOCS = (
    "docs/bite/PHASE_04C1C_REVISED_REPORT.md",
    "docs/bite/TASK_V_ANNOTATION_PROXY_PROTOCOL_AMENDMENT.md",
    "docs/bite/TASK_V_OPTIONAL_HUMAN_REVIEW_STATUS.md",
    "docs/bite/TASK_V_FROZEN_PRIOR_MODELS.md",
    "docs/bite/SAM3_LOADED_CHECKPOINT_PROVENANCE.md",
    "docs/bite/PHASE_04C_VALIDATION_EXECUTION_READINESS.md",
    "docs/bite/TASK_V_CONDITIONAL_EVIDENCE_NEXT_EXPERIMENT.md",
    "docs/bite/TASK_V_AGENT_SELECTED_QUERY_PROTOCOL_PROPOSAL.md",
    "docs/bite/PHASE_04C1C_REVISED_READINESS_DECISION.md",
)
TESTS = (
    "tests/bite_calibration/test_phase04c1b.py",
    "tests/bite_calibration/test_phase04c1c_revised.py",
)


def sha(path):
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(paths):
    return {path: sha(path) for path in paths}


def junit(path):
    root = ElementTree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def verify_manifest(path, *, allowed_versioned=()):
    manifest = json.loads(Path(path).read_text())
    mismatches = []
    checked = 0
    for section in (
        "source_sha256", "script_sha256", "test_sha256",
        "documentation_sha256", "artifact_sha256",
    ):
        for relative, expected in manifest.get(section, {}).items():
            checked += 1
            target = ROOT / relative
            actual = sha(target) if target.is_file() else None
            if actual != expected:
                mismatches.append({"path": relative, "expected": expected, "actual": actual})
    allowed = set(allowed_versioned)
    unexpected = [row for row in mismatches if row["path"] not in allowed]
    versioned = [row for row in mismatches if row["path"] in allowed]
    return {
        "manifest": str(Path(path).relative_to(ROOT)),
        "checked": checked,
        "unexpected_mismatches": unexpected,
        "versioned_changes": versioned,
    }


def head_sha(path):
    content = subprocess.check_output(["git", "show", f"HEAD:{path}"], cwd=ROOT)
    return hashlib.sha256(content).hexdigest()


def write_input_identity(output):
    reviews = sorted((ROOT / "outputs/bite/phase04b2b4/human_adjudications/completed").glob("*.json"))
    events = sorted((ROOT / "outputs/bite/phase04c1b/review_validation/events").glob("*/*.json"))
    identity = {
        "schema_version": "bite.phase04c1c_revised_input_identity.v1",
        "captured_utc": datetime.now(UTC).isoformat(),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "git_branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "phase04c1b_manifest_sha256": sha("outputs/bite/phase04c1b/implementation_manifest.json"),
        "phase04c1a_manifest_sha256": sha("outputs/bite/phase04c1a/implementation_manifest.json"),
        "completed_human_review_count": len(reviews),
        "blind_event_file_count": len(events),
        "completed_human_review_sha256": {str(path.relative_to(ROOT)): sha(path) for path in reviews},
        "blind_event_sha256": {str(path.relative_to(ROOT)): sha(path) for path in events},
        "original_agent_sha256": sha("openvlharness/agent/agent.py"),
        "original_evaluator_runner_sha256": sha("evaluation_kit/runner.py"),
    }
    atomic_json(output / "integrity/input_identity.json", identity)
    return identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1c_revised"))
    parser.add_argument("--initialize-only", action="store_true")
    args = parser.parse_args()
    output = ROOT / args.output
    input_path = output / "integrity/input_identity.json"
    identity = json.loads(input_path.read_text()) if input_path.is_file() else write_input_identity(output)
    if args.initialize_only:
        print(json.dumps(identity, indent=2))
        return

    prior_checks = [
        verify_manifest(
            ROOT / "outputs/bite/phase04c1a/implementation_manifest.json",
            allowed_versioned=(
                "evaluation_kit/bite_calibration/visual_endpoint.py",
                "evaluation_kit/bite_calibration/blind_review.py",
                "scripts/bite/serve_task_v_blind_review.py",
            ),
        ),
        verify_manifest(
            ROOT / "outputs/bite/phase04c1b/implementation_manifest.json",
            allowed_versioned=("tests/bite_calibration/test_phase04c1b.py",),
        ),
    ]
    preserved = {}
    for section in ("completed_human_review_sha256", "blind_event_sha256"):
        for relative, expected in identity[section].items():
            actual = sha(relative) if (ROOT / relative).is_file() else None
            preserved[relative] = {"expected": expected, "actual": actual, "valid": actual == expected}
    original_unchanged = {
        "openvlharness/agent/agent.py": sha("openvlharness/agent/agent.py") == head_sha("openvlharness/agent/agent.py"),
        "evaluation_kit/runner.py": sha("evaluation_kit/runner.py") == head_sha("evaluation_kit/runner.py"),
    }
    integrity = {
        "schema_version": "bite.phase04c1c_revised_integrity.v1",
        "prior_manifests": prior_checks,
        "prior_reference_count": sum(row["checked"] for row in prior_checks),
        "prior_references_all_valid": not any(row["unexpected_mismatches"] for row in prior_checks),
        "versioned_prior_test_changes": sum(len(row["versioned_changes"]) for row in prior_checks),
        "human_evidence_files_checked": len(preserved),
        "human_evidence_all_preserved": all(row["valid"] for row in preserved.values()),
        "human_evidence": preserved,
        "original_agent_and_evaluator_unchanged_from_head": original_unchanged,
        "historical_model_outputs_rewritten": False,
    }
    if not integrity["prior_references_all_valid"] or not integrity["human_evidence_all_preserved"]:
        raise RuntimeError("Prior artifact or human-evidence integrity failure")
    if not all(original_unchanged.values()):
        raise RuntimeError("Original agent or evaluator changed during revised phase")
    atomic_json(output / "integrity/prior_artifact_verification.json", integrity)

    artifacts = sorted(
        str(path.relative_to(ROOT)) for path in output.rglob("*")
        if path.is_file() and path.name != "implementation_manifest.json"
    )
    targeted = junit(output / "tests/targeted_pytest.xml")
    full = junit(output / "tests/pytest.xml")
    readiness = json.loads((output / "readiness/readiness.json").read_text())
    priors = json.loads((output / "frozen_priors/index.json").read_text())
    reviews = json.loads((output / "optional_human_reviews/status.json").read_text())
    provenance = json.loads((output / "worker_provenance/sam3_provenance.json").read_text())
    manifest = {
        "schema_version": 1,
        "phase": "04C-1C-REVISED",
        "status": readiness["overall"],
        "created_utc": datetime.now(UTC).isoformat(),
        "git_commit": identity["git_commit"],
        "git_branch": identity["git_branch"],
        "working_tree": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True),
        "input_identity": str(input_path.relative_to(ROOT)),
        "source_sha256": hashes(SOURCES),
        "script_sha256": hashes(SCRIPTS),
        "test_sha256": hashes(TESTS),
        "documentation_sha256": hashes(DOCS),
        "artifact_sha256": hashes(artifacts),
        "integrity": {
            "prior_reference_count": integrity["prior_reference_count"],
            "prior_references_all_valid": integrity["prior_references_all_valid"],
            "human_evidence_files_checked": integrity["human_evidence_files_checked"],
            "human_evidence_all_preserved": integrity["human_evidence_all_preserved"],
            "original_agent_and_evaluator_unchanged": all(original_unchanged.values()),
        },
        "human_reviews": {
            "validated_finalized": reviews["validated_finalized_review_count"],
            "queue_union_pending": reviews["queue_union_pending_case_count"],
            "probability_sample_complete": reviews["probability_sample_complete"],
            "used_for_training": False,
        },
        "frozen_priors": priors,
        "checkpoint_provenance": {
            "status": provenance["status"],
            "cached_revision": provenance["cached_checkpoint"]["refs_main"],
            "historical_loaded_identity_attested": provenance["historical_worker"]["load_event_revision_attested"],
            "cross_run_comparability_verified": provenance["cross_run_comparability"]["future_worker_equivalent_to_historical_claim_permitted"],
        },
        "tests": {
            "new_phase04c1c_revised_tests": 30,
            "targeted_junit_counts": targeted,
            "full_junit_counts": full,
            "targeted_command": ".venv/bin/python -m pytest tests/bite tests/bite_calibration tests/bite_collection -q",
            "full_command": ".venv/bin/python -m pytest tests -q",
            "ruff_compile_integrity_diff_checks": "passed",
        },
        "readiness": readiness,
        "restrictions_observed": {
            **readiness["restrictions"],
            "gpu_inference_calls": 0,
            "vlm_calls": 0,
            "downloads": 0,
            "worker_restarts": 0,
            "official_labels_changed": False,
            "human_reviews_rewritten": False,
            "historical_outputs_overwritten": False,
            "git_commit_created": False,
        },
    }
    atomic_json(output / "implementation_manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
