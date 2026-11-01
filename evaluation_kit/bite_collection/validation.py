"""Collection consistency and scientific-isolation validation."""

import json
import re

from .schemas import validate_branch, validate_snapshot

_GT_KEY = re.compile(r"(^gt($|_)|ground_truth|offline_label|official_tp|annotation)", re.I)


def _no_gt(value, path="runtime"):
    if isinstance(value, dict):
        for key, child in value.items():
            if _GT_KEY.search(str(key)):
                raise ValueError(f"Offline GT field in collection runtime: {path}.{key}")
            _no_gt(child, path + "." + str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _no_gt(child, f"{path}[{index}]")


def validate_collection(snapshot_record, branches):
    validate_snapshot(snapshot_record)
    ids = set()
    expenditure = 0
    for branch in branches:
        validate_branch(branch)
        if branch["branch_id"] in ids:
            raise ValueError("Duplicate branch identity")
        ids.add(branch["branch_id"])
        if branch["parent_snapshot_id"] != snapshot_record["snapshot_id"]:
            raise ValueError("Branch parent snapshot mismatch")
        if branch["parent_state_digest"] != snapshot_record["state_digest"]:
            raise ValueError("Branch parent state digest mismatch")
        _no_gt(branch)
        json.dumps(branch, allow_nan=False)
        expenditure += branch["branch_cost"]
    return {"valid": True, "snapshot_id": snapshot_record["snapshot_id"],
            "branches": len(branches), "actual_continuation_expenditure": expenditure,
            "all_share_parent": True, "offline_gt_used": False}
