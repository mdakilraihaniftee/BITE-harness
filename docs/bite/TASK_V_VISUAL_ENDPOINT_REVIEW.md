# Task V visual endpoint review

The historical `bite.visual_plausibility.v1` contract is preserved unchanged.
It leaves “plausibility supported but localization inadequate” unknown, which
is too coarse for a candidate-verification endpoint that requires localization.

New reviews use **`bite.visual_verification.v2`** and blind protocol
**`bite.task_v_blind_adjudication_protocol.v3`**. They record independently:

- object visibly present;
- proposed class correct;
- localization adequate;
- evidence ambiguous;
- localization evidence insufficient.

The composite mapping is:

| Situation | `H_visual` |
| --- | --- |
| presence, class and adequate localization supported | 1 |
| queried object decisively absent | 0 |
| proposed class decisively wrong | 0 |
| object/class supported but box decisively localizes the wrong location | 0 |
| competing instance makes identity ambiguous | unknown |
| localization ambiguous or evidence insufficient | unknown |
| general image evidence ambiguous/insufficient | unknown |

Wrong location is therefore an explicit incorrect proposal even when object
presence is true. Ambiguity is never forced negative. Qualitative localization
is not converted to IoU .50 or .75. Threshold-specific corrected labels remain
unknown unless an independently approved reference-geometry adjudication is
completed. Optional boxes remain nonauthoritative research annotations.

V2 and protocol v3 apply prospectively. Historical v1/v2 records are readable
and are not rewritten. There were zero completed reviews at the version freeze.

