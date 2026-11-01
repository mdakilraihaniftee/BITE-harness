"""Exact held-out overlap and review-only perceptual duplicate candidates."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from .split_integrity import audit_partitions


def difference_hash(path, size=8):
    with Image.open(path) as image:
        resized = image.convert("L").resize((size + 1, size))
        pixels = list(resized.get_flattened_data())
    bits = []
    for row in range(size):
        offset = row * (size + 1)
        bits.extend(pixels[offset + column] > pixels[offset + column + 1] for column in range(size))
    value = sum(int(bit) << index for index, bit in enumerate(bits))
    return f"{value:0{size * size // 4}x}"


def hamming_distance(left, right):
    return (int(left, 16) ^ int(right, 16)).bit_count()


def audit_train_against_heldout(train_entries, heldout_entries, *, perceptual=False,
                                near_threshold=4, max_candidates=10000):
    train = [{**entry, "partition": "candidate_train"} for entry in train_entries]
    heldout = [{**entry, "partition": entry.get("partition", "heldout_reference")} for entry in heldout_entries]
    exact_audit = audit_partitions(train + heldout)
    exact = [finding for finding in exact_audit["overlaps"]
             if "candidate_train" in finding["partitions"] and len(finding["partitions"]) > 1
             and finding["kind"] in {"image_sha256", "image_path", "source_image_id", "scene_id", "source_parent_id"}]
    near = []
    if perceptual:
        train_hashes = [(entry, difference_hash(entry["image_path"])) for entry in train if Path(entry.get("image_path", "")).is_file()]
        held_hashes = [(entry, difference_hash(entry["image_path"])) for entry in heldout if Path(entry.get("image_path", "")).is_file()]
        for train_entry, train_hash in train_hashes:
            for held_entry, held_hash in held_hashes:
                distance = hamming_distance(train_hash, held_hash)
                if distance <= near_threshold:
                    near.append({
                        "train_entry_id": train_entry["entry_id"], "heldout_entry_id": held_entry["entry_id"],
                        "distance": distance, "threshold": near_threshold,
                        "status": "review_required_quarantined", "identity_confirmed": False,
                    })
                    if len(near) > max_candidates:
                        raise ValueError("Near-duplicate candidate count exceeds review safety limit")
    quarantine = sorted({entry_id for finding in exact for entry_id in finding["entry_ids"] if any(
        item["entry_id"] == entry_id for item in train)} | {item["train_entry_id"] for item in near})
    return {
        "schema_version": "bite.heldout_overlap_audit.v1",
        "exact_overlap_findings": exact, "near_duplicate_method": "dhash64" if perceptual else "not_run",
        "near_duplicate_candidates": near,
        "near_duplicate_semantics": "candidate for manual review; not asserted identity",
        "quarantined_train_entry_ids": quarantine,
        "approved_disjoint": not exact and not near,
        "full_exact_audit": exact_audit,
    }
