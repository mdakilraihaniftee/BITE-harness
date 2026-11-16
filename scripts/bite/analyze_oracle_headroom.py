#!/usr/bin/env python3
"""Phase 4C-1G post-collection analysis (written before any final-answer data).

Order: verify complete *live* four-branch run -> finalize and hash the GT-free
outcome table -> open official Aquarium annotations and count the queried class
-> join -> Stage A oracle headroom -> Stage B LOGO selectors -> transitions,
combined evidence and measured costs -> predeclared go/no-go screen.

Refuses to run (and opens no labels) when the live run is absent or incomplete.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation_kit.bite_calibration.learnable_headroom import learnable_headroom
from evaluation_kit.bite_calibration.oracle_headroom import oracle_headroom
from evaluation_kit.bite_calibration.task_level_branch_runner import (
    build_count_labels,
    finalize_outcomes,
    join_outcomes,
    load_count_labels,
    load_finalized,
    load_semantic_observations,
)
from evaluation_kit.bite_calibration.task_level_decision_analysis import (
    classify,
    combined_evidence,
    measured_costs,
    transitions,
)
from evaluation_kit.bite_calibration.task_level_probe_protocol import (
    BRANCHES,
    verify_task_manifest,
)
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
PHASE = ROOT / "outputs/bite/phase04c1g"
RUN = PHASE / "raw_continuations/branch_run"
SEMANTIC_RUN = ROOT / "outputs/bite/phase04c1f/raw_observations/semantic_pilot_run"
SEMANTIC_MANIFEST = ROOT / "outputs/bite/phase04c1e/semantic_pilot_manifest/manifest.json"


def _ground_truth_loader():
    from evaluation_kit.bite_collection.dataset_adapter import AquariumDatasetAdapter

    adapter = AquariumDatasetAdapter()
    entries = {entry.entry_id: entry for entry in adapter.entries()}
    return lambda entry_id: adapter.load_offline_ground_truth(entries[entry_id])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=RUN)
    args = parser.parse_args()
    manifest = verify_task_manifest(json.loads((PHASE / "task_manifest/task_manifest.json").read_text()))
    if not (args.run / "run_configuration.json").is_file():
        raise SystemExit("No live branch run exists; nothing analyzed and no labels opened")
    finalized, labels = PHASE / "finalized_outputs", PHASE / "offline_labels"
    if (finalized / "finalization.json").exists():
        record, outcome_rows = load_finalized(finalized)
    else:
        record, outcome_rows = finalize_outcomes(manifest, args.run, finalized, branches=BRANCHES, require_live=True)
    semantic, semantic_summary = load_semantic_observations(
        SEMANTIC_RUN, manifest, json.loads(SEMANTIC_MANIFEST.read_text()), require_live=True)
    if (labels / "count_labels.jsonl").exists():
        label_rows = load_count_labels(labels, finalized)
    else:
        label_rows = build_count_labels(manifest, finalized, labels, load_ground_truth=_ground_truth_loader())
    rows = join_outcomes(manifest, outcome_rows, label_rows)
    oracle = oracle_headroom(rows)
    learnable = learnable_headroom(rows)
    decision = classify(oracle, learnable, rows, executed=True)
    atomic_json(PHASE / "oracle_headroom/oracle_headroom.json", {k: v for k, v in oracle.items() if k != "bootstrap"})
    atomic_json(PHASE / "statistical_uncertainty/oracle_bootstrap.json", oracle["bootstrap"])
    atomic_json(PHASE / "learnable_headroom/learnable_headroom.json", learnable)
    atomic_json(PHASE / "decision_transitions/transitions.json", transitions(rows))
    atomic_json(PHASE / "decision_transitions/combined_evidence.json", combined_evidence(rows))
    atomic_json(PHASE / "costs/measured_costs.json", measured_costs(outcome_rows, manifest, semantic))
    atomic_json(PHASE / "costs/semantic_run_summary.json", semantic_summary)
    atomic_json(PHASE / "readiness/research_decision.json", decision)
    print(json.dumps({"finalized_table_sha256": record["table_sha256"], "outcome": decision["outcome"],
                      "zero_cost": oracle["zero_cost"], "branches": oracle["branches"]}, indent=2))


if __name__ == "__main__":
    main()
