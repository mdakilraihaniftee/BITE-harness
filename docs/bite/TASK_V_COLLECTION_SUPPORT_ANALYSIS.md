# Task V collection support analysis

## Decision

The pilot is an engineering success and supports debugging an exploratory
cluster-aware conditional model, but it does **not** yet justify a reliable Task
V probability model or Phase 4C estimation.

Evidence for this decision:

- Both valid and invalid original proposals were observed, and both thresholds
  are represented.
- Only four IoU-0.50 positives and three IoU-0.75 positives exist across 20
  groups. Positive support is too sparse for stable stratification.
- Four of seven query classes have zero positives in this sample. Class-specific
  likelihoods would be unidentified or dominated by smoothing assumptions.
- Exact repeat yielded 38/38 identical boxes, scores, and masks, so it provides
  no empirical conditional outcome variation under this worker configuration.
- Zoom is informative operationally: 32 unique aligned results changed geometry
  and score, five were ambiguous, and one had no aligned proposal. Those outcomes
  require an association-aware observation model rather than a binary success bit.
- Two successful zero-detection states were observed, but neither is an H_V
  negative because no original candidate existed.
- States are clustered by source group, and all repeat/crop observations share
  pixels, query, backend, and checkpoint. Candidate rows are not independent.

## Before Phase 4C

Keep the present 20 groups frozen as a pipeline pilot. Define a separate,
pre-registered expansion inside `calibration_fit` that increases group-level
coverage and prespecifies minimum positive support by class and size without
using `calibration_validation` or `internal_test`. Do not adaptively choose images
from observed SAM correctness. Candidate-positive enrichment, if scientifically
needed, must use runtime-visible prespecified strata or a separately disclosed
sampling design with recorded propensities—not GT correctness.

Before estimation, also freeze:

1. The target-alignment treatment for ambiguous/missing focused results.
2. A clustered resampling or hierarchical analysis unit at source-group level.
3. Whether exact repeat is retained as a deterministic outcome or removed as a
   zero-variation action for this checkpoint.
4. Minimum per-class/per-size support and a held-out calibration-validation gate.
5. Checkpoint identity instrumentation; the current health API does not certify
   the exact worker revision.

No posterior, likelihood, confidence interval, or certificate is reported here.

