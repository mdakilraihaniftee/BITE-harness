"""Frozen, design-based Task V expansion selection and action allocation."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict
from pathlib import Path

from .dataset_adapter import CLASSES
from .snapshot import canonical_digest

PROTOCOL_VERSION = "bite.task_v_expansion.v1"


def freeze_expansion_protocol(
    adapter, *, pilot_selection_path="outputs/bite/phase04b2b2/preflight/sample_selection_manifest.json",
    group_count=30, repeat_group_count=5, selection_seed=418, repeat_seed=419,
):
    if group_count != 30 or repeat_group_count != 5:
        raise ValueError("Task V expansion v1 is frozen to 30 groups and five repeat-control groups")
    pilot = json.loads(Path(pilot_selection_path).read_text())
    if pilot.get("manifest_sha256") != adapter.manifest["manifest_sha256"]:
        raise ValueError("Pilot and expansion source manifest identities differ")
    pilot_groups = set(pilot["source_groups"])
    grouped = {}
    for entry in adapter.entries():
        grouped.setdefault(entry.source_group_id, []).append(entry)
    eligible = sorted(set(grouped) - pilot_groups)
    if len(grouped) != 277 or len(pilot_groups) != 20 or len(eligible) != 257:
        raise ValueError("Unexpected calibration-fit expansion sampling frame")
    selected = random.Random(selection_seed).sample(eligible, group_count)
    repeat_groups = random.Random(repeat_seed).sample(selected, repeat_group_count)
    states = []
    for group_index, group in enumerate(selected):
        representative = min(grouped[group], key=lambda entry: (
            hashlib.sha256(f"{selection_seed}:{group}:{entry.image_sha256}".encode()).hexdigest(), entry.entry_id))
        for query_index, query in enumerate(CLASSES):
            state_id = "task_v_expansion_state:" + canonical_digest({
                "protocol": PROTOCOL_VERSION, "manifest": adapter.manifest["manifest_sha256"],
                "selection_seed": selection_seed, "group": group,
                "entry": representative.entry_id, "query": query,
            })
            states.append({
                "state_id": state_id, "group_index": group_index, "query_index": query_index,
                "entry": asdict(representative), "query": query, "permitted_classes": list(CLASSES),
                "is_canary_group": group_index < 2, "repeat_control_group": group in repeat_groups,
            })
    unsigned = {
        "schema_version": PROTOCOL_VERSION, "source_id": adapter.preflight["source_id"],
        "manifest_sha256": adapter.manifest["manifest_sha256"], "partition": "calibration_fit",
        "original_pilot_cohort": "bite.task_v_pilot.seed417.g20.v1",
        "cohort_id": "bite.task_v_expansion.seed418.g30.v1",
        "eligible_source_groups": eligible, "eligible_source_group_count": len(eligible),
        "excluded_original_pilot_groups": sorted(pilot_groups),
        "selected_source_groups": selected, "source_groups": selected, "source_group_count": group_count,
        "image_count": group_count, "states": states, "scheduled_query_count": len(states),
        "source_classes": list(CLASSES), "queries_per_group": 7,
        "selection_seed": selection_seed, "seed": selection_seed,
        "selection_rng": "python.random.Random(MT19937).sample_without_replacement",
        "group_inclusion_probability": group_count / len(eligible),
        "repeat_control_seed": repeat_seed, "repeat_control_groups": repeat_groups,
        "repeat_control_group_inclusion_probability": repeat_group_count / group_count,
        "repeat_runtime_eligibility": "candidate-present state with valid root geometry",
        "representative_rule": "lowest sha256(selection_seed:group:image_sha256), independent of GT and SAM outcomes",
        "query_policy": "all seven approved source-vocabulary classes per selected image",
        "query_distribution_target": "uniform scheduled Aquarium source-vocabulary queries, not naturally selected VLM queries",
        "selection_uses_ground_truth": False, "selection_uses_tool_outcomes": False,
        "branch_budget": 3, "prefix_dispatch_cap": 210, "zoom_focus_dispatch_cap": 420,
        "repeat_dispatch_cap": 35, "maximum_public_dispatches": 665,
        "action_policy": "Zoom→focused grounding for every eligible candidate; exact repeat only in frozen five-group control",
    }
    return {**unsigned, "protocol_sha256": canonical_digest(unsigned)}

