"""Freeze and restore complete tool-executable memory snapshots."""

import base64
import copy
from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path

from openvlharness.memory.store import MemoryStore
from openvlharness.memory.run_state import (
    BindingDescriptor, BindingsState, FieldDescriptor, ImagesState, MemoryRunState, UrlsState,
)

from .schemas import SNAPSHOT_VERSION, validate_snapshot


def canonical_digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _encode(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    if isinstance(value, set):
        return {"__set__": [_encode(v) for v in sorted(value)]}
    if isinstance(value, bytes):
        return {"__bytes__": base64.b64encode(value).decode("ascii")}
    if hasattr(value, "dtype") and hasattr(value, "shape") and hasattr(value, "tolist"):
        return {"__ndarray__": _encode(value.tolist()), "dtype": str(value.dtype), "shape": list(value.shape)}
    if is_dataclass(value):
        return _encode(asdict(value))
    raise TypeError(f"Unsupported snapshot value: {type(value).__name__}")


def _decode(value):
    if isinstance(value, list):
        return [_decode(v) for v in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"__set__"}:
        return set(_decode(value["__set__"]))
    if set(value) == {"__bytes__"}:
        return base64.b64decode(value["__bytes__"])
    if "__ndarray__" in value:
        import numpy as np
        array = np.asarray(_decode(value["__ndarray__"]), dtype=value["dtype"])
        return array.reshape(value["shape"])
    return {k: _decode(v) for k, v in value.items()}


def serialize_memory(memory):
    state = memory.state
    return {
        "configuration": {
            "modules": list(memory.modules), "emit_policy": memory.emit_policy,
            "webpage_env_update_limit": memory.webpage_env_update_limit,
        },
        "state": {
            "images": _encode(state.images), "bindings": _encode(state.bindings),
            "urls": _encode(state.urls), "scratch": {},
        },
    }


def _descriptor(value):
    return BindingDescriptor(
        key=value.get("key", ""), source_tool=value.get("source_tool", ""),
        source_args=value.get("source_args", {}),
        fields={key: FieldDescriptor(**field) for key, field in value.get("fields", {}).items()},
    )


def restore_memory(payload):
    config = payload["configuration"]
    memory = MemoryStore(**config)
    raw = _decode(payload["state"])
    images = ImagesState(**raw["images"])
    bindings_raw = raw["bindings"]
    bindings = BindingsState(
        bindings=bindings_raw["bindings"], binding_counters=bindings_raw["binding_counters"],
        descriptors={key: _descriptor(value) for key, value in bindings_raw["descriptors"].items()},
        last_descriptors_count=bindings_raw["last_descriptors_count"],
    )
    urls = UrlsState(**raw["urls"])
    memory.state = MemoryRunState(images=images, bindings=bindings, urls=urls, scratch={})
    return memory


def _image_facts(memory):
    facts = []
    for image_id, entry in memory.state.images.registry.items():
        data_url = entry.get("data_url")
        sha = None
        mime = None
        width = height = None
        if isinstance(data_url, str) and data_url.startswith("data:") and "," in data_url:
            header, encoded = data_url.split(",", 1)
            raw = base64.b64decode(encoded)
            sha = hashlib.sha256(raw).hexdigest()
            mime = header[5:].split(";", 1)[0]
            from io import BytesIO
            from PIL import Image
            with Image.open(BytesIO(raw)) as image:
                width, height = image.size
        facts.append({"image_id": image_id, "sha256": sha, "mime_type": mime,
                      "width": width, "height": height,
                      "source": entry.get("source"), "aliases": sorted(entry.get("aliases", [])),
                      "has_local_pixels": sha is not None, "url": entry.get("url")})
    return facts


def capability_identity(capabilities):
    return {
        name: {
            "public_name": capability.name, "backend": capability.backend,
            "concrete_name": capability.concrete_name,
            "schema_digest": canonical_digest(capability.public_schema()),
            "service_config_digest": canonical_digest(_encode(capability.service_config)),
        }
        for name, capability in sorted(capabilities.items())
    }


class FrozenSnapshot:
    """Immutable-by-convention manifest plus private independently restorable payload."""

    def __init__(self, record, capabilities=None):
        validate_snapshot(record)
        self._record = copy.deepcopy(record)
        self.capabilities = capabilities or {}

    @property
    def record(self):
        return copy.deepcopy(self._record)


def freeze_state(
    memory, *, task, source_group_id, source_image_sha256, capabilities,
    previous_actions=(), previous_observations=(), candidate_history=(), provenance=None,
    prefix_logical_cost=0, native_history=None, allowed_action_types=None,
):
    """Freeze a real MemoryStore; no observer reconstruction is accepted."""
    if not isinstance(memory, MemoryStore):
        raise TypeError("freeze_state requires a live MemoryStore")
    memory_payload = serialize_memory(copy.deepcopy(memory))
    if not source_image_sha256 or len(source_image_sha256) != 64:
        raise ValueError("A verified source image SHA-256 is required")
    local_images = _image_facts(memory)
    roots = [item for item in local_images if item["image_id"] == task.get("root_image_id", "input_image_1")]
    if len(roots) != 1 or roots[0]["sha256"] != source_image_sha256:
        raise ValueError("Frozen root image does not match the declared source SHA-256")
    missing = [item["image_id"] for item in local_images if not item["has_local_pixels"]]
    completeness = "tool_execution_complete" if not missing else "incomplete"
    limits = [] if not missing else ["Images without locally frozen bytes: " + ", ".join(missing)]
    limits.append("Provider-native history is preserved but controlled tool actions do not extend it")
    limits.append("Complete VLM-continuation cloning is unavailable in collection_state.v1")
    content = {
        "schema_version": SNAPSHOT_VERSION,
        "task": copy.deepcopy(task), "source_group_id": source_group_id,
        "source_image_sha256": source_image_sha256,
        "prefix_action_count": len(previous_actions), "prefix_logical_cost": prefix_logical_cost,
        "allowed_action_types": list(allowed_action_types or [
            "root_grounding", "repeated_grounding", "crop_generation", "focused_grounding",
        ]),
        "memory": memory_payload,
        "execution_context": {"capabilities": capability_identity(capabilities), "image_facts": local_images},
        "previous_actions": _encode(list(previous_actions)),
        "previous_observations": _encode(list(previous_observations)),
        "candidate_history": _encode(list(candidate_history)),
        "provenance": _encode(provenance or {"nodes": [], "edges": [], "crop_frames": {}}),
        "native_history": _encode(native_history) if native_history is not None else None,
        "history_mode": "preserved_not_extended" if native_history is not None else "unavailable",
        "snapshot_completeness": completeness, "capture_complete": completeness == "tool_execution_complete",
        "limitations": limits,
    }
    digest = canonical_digest(content)
    record = {"snapshot_id": "snapshot:" + digest, "state_digest": digest, **content}
    return FrozenSnapshot(record, capabilities=capabilities)


def load_snapshot(path, *, capabilities):
    from .persistence import hydrate_snapshot_record
    record = hydrate_snapshot_record(path)
    snapshot = FrozenSnapshot(record, capabilities=capabilities)
    expected = snapshot.record
    state_digest = expected.pop("state_digest")
    expected.pop("snapshot_id")
    if canonical_digest(expected) != state_digest:
        raise ValueError("Snapshot digest mismatch")
    if capability_identity(capabilities) != record["execution_context"]["capabilities"]:
        raise ValueError("Runtime capabilities do not match the frozen execution context")
    return snapshot
