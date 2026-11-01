# Task V annotation reliability

**Decision: human adjudication pending.** This report separates reliable
reconstruction of the annotation endpoint from unresolved visual correctness.

The 241 candidate-present states reproduce the frozen COCO-based labels:

| Cohort | Candidates | Positive @ 0.50 | Negative @ 0.50 | Positive @ 0.75 | Negative @ 0.75 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Engineering pilot | 38 | 4 | 34 | 3 | 35 |
| Seven-class expansion | 203 | 31 | 172 | 23 | 180 |
| Total | 241 | 35 | 206 | 26 | 215 |

At IoU 0.50, 191 of 206 negatives have no annotated queried-class instance:
32 in the pilot and 159 in the expansion. This is a statement about annotation
scope, not visual absence. Machine-label unknown count is zero because geometry,
class mapping, and annotation scope were reconstructible; it is not evidence
that annotation missingness is zero.

All 241 visual labels are currently `not_reviewed`. Completed human judgments:
**0**. The suspected omission rate and inter-review agreement are therefore
**not estimable**. There are 205 previously identified negative visual reviews
pending; the current interface additionally makes positive controls and other
diagnostic candidates available without changing any historical label.

The probability review set contains 120 candidate cases from 25 sampled source
groups. The targeted set contains 228 cases and is explicitly excluded from
prevalence estimation. Only reviews in the probability sample may contribute
to an omission-rate estimate, with cohort-specific inclusion probabilities and
source-group clustering. Targeted reviews may explain failure modes but cannot
measure their population prevalence.

The Phase 4B-2B-3 geometry audit remains valid: every candidate label, image
hash, annotation identity, transform, and eligible IoU reproduced, and no
systematic implementation defect was found. The unresolved issue is semantic
annotation completeness and visual identity, not label-pipeline arithmetic.

Accordingly, `H_annotation` remains usable as a precisely defined proxy endpoint
for engineering analysis. A real-world `H_visual` model is not ready until the
prespecified human review is completed and disagreement is assessed. No COCO
annotation, calibration record, or benchmark result was altered.

