#!/usr/bin/env python3
"""Freeze the Phase 4C-1G Protocol A counting probe (no model calls, no labels).

Writes, under outputs/bite/phase04c1g/:

* protocol/        the prompt template, parser, renderer, selector and decision-rule contracts, and the analysis plan
* task_manifest/   the 101 frozen counting tasks (GT-blind) and the pre-call feature table
* branch_inputs/   reproducibility digests and size statistics for the B0/B1 inputs (B2/B3 need semantic outputs)
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from evaluation_kit.bite_calibration.branch_evidence_renderer import (
    render_branch,
    renderer_contract,
)
from evaluation_kit.bite_calibration.learnable_headroom import SELECTOR_SPEC
from evaluation_kit.bite_calibration.oracle_headroom import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    COST_CONVENTION,
    LAMBDA_GRID,
)
from evaluation_kit.bite_calibration.semantic_observation_schema import canonical_sha256
from evaluation_kit.bite_calibration.task_level_decision_analysis import DECISION_RULE
from evaluation_kit.bite_calibration.task_level_probe_protocol import (
    ANSWER_PARSER,
    BRANCH_EVIDENCE,
    INCREMENTAL_LOGICAL_COST,
    PARSER_SHA256,
    PROMPT_SHA256,
    PROMPT_TEMPLATE,
    PROTOCOL_LABEL,
    build_task_manifest,
    verify_task_manifest,
)
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = "outputs/bite/phase04b2b3/expansion/aquarium_task_v_expansion_seed418_g30"
SEMANTIC_MANIFEST = "outputs/bite/phase04c1e/semantic_pilot_manifest/manifest.json"


def analysis_plan():
    return {
        "schema_version": "bite.phase04c1g_analysis_plan.v1",
        "frozen_before_final_answer_data": True,
        "protocol": PROTOCOL_LABEL,
        "primary_metric": "exact-count accuracy; invalid answers count as incorrect",
        "secondary_metric": "presence accuracy derived from the parsed count (count > 0)",
        "strata_reported": ["official count zero", "official count positive", "query class"],
        "oracle": {
            "branch_set": ["B0", "B1", "B2", "B3"], "single_action_set": ["B0", "B1", "B2"],
            "statistics": ["best fixed branch (hindsight)", "per-case hindsight oracle", "oracle adaptivity gap",
                           "single-action oracle", "combined-evidence oracle gap", "budget-adjusted versions"],
            "lambda_grid": list(LAMBDA_GRID), "cost_convention": COST_CONVENTION,
            "incremental_logical_cost": INCREMENTAL_LOGICAL_COST,
        },
        "selectors": SELECTOR_SPEC,
        "uncertainty": {"method": "paired percentile source-group bootstrap", "seed": BOOTSTRAP_SEED,
                        "replicates": BOOTSTRAP_REPLICATES, "unit": "source group",
                        "candidate_rows_resampled_iid": False, "refit_inside_bootstrap": False},
        "influence": "leave-one-source-group-out recomputation (selections held fixed)",
        "decision_rule": DECISION_RULE,
        "label_source": ("official Aquarium COCO annotations of the calibration-fit image, opened through "
                         "AquariumDatasetAdapter.load_offline_ground_truth only after raw-table finalization"),
        "count_definition": "number of annotations whose category name equals the queried class (all iscrowd values)",
        "not_planned": ["order-reversed B3 (needs separate budget)",
                        "P4 direct VLM selector (needs separate authorization)", "any additional task family"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/bite/phase04c1g")
    args = parser.parse_args()
    out = args.output
    semantic_manifest = json.loads((ROOT / SEMANTIC_MANIFEST).read_text())
    contract = renderer_contract()
    manifest = verify_task_manifest(build_task_manifest(
        semantic_manifest, root=ROOT, run_dir=RUN_DIR, semantic_manifest_path=SEMANTIC_MANIFEST,
        renderer_contract=contract))
    again = build_task_manifest(semantic_manifest, root=ROOT, run_dir=RUN_DIR,
                                semantic_manifest_path=SEMANTIC_MANIFEST, renderer_contract=contract)
    if again["manifest_sha256"] != manifest["manifest_sha256"]:
        raise SystemExit("Task manifest construction is not deterministic")
    atomic_json(out / "task_manifest/task_manifest.json", manifest)
    with (out / "task_manifest/precall_features.jsonl").open("w") as stream:
        for task in manifest["tasks"]:
            stream.write(json.dumps({"task_id": task["task_id"], "source_group_id": task["source_group_id"],
                                     "query": task["query"], "features": task["precall_features"]},
                                    sort_keys=True) + "\n")
    atomic_json(out / "protocol/prompt_template.json", {**PROMPT_TEMPLATE, "prompt_sha256": PROMPT_SHA256})
    atomic_json(out / "protocol/answer_parser.json", {**ANSWER_PARSER, "parser_sha256": PARSER_SHA256})
    atomic_json(out / "protocol/renderer_contract.json", contract)
    plan = analysis_plan()
    plan["analysis_plan_sha256"] = canonical_sha256(plan)
    atomic_json(out / "protocol/analysis_plan.json", plan)

    rows = []
    for task in manifest["tasks"]:
        for branch in ("B0", "B1"):
            _, first = render_branch(task, branch, root=ROOT)
            _, second = render_branch(task, branch, root=ROOT)
            if first["messages_sha256"] != second["messages_sha256"]:
                raise SystemExit(f"Rendering not deterministic for {task['task_id']} {branch}")
            rows.append({"task_id": task["task_id"], "branch": branch, "messages_sha256": first["messages_sha256"],
                         "common_header_sha256": first["common_header_sha256"],
                         "common_footer_sha256": first["common_footer_sha256"],
                         "evidence_characters": first["evidence_characters"], "image_count": first["image_count"],
                         "tool_calls_rendered": first["tool_calls_rendered"]})
    (out / "branch_inputs").mkdir(parents=True, exist_ok=True)
    with (out / "branch_inputs/b0_b1_render_digests.jsonl").open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    common_identical = all(
        a["common_header_sha256"] == b["common_header_sha256"] and a["common_footer_sha256"] == b["common_footer_sha256"]
        for a, b in zip(rows[::2], rows[1::2]))
    sizes = {b: [r["evidence_characters"] for r in rows if r["branch"] == b] for b in ("B0", "B1")}
    summary = {
        "schema_version": "bite.phase04c1g_preparation.v1",
        "protocol": PROTOCOL_LABEL,
        "task_manifest_sha256": manifest["manifest_sha256"],
        "task_count": len(manifest["tasks"]),
        "source_group_count": manifest["population"]["source_group_count"],
        "prompt_sha256": PROMPT_SHA256, "parser_sha256": PARSER_SHA256,
        "renderer_sha256": contract["renderer_sha256"],
        "analysis_plan_sha256": plan["analysis_plan_sha256"],
        "branch_evidence": {b: list(v) for b, v in BRANCH_EVIDENCE.items()},
        "b0_b1_rendered_deterministically": True,
        "common_header_and_footer_identical_across_b0_b1": common_identical,
        "evidence_characters": {b: {"median": statistics.median(v), "maximum": max(v)} for b, v in sizes.items()},
        "b2_b3_rendered": False,
        "b2_b3_reason": "semantic_region_inspect_v1 outputs do not exist yet (4C-1F pilot not executed)",
        "model_calls": 0,
        "offline_labels_accessed": False,
    }
    atomic_json(out / "task_manifest/preparation_summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
