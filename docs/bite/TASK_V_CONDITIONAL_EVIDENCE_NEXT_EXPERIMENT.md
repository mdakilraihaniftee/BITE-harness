# Task V conditional-evidence next experiment

Status: **DESIGN ONLY — NOT FITTED**.

The next scientific question is whether Zoom followed by focused grounding improves
prediction of the original candidate's fixed COCO label beyond initial state `s0`.
Compare frozen `p0=P(H|s0)` with restricted `p1=P(H|s0,O_zoom)` using paired
source-group `Delta Brier = Brier(p1)-Brier(p0)`; negative favors the tool-informed
model. Also compare constant prevalence, raw SAM 3 score, frozen score-only prior,
frozen compact prior, and an optional prespecified deterministic consistency rule.

Existing evidence is insufficient: 73/73 exact repeats were identical; focused
geometry changed, but median aligned IoU was approximately 0.97 and target
association occurred for both correct and incorrect originals. Same image, crop,
and backend induce dependence. Repeated outputs must not be multiplied as
independent likelihood factors; the required object is `K_a(o|H,s0)`.

Feature development may use jointly observed calibration-fit branches only and must
freeze before held-out evaluation. The 72 validation groups remain untouched for
paired grouped evaluation. Raw score uses the same cases, labels and groups. Stop,
repeat and Zoom/focused costs are 0, 1 and 2 logical calls respectively, but no
expected information gain or risk-reduction claim is permitted before a validated
likelihood exists. A null held-out result should motivate a complementary action,
not a forced positive conclusion.

Machine design:
`outputs/bite/phase04c1c_revised/conditional_evidence_design/conditional_evidence_experiment.json`.

