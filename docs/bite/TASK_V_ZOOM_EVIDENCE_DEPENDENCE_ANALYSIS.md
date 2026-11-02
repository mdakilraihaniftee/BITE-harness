# Task V Zoom evidence-dependence analysis

The controlled observation is Zoom followed by focused grounding with the same
SAM 3 backend on a crop derived from the original proposal. It costs two logical
calls and is dependent on the initial observation by image content, crop
construction, backend, checkpoint and association rule.

The GT-free runtime table contains 176 unique associations, 21 ambiguous
associations and six no-alignments. No execution failed. Missing focused scores,
score changes and root IoUs remain null for all 27 non-unique cases. Target
association uses runtime-visible class and geometry, not GT identity. Because
the association procedure itself favors geometrically overlapping proposals,
high overlap is not independent confirmation.

At IoU .50, 29/31 positives and 147/172 negatives associate uniquely. Median
root IoU is 0.9740 for positives and 0.9681 for negatives. Median score change
is only 0.0117 for positives but 0.0625 for negatives. At .75, 21/23 positives
and 155/180 negatives associate uniquely; median score changes are 0.0117 and
0.0586. Thus association, high overlap and score increase occur in both classes
and do not act as simple verification signals.

Class-specific M1-minus-M0 Brier changes vary in sign. At .50, penguin improves
most (-0.001962) while stingray worsens most (+0.001658). At .75, fish improves
most (-0.003037). Improvement is not confined to one class, but cells are too
small for class-specific inference. High-score annotation negatives show small
favorable differences, as do no-annotated-class cases, but annotation presence
was used only for offline diagnosis and never as a predictor.

All 73 historical exact repeats reproduced boxes, scores and masks exactly
(38 pilot plus 35 expansion). They are stability controls, not independent
evidence.

The relevant likelihood is `P(O_zoom | H, s0)`, not an unconditional factor
multiplied as though tool outputs were independent. If the conditional
observation distributions are equal under `H=1` and `H=0`, observing Zoom leaves
the ideal posterior unchanged. The experiment does not assume that equality;
it finds that the available sparse data do not resolve a useful difference.

Under a correctly specified distribution, squared-loss projection gives

`E[(H-E[H|S])^2] - E[(H-E[H|S,O])^2] = E[(E[H|S,O]-E[H|S])^2]`.

This identity requires true conditional expectations, compatible populations
and free observations. The empirical cross-fitted model is estimated,
misspecified, finite-sample and costly, so its Brier difference is not the ideal
information gain. `s0` is the recorded computational state, not all information
in the underlying pixels.

Machine diagnostics are in
`outputs/bite/phase04c1d/evidence_dependence/`.
