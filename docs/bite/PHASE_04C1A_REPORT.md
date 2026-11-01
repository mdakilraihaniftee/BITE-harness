# Phase 4C-1A — exploratory prior calibration and frozen validation design

Report date: **2026-11-01**. Status:
**ENGINEERING_SUCCESS / PROXY_PRIOR_EXPLORATORY / HUMAN_REVIEW_PENDING**.

This phase hardened the existing review workflow with server-enforced blind
events, defined a separate visual endpoint and optional human box contract,
cross-fitted three compact annotation-proxy priors, quantified grouped
uncertainty, generated 12 nondeployment model cards, and froze—but did not
execute—the 72-group validation protocol.

The primary expansion experiment uses 30 source groups and 203 candidates.
Three deterministic group-disjoint folds support both IoU endpoints. Score-only
improves primary .50 Brier from 0.129805 to 0.085108. Adding relative area gives
0.085152 and therefore no consistent incremental improvement. The pilot remains
a sparse sensitivity cohort with only four/three positive-bearing groups.

Human reviews remain 0/235 queued cases. All source hashes and sampling
probabilities reproduce, omission prevalence and agreement remain unreported,
and no unfinished visual record enters fitting. The fitted label is explicitly
the imperfect COCO annotation proxy.

No new SAM 3/Qwen inference, training, dataset/checkpoint download, Zoom
likelihood, posterior update, validation canary, planner, controller, evaluator
change, or certificate occurred. Original artifacts and COCO annotations were
not rewritten. The internal-test partition was not accessed.

Machine outputs are under `outputs/bite/phase04c1a/`. Aquarium Combined
(Roboflow), obtained through the GLIP-curated archive, is CC BY 4.0; images stay
internal and are not redistributed.
