# Task V action-space reassessment

## Exact repeat

All 73 recorded exact-repeat controls reproduced boxes, scores, and masks under
the observed deployment. Repeating grounding costs one logical dispatch and,
for this deterministic same-checkpoint regime, adds no observed output
variation. It should remain a limited stability/control action, not a primary
verification action and not an independent likelihood factor. This conclusion
does not extend to stochastic serving, different checkpoints, or altered
preprocessing.

## Zoom followed by focused grounding

Zoom plus focused grounding costs two logical dispatches and changes the input
pixels and proposal set. It therefore produces a new observation event, but it
uses the same source image, derives the crop from the original proposal, and
uses the same SAM 3 backend. These dependencies are explicit.

The richer features are technically valid and plausibly useful for localization:
root-frame agreement, displacement, area/width/height change, score change,
proposal counts, ambiguity, boundary contact, and rank change. Descriptively,
however, annotation-positive and annotation-negative cases overlap heavily.
Unique aligned support occurred in 4/4 versus 28/34 pilot cases and 29/31 versus
147/172 expansion cases. Median root IoU was near 0.97 in every aligned cell.
Human annotation adjudication is still pending. The current evidence therefore
does not justify claiming a positive verification-risk reduction.

For a first restricted model, Zoom can remain an experimental observation whose
incremental predictive value must beat compact no-new-tool baselines on held-out
source groups. If it does not, it should not be promoted to a verification
action merely because its box or score changed.

## Future action proposals

If the restricted Zoom model fails, future work may separately evaluate a
verified independent detector, a differently trained visual analyzer, an
independent consistency check, a targeted VLM inspection, or a runtime-grounded
crop/query policy with stable target association. Each requires a separately
versioned checkpoint, observation contract, dependency analysis, and controlled
collection. None was installed, downloaded, launched, or endorsed in this phase.

