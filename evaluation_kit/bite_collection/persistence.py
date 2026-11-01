"""Atomic, content-addressed persistence for snapshots and branch envelopes."""

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .budget import experimental_expenditure
from .schemas import validate_branch, validate_snapshot


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(handle, "w") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _externalize(record, snapshot_path):
    record = copy.deepcopy(record)
    registry = record["memory"]["state"]["images"]["registry"]
    artifact_dir = snapshot_path.parent / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for entry in registry.values():
        data_url = entry.get("data_url")
        if not isinstance(data_url, str) or not data_url.startswith("data:") or "," not in data_url:
            continue
        header, encoded = data_url.split(",", 1)
        raw = base64.b64decode(encoded)
        sha = hashlib.sha256(raw).hexdigest()
        suffix = ".png" if "png" in header else ".jpg" if "jpeg" in header else ".bin"
        artifact_path = artifact_dir / (sha + suffix)
        if not artifact_path.exists():
            artifact_path.write_bytes(raw)
        entry["data_url"] = {"artifact_path": str(artifact_path.relative_to(snapshot_path.parent)),
                             "sha256": sha, "data_url_header": header}
    return record


def save_snapshot(snapshot, path):
    path = Path(path)
    record = _externalize(snapshot.record, path)
    validate_snapshot(record)
    atomic_json(path, record)
    return path


def hydrate_snapshot_record(path):
    path = Path(path)
    record = json.loads(path.read_text())
    registry = record["memory"]["state"]["images"]["registry"]
    for entry in registry.values():
        ref = entry.get("data_url")
        if not isinstance(ref, dict) or "artifact_path" not in ref:
            continue
        artifact = path.parent / ref["artifact_path"]
        raw = artifact.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ValueError("Snapshot image artifact digest mismatch")
        entry["data_url"] = ref["data_url_header"] + "," + base64.b64encode(raw).decode("ascii")
    return record


def save_collection(output_dir, snapshot, branch_records, *, design):
    output = Path(output_dir)
    snapshot_path = output / "snapshots" / (snapshot.record["snapshot_id"].replace(":", "_") + ".json")
    save_snapshot(snapshot, snapshot_path)
    branch_paths = []
    for record in branch_records:
        validate_branch(record)
        path = output / "branches" / (record["branch_id"].replace(":", "_") + ".json")
        persisted = copy.deepcopy(record)
        artifact_dir = output / "observations" / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        for artifact in persisted["resulting_artifacts"]:
            data_url = artifact.get("data_url")
            if not isinstance(data_url, str) or not data_url.startswith("data:") or "," not in data_url:
                continue
            header, encoded = data_url.split(",", 1)
            raw = base64.b64decode(encoded)
            sha = hashlib.sha256(raw).hexdigest()
            suffix = ".png" if "png" in header else ".jpg" if "jpeg" in header else ".bin"
            artifact_path = artifact_dir / (sha + suffix)
            if not artifact_path.exists():
                artifact_path.write_bytes(raw)
            artifact["data_url"] = None
            artifact["content_reference"] = {
                "path": str(artifact_path), "sha256": sha, "mime_type": header[5:].split(";", 1)[0],
            }
        atomic_json(path, persisted)
        branch_paths.append(str(path))
    manifest = {
        "schema_version": "bite.collection_manifest.v1", "status": "complete",
        "snapshot": str(snapshot_path), "branches": branch_paths, "selection_design": design,
        "branch_count": len(branch_records),
        "prefix_cost_for_each_hypothetical_path": snapshot.record["prefix_logical_cost"],
        "actual_continuation_expenditure": experimental_expenditure(branch_records),
        "offline_gt_used": False,
    }
    atomic_json(output / "manifests" / "collection_manifest.json", manifest)
    return manifest
