"""Run independent selected action paths from one frozen prefix."""

import copy

from .budget import path_cost
from .cloning import clone_snapshot
from .eligibility import validate_step
from .executor import execute_action
from .schemas import COLLECTION_VERSION, validate_branch
from .snapshot import canonical_digest


class BranchRunner:
    def __init__(self, snapshot, *, collection_run_id, eligible_actions, ineligible_actions, branch_budget=3):
        self.snapshot = snapshot
        self.collection_run_id = collection_run_id
        self.eligible_actions = copy.deepcopy(eligible_actions)
        self.ineligible_actions = copy.deepcopy(ineligible_actions)
        self.branch_budget = branch_budget

    def run(self, selection, *, branch_index=0):
        path = copy.deepcopy(selection["path"])
        branch_id = "branch:" + canonical_digest({
            "run": self.collection_run_id, "snapshot": self.snapshot.record["snapshot_id"],
            "design": selection["selection_design"], "path": path, "index": branch_index,
        })
        branch = clone_snapshot(self.snapshot, branch_id=branch_id)
        prefix_count = len(branch.actions)
        selected_steps = []
        status = "complete"
        capture_complete = True
        last_crop = None
        for raw_step in path["steps"]:
            step = copy.deepcopy(raw_step)
            if step["arguments"].get("image_id") == "$last_crop":
                if last_crop is None:
                    branch.errors.append({"action_id": step["action_id"], "reason": "failed_prerequisite_action"})
                    status, capture_complete = "partial", False
                    break
                step["arguments"]["image_id"] = last_crop
            remaining = self.branch_budget - branch.branch_cost
            ok, reason = validate_step(step, branch, remaining_budget=remaining)
            if not ok:
                branch.errors.append({"action_id": step["action_id"], "reason": reason})
                status, capture_complete = "partial", False
                break
            result = execute_action(branch, step, remaining_budget=remaining)
            selected_steps.append(result["recorded_action"] if result.get("recorded_action") else step)
            crop = ((result.get("observation") or {}).get("crop") or {})
            if crop.get("child_image_id"):
                last_crop = crop["child_image_id"]
            if not result.get("dispatched"):
                status, capture_complete = "partial", False
                break
        continuation_observations = branch.observations[len(self.snapshot.record["previous_observations"]):]
        continuation_candidates = [candidate for candidate in branch.candidates
                                   if candidate.get("source_observation_id") in {
                                       item.get("joint_observation_id") for item in continuation_observations}]
        candidate_rows = []
        for candidate in continuation_candidates:
            observation = next(item for item in continuation_observations
                               if item["joint_observation_id"] == candidate["source_observation_id"])
            action = next(item for item in selected_steps if item.get("observation_id") == observation["joint_observation_id"])
            candidate_rows.append({
                "candidate": copy.deepcopy(candidate), "joint_observation_id": observation["joint_observation_id"],
                "action": copy.deepcopy(action),
                "outcome": copy.deepcopy(observation.get("candidate_outcomes", {}).get(
                    candidate["candidate_id"], observation["outcome"])),
                "logical_cost_accounting_id": observation["logical_cost_accounting_id"],
                "preceding_candidate_ids": [item["candidate_id"] for item in branch.candidates
                                            if item["candidate_id"] != candidate["candidate_id"]],
            })
        prefix_image_ids = set(self.snapshot.record["memory"]["state"]["images"]["registry"])
        resulting_artifacts = []
        for image_id, entry in branch.memory.state.images.registry.items():
            if image_id in prefix_image_ids:
                continue
            resulting_artifacts.append({
                "kind": "image", "image_id": image_id, "source": entry.get("source"),
                "aliases": sorted(entry.get("aliases", [])), "data_url": entry.get("data_url"),
            })
        record = {
            "schema_version": COLLECTION_VERSION, "collection_run_id": self.collection_run_id,
            "source_group_id": branch.source_group_id, "parent_snapshot_id": branch.parent_snapshot_id,
            "parent_state_digest": branch.parent_state_digest, "branch_id": branch.branch_id,
            "selection_design": selection["selection_design"],
            "eligible_actions": copy.deepcopy(self.eligible_actions),
            "ineligible_actions": copy.deepcopy(self.ineligible_actions),
            "selection_probability": selection["selection_probability"],
            "path_draw_probability": selection["path_draw_probability"],
            "selection_steps": copy.deepcopy(selection["selection_steps"]),
            "selection_seed": selection.get("selection_seed"), "rng": selection.get("rng"),
            "selected_path": selected_steps, "prefix_cost": branch.prefix_cost,
            "branch_cost": branch.branch_cost,
            "hypothetical_path_cost": path_cost(branch.prefix_cost, branch.branch_cost),
            "experimental_expenditure_contribution": branch.branch_cost,
            "observations": copy.deepcopy(continuation_observations), "candidate_rows": candidate_rows,
            "resulting_artifacts": resulting_artifacts,
            "terminal_state_digest": branch.state_digest(), "status": status,
            "capture_complete": capture_complete, "offline_gt_used": False,
            "native_history_extended": False, "errors": copy.deepcopy(branch.errors),
        }
        validate_branch(record)
        if len(branch.actions) < prefix_count:
            raise AssertionError("Frozen prefix action history was lost")
        return record, branch

    def run_all(self, selections):
        snapshot_before = self.snapshot.record
        records = [self.run(selection, branch_index=index)[0] for index, selection in enumerate(selections)]
        if self.snapshot.record != snapshot_before:
            raise AssertionError("Branch execution mutated the frozen snapshot")
        return records
