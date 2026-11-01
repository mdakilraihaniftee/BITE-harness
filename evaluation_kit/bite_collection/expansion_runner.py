"""Expansion policy specialization of the existing dataset batch collector."""

from __future__ import annotations

from .batch_runner import TaskVBatchRunner


class TaskVExpansionRunner(TaskVBatchRunner):
    def __init__(self, *, adapter, selection, capabilities, memory_config, run_dir,
                 collection_run_id, resume=False):
        configuration = {
            "schema_version": "bite.task_v_expansion_collection_config.v1",
            "protocol_version": selection["schema_version"], "protocol_sha256": selection["protocol_sha256"],
            "collection_run_id": collection_run_id, "source_id": adapter.preflight["source_id"],
            "manifest_sha256": selection["manifest_sha256"], "partition": selection["partition"],
            "selection_seed": selection["selection_seed"], "repeat_control_seed": selection["repeat_control_seed"],
            "selected_source_groups": selection["selected_source_groups"],
            "repeat_control_groups": selection["repeat_control_groups"],
            "scheduled_state_ids": [state["state_id"] for state in selection["states"]],
            "branch_budget": 3, "dispatch_cap": 665,
            "design": "task_v_expansion_zoom_all_repeat_control.v1",
            "selection_design": "deterministic_paths_under_frozen_random_group_allocation.v1",
            "candidate_rule": "highest retained score; stable detector-rank tie break; no fallback",
            "query_schedule": "all_seven_approved_source_classes.v1",
            "backend": "sam3_segment", "zoom_padding": 50, "orchestrator_model": None,
            "checkpoint_verified_by_worker": False, "probability_model_fitted": False,
        }
        super().__init__(
            adapter=adapter, selection=selection, capabilities=capabilities, memory_config=memory_config,
            run_dir=run_dir, collection_run_id=collection_run_id, resume=resume,
            dispatch_cap=665, branch_budget=3, experiment_configuration=configuration,
            stage_evidence=True,
        )

    def _state_dispatch_upper_bound(self, state):
        return 4 if state["repeat_control_group"] else 3

    def _declared_actions(self, eligible, state):
        result = [row for row in eligible if row["path_name"].startswith("zoom_focus:")]
        if state["repeat_control_group"]:
            result.extend(row for row in eligible if row["path_name"].startswith("repeat:"))
        return result

    def _execution_filename(self, canary_only):
        return "canary_execution.json" if canary_only else "expansion_execution.json"

