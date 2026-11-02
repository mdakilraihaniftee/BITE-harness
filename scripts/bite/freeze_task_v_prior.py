#!/usr/bin/env python3
"""Fit and freeze the prespecified Task V annotation-proxy priors once on fit data."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from evaluation_kit.bite_calibration.frozen_prior_export import (
    build_frozen_priors,
    canonical_sha,
    validate_frozen_artifact,
)
from evaluation_kit.bite_calibration.prior_model import predict
from evaluation_kit.bite_calibration.proxy_calibration import load_proxy_records
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1c_revised"))
    args = parser.parse_args()
    paired = ROOT / "outputs/bite/phase04b2b4/diagnostics/expansion_paired_diagnostics.jsonl"
    cases = ROOT / "outputs/bite/phase04b2b4/review_interface/review_cases.jsonl"
    artifacts = build_frozen_priors(
        paired_path=paired,
        review_cases_path=cases,
        prior_model_path=ROOT / "evaluation_kit/bite_calibration/prior_model.py",
    )
    destination = args.output / "frozen_priors"
    index = {
        "schema_version": "bite.task_v_frozen_prior_index.v1",
        "status": "FROZEN_FIT_ONLY",
        "primary_model": "score_only_logistic",
        "artifacts": [],
        "calibration_validation_accessed": False,
        "internal_test_accessed": False,
    }
    for artifact in artifacts:
        validate_frozen_artifact(artifact)
        endpoint = artifact["endpoint"].split("_")[-1].replace(".", "_")
        name = f"{endpoint}_{artifact['model_name']}.json"
        path = destination / name
        atomic_json(path, artifact)
        reloaded = json.loads(path.read_text())
        validate_frozen_artifact(reloaded)
        records = load_proxy_records(
            paired, cases, endpoint=artifact["endpoint"].split("_")[-1], cohort_name="expansion",
        )
        replay = predict(reloaded["fit"], records)
        if canonical_sha(replay) != artifact["prediction_reproducibility"]["fit_predictions_sha256"]:
            raise RuntimeError("Serialized prior failed deterministic prediction replay")
        index["artifacts"].append({
            "path": str(path),
            "endpoint": artifact["endpoint"],
            "model_name": artifact["model_name"],
            "role": artifact["model_role"],
            "model_payload_sha256": artifact["serialized_model_payload_sha256"],
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    atomic_json(destination / "index.json", index)
    print(json.dumps(index, indent=2))


if __name__ == "__main__":
    main()
