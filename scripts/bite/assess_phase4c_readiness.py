#!/usr/bin/env python3
"""Write the unfitted Phase 4C model specification and readiness decision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.model_specification import (
    phase4c_model_specification,
)
from evaluation_kit.bite_calibration.statistical_readiness import assess_readiness
from evaluation_kit.bite_collection.persistence import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04b2b4"))
    args = parser.parse_args()
    load = lambda path: json.loads(Path(path).read_text())
    integrity = load(args.output / "integrity/historical_artifact_verification.json")
    reviews = load(args.output / "validation/human_adjudication_validation.json")
    diagnostics = load(args.output / "diagnostics/conditional_evidence_summary.json")
    support = load("outputs/bite/phase04b2b3/analysis/task_v_support_summary.json")
    specification = phase4c_model_specification()
    readiness = assess_readiness(
        integrity=integrity, review_validation=reviews, diagnostics=diagnostics,
        support_summary=support,
    )
    atomic_json(args.output / "model_specification/phase4c_restricted_model_specification.json", specification)
    atomic_json(args.output / "readiness/phase4c_readiness.json", readiness)
    print(json.dumps(readiness, indent=2))


if __name__ == "__main__":
    main()
