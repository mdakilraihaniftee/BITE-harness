"""Coordinator answer state, optional memory, peer communication, and the config matrix.

All runs use the deterministic scripted fixture (real MainAgent loop, scripted
model endpoint and tools); none of this is model performance.
"""

from __future__ import annotations

import importlib.util
import json
from itertools import product
from pathlib import Path
from typing import Any

import pytest

from openvlharness.multi_agent import MultiAgentOrchestrator
from openvlharness.multi_agent.config import (
    apply_run_options,
    effective_run_config,
    load_multi_agent_config,
)
from openvlharness.multi_agent.estimate import EstimateTracker
from openvlharness.multi_agent.testing import (
    FIXTURE_TASK,
    ScriptedAgentBuilder,
    create_scene,
    fixture_config,
)

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("studio_config_matrix", ROOT / "scripts/studio_config_matrix.py")
matrix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(matrix)


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, agent_id, event_type, payload, **metadata):
        self.events.append((event_type, payload))
        return {"event_id": f"evt_{len(self.events)}"}

    def types(self) -> list[str]:
        return [item[0] for item in self.events]


EVIDENCE = [{"worker_id": "worker_01", "report_event_id": "evt_r1", "delivered_event_id": "evt_d1",
             "candidate_answer": "12", "tool_call_refs": ["call_a"]}]


def test_a_no_estimate_initially(tmp_path: Path) -> None:
    recorder = Recorder()
    tracker = EstimateTracker(recorder, tmp_path / "history.json")
    assert tracker.current() == {"revision": 0, "estimate": None, "estimate_type": None, "status": "none"}
    assert recorder.events == [] and not (tmp_path / "history.json").exists()


def test_b_to_f_estimate_lifecycle(tmp_path: Path) -> None:
    recorder = Recorder()
    tracker = EstimateTracker(recorder, tmp_path / "history.json")
    # B: first provisional estimate
    event = tracker.assess(estimate="12", status="provisional", summary="s", reason=None, evidence=EVIDENCE, round_index=1)
    assert event and tracker.current()["status"] == "provisional" and tracker.current()["estimate"] == "12"
    first = recorder.events[-1][1]
    assert first["change_kind"] == "initial" and first["previous_estimate"] is None and first["revision"] == 1
    assert first["evidence_refs"] == ["evt_r1", "evt_d1"] and first["estimate_type"] == "integer"
    # C: evidence received, no change -> no revision event
    assert tracker.assess(estimate=" 12 ", status="provisional", summary="same", reason=None, evidence=EVIDENCE, round_index=2) is None
    assert recorder.types()[-1] == "COORDINATOR_REASSESSMENT_RECORDED"
    assert recorder.events[-1][1]["outcome"] == "retained" and tracker.current()["revision"] == 1
    assert recorder.types().count("COORDINATOR_ESTIMATE_UPDATED") == 1
    # D: revision
    tracker.assess(estimate=14, status="provisional", summary="two more", reason="new candidates", evidence=EVIDENCE, round_index=2)
    revised = recorder.events[-1][1]
    assert revised["change_kind"] == "revised" and revised["previous_estimate"] == "12" and revised["estimate"] == "14"
    assert tracker.current()["status"] == "revised" and tracker.current()["revision"] == 2
    # E: withdrawal -> unresolved, the stale value is not kept as current
    tracker.assess(estimate=None, status="unresolved", summary="conflict", reason="contradicted", evidence=EVIDENCE, round_index=3)
    withdrawn = recorder.events[-1][1]
    assert withdrawn["change_kind"] == "withdrawn" and tracker.current()["estimate"] is None
    assert tracker.current()["status"] == "unresolved"
    # Restored after withdrawal
    tracker.assess(estimate="13", status="provisional", summary="ok", reason="verified", evidence=EVIDENCE, round_index=4)
    assert recorder.events[-1][1]["change_kind"] == "restored"
    # F: finalization keeps history and does not claim a numeric change
    tracker.finalize("13", evidence=EVIDENCE)
    final = recorder.events[-1][1]
    assert final["status"] == "final" and final["change_kind"] == "finalized" and final["value_changed"] is False
    history = json.loads((tmp_path / "history.json").read_text())["history"]
    assert [h["change_kind"] for h in history] == ["initial", "revised", "withdrawn", "restored", "finalized"]
    assert [h["revision"] for h in history] == [1, 2, 3, 4, 5]


def test_unresolved_without_prior_estimate_is_not_a_revision(tmp_path: Path) -> None:
    recorder = Recorder()
    tracker = EstimateTracker(recorder)
    assert tracker.assess(estimate="unknown", status="provisional", summary=None, reason=None, evidence=[], round_index=1) is None
    assert tracker.current()["status"] == "none"
    tracker.finalize(None, evidence=[])
    assert tracker.current()["status"] == "abstained"


