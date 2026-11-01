# Phase 4C validation collection protocol

Protocol: **`bite.task_v_validation_collection.v1`**. Status:
**FROZEN_DESIGN_NOT_EXECUTED**.

The metadata-only selection uses all 72 groups in the frozen Aquarium
`calibration_validation` partition. One representative entry per group is the
lexicographically first frozen entry ID. No validation image, annotation,
detector outcome, or difficulty judgment was loaded for feature/model design.
Internal test remains locked.

Each representative receives seven source-vocabulary queries. The future path
is initial grounding, then—only for candidate-present eligible states—Zoom and
same-class focused grounding. Exact repeat is not routine. The per-state maximum
is three public calls, giving planning bounds of 504 query states and 1,512
logical dispatches. These are not observed counts.

The protocol freezes initial-feature and focused-feature schemas, annotation and
visual endpoints, candidate selection, explicit missing/ambiguous handling,
three prior comparators, calibration metrics, grouped bootstrap uncertainty,
failure accounting, raw-before-label persistence, and source/checkpoint
compatibility. Exact SAM 3 worker revision must be attested before collection;
any checkpoint or protocol change requires a new run identity.

No canary, GPU inference, or model call was executed in Phase 4C-1A.

