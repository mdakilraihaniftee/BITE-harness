# Phase 4C-1C Revised — annotation-proxy calibration and validation preparation

Report date: **2026-11-01**. Status: **ENGINEERING_SUCCESS /
ANNOTATION_PROXY_READY / VALIDATION_EXECUTION_PENDING /
CHECKPOINT_COMPARABILITY_UNVERIFIED**.

Protocol v2 adopts official COCO candidate correctness at IoU .50 as primary and
.75 as the stricter companion. Empty same-class annotation sets are benchmark
negative; no-candidate states remain separate. The endpoint is reproducible but is
not exhaustive visual truth. Human review is supplemental for this endpoint and
remains required for visual-truth or omission-prevalence claims.

Twenty genuine finalized reviews were validated and preserved. The queue union has
215 pending cases; the incomplete probability sample supports no population
omission estimate and did not alter labels or models.

Six final fit-only priors were frozen from the 30-group/203-candidate expansion:
constant, score-only and compact at both thresholds. Score-only is primary. Model
serialization and deterministic prediction replay passed. Phase 4C-1B development
evidence remains unchanged: score-only-minus-constant Brier was -0.044698
[-0.060112, -0.028660] at .50 and -0.030534 [-0.044531, -0.015740] at .75.
Sensitivity bounds also remain: suspected-omission reversal at 28/18 candidate
flips or 6/4 groups, and two-sided reversal at 12/9. These are fixed-prediction
hypothetical bounds, not empirical errors and not refit analyses.

SAM 3 provenance is `CACHE_CONFIG_VERIFIED_ONLY`. The cached revision and file
hashes are known, but no active process exists and historical logs do not attest
the old worker's load-time weights or preprocessing. Historical-to-future
comparability is therefore unverified.

The 72-group, seven-query, maximum-1,512-dispatch validation design passes revised
metadata checks and is compatible with the frozen priors. It remains NO-GO pending
separate authorization, checkpoint-comparability disposition, fresh resource
checks, budget and storage confirmation. No held-out labels, internal-test records,
SAM 3/Qwen inference, downloads, conditional Zoom fit, posterior, planner, Bellman
optimization, certificate, agent-loop change, evaluator change, service restart or
git commit occurred.

Aquarium Combined/Roboflow via the GLIP-curated archive remains attributed under
CC BY 4.0. Images and overlays remain internal and are not redistributed.

