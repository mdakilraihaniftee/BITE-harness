"""Task model and DAG validation."""

import pytest

from openvlharness.parsec_vl.dag import (
    GraphError, InvalidTransition, Task, TaskStatus, bottom_levels, graph_metrics, lower_bound, validate_graph,
)


def t(tid, deps=(), cost=1.0, pool="cpu"):
    return Task(task_id=tid, operation="op", dependency_ids=deps, estimated_cost=cost, resource_type=pool)


def test_valid_dag_is_returned_in_topological_order():
    order = validate_graph([t("crop_ocr", ("crop",)), t("crop", ("grounding",)), t("grounding"), t("ocr"), t("depth")])
    position = {task.task_id: i for i, task in enumerate(order)}
    assert position["grounding"] < position["crop"] < position["crop_ocr"]
    assert len(order) == 5


def test_cycle_is_rejected():
    with pytest.raises(GraphError, match="cycle"):
        validate_graph([t("a", ("c",)), t("b", ("a",)), t("c", ("b",))])


def test_self_dependency_is_rejected():
    with pytest.raises(GraphError, match="itself"):
        t("a", ("a",))


def test_missing_dependency_is_rejected():
    with pytest.raises(GraphError, match="unknown task"):
        validate_graph([t("a", ("ghost",))])


def test_duplicate_ids_are_rejected_within_and_across_submissions():
    with pytest.raises(GraphError, match="duplicate"):
        validate_graph([t("a"), t("a")])
    with pytest.raises(GraphError, match="duplicate"):
        validate_graph([t("a")], {"a": t("a")})


def test_new_tasks_may_depend_on_existing_tasks():
    existing = {"g": t("g")}
    assert [x.task_id for x in validate_graph([t("crop", ("g",))], existing)] == ["crop"]


def test_status_transitions_are_validated():
    task = t("a")
    task.transition(TaskStatus.READY)
    task.transition(TaskStatus.RESERVED)
    task.transition(TaskStatus.RUNNING)
    with pytest.raises(InvalidTransition):
        task.transition(TaskStatus.CANCELLED)  # in-flight work is never cancelled
    task.transition(TaskStatus.COMPLETED)
    with pytest.raises(InvalidTransition):
        task.transition(TaskStatus.RUNNING)  # terminal
    blocked = t("b")
    blocked.transition(TaskStatus.BLOCKED)
    with pytest.raises(InvalidTransition):
        blocked.transition(TaskStatus.RUNNING)  # must become READY and be reserved first


def test_bottom_levels_follow_the_longest_downstream_path():
    tasks = {x.task_id: x for x in [t("g", cost=2), t("crop", ("g",), cost=1), t("crop_ocr", ("crop",), cost=3),
                                    t("ocr", cost=4), t("depth", cost=1)]}
    levels = bottom_levels(tasks)
    assert levels == {"g": 6, "crop": 4, "crop_ocr": 3, "ocr": 4, "depth": 1}


def test_bottom_levels_without_estimates_count_tasks():
    tasks = {x.task_id: x for x in [t("a", cost=None), t("b", ("a",), cost=None), t("c", cost=None)]}
    assert bottom_levels(tasks) == {"a": 2, "b": 1, "c": 1}


def test_graph_metrics_and_lower_bound():
    tasks = [t("g", cost=2, pool="gpu"), t("crop", ("g",), cost=1), t("ocr", cost=4, pool="gpu"), t("depth", cost=1)]
    metrics = graph_metrics(tasks)
    assert metrics["T1"] == 8 and metrics["Tinf"] == 4 and metrics["available_parallelism"] == 2
    assert metrics["work_by_resource"] == {"gpu": 6, "cpu": 2}
    bound = lower_bound(metrics, {"gpu": 1, "cpu": 4}, workers=4)
    assert bound["T_LB"] == 6 and bound["binding_term"] == "resource:gpu"


def test_unknown_durations_are_reported_not_guessed():
    metrics = graph_metrics([t("a", cost=None), t("b", cost=2)])
    assert metrics["unknown_durations"] == ["a"] and metrics["T1"] == 2
