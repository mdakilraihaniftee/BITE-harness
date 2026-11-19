"""Monte Carlo evaluation: real processes, identical results across process counts."""

import os
import random

import pytest

from openvlharness.parsec_vl.montecarlo import OutcomeModel, PlanEvaluator, finalize_spec, rollout, run_batch

SPEC = finalize_spec({
    "workers": 4, "budget": None, "capacities": {"ocr": 1, "gpu": 1, "cpu": 4},
    "actions": {"ocr": {"pool": "ocr", "deps": (), "duration": ("lognormal", 0.23, 0.3), "p_ok": 0.3},
                "g": {"pool": "gpu", "deps": (), "duration": ("lognormal", 0.93, 0.3), "p_ok": 0.9},
                "z": {"pool": "cpu", "deps": ("g",), "duration": ("lognormal", 0.06, 0.3), "p_ok": 1.0},
                "o2": {"pool": "ocr", "deps": ("z",), "duration": ("lognormal", 0.23, 0.3), "p_ok": 0.9}},
    "branches": [{"actions": ["ocr"], "goal": "ocr"}, {"actions": ["g", "z", "o2"], "goal": "o2"}]})
CANDIDATES = [(SPEC, ()), (SPEC, (1,))]


def test_rollout_respects_dependencies_and_probabilities():
    results = [rollout(SPEC, (), random.Random(i)) for i in range(20000)]
    p = sum(r[2] for r in results) / len(results)
    assert abs(p - (0.3 + 0.7 * 0.9 * 0.9)) < 0.01  # closed form of the declared model
    # Without speculation nothing is wasted; the fallback chain only runs after the primary failed.
    assert all(r[3] == 0 for r in results)
    # A fallback can never finish before grounding + zoom + OCR could have run after the primary.
    assert min(r[0] for r in results if r[1] == 4) > 0.5


def test_speculation_trades_cost_for_latency_on_common_draws():
    seq = [rollout(SPEC, (), random.Random(i)) for i in range(5000)]
    spec = [rollout(SPEC, (1,), random.Random(i)) for i in range(5000)]
    assert sum(r[0] for r in spec) < sum(r[0] for r in seq)
    assert sum(r[1] for r in spec) > sum(r[1] for r in seq)
    assert [r[2] for r in spec] == [r[2] for r in seq]  # same draws, same operational outcome


def test_budget_limit_is_respected():
    spec = {**SPEC, "budget": 2}
    assert all(r[1] <= 2 for r in (rollout(spec, (1,), random.Random(i)) for i in range(2000)))


def test_same_rollouts_same_estimates_for_any_process_count():
    reference = PlanEvaluator(processes=0, batch_size=200).evaluate(CANDIDATES, 2000, seed=7)
    for processes in (1, 2, 4):
        with PlanEvaluator(processes=processes, batch_size=200) as evaluator:
            result = evaluator.evaluate(CANDIDATES, 2000, seed=7)
        assert [e.to_dict() for e in result.estimates] == [e.to_dict() for e in reference.estimates]
        assert result.complete and result.batches == result.batches_done == 20


def test_evaluation_runs_in_separate_processes():
    with PlanEvaluator(processes=2, batch_size=100) as evaluator:
        result = evaluator.evaluate(CANDIDATES, 2000, seed=1)
    assert os.getpid() not in result.worker_pids and len(result.worker_pids) == 2
    assert result.cpu_seconds > 0


def test_different_seed_changes_the_draws_not_the_problem():
    a = PlanEvaluator(processes=0).evaluate(CANDIDATES, 1000, seed=1).estimates[0]
    b = PlanEvaluator(processes=0).evaluate(CANDIDATES, 1000, seed=2).estimates[0]
    assert a.latency_mean != b.latency_mean and abs(a.p_operational - b.p_operational) < 0.08


def test_time_budget_returns_partial_but_aligned_results():
    with PlanEvaluator(processes=1, batch_size=50) as evaluator:
        result = evaluator.evaluate(CANDIDATES, 200000, seed=3, time_budget=0.15)
    assert not result.complete and result.wall_seconds < 2.0
    counts = {e.rollouts for e in result.estimates}
    assert len(counts) == 1  # every candidate uses the same seeds


@pytest.mark.parametrize("completed,common", [([(0, 0), (0, 200), (1, 0), (1, 100)], 100), ([(0, 0)], 0)])
def test_partial_batches_use_only_the_shared_contiguous_seed_prefix(monkeypatch, completed, common):
    def partial(self, units, candidates, seed, results, timing, began, time_budget):
        for candidate, start in completed:
            spec, option = candidates[candidate]
            results[candidate, start] = run_batch(spec, option, seed, start, 100)

    monkeypatch.setattr(PlanEvaluator, "_run_pool", partial)
    result = PlanEvaluator(processes=2, batch_size=100).evaluate(CANDIDATES, 300, seed=19, time_budget=0.01)
    expected = PlanEvaluator(processes=0, batch_size=100).evaluate(CANDIDATES, common, seed=19)
    assert not result.complete
    assert [e.to_dict() for e in result.estimates] == [e.to_dict() for e in expected.estimates]


def test_crashed_worker_is_recovered():
    with PlanEvaluator(processes=2, batch_size=500) as evaluator:
        evaluator.start()
        for process in list(evaluator._pool._processes.values())[:1]:
            process.kill()
        result = evaluator.evaluate(CANDIDATES, 2000, seed=5)
    assert result.complete and evaluator.restarts == 1
    assert [e.to_dict() for e in result.estimates] == [e.to_dict() for e in PlanEvaluator(processes=0).evaluate(CANDIDATES, 2000, seed=5).estimates]


def test_outcome_model_keeps_its_source():
    model = OutcomeModel(durations={"OCR_Tool": ("empirical", (0.2, 0.3, 0.4))}, p_ok={"OCR_Tool": 0.7}, source="empirical")
    assert model.median("OCR_Tool") == 0.3 and model.success("Zoom_In_Tool") == 0.5
    assert model.to_dict()["durations"]["OCR_Tool"] == ("empirical", 3)
