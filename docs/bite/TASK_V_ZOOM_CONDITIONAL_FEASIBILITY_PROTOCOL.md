# Task V Zoom conditional-feasibility protocol

Protocol: `bite.task_v_zoom_conditional_feasibility.v1`. Status: **FROZEN
EXPLORATORY CALIBRATION-FIT PROTOCOL**.

The primary cohort is the 30-source-group, seven-query expansion. Its 203
candidate-present states are evaluated separately from the 19-group, two-query
pilot sensitivity cohort. The fixed target is correctness of the original
selected proposal against eligible same-class COCO annotations at IoU 0.50 and
0.75. Focused-proposal correctness never changes that target; no-candidate states
remain a separate endpoint.

M0 is the original Phase 4C-1A score-only out-of-fold prediction. M1 is a pooled,
L2-regularized logistic model with the original score, focused-minus-original
score change, an explicit score-change-observed indicator, and fixed indicators
for ambiguous association, no alignment, and execution failure. Unique alignment
is the reference category. Missing score change is imputed to the training fold's
observed mean, which becomes standardized zero, while its observed indicator stays
false. Thus an unavailable change is not represented as an observed zero.

The optional secondary comparator adds exactly one root-frame box-IoU feature.
It uses the same fold-local missing-value rule and is not confirmatory. Mask
overlap is excluded because no verified root-frame mask transform exists.
Identifiers, query/class identity, annotation presence, GT association and all
offline diagnostic labels are forbidden predictors.

The original endpoint-specific three-fold source-group assignments are reused.
All transformations and M1 coefficients are fitted inside each training fold.
M0 and M1 use identical candidate IDs and evaluation folds; the full-fit frozen
prior is never evaluated in-sample as M0. Primary loss is paired M1-minus-M0
Brier score. Log loss and error at 0.5 are secondary. Uncertainty uses 2,000
paired percentile source-group bootstrap draws with seed 461, shared across model
comparisons. Candidate rows are not bootstrapped independently.

All candidate-present cases, including 21 ambiguous associations and six
no-alignments, remain in the primary intention-to-observe analysis. Aligned-only
results are selection-biased diagnostics. The exact-repeat, shuffled-Zoom and
synthetic-signal checks are implementation controls and cannot tune the real
model.

The machine protocol is
`outputs/bite/phase04c1d/protocol/zoom_conditional_feasibility_v1.json`.
This is development fitting against an annotation proxy, not blind validation.

Aquarium Combined (Roboflow), obtained through the GLIP-curated archive, is
attributed under CC BY 4.0. Source imagery remains internal.
