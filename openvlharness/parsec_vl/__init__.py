"""PARSEC-VL: dependency-aware parallel execution for the multi-agent visual harness.

Phase 1 provides the task/DAG model (``dag``), typed resource pools and the
budget adapter over the run's existing ledger (``resources``), one scheduling
engine with policies E0/E1/E2 (``scheduler``), the harness integration that
runs agents' tool calls through it (``harness``), runtime profiling of event
logs (``profiling``), and the controlled benchmark workloads (``workloads``).
"""

from .dag import GraphError, InvalidTransition, Task, TaskOutput, TaskStatus, bottom_levels, graph_metrics, lower_bound
from .resources import BudgetAdapter, ResourcePools
from .scheduler import POLICIES, Scheduler, normalize_policy

__all__ = [
    "BudgetAdapter", "GraphError", "InvalidTransition", "POLICIES", "ResourcePools", "Scheduler", "Task",
    "TaskOutput", "TaskStatus", "bottom_levels", "graph_metrics", "lower_bound", "normalize_policy",
]
