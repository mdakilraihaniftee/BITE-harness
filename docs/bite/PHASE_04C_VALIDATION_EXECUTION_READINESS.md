# Phase 4C annotation-proxy validation execution readiness

Status: **METADATA PREFLIGHT PASS / EXECUTION NO-GO**.

The unchanged `bite.task_v_validation_collection.v1` design contains 72 disjoint
calibration-validation source groups, one representative image per group, and the
seven frozen Aquarium queries. It permits at most 504 initial query states and
1,512 logical dispatches. The candidate is the highest retained initial detector
score with stable detector-rank tie-breaking. Eligible follow-up is Zoom followed
by same-class focused grounding; routine exact repeat is excluded.

The earlier verified split report remains valid: 277 fit groups, 72 validation
groups, 50 locked internal-test groups, zero group overlap, and zero quarantined
validation images. This phase rechecked the frozen manifest file identity but did
not open held-out correctness labels or internal-test records.

Future execution order is fixed: collect initial SAM 3 output; extract GT-free
features; apply and persist the frozen prior before action or GT; collect isolated
Zoom/focused evidence for eligible states; finalize raw evidence and provenance;
then open official GT, label the original candidate, and evaluate the unchanged
prior. Zoom evidence remains separate and cannot revise the frozen initial
probability in this evaluation.

Human review is not an execution gate for this COCO endpoint. Current NO-GO reasons
are separate researcher authorization, an explicit checkpoint-comparability
decision, fresh worker/resource readiness, confirmed budget, and confirmed storage
identity. Resume/corruption detection, raw-before-label persistence, branch
isolation, transforms, and logical costs remain required. The machine contract is
`outputs/bite/phase04c1c_revised/validation_preflight/preflight_v2.json`.

