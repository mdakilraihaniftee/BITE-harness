"""GT-free helpers for starting collection states and recording prefix evidence."""

import base64
import hashlib

from openvlharness.memory.store import MemoryStore

from .cloning import BranchState
from .executor import execute_action


def source_image_identity(memory, image_id="input_image_1"):
    entry = memory.state.images.registry.get(image_id)
    if not entry or not isinstance(entry.get("data_url"), str):
        raise ValueError("Original image bytes are not registered")
    raw = base64.b64decode(entry["data_url"].split(",", 1)[1])
    return hashlib.sha256(raw).hexdigest()


def new_memory(question, *, modules=("image", "tool_context", "url"), emit_policy="always"):
    memory = MemoryStore(modules=modules, emit_policy=emit_policy)
    memory.start(question)
    return memory


def execute_prefix(memory, capabilities, *, task, source_group_id, source_image_sha256, actions):
    """Create the shared prefix with the same public capability path used by branches."""
    state = BranchState(
        branch_id="prefix", parent_snapshot_id="pre_freeze", parent_state_digest="pre_freeze",
        memory=memory, capabilities=capabilities, task=task, source_group_id=source_group_id,
        source_image_sha256=source_image_sha256, prefix_cost=0, native_history=None,
        provenance={"nodes": [], "edges": [], "crop_frames": {}},
    )
    for action in actions:
        result = execute_action(state, action)
        if not result.get("dispatched"):
            raise RuntimeError("Prefix action did not reach the capability dispatch boundary")
    return state
