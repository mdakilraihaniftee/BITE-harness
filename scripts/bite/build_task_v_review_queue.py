#!/usr/bin/env python3
"""Build the source-group-aware Task V review queue and offline interface."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation_kit.bite_calibration.adjudication_export import (
    build_review_cases,
    write_review_bundle,
)
from evaluation_kit.bite_collection.dataset_adapter import (
    MANIFEST_DIGEST,
    AquariumDatasetAdapter,
)
from evaluation_kit.bite_collection.integrity import validate_run_directory
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "outputs/bite/phase04b2b4"


def _jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _verify_prior_artifacts():
    manifest_path = ROOT / "outputs/bite/phase04b2b3/implementation_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    checks = {}
    for relative, expected in manifest["artifact_sha256"].items():
        path = ROOT / relative
        actual = _sha(path)
        checks[relative] = {"expected": expected, "actual": actual, "valid": expected == actual}
    historical_root = ROOT / "outputs/bite/phase04b2b2/observations/aquarium_task_v_seed417_g20"
    expansion_root = ROOT / "outputs/bite/phase04b2b3/expansion/aquarium_task_v_expansion_seed418_g30"
    historical = validate_run_directory(historical_root)
    expansion = validate_run_directory(expansion_root)
    result = {
        "schema_version": "bite.phase04b2b4_integrity_verification.v1",
        "prior_manifest_sha256": _sha(manifest_path),
        "prior_artifact_checks": checks,
        "all_prior_artifact_checks_valid": all(row["valid"] for row in checks.values()),
        "historical_valid": historical["valid"], "historical_state_count": historical["state_count"],
        "expansion_valid": expansion["valid"], "expansion_state_count": expansion["state_count"],
        "source_manifest_sha256": MANIFEST_DIGEST,
        "expected_source_manifest_sha256": "61df2e5f2a817b022f07358ec5b63438c8cfb56973009cf854c7b460c86aebd4",
        "source_identity_valid": MANIFEST_DIGEST == "61df2e5f2a817b022f07358ec5b63438c8cfb56973009cf854c7b460c86aebd4",
        "no_gpu_or_model_service_required": True,
    }
    if not all((result["all_prior_artifact_checks_valid"], historical["valid"], expansion["valid"],
                result["source_identity_valid"])):
        raise RuntimeError("Historical integrity verification failed")
    return result


def main():
    for directory in (
        "integrity", "review_sampling", "review_interface", "human_adjudications/completed",
        "conditional_features", "diagnostics", "model_specification", "readiness", "validation",
    ):
        (OUTPUT / directory).mkdir(parents=True, exist_ok=True)
    integrity = _verify_prior_artifacts()
    atomic_json(OUTPUT / "integrity/historical_artifact_verification.json", integrity)
    adapter = AquariumDatasetAdapter()
    cohorts = [
        (
            "bite.task_v_pilot.seed417.g20.v1", "two_source_classes_per_group.v1",
            ROOT / "outputs/bite/phase04b2b3/audit_existing/negative_diagnostics.jsonl",
            ROOT / "outputs/bite/phase04b2b3/analysis/focused_pairs.jsonl",
        ),
        (
            "bite.task_v_expansion.seed418.g30.v1", "all_seven_source_classes_per_group.v1",
            ROOT / "outputs/bite/phase04b2b3/offline_labels/expansion_diagnostics/negative_diagnostics.jsonl",
            ROOT / "outputs/bite/phase04b2b3/analysis/expansion_focused/focused_pairs.jsonl",
        ),
    ]
    cases = []
    for cohort, design, diagnostics, pairs in cohorts:
        cases.extend(build_review_cases(
            diagnostics=_jsonl(diagnostics), focused_pairs=_jsonl(pairs), cohort_id=cohort,
            query_design_id=design, adapter=adapter,
        ))
    result = write_review_bundle(OUTPUT / "review_interface", cases, seed=420)
    for name in ("statistical_review_sample.json", "targeted_review_sample.json"):
        value = json.loads((OUTPUT / "review_interface" / name).read_text())
        atomic_json(OUTPUT / "review_sampling" / name, value)
    pending = (OUTPUT / "review_interface/pending_adjudications.jsonl").read_text()
    (OUTPUT / "human_adjudications/pending_adjudications.jsonl").write_text(pending)
    atomic_json(OUTPUT / "review_sampling/review_sampling_summary.json", {
        "schema_version": "bite.task_v_review_sampling_summary.v1",
        "total_candidate_cases": len(cases), "statistical": result["statistical"],
        "targeted": result["targeted"], "review_queue_union_count": result["queue_count"],
        "completed_human_judgments": 0, "human_status": "PENDING",
    })
    print(json.dumps({"status": "SUCCESS", "candidate_cases": len(cases), **result}, indent=2))


if __name__ == "__main__":
    main()
