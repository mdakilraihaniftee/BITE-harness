"""Dataset-level Task V collection on isolated Phase 4B-1 branch snapshots."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from evaluation_kit.bite_calibration.matching import label_candidates
from evaluation_kit.bite_calibration.operational_state import build_operational_state
from evaluation_kit.bite_calibration.records import build_collection_records
from evaluation_kit.bite_calibration.target_outcomes import summarize_target_aligned
from evaluation_kit.bite_calibration.validation import validate_records
from openvlharness.bootstrap import memory_factory

from .action_selection import deterministic_coverage
from .branch_runner import BranchRunner
from .eligibility import get_action_alternatives, make_action
from .integrity import StageEventLedger
from .persistence import atomic_json, save_collection
from .resume import ResumeLedger, file_digest
from .snapshot import freeze_state
from .state_builder import execute_prefix, source_image_identity
from .validation import validate_collection


def _best_candidate(candidates):
    if not candidates:
        return None, None
    def key(item):
        rank, candidate = item
        scores = candidate.get("raw_scores") or []
        score = scores[0] if scores and isinstance(scores[0], (int, float)) and math.isfinite(scores[0]) else -math.inf
        return score, -rank
    rank, candidate = max(enumerate(candidates), key=key)
    return copy.deepcopy(candidate), rank


def _runtime_probe(capabilities, task, memory, actions, candidates):
    return type("RuntimeProbe", (), {
        "capabilities": capabilities, "task": task, "memory": memory,
        "actions": actions, "candidates": candidates,
    })()


def _target_summaries(branch, initial_candidate):
    by_id = {row["candidate"]["candidate_id"]: row["candidate"] for row in branch["candidate_rows"]}
    for observation in branch["observations"]:
        if observation["capability"] != "Visual_Grounding_Tool":
            continue
        observed = [by_id[candidate_id] for candidate_id in observation.get("candidate_ids", []) if candidate_id in by_id]
        summary = summarize_target_aligned(initial_candidate, observed, observation)
        # The collection validator forbids even negatively asserted GT-named fields.
        summary.pop("gt_identity_used", None)
        observation["target_aligned_outcome"] = summary


def _repeat_comparison(branch, prefix_observation):
    observation = next((row for row in branch["observations"]
                        if row["capability"] == "Visual_Grounding_Tool"), None)
    if observation is None:
        return None
    old = prefix_observation.get("canonical_result") or {}
    new = observation.get("canonical_result") or {}
    return {
        "previous_observation_id": prefix_observation.get("joint_observation_id"),
        "current_observation_id": observation.get("joint_observation_id"),
        "boxes_exactly_identical": old.get("boxes") == new.get("boxes"),
        "scores_exactly_identical": old.get("scores") == new.get("scores"),
        "masks_exactly_identical": old.get("masks") == new.get("masks"),
        "proposal_counts_identical": len(old.get("boxes") or []) == len(new.get("boxes") or []),
        "dependence_note": "Exact repeat shares pixels, query, backend and checkpoint; it is not independent evidence",
    }


def _jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text("".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows))
    temporary.replace(path)


class TaskVBatchRunner:
    def __init__(self, *, adapter, selection, capabilities, memory_config, run_dir,
                 collection_run_id, resume=False, dispatch_cap=160, branch_budget=3,
                 experiment_configuration=None, stage_evidence=False):
        self.adapter = adapter
        self.selection = copy.deepcopy(selection)
        self.capabilities = capabilities
        self.memory_config = copy.deepcopy(memory_config)
        self.run_dir = Path(run_dir)
        self.collection_run_id = collection_run_id
        self.dispatch_cap = dispatch_cap
        self.branch_budget = branch_budget
        self.stage_evidence = stage_evidence
        if selection["maximum_public_dispatches"] > dispatch_cap:
            raise ValueError("Declared sample exceeds the global public-dispatch cap")
        required = {"Visual_Grounding_Tool", "Zoom_In_Tool"}
        if not required <= set(capabilities):
            raise ValueError("Task V collection requires grounding and zoom capabilities")
        if capabilities["Visual_Grounding_Tool"].backend != "sam3_segment":
            raise ValueError("Task V pilot is frozen to the SAM 3 backend")
        configuration = experiment_configuration or {
            "schema_version": "bite.task_v_collection_config.v1", "collection_run_id": collection_run_id,
            "source_id": adapter.preflight["source_id"], "manifest_sha256": selection["manifest_sha256"],
            "partition": selection["partition"], "selection_seed": selection["seed"],
            "selected_source_groups": selection["source_groups"],
            "scheduled_state_ids": [state["state_id"] for state in selection["states"]],
            "branch_budget": branch_budget, "dispatch_cap": dispatch_cap,
            "design": "deterministic_task_v_repeat_and_zoom_focus.v1",
            "candidate_rule": "highest retained score; stable detector-rank tie break; no fallback",
            "query_schedule": "frozen_gt_independent_query_schedule.v2",
            "backend": "sam3_segment", "zoom_padding": 50, "orchestrator_model": None,
            "probability_model_fitted": False,
        }
        self.configuration = configuration
        self.ledger = ResumeLedger(run_dir, configuration, resume=resume)
        atomic_json(self.run_dir / "sample_selection_manifest.json", self.selection)

    def _state_dispatch_upper_bound(self, state):
        return 4

    def _declared_actions(self, eligible, state):
        return [row for row in eligible if row["path_name"].startswith(("repeat:", "zoom_focus:"))]

    def _execution_filename(self, canary_only):
        return "canary_execution.json" if canary_only else "pilot_execution.json"

    def _completed_dispatches(self):
        total = 0
        for state in self.selection["states"]:
            result = self.ledger.inspect(state["state_id"])
            if result["status"] == "complete":
                total += int(result["record"].get("actual_dispatches", 0))
        return total

    def run(self, *, canary_only=False):
        if not canary_only:
            for state in self.selection["states"]:
                if state["is_canary_group"] and self.ledger.inspect(state["state_id"])["status"] != "complete":
                    raise RuntimeError("Canary states must complete before the remaining frozen sample")
        dispatched = self._completed_dispatches()
        results = []
        for state in self.selection["states"]:
            if canary_only != bool(state["is_canary_group"]) and canary_only:
                continue
            inspection = self.ledger.inspect(state["state_id"])
            if inspection["status"] == "complete":
                results.append({"state_id": state["state_id"], "status": "resumed_complete",
                                "actual_dispatches": inspection["record"]["actual_dispatches"]})
                continue
            if inspection["status"] != "pending":
                raise RuntimeError(f"State {state['state_id']} is {inspection['status']}; explicit new execution is required")
            if dispatched + self._state_dispatch_upper_bound(state) > self.dispatch_cap:
                raise RuntimeError("Global public-dispatch cap would be exceeded")
            result = self._run_state(state)
            dispatched += result["actual_dispatches"]
            results.append(result)
        summary = {
            "schema_version": "bite.task_v_batch_execution.v1", "collection_run_id": self.collection_run_id,
            "canary_only": canary_only, "states_considered": len(results),
            "newly_completed": sum(row["status"] == "complete" for row in results),
            "resumed_complete": sum(row["status"] == "resumed_complete" for row in results),
            "actual_dispatches_after_run": self._completed_dispatches(), "dispatch_cap": self.dispatch_cap,
            "results": results,
        }
        atomic_json(self.run_dir / self._execution_filename(canary_only), summary)
        return summary

    def _run_state(self, state):
        entry_data = state["entry"]
        entry = next(row for row in self.adapter.entries() if row.entry_id == entry_data["entry_id"])
        state_dir = self.ledger.state_dir(state["state_id"])
        events = StageEventLedger(state_dir / "stage_events.jsonl") if self.stage_evidence else None
        if events:
            events.append("runtime_started", {"state_id": state["state_id"], "offline_gt_opened": False})
        memory = memory_factory(self.memory_config)()
        question = f"Locate all {state['query']} in the registered Aquarium image."
        memory.start([{"type": "image", "value": entry.runtime_image()}, {"type": "text", "value": question}])
        if source_image_identity(memory) != entry.image_sha256:
            raise ValueError("Runtime image registry changed the verified source bytes")
        task = {
            "hypothesis_task": "candidate_verification", "dataset": self.adapter.preflight["source_id"],
            "sample_id": entry.entry_id, "question": question, "query": state["query"],
            "permitted_classes": list(state.get("permitted_classes", entry.queries)), "source_domain": "Aquarium",
            "root_image_id": "input_image_1", "source_entry_id": entry.entry_id,
            "partition": entry.partition,
        }
        prefix_action = make_action(
            "root_grounding", "Visual_Grounding_Tool", "sam3_segment",
            {"image_id": "input_image_1", "query": state["query"]},
        )
        prefix = execute_prefix(
            memory, self.capabilities, task=task, source_group_id=entry.source_group_id,
            source_image_sha256=entry.image_sha256, actions=[prefix_action],
        )
        prefix_observation = prefix.observations[-1]
        selected, selected_rank = _best_candidate(prefix.candidates)
        candidate_usable = bool(selected and selected.get("bbox_root_xyxy") is not None and not selected.get("frame_reason"))
        candidate_history = [selected] if selected is not None else []
        snapshot = freeze_state(
            memory, task=task, source_group_id=entry.source_group_id, source_image_sha256=entry.image_sha256,
            capabilities=self.capabilities, previous_actions=prefix.actions,
            previous_observations=prefix.observations, candidate_history=candidate_history,
            provenance=prefix.provenance, prefix_logical_cost=prefix.branch_cost, native_history=None,
        )
        probe = _runtime_probe(self.capabilities, task, memory, prefix.actions, candidate_history)
        eligible, ineligible = get_action_alternatives(probe, remaining_budget=self.branch_budget)
        declared = self._declared_actions(eligible, state)
        excluded = [row for row in eligible if row not in declared]
        ineligible = [*ineligible, *[{**row, "eligibility": "excluded", "reason": "outside_task_v_pilot"} for row in excluded]]
        if not candidate_usable:
            declared = []
            ineligible.append({
                "path_name": "task_v_branches", "steps": [], "estimated_branch_cost": 0,
                "eligibility": "ineligible", "reason": "no_usable_initial_candidate",
            })
        selections = deterministic_coverage(
            declared, design_id=self.configuration.get("selection_design", "deterministic_task_v_coverage.v1"))
        runner = BranchRunner(
            snapshot, collection_run_id=self.collection_run_id,
            eligible_actions=declared, ineligible_actions=ineligible, branch_budget=self.branch_budget,
        )
        branches = runner.run_all(selections)
        for branch in branches:
            _target_summaries(branch, selected)
            if branch["selected_path"] and branch["selected_path"][0]["action_template"] == "repeated_grounding":
                branch["observations"][0]["exact_repeat_comparison"] = _repeat_comparison(branch, prefix_observation)
        validation = validate_collection(snapshot.record, branches)
        root = prefix_observation.get("root_image") or {}
        operational = build_operational_state(
            task=task, candidate=selected, prior_candidates=(), previous_observation=prefix_observation,
            current_action=prefix.actions[-1], root_dimensions=(root.get("width"), root.get("height")),
            remaining_budget=self.branch_budget, source_group_id=entry.source_group_id,
            source_image_sha256=entry.image_sha256,
        )
        collection_dir = state_dir / "raw_collection"
        save_collection(collection_dir, snapshot, branches, design={
            "id": self.configuration["design"],
            "excluded_unrelated_branches": True, "selection_uses_gt": False,
        })
        initial_raw = {
            "schema_version": "bite.task_v_initial_state.v1", "state_id": state["state_id"],
            "source_group_id": entry.source_group_id, "source_entry_id": entry.entry_id,
            "source_image_sha256": entry.image_sha256, "partition": entry.partition,
            "query": state["query"], "prefix_action": prefix.actions[-1],
            "prefix_observation": prefix_observation, "candidate_selection_rule": self.configuration["candidate_rule"],
            "selected_detector_rank": selected_rank, "selected_candidate": selected,
            "candidate_usable": candidate_usable, "candidate_count": len(prefix.candidates),
            "no_candidate_state": not bool(prefix.candidates), "offline_gt_used": False,
            "operational_state_id": operational["state_id"], "parent_snapshot_id": snapshot.record["snapshot_id"],
        }
        atomic_json(state_dir / "initial_raw_state.json", initial_raw)
        atomic_json(state_dir / "operational_state.json", operational)
        atomic_json(state_dir / "raw_validation.json", validation)
        raw_paths = [path for path in state_dir.rglob("*") if path.is_file()
                     and "offline_labels" not in path.parts and path.name != "stage_events.jsonl"]
        actual_dispatches = prefix.branch_cost + validation["actual_continuation_expenditure"]
        raw_record = self.ledger.mark_raw(state["state_id"], raw_paths, {
            "source_group_id": entry.source_group_id, "source_entry_id": entry.entry_id,
            "query": state["query"], "parent_snapshot_id": snapshot.record["snapshot_id"],
            "actual_dispatches": actual_dispatches,
        })

        raw_completion_path = state_dir / "raw_completion.json"
        raw_completion_sha256 = file_digest(raw_completion_path)
        if events:
            events.append("raw_finalized", {
                "raw_completion_sha256": raw_completion_sha256,
                "raw_content_file_count": len(raw_record["content_sha256"]),
            })
            events.append("offline_gt_open_authorized", {
                "requires_event": "raw_finalized", "raw_completion_sha256": raw_completion_sha256,
            })

        # Scientific boundary: no annotation loader is called before raw_completion.json exists.
        gt = self.adapter.load_offline_ground_truth(entry)
        if not (state_dir / "raw_completion.json").is_file():
            raise AssertionError("Offline GT was reached before raw persistence")
        initial_labels, initial_matching = label_candidates([selected] if selected else [], gt, (.5, .75),
                                                             assignment_scope="per_observation", score_mode="retained")
        branch_rows, branch_matching = build_collection_records(
            branches, gt, thresholds=(.5, .75), score_mode="retained", partition="calibration_fit",
        )
        validate_records(branch_rows)
        labels_dir = state_dir / "offline_labels"
        labels_dir.mkdir(parents=True, exist_ok=True)
        initial_label = {
            "schema_version": "bite.task_v_initial_candidate_labels.v1", "state_id": state["state_id"],
            "candidate_id": selected.get("candidate_id") if selected else None,
            "labels": initial_labels.get(selected.get("candidate_id"), []) if selected else [],
            "reason": None if selected else "successful_or_failed_initial_observation_has_no_candidate",
            "matching_summary": initial_matching, "labels_refer_to_original_candidate": True,
            "raw_completion_sha256_before_gt_open": raw_completion_sha256,
        }
        atomic_json(labels_dir / "initial_candidate_labels.json", initial_label)
        _jsonl(labels_dir / "branch_calibration_records.jsonl", branch_rows)
        atomic_json(labels_dir / "branch_matching_summary.json", branch_matching)
        if events:
            events.append("labels_finalized", {
                "initial_labels_sha256": file_digest(labels_dir / "initial_candidate_labels.json"),
                "branch_records_sha256": file_digest(labels_dir / "branch_calibration_records.jsonl"),
            })
        label_paths = list(labels_dir.rglob("*"))
        if events:
            label_paths.append(events.path)
        completion = self.ledger.complete(state["state_id"], raw_record, [p for p in label_paths if p.is_file()], {
            "offline_labels_complete": True,
            "stage_order_evidence": "stage_events.jsonl" if events else "historical_code_path_only",
            "branch_count": len(branches), "candidate_present": selected is not None,
        })
        return {
            "state_id": state["state_id"], "status": "complete", "source_group_id": entry.source_group_id,
            "query": state["query"], "prefix_success": prefix_observation["success"],
            "candidate_present": selected is not None, "candidate_usable": candidate_usable,
            "branch_count": len(branches), "actual_dispatches": actual_dispatches,
            "parent_snapshot_id": snapshot.record["snapshot_id"],
            "content_file_count": len(completion["content_sha256"]),
        }