def _run(tmp_path: Path, **kwargs: Any):
    image = create_scene(tmp_path / "scene.png")
    builder = ScriptedAgentBuilder(image, scenario=kwargs.pop("scenario", "standard"))
    run_id = kwargs.pop("run_id", "run")
    config = kwargs.pop("config", None) or fixture_config(tmp_path, **kwargs)
    orchestrator = MultiAgentOrchestrator(config, factory=builder.factory(), run_id=run_id)
    result = orchestrator.run(FIXTURE_TASK, [{"type": "image", "value": str(image)}, {"type": "text", "value": FIXTURE_TASK}])
    events = [json.loads(line) for line in (orchestrator.run_dir / "events.jsonl").read_text().splitlines()]
    return orchestrator, builder, result, events


def test_withdrawal_scenario_records_unresolved_state(tmp_path: Path) -> None:
    _, _, result, events = _run(tmp_path, workers=1, memory=True, peer=False, scenario="withdrawal")
    kinds = [e["payload"]["change_kind"] for e in events if e["event_type"] == "COORDINATOR_ESTIMATE_UPDATED"]
    assert kinds == ["initial", "withdrawn", "finalized"]
    assert result["extra_records"]["status"] == "COMPLETED"


@pytest.mark.parametrize("workers,memory,peer", list(product((1, 2, 3, 4), (True, False), (True, False))))
def test_configuration_matrix(tmp_path: Path, workers: int, memory: bool, peer: bool) -> None:
    run_dir, builder, result = matrix.run_fixture(tmp_path, workers=workers, memory=memory, peer=peer, run_id="m")
    assert result["extra_records"]["status"] == "COMPLETED"
    validation = matrix.validate_run(run_dir, builder, workers=workers, memory=memory, peer=peer)
    failed = {k: v["detail"] for k, v in validation["checks"].items() if not v["passed"]}
    assert not failed, failed


def test_memory_switch_changes_what_workers_receive(tmp_path: Path) -> None:
    _, on, _, _ = _run(tmp_path / "on", workers=1, memory=True, peer=False)
    _, off, _, off_events = _run(tmp_path / "off", workers=1, memory=False, peer=False)
    on_text = json.dumps(on.policies["worker_01"].requests)
    off_text = json.dumps(off.policies["worker_01"].requests)
    assert "Your private notebook from earlier phases" in on_text
    assert "Your private notebook from earlier phases" not in off_text
    # Working context (image registry inventory) is still used with memory off.
    assert any(e["event_type"] == "MEMORY_WRITTEN" and e["payload"].get("memory_kind") == "working_context" for e in off_events)
    assert not any(e["event_type"].startswith("OPTIONAL_MEMORY") for e in off_events)
    # Without notes the worker must re-derive the region: more tool calls.
    on_calls = json.loads((tmp_path / "on/run/workers/worker_01/result.json").read_text())["tool_calls"]
    off_calls = json.loads((tmp_path / "off/run/workers/worker_01/result.json").read_text())["tool_calls"]
    assert off_calls > on_calls


def test_peer_communication_off_keeps_coordinator_channel(tmp_path: Path) -> None:
    _, builder, _, events = _run(tmp_path, workers=3, memory=True, peer=False)
    sent = [e for e in events if e["event_type"] == "MESSAGE_SENT"]
    assert not [e for e in sent if e["payload"]["channel"] == "peer"]
    assert {e["payload"]["message_type"] for e in sent} >= {"TASK_ASSIGNMENT", "CANDIDATE_ANSWER"}
    for worker_id in ("worker_01", "worker_02", "worker_03"):
        assert "Review these peer claims" not in json.dumps(builder.policies[worker_id].requests)


def test_peer_communication_on_does_not_force_review_for_single_worker(tmp_path: Path) -> None:
    _, _, _, events = _run(tmp_path, workers=1, memory=True, peer=True)
    assert not [e for e in events if e["event_type"] in {"PEER_REVIEW_STARTED", "VERIFICATION_REQUESTED"}]


def test_estimates_disabled_adds_no_coordinator_calls(tmp_path: Path) -> None:
    orchestrator, _, _, events = _run(tmp_path, workers=2, memory=True, peer=False, estimate_updates=False, follow_up_rounds=0)
    assert orchestrator.budget.used("coordinator", "model_requests") == 2  # plan + synthesis
    estimates = [e for e in events if e["event_type"] == "COORDINATOR_ESTIMATE_UPDATED"]
    assert [e["payload"]["change_kind"] for e in estimates] == ["finalized"]
    assert estimates[0]["payload"]["previous_estimate"] is None


def test_reassessments_are_counted_and_bounded_by_budget(tmp_path: Path) -> None:
    config = fixture_config(tmp_path, workers=1, memory=True, peer=False)
    config["coordinator"]["model_requests"] = 2
    orchestrator, _, result, events = _run(tmp_path, config=config)
    assert result["extra_records"]["status"] == "COMPLETED"
    skipped = [e for e in events if e["event_type"] == "COORDINATOR_REASSESSMENT_RECORDED"]
    assert skipped and all(e["payload"]["outcome"] == "skipped_budget" for e in skipped)
    assert orchestrator.budget.used("coordinator", "model_requests") == 2
    used = [e["payload"]["model_requests"] for e in events if e["event_type"] == "COORDINATOR_ESTIMATE_UPDATED" and e["payload"]["change_kind"] != "finalized"]
    assert used == []


