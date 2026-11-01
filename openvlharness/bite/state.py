"""One state object per generate invocation, never stored on a shared agent."""
from dataclasses import dataclass, field
from .budget import Budget


@dataclass
class BITEObserverState:
    run_id: str
    sample_id: str | None
    question_id: str
    budget: Budget = field(default_factory=Budget)
    events: list = field(default_factory=list)
    artifacts: dict = field(default_factory=dict)
    nodes: dict = field(default_factory=dict)
    provenance_edges: list = field(default_factory=list)
    errors: list = field(default_factory=list)
