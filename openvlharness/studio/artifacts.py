"""Run-scoped visual artifact persistence with safe, content-addressed IDs."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import mimetypes
import os
import re
import threading
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

_DATA_URL = re.compile(r"^data:([\w.+-]+/[\w.+-]+);base64,(.*)$", re.DOTALL)
_SAFE_ID = re.compile(r"^artifact_[0-9a-f]{64}$")
_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}


class ArtifactStore:
    """Extract large images from events and expose only run-scoped logical IDs."""

    def __init__(
        self, run_dir: Path, *, max_asset_bytes: int = 50 * 1024 * 1024
    ) -> None:
        self.run_dir = run_dir.resolve()
        self.root = (self.run_dir / "assets").resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.registry_path = self.run_dir / "artifacts.json"
        self.max_asset_bytes = max_asset_bytes
        self.registry: dict[str, dict[str, Any]] = {}
        self.aliases: dict[str, str] = {}
        self._lock = threading.Lock()
        self._persist()

    def _persist(self) -> None:
        payload = {
            "schema_version": "studio.artifacts.v1",
            "artifacts": self.registry,
            "aliases": self.aliases,
        }
        self.registry_path.write_text(
            json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
        )
        os.chmod(self.registry_path, 0o600)

    @staticmethod
    def _image_metadata(data: bytes) -> dict[str, Any]:
        try:
            with Image.open(BytesIO(data)) as image:
                return {
                    "width": image.width,
                    "height": image.height,
                    "format": image.format,
                }
        except (OSError, ValueError):
            return {}

    def _register_bytes(
        self,
        data: bytes,
        mime_type: str,
        *,
        source_agent_id: str,
        source_event_id: str,
        artifact_type: str,
        alias: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        if len(data) > self.max_asset_bytes:
            raise ValueError(f"Artifact exceeds {self.max_asset_bytes} bytes")
        digest = hashlib.sha256(data).hexdigest()
        artifact_id = f"artifact_{digest}"
        extension = (
            _EXTENSIONS.get(mime_type) or mimetypes.guess_extension(mime_type) or ".bin"
        )
        filename = digest + extension
        path = (self.root / filename).resolve()
        if path.parent != self.root:
            raise ValueError("Invalid artifact storage path")
        with self._lock:
            if artifact_id not in self.registry:
                path.write_bytes(data)
                os.chmod(path, 0o600)
                self.registry[artifact_id] = {
                    "artifact_id": artifact_id,
                    "run_id": self.run_dir.name,
                    "source_agent_id": source_agent_id,
                    "source_event_id": source_event_id,
                    "source_image_id": (metadata or {}).get("source_image_id"),
                    "frame_id": (metadata or {}).get("frame_id"),
                    "artifact_type": artifact_type,
                    "coordinate_system": (metadata or {}).get(
                        "coordinate_system", "source_pixels"
                    ),
                    "transform_metadata": (metadata or {}).get(
                        "transform_metadata", {}
                    ),
                    "content_digest": f"sha256:{digest}",
                    "storage_reference": f"assets/{filename}",
                    "mime_type": mime_type,
                    "size_bytes": len(data),
                    **self._image_metadata(data),
                }
            if alias:
                self.aliases[alias] = artifact_id
            self._persist()
        return artifact_id

    def register_file(
        self,
        path: str | Path,
        *,
        source_event_id: str,
        alias: str | None = None,
        source_agent_id: str = "orchestrator",
    ) -> str:
        source = Path(path).resolve(strict=True)
        if not source.is_file():
            raise ValueError("Input artifact is not a regular file")
        mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        return self._register_bytes(
            source.read_bytes(),
            mime_type,
            source_agent_id=source_agent_id,
            source_event_id=source_event_id,
            artifact_type="source_image",
            alias=alias,
        )

    def extract(
        self,
        value: Any,
        *,
        source_agent_id: str,
        source_event_id: str,
        key_hint: str = "",
    ) -> tuple[Any, list[str]]:
        """Replace embedded images and oversized opaque values with bounded references."""
        refs: list[str] = []
        if isinstance(value, dict):
            clean = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if lowered in {"pred_masks", "masks"} and isinstance(item, list):
                    clean[key] = {"encoding": "omitted_rle", "count": len(item)}
                    continue
                cleaned, nested = self.extract(
                    item,
                    source_agent_id=source_agent_id,
                    source_event_id=source_event_id,
                    key_hint=lowered,
                )
                clean[key] = cleaned
                refs.extend(nested)
            return clean, list(dict.fromkeys(refs))
        if isinstance(value, list):
            clean_list = []
            for item in value:
                cleaned, nested = self.extract(
                    item,
                    source_agent_id=source_agent_id,
                    source_event_id=source_event_id,
                    key_hint=key_hint,
                )
                clean_list.append(cleaned)
                refs.extend(nested)
            return clean_list, list(dict.fromkeys(refs))
        if isinstance(value, str):
            match = _DATA_URL.match(value.strip())
            is_b64_key = "base64" in key_hint or key_hint.endswith("_b64")
            if match or is_b64_key:
                mime_type = match.group(1) if match else "image/png"
                encoded = match.group(2) if match else value
                try:
                    data = base64.b64decode(encoded, validate=True)
                    artifact_id = self._register_bytes(
                        data,
                        mime_type,
                        source_agent_id=source_agent_id,
                        source_event_id=source_event_id,
                        artifact_type="tool_visual_output",
                    )
                    return {"artifact_ref": artifact_id}, [artifact_id]
                except (ValueError, base64.binascii.Error):
                    return {
                        "redacted_invalid_embedded_data": True,
                        "characters": len(value),
                    }, []
            if len(value) > 8192:
                digest = hashlib.sha256(value.encode()).hexdigest()
                return {
                    "omitted_large_value": True,
                    "characters": len(value),
                    "content_digest": f"sha256:{digest}",
                }, []
        return copy.deepcopy(value), []

    def resolve(self, artifact_id: str) -> tuple[Path, dict[str, Any]]:
        if not _SAFE_ID.fullmatch(artifact_id):
            raise KeyError(artifact_id)
        record = self.registry.get(artifact_id)
        if record is None:
            raise KeyError(artifact_id)
        path = (self.run_dir / record["storage_reference"]).resolve()
        if path.parent != self.root or path.is_symlink() or not path.is_file():
            raise KeyError(artifact_id)
        return path, copy.deepcopy(record)

    @classmethod
    def load(cls, run_dir: Path) -> ArtifactStore:
        instance = cls.__new__(cls)
        instance.run_dir = run_dir.resolve()
        instance.root = (instance.run_dir / "assets").resolve()
        instance.registry_path = instance.run_dir / "artifacts.json"
        instance.max_asset_bytes = 50 * 1024 * 1024
        payload = json.loads(instance.registry_path.read_text(encoding="utf-8"))
        instance.registry = payload.get("artifacts", {})
        instance.aliases = payload.get("aliases", {})
        instance._lock = threading.Lock()
        return instance
