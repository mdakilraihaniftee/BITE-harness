"""Opt-in passive evidence capture; no decision or inference APIs."""
from .observer import EvidenceObserver, create_observer

__all__ = ["EvidenceObserver", "create_observer"]
