"""Acquisition planning only; this module never downloads or accepts terms."""

from __future__ import annotations

from pathlib import Path


def acquisition_plan(source, destination):
    destination = Path(destination).resolve()
    archives = source.get("archives") or ([source["archive"]] if source.get("archive") else [])
    items = []
    for archive in archives:
        items.append({
            "url": archive["url"],
            "expected_bytes": archive["bytes"],
            "expected_sha256": archive.get("sha256"),
            "expected_etag": archive.get("etag"),
            "destination": str(destination / archive["destination_relative"]),
            "verification": "sha256" if archive.get("sha256") else "publisher_etag_and_local_sha256_record",
        })
    return {
        "schema_version": "bite.calibration_acquisition_plan.v1",
        "source_id": source["source_id"],
        "dry_run_only": True,
        "automatic_download_permitted": False,
        "terms_review_required": "license_review_required" in source.get("acquisition_status", []),
        "credentials_required": bool(source.get("license_access", {}).get("credentials_required")),
        "archives": items,
        "total_expected_bytes": sum(item["expected_bytes"] for item in items),
        "required_free_bytes_recommended": sum(item["expected_bytes"] for item in items) * 2,
        "next_step": "Review terms and approve exact archives; then download outside this tool and verify before extraction.",
    }
