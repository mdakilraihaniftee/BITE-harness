"""GT-free deterministic source-class query scheduling."""

from __future__ import annotations

import hashlib


def schedule_queries(source_group_id, available_verified_classes, *, requested_count=2, seed=417):
    if not source_group_id:
        raise ValueError("source_group_id is required")
    if not isinstance(requested_count, int) or requested_count < 0:
        raise ValueError("requested_count must be a nonnegative integer")
    unique = {}
    for value in available_verified_classes:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Available classes must be nonempty strings")
        unique.setdefault(value.strip().casefold(), value.strip())
    available = sorted(unique.values(), key=str.casefold)
    scheduled_count = min(requested_count, len(available))
    ranked = sorted(available, key=lambda name: hashlib.sha256(
        f"{seed}:{source_group_id}:{name.casefold()}".encode()).hexdigest())
    return {
        "schema_version": "bite.query_schedule.v2", "source_group_id": source_group_id,
        "seed": seed, "requested_classes_per_group": requested_count,
        "available_verified_classes": available, "scheduled_count": scheduled_count,
        "queries": ranked[:scheduled_count],
        "selection_rule": "lowest sha256(seed:source_group_id:casefolded_class)",
        "gt_presence_used": False, "fabricated_classes": False,
    }
