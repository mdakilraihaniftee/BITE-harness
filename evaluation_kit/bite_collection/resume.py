"""Content-verified, atomic resume ledger for dataset-wide collection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .persistence import atomic_json
from .snapshot import canonical_digest


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ResumeLedger:
    def __init__(self, run_dir, configuration, *, resume=False):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.run_dir / "run_configuration.json"
        self.config_digest = canonical_digest(configuration)
        payload = {"configuration": configuration, "configuration_sha256": self.config_digest}
        if self.config_path.exists():
            previous = json.loads(self.config_path.read_text())
            if previous != payload:
                raise ValueError("Resume run configuration mismatch")
            if not resume:
                raise FileExistsError("Collection run already exists; pass --resume")
        else:
            atomic_json(self.config_path, payload)
        self.resume = resume

    def state_dir(self, state_id):
        return self.run_dir / "states" / state_id.replace(":", "_")

    def inspect(self, state_id):
        state_dir = self.state_dir(state_id)
        marker = state_dir / "completion.json"
        if not marker.exists():
            partial = state_dir.exists() and any(state_dir.iterdir())
            return {"status": "partial_requires_explicit_new_execution" if partial else "pending",
                    "state_dir": str(state_dir)}
        record = json.loads(marker.read_text())
        for relative, expected in record.get("content_sha256", {}).items():
            path = state_dir / relative
            if not path.is_file() or file_digest(path) != expected:
                return {"status": "corrupt", "state_dir": str(state_dir), "corrupt_path": str(path)}
        if record.get("configuration_sha256") != self.config_digest:
            return {"status": "corrupt", "state_dir": str(state_dir), "reason": "configuration_digest_mismatch"}
        return {"status": "complete", "state_dir": str(state_dir), "record": record}

    def mark_raw(self, state_id, paths, metadata):
        state_dir = self.state_dir(state_id)
        state_dir.mkdir(parents=True, exist_ok=True)
        content = {str(Path(path).resolve().relative_to(state_dir.resolve())): file_digest(path) for path in paths}
        record = {
            "schema_version": "bite.collection_state_completion.v1", "state_id": state_id,
            "configuration_sha256": self.config_digest, "raw_persisted": True,
            "offline_labels_complete": False, "content_sha256": content, **metadata,
        }
        atomic_json(state_dir / "raw_completion.json", record)
        return record

    def complete(self, state_id, raw_record, label_paths, metadata):
        state_dir = self.state_dir(state_id)
        content = dict(raw_record["content_sha256"])
        content.update({str(Path(path).resolve().relative_to(state_dir.resolve())): file_digest(path) for path in label_paths})
        record = {**raw_record, "offline_labels_complete": True, "content_sha256": content, **metadata}
        atomic_json(state_dir / "completion.json", record)
        return record

