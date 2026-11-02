# Task V optional human-review status

Status: **OPTIONAL SUPPLEMENTAL REVIEW — PARTIAL**.

Twenty finalized human judgments were validated against their case, annotation,
candidate, reviewer, immutable blind-event, and protocol identities. They comprise
20 blind first-pass submissions, 20 GT reveals, one post-reveal adjustment, and 20
final completion records. No event chain is incomplete. All records use human
reviewer `ai5377`, adjudication protocol v1 and blind protocol v3.

The 235-case queue union is 20 complete and 215 pending. Set A is 20/120 complete;
Set B is 19/228 complete because the sets overlap. Across all 241 candidate review
cases, 221 have no finalized judgment. The frozen 25-case independent second-review
subset is not complete.

At IoU .50, the partial descriptive cross-tab is:

| Annotation label | Visual positive | Visual negative | Class ambiguous | Localization ambiguous |
| --- | ---: | ---: | ---: | ---: |
| Negative | 0 | 12 | 4 | 2 |
| Positive | 1 | 1 | 0 | 0 |

One annotation-negative review explicitly flagged a possibly missing annotation;
six visual labels were ambiguous, and sixteen controls marked localization
inadequate. These counts are supplementary and include neither a completed
probability sample nor independent reliability assessment. They do not estimate
dataset-wide omission prevalence and do not replace, correct, or refit COCO labels.

All original completion and blind-event files remain in their existing locations;
the phase stores only their validation summary and hashes. Human review no longer
blocks annotation-proxy work, but visual-truth and omission-prevalence claims remain
gated. The machine summary is
`outputs/bite/phase04c1c_revised/optional_human_reviews/status.json`.

