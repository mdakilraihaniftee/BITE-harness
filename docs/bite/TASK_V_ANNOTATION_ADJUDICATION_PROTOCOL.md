# Task V annotation-adjudication protocol

Protocol version: **`bite.task_v_adjudication_protocol.v1`**. Frozen on
2026-11-01. This is an internal, offline protocol for Aquarium Combined
candidate proposals. It does not amend the source COCO file or any official
benchmark output.

## Endpoints

The annotation endpoint and visual endpoint are deliberately separate.
`H_annotation` is preserved at IoU 0.50 and 0.75 with values `positive`,
`negative`, or `unknown`. `H_visual_review` is one of:

- `visually_supported_positive`
- `visually_supported_negative`
- `possible_annotation_omission`
- `class_identity_ambiguous`
- `localization_ambiguous`
- `insufficient_image_evidence`
- `not_reviewed`

A visual judgment never overwrites `H_annotation`. A completed record also
contains human reviewer identity, a timezone-aware timestamp, six tri-state
evidence controls, applicable IoU thresholds, correction defensibility and its
reason, comments, annotation SHA-256, and protocol version. The validator
rejects AI-authored completion, anonymous review, naive timestamps, incomplete
controls, mismatched annotation identities, and duplicate case/reviewer pairs.

## Blind-first procedure

The reviewer first sees the original image, query, initial SAM 3 proposal,
score, size, case ID, and source-group ID. The machine verdict and all GT,
crop, and focused-proposal overlays remain hidden. After making an independent
visual inspection, the reviewer selects **Reveal GT and machine label**. The
revealed view draws same-class GT in green, other-class GT in cyan, the crop in
orange, and the focused proposal in magenta. The original proposal remains red.

The reviewer answers whether the queried object is present, the class appears
correct, the box localizes it, an annotation appears missing, a competing
instance creates ambiguity, and evidence is inconclusive. If proposing a
possible omission, the reviewer must state whether a corrected research label
could be defensible and why. That judgment remains a visual sidecar unless a
separate annotation-amendment process is approved.

Independent second review is supported: records are keyed by case and reviewer.
The validation report preserves agreement or disagreement. It does not silently
resolve conflicts.

## Two review samples

Set A is a source-group sample drawn independently without replacement within
each frozen cohort using seed 420. Its frame is candidate-bearing calibration-fit
groups, because the endpoint concerns observed candidate proposals. Ten of 19
eligible pilot groups and 15 of 30 expansion groups were selected, giving group
and case inclusion probabilities 10/19 and 15/30 respectively. All candidates
in each selected group are retained. The result has 120 cases and covers both
query designs, all seven classes, both annotation labels, all three candidate
size bands, and annotation-present/absent diagnostic categories. Estimates
must remain cohort-stratified and account for source-group clustering.

Set B is a deterministic diagnostic union. It contains 228 cases selected for
one or more of: high-score annotation-negative status, missing queried-class
annotation, insufficient localization, wrong-class/instance or wrong-location
diagnosis, ambiguous focused association, or small candidate size. It includes
all 29 high-score invalid cases. It has no probability-of-selection estimand and
must never be used to estimate annotation-error prevalence.

The union contains 235 cases. Six cases are outside both sets. Pending records
are not human judgments.

## Operation

Rebuild and verify the frozen queue:

```bash
.venv/bin/python scripts/bite/build_task_v_review_queue.py
```

Start the loopback-only interface; no model service is needed:

```bash
.venv/bin/python scripts/bite/serve_task_v_review.py --host 127.0.0.1 --port 8114
```

Validate supplied reviews:

```bash
.venv/bin/python scripts/bite/validate_task_v_reviews.py
```

Completed records are written under
`outputs/bite/phase04b2b4/human_adjudications/completed/`. Review images remain
local. Aquarium Combined (Roboflow), obtained through the GLIP-curated archive,
is CC BY 4.0. No source image or derived overlay is redistributed by this phase.

