# Task V Zoom model readiness

Decision: **INCONCLUSIVE_INSUFFICIENT_SUPPORT**.

The restricted discriminative M1 is technically valid for the declared
calibration-fit experiment: runtime features are label-free, all 203 cases join,
folds are source-group-disjoint, missingness is explicit, transformations are
fold-local and probabilities are finite. It is not a validated observation
kernel.

No general `K_zoom(o|H,s)` should be fitted now. Only 31/23 positives exist, 27
action observations are ambiguous or unaligned, jellyfish has no positive
support, and same-backend dependence is strong. Primary Brier intervals cross
zero at both thresholds. Annotation omission and historical checkpoint identity
remain material. A larger feature set or density model would be more likely to
overfit than to resolve those limitations.

If later fit-only evidence becomes adequate, a candidate kernel should remain
small and prespecified: condition on a coarse initial-score band plus a pooled
observation category (unique with fixed consistency band, unique other,
ambiguous, absent, failure), use conservative smoothing and retain source-group
evaluation. Bands must be frozen independently of validation outcomes. This is
a future design suggestion, not an implemented kernel or posterior.

The next scientific branch is
`ZOOM_INCONCLUSIVE_MORE_FIT_EVIDENCE_NEEDED`: identify the exact missing
calibration-fit support under a separately approved collection plan. Do not use
held-out labels to repair development support, and do not promote the current
Zoom model to validation merely because one endpoint moved favorably.
