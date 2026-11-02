"""Endpoint-specific scientific decision for Phase 4C-1D."""

from __future__ import annotations

from .zoom_incremental_model import BASELINE_MODEL, PRIMARY_MODEL

READINESS_VERSION = "bite.phase04c1d_zoom_readiness.v1"


def assess_zoom_readiness(results_by_endpoint, *, checkpoint_status):
    evidence = {}
    for endpoint, result in sorted(results_by_endpoint.items()):
        comparison = result["paired_uncertainty"]["comparisons"][
            f"{PRIMARY_MODEL}_minus_{BASELINE_MODEL}"
        ]["case_level"]["brier_score"]
        evidence[endpoint] = comparison
    intervals_strictly_favorable = all(row["upper_97_5"] < 0 for row in evidence.values())
    observed_favorable = [row["observed_difference"] < 0 for row in evidence.values()]
    if intervals_strictly_favorable:
        conditional_decision = "EXPLORATORY_INCREMENTAL_SIGNAL_OBSERVED"
        research_decision = "ZOOM_PROMISING_CONTINUE_TO_VALIDATION"
        next_branch = "resolve matched-worker provenance, then seek separate held-out collection authorization"
    elif not any(observed_favorable):
        conditional_decision = "NO_RELIABLE_INCREMENTAL_SIGNAL"
        research_decision = "ZOOM_UNHELPFUL_REVISE_ACTION_SPACE"
        next_branch = "preserve the negative result and pre-register a complementary independent action"
    else:
        conditional_decision = "INCONCLUSIVE_INSUFFICIENT_SUPPORT"
        research_decision = "ZOOM_INCONCLUSIVE_MORE_FIT_EVIDENCE_NEEDED"
        next_branch = "identify additional calibration-fit groups/cases under a separately approved collection plan"
    return {
        "schema_version": READINESS_VERSION,
        "status": "ENGINEERING_SUCCESS",
        "conditional_usefulness_decision": conditional_decision,
        "research_decision": research_decision,
        "primary_brier_evidence": evidence,
        "decision_rule": {
            "promising": "primary paired Brier 95% group-bootstrap intervals strictly below zero at both endpoints",
            "unhelpful": "primary observed paired Brier differences nonnegative at both endpoints",
            "otherwise": "inconclusive",
            "rule_frozen_in_source_before result interpretation": True,
        },
        "next_branch": next_branch,
        "conditional_kernel": {
            "fit_justified_now": False,
            "reason": (
                "M1 is a low-dimensional discriminative development model; sparse positives, ambiguous outcomes, "
                "annotation limitations, same-backend dependence, and checkpoint uncertainty remain material."
            ),
            "posterior_update_authorized": False,
        },
        "validation": {
            "authorized": False,
            "checkpoint_status": checkpoint_status,
            "matched_worker_bridge_pending": True,
            "development_result_is_blind_validation": False,
        },
        "human_review": {
            "required_for_coco_endpoint": False,
            "existing_records_preserved": True,
        },
        "planner_ready": False,
        "certificate_ready": False,
    }
