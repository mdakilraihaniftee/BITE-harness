# Task V focused-evidence analysis

This report keeps three quantities separate: correctness of the original
candidate hypothesis, the runtime association of focused evidence, and offline
localization quality of the focused proposal. Focused results never relabel the
original hypothesis.

## Original 20-group pilot

All 38 candidate states have paired focused observations. At IoU 0.50:

| Original hypothesis | Focused target support | Ambiguous | No alignment |
| --- | ---: | ---: | ---: |
| Correct | 4 | 0 | 0 |
| Incorrect | 28 | 5 | 1 |

At IoU 0.75, the corresponding rows are correct 3/0/0 and incorrect 29/5/1.
Thirty-two uniquely aligned focused proposals changed both geometry and score.
The same assigned GT instance was established for 4 candidates at IoU 0.50 and
3 at IoU 0.75. These counts show that focused target support is common under
both hypothesis classes; changed boxes or scores are not evidence of corrective
causal benefit by themselves.

All 38 repeat branches are exactly equal in persisted full-precision boxes,
scores, masks, and proposal ordering—not merely rounded display values. This is
an observed deterministic baseline for this worker/configuration, not a theorem
about other checkpoints or deployments.

## Seven-class expansion

The expansion contains 203 paired focused observations. At IoU 0.50, incorrect
initial candidates split into 147 target-support, 19 ambiguous, and 6 no-alignment
outcomes; correct candidates split into 29 target-support and 2 ambiguous.
At IoU 0.75 the corresponding target-support counts are 155 incorrect and 21
correct, with 19/6 and 2 ambiguity/no-alignment counts unchanged.

Unique target alignment occurred 176 times. Geometry changed in all 176; score
changed in 172. Same assigned GT was established 29 times at IoU 0.50 and 21 at
IoU 0.75. The five-group repeat control produced 35/35 exact full-precision
box, score, and mask repeats.

These outcomes do not provide a clean descriptive separator: target support is
frequent for both correct and incorrect initial hypotheses, and 21 expansion
pairs remain association-ambiguous. No likelihood, information gain, causal
effect, posterior, or statistical significance was estimated. The paired tables
are in `outputs/bite/phase04b2b3/analysis/`.

Source attribution: Aquarium Combined (Roboflow), GLIP-curated archive,
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). No source-derived
image is embedded here.
