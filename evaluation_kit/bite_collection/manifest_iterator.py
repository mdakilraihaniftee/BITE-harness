"""Deterministic source-group iteration over a frozen calibration manifest."""

from __future__ import annotations

import hashlib
from dataclasses import asdict

from .snapshot import canonical_digest


def _rank(seed, *parts):
    return hashlib.sha256(":".join([str(seed), *map(str, parts)]).encode()).hexdigest()


def select_states(adapter, *, seed=417, max_groups=20, max_queries=2):
    if not 0 <= max_groups <= 20:
        raise ValueError("Pilot source-group cap is 20")
    if not 0 <= max_queries <= 2:
        raise ValueError("Pilot query cap is two per source group")
    grouped = {}
    for entry in adapter.entries():
        grouped.setdefault(entry.source_group_id, []).append(entry)
    selected_groups = sorted(grouped, key=lambda group: (_rank(seed, group), group))[:max_groups]
    states = []
    for group_index, group in enumerate(selected_groups):
        representatives = sorted(grouped[group], key=lambda entry: (_rank(seed, group, entry.image_sha256), entry.entry_id))
        entry = representatives[0]
        for query_index, query in enumerate(entry.queries[:max_queries]):
            state_id = "task_v_state:" + canonical_digest({
                "manifest": adapter.manifest["manifest_sha256"], "seed": seed,
                "group": group, "entry": entry.entry_id, "image_sha256": entry.image_sha256,
                "query": query,
            })
            states.append({
                "state_id": state_id, "group_index": group_index, "query_index": query_index,
                "entry": asdict(entry), "query": query, "is_canary_group": group_index < 2,
            })
    return {
        "schema_version": "bite.task_v_sample_selection.v1",
        "manifest_sha256": adapter.manifest["manifest_sha256"], "partition": adapter.allowed_partition,
        "seed": seed, "max_source_groups": max_groups, "max_queries_per_group": max_queries,
        "selection_rule": "lowest sha256(seed:source_group_id); representative lowest sha256(seed:group:image_sha256)",
        "selection_uses_ground_truth": False, "selection_uses_tool_outcomes": False,
        "source_groups": selected_groups, "source_group_count": len(selected_groups),
        "image_count": len({state["entry"]["entry_id"] for state in states}),
        "scheduled_query_count": len(states), "maximum_public_dispatches": len(states) * 4,
        "states": states,
    }

