"""Recording-only accounting, deliberately without an enforcement operation."""
from dataclasses import asdict, dataclass


@dataclass
class Budget:
    reference_limit: int | None = 15
    model_iterations: int = 0
    logical_tool_calls: int = 0
    successful_tool_calls: int = 0
    failed_tool_calls: int = 0
    rejected_proposals: int = 0

    def export(self):
        return {**asdict(self), "remaining_budget": (
            None if self.reference_limit is None else self.reference_limit - self.logical_tool_calls),
            "enforced": False, "physical_backend_attempts": None,
            "physical_attempts_reason": "Transport/provider subattempts are not instrumented"}
