# Phase 4C-1D — conditional Zoom feasibility and matched-worker preparation

Report date: **2026-11-02**. Status: **ENGINEERING_SUCCESS / ZOOM
INCREMENTAL SIGNAL INCONCLUSIVE / CHECKPOINT BRIDGE PENDING**.

The authoritative GT-free runtime table reproduces all 203 expansion candidates
in 30 source groups. It contains 176 unique associations, 21 ambiguous
associations and six no-alignments, with no execution failures or invented
focused scores. Original candidate labels, candidate identities and endpoint-
specific Phase 4C-1A folds reproduce exactly.

The prespecified restricted M1 adds signed focused-score change plus explicit
association/missingness to the initial detector score. At IoU .50 it changes
Brier from 0.085108 to 0.085342 (difference +0.000235, grouped 95% interval
[-0.000737, +0.001254]). At .75 it changes 0.075511 to 0.074823 (difference
-0.000688 [-0.001734, +0.000168]). Both intervals cross zero and directions
differ. The optional geometry comparator also remains unresolved. Pilot and
negative-control results do not justify another feature search.

Always-Zoom costs 406 additional logical calls. It introduces two net .50
errors and avoids one .75 error before charging any action penalty. This is an
offline observed comparison, not a policy value or end-to-end agent result.

The dependence analysis explains why a crop derived from the original proposal
and processed by the same SAM 3 backend is not independent verification. M1 is
a discriminative development model, not a generative observation kernel. No
likelihood, posterior, information-gain theorem, planner or certificate follows.

An opt-in attested-worker plan verifies the cached immutable revision and actual
`sam3.pt` artifact without loading it. A 210-initial-call/630-total-call fit-only
bridge protocol freezes comparison tolerances, but neither the worker nor bridge
was executed. Historical checkpoint/preprocessing identity remains unverified.

No validation/internal-test inference, SAM 3/Qwen call, checkpoint or dataset
download, service restart, underlying-model training, agent/evaluator change,
human-review rewrite, posterior update, planner, commit or reset occurred.

The research decision is `ZOOM_INCONCLUSIVE_MORE_FIT_EVIDENCE_NEEDED`. Stop
after this phase. Any new fit collection, worker startup, bridge or validation
requires separate authorization.

Aquarium Combined (Roboflow), obtained through the GLIP-curated archive, is
attributed under CC BY 4.0. Images and derived visual artifacts remain internal.
