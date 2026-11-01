"""Independent branch restoration from a frozen collection snapshot."""

import copy
from dataclasses import dataclass, field

from .snapshot import canonical_digest, capability_identity, restore_memory


@dataclass
class BranchState:
    branch_id: str
    parent_snapshot_id: str
    parent_state_digest: str
    memory: object
    capabilities: dict
    task: dict
    source_group_id: str
    source_image_sha256: str
    prefix_cost: int
    native_history: list | None
    actions: list = field(default_factory=list)
    observations: list = field(default_factory=list)
    candidates: list = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    branch_cost: int = 0
    errors: list = field(default_factory=list)

    def state_digest(self):
        from .snapshot import serialize_memory
        return canonical_digest({
            "memory": serialize_memory(self.memory), "actions": self.actions,
            "observations": self.observations, "candidates": self.candidates,
            "provenance": self.provenance, "branch_cost": self.branch_cost,
        })


def clone_snapshot(snapshot, *, branch_id, capabilities=None):
    record = snapshot.record
    if record["snapshot_completeness"] != "tool_execution_complete":
        raise ValueError("Cannot execute a branch from an incomplete snapshot")
    selected = capabilities or snapshot.capabilities
    if capability_identity(selected) != record["execution_context"]["capabilities"]:
        raise ValueError("Branch capability registry differs from frozen state")
    return BranchState(
        branch_id=branch_id, parent_snapshot_id=record["snapshot_id"],
        parent_state_digest=record["state_digest"], memory=restore_memory(record["memory"]),
        capabilities=selected, task=copy.deepcopy(record["task"]),
        source_group_id=record["source_group_id"], source_image_sha256=record["source_image_sha256"],
        prefix_cost=record["prefix_logical_cost"], native_history=copy.deepcopy(record["native_history"]),
        actions=copy.deepcopy(record["previous_actions"]), observations=copy.deepcopy(record["previous_observations"]),
        candidates=copy.deepcopy(record["candidate_history"]), provenance=copy.deepcopy(record["provenance"]),
    )