def test_global_tool_budget_exhaustion_is_enforced(tmp_path: Path) -> None:
    orchestrator, _, result, events = _run(tmp_path, workers=4, memory=False, peer=True, global_tool_calls=3)
    assert orchestrator.budget.snapshot()["global"]["tool_calls"]["used"] <= 3
    denials = [e for e in events if e["event_type"] == "TOOL_CALL_FAILED" and "budget" in json.dumps(e["payload"]).lower()]
    assert denials
    assert result["extra_records"]["status"] == "COMPLETED"


def test_run_options_and_effective_config_validation() -> None:
    base = fixture_config(Path("/tmp/unused"), workers=2, memory=True, peer=True)
    changed = apply_run_options(base, num_agents=4, worker_memory=False, peer_communication=False, mode="concurrent",
                                estimate_updates=True, max_reassessments=1, follow_up_rounds=0)
    effective = effective_run_config(changed)
    assert effective["num_workers"] == 4 and not effective["optional_worker_memory_enabled"]
    assert not effective["peer_communication_enabled"] and effective["coordinator_assignment_enabled"]
    assert effective["coordinator_estimate_updates"]["additional_model_requests_max"] == 1
    assert base["num_agents"] == 2  # original untouched
    for bad in ({"num_agents": 5}, {"mode": "parallel"}, {"max_reassessments": 9}, {"follow_up_rounds": -1}):
        with pytest.raises(ValueError):
            apply_run_options(base, **bad)
    with pytest.raises(ValueError, match="Unknown"):
        load_multi_agent_config({"multi_agent": {"num_agents": 1, "coordinator": {"estimate_updates": {"often": True}}, "workers": {}}})
    with pytest.raises(ValueError, match="memory"):
        load_multi_agent_config({"multi_agent": {"num_agents": 1, "coordinator": {}, "workers": {}, "memory": {"optional_worker_memory": "yes"}}})
    communication_off = apply_run_options(base, communication=False)
    assert effective_run_config(communication_off)["coordinator_reporting_channel"] == "direct_result_handoff"


def test_communication_disabled_still_reaches_coordinator(tmp_path: Path) -> None:
    config = apply_run_options(fixture_config(tmp_path, workers=2, memory=True, peer=True), communication=False)
    _, _, result, events = _run(tmp_path, config=config)
    assert result["extra_records"]["status"] == "COMPLETED"
    estimates = [e for e in events if e["event_type"] == "COORDINATOR_ESTIMATE_UPDATED"]
    assert estimates and all(item["channel"] == "direct_result_handoff" for item in estimates[0]["payload"]["evidence"])
    assert not [e for e in events if e["event_type"] == "MESSAGE_SENT" and e["payload"]["message_type"] != "TASK_ASSIGNMENT"]


def _two_request_coordinator(builder: ScriptedAgentBuilder):
    """Mimic the real Qwen pattern: the first reply of each call lacks answer tags."""
    original = builder.__call__

    def build(config, actor_id, tool_access):
        agent = original(config, actor_id, tool_access)
        if actor_id == "coordinator":
            policy = agent.adapter.requester

            def requester(payload):
                if payload["messages"][-1]["role"] == "user":
                    policy.requests.append(payload)
                    return {"choices": [{"message": {"role": "assistant", "content": "Let me consider the reports."}}],
                            "usage": {"completion_tokens": 5}}
                return policy(payload)

            agent.adapter.requester = requester
        return agent

    return build


@pytest.mark.parametrize("limit,reassessed", [(4, False), (6, True), (8, True)])
def test_multi_request_coordinator_calls_never_starve_synthesis(tmp_path: Path, limit: int, reassessed: bool) -> None:
    """Regression: real coordinator calls can cost 2 requests; synthesis must still run."""
    from openvlharness.multi_agent import AgentFactory

    image = create_scene(tmp_path / "scene.png")
    builder = ScriptedAgentBuilder(image)
    config = fixture_config(tmp_path, workers=1, memory=True, peer=False, follow_up_rounds=0)
    config["coordinator"]["model_requests"] = limit
    orchestrator = MultiAgentOrchestrator(config, factory=AgentFactory(_two_request_coordinator(builder)), run_id="r")
    result = orchestrator.run(FIXTURE_TASK, [{"type": "image", "value": str(image)}, {"type": "text", "value": FIXTURE_TASK}])
    events = [json.loads(line) for line in (orchestrator.run_dir / "events.jsonl").read_text().splitlines()]
    assert result["extra_records"]["status"] == "COMPLETED" and result["prediction"] == "4"
    kinds = [e["payload"]["change_kind"] for e in events if e["event_type"] == "COORDINATOR_ESTIMATE_UPDATED"]
    assert ("initial" in kinds) is reassessed
    assert orchestrator.budget.used("coordinator", "model_requests") <= limit
    if reassessed:
        update = next(e for e in events if e["event_type"] == "COORDINATOR_ESTIMATE_UPDATED")
        assert update["payload"]["model_requests"] == 2  # the extra cost is measured and reported
