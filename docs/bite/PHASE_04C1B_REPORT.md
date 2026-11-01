# Phase 4C-1B — paired robustness and validation readiness

Report date: **2026-11-01**. Status:
**ENGINEERING_SUCCESS / PAIRED_COMPARISON_COMPLETE / LABEL_REVIEW_PENDING**.

All Phase 4C-1A out-of-fold metrics independently reproduce from stored
predictions without refitting. Paired source-group bootstrap shows primary
score-only-minus-constant Brier differences of -0.044698
[-0.060112, -0.028660] at IoU .50 and -0.030534
[-0.044531, -0.015740] at .75. Pilot comparisons remain inconclusive, and
development selection optimism remains explicit.

Exact additive sensitivity analysis was derived and verified against exhaustive
small-world enumeration. In the suspected-missing-annotation scenario, 28
candidate flips (.50) or 18 (.75) can reverse the fixed-prediction expansion
Brier ranking; clustered budgets require 6 or 4 groups. These are hypothetical
worst cases, not empirical omissions, and do not cover retraining.

The review server remains loopback-only and server-enforces blind submission
before score/GT reveal. All 235 queued source identities validate and no human
judgment was fabricated. Set A remains 0/120. New prospective reviews use the
v2 visual-verification endpoint, which explicitly treats decisive wrong
localization as failure while preserving ambiguity as unknown.

The 72-group, 1,512-call validation protocol passes metadata-only split,
quarantine, schema, budget and resume checks. It remains unexecuted and new
inference is unauthorized. Exact loaded SAM 3 revision, weight hash,
preprocessing and worker code remain unattested, preventing cross-run identity
claims.

No SAM 3/Qwen inference, training, dataset/checkpoint download, Zoom likelihood,
posterior update, online belief state, planner, evaluator change or certificate
occurred. Historical output artifacts were not rewritten; Aquarium imagery
remains internal with Aquarium Combined/GLIP and CC BY 4.0 attribution.

