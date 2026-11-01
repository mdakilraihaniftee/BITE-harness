# Phase 4C restricted model specification

Status: **pre-registered proposal; unfitted**. The supported population is the
cohort-stratified Aquarium calibration-fit query regimes, not arbitrary
VLM-selected queries. Source group is the partition and uncertainty unit.

## Label and prior

The intended primary endpoint is a prespecified reduction of completed visual
adjudication after review reliability is established. Set `H_V=1` only when
object present, class correct, and reasonable localization are all `yes`, while
image inconclusive is `no`. Set `H_V=0` when at least one of those first three
controls is `no` and ambiguity/inconclusive controls are `no`. Any `uncertain`,
class/localization-ambiguous, or insufficient-evidence review remains unknown
and is handled by abstention/sensitivity analysis. A possible annotation
omission can therefore be visually positive without changing COCO. The unchanged
annotation label at IoU 0.50 is a proxy/sensitivity endpoint; unresolved visual
labels are never coerced to it.

For supported state (s), the first prior is

\[
p_\theta(s)=P(H_V=1\mid s).
\]

Candidate predictors are initial SAM 3 score, log relative proposal area,
cohort/query-design identity, and a limited pooled class representation. The
first implementation may use a regularized pooled logistic model or an equally
compact monotone alternative. Saturated per-class models, GT IoU, GT identity,
and post-action fields are forbidden.

## Conditional Zoom observation

For the frozen Zoom then focused-SAM-3 regime,

\[
K_z(o\mid H_V,s)=P(O_z=o\mid H_V,s).
\]

This is a statistical model under the controlled collection design, not a causal
law for arbitrary agents. A first coarse outcome should distinguish unique
alignment with prespecified consistency bands, other unique alignment,
ambiguous association, no alignment, and execution failure. Candidate continuous
features are root IoU, normalized displacement, score change, log area ratio,
and proposal-count change. Any band must be frozen from scientific/engineering
tolerances before validation, not tuned for best development accuracy.

The future update, if the models pass validation, is

\[
P(H=1\mid s,o,a)=
\frac{K_a(o\mid H=1,s)p_\theta(s)}
{K_a(o\mid H=1,s)p_\theta(s)+K_a(o\mid H=0,s)[1-p_\theta(s)]}.
\]

No likelihood, posterior, or calibration curve was computed in Phase 4B-2B-4.

## Comparators and evaluation

The frozen comparisons are: (A) constant prevalence within declared design,
(B) detector score only, (C) compact initial-state features, and (D) the same
initial state plus observed Zoom evidence. Held-out metrics are Brier score,
log loss, reliability diagnostics, and forced binary-decision error. Intervals
use source-group bootstrap or cluster-robust sensitivity analysis; row-i.i.d.
intervals are forbidden.

The existing 50 collected groups are calibration-fit development data and keep
their pilot/expansion identities. The 72 calibration-validation groups require
the same branch protocol only after feature, outcome, and modeling decisions are
frozen. The 50 internal-test groups remain locked until the full protocol is
frozen. No class query, crop, or branch from a group may cross partitions.

The model abstains or reports a supported uncertainty set for unsupported
class/context, no candidate, unknown fitting label, invalid coordinate
provenance, missing action outcome, unsupported backend revision, inadequate
group support, or serious distribution shift. No numerical fallback threshold
is invented for these cells.

## Link to later planning

Under equal binary costs, stop risk is

\[
R_{stop}(p)=\min(p,1-p).
\]

The conceptual one-step action risk and reduction are

\[
R_{after}(s,a)=E_{O_a\mid s}[R_{stop}(P(H=1\mid s,O_a,a))],
\qquad
\Delta R(s,a)=R_{stop}(p(s))-R_{after}(s,a).
\]

Repeat costs one dispatch and Zoom-focus costs two. Geometry changes do not
guarantee positive \(\Delta R\). Candidate verification also omits missed
objects, final-answer errors, feasibility, model misspecification, and other
end-to-end agent losses. This phase implements neither a planner nor an
identifiability certificate.

