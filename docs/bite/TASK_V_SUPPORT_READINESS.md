# Task V support readiness

The original pilot and expansion are reported as separate designs:

| Cohort | Groups | States | Candidates | H_V +/− at 0.50 | Calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pilot, seed 417, two queries/group | 20 | 40 | 38 | 4 / 34 | 154 |
| Expansion, seed 418, seven queries/group | 30 | 210 | 203 | 31 / 172 | 651 |

Raw-count pooling gives 50 groups, 250 query states, 241 candidates, 9 empty
states, 35/206 positive/negative at IoU 0.50, 26/215 at IoU 0.75, 241 focused
pairs, 73 repeat observations, and 805 dispatches. These totals are descriptive
only. The pilot's two-class-per-group policy and expansion's uniform seven-class
policy cannot be treated as one unweighted population estimate, and neither is
the distribution of queries selected by a natural VLM agent.

Both hypothesis classes are now observed, but support remains sparse and
imbalanced. In the expansion, jellyfish is negative-only at IoU 0.50 and the
large-size cell is negative-only. Other class cells contain both outcomes but
some have only 2–4 positives. Same-image classes, crops, and repeated calls are
dependent; row-level confidence intervals would be invalid.

Focused target support does not descriptively separate correct from incorrect
initial candidates: it appears for 29/31 correct and 147/172 incorrect expansion
candidates at IoU 0.50, with 21 ambiguous and 6 unaligned pairs overall. The
observed repeat control remains exactly deterministic (73/73 across cohorts),
so it contributes deployment-specific stability evidence, not an independent
likelihood replicate.

**Readiness decision:** do not begin a general class-conditional Task V
probability model. Class-specific kernels are too sparse, and annotation-negative
states require visual review. If a later phase is separately approved, the
scientifically defensible first fit is a restricted pooled model with
source-group-aware validation, explicit cohort/design covariates, held-out
calibration-validation data, and conservative abstention. No probability was
fitted here.

The full machine-readable, design-stratified assessment is
`outputs/bite/phase04b2b3/analysis/task_v_support_summary.json`.

Source attribution: Aquarium Combined (Roboflow), GLIP-curated archive,
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
