# Phase 4C validation preflight

Status: **ENGINEERING_COMPATIBLE / INFERENCE_NOT_AUTHORIZED**.

The frozen Aquarium source approval, CC BY 4.0 attribution, source ID, archive
identity and partition manifest reproduce. The manifest has 277 fit groups, 72
calibration-validation groups and 50 locked internal-test groups. All group
intersections are empty, and no quarantined image occurs in validation. This
preflight reads metadata only; it does not open validation annotations, inspect
correctness labels, run a canary or invoke a network model/tool endpoint.

`bite.task_v_validation_collection.v1` remains unchanged: 72 representatives,
seven fixed queries, at most 504 states and 1,512 logical calls, highest-score
stable-rank candidate selection, initial grounding followed by eligible
Zoom→same-class grounding, raw-before-label persistence, and atomic state-level
resume. Internal test remains locked.

The blind evaluation plan freezes score-only as primary and constant/compact as
comparators. Before a separately authorized run, each prior is refitted once on
all eligible seven-query expansion `calibration_fit` rows only. Beta(1,1), L2
lambda 1, features, train-only standardization, identity score handling,
unsupported missing values, Brier primary loss and paired grouped uncertainty
are frozen. Validation may remain model-selection data, but must not later be
described as an untouched final test if used to adjust the system.

Checkpoint provenance remains the blocking gate. The cache historically
contains `facebook/sam3` revision
`3c879f39826c281e95690f02c7821c4de09afae7`, but existing worker health only
reported `status=ok`. It did not attest the loaded identifier/revision, weight
hash, preprocessing configuration, or worker code/config revision. The earlier
and future workers therefore cannot yet be claimed identical. No worker was
restarted or modified to change this result.

A separate collection run may be authorized only after checkpoint attestation,
explicit researcher authorization, and a fresh resource/service preflight.
Human visual labels remain pending, but annotation-proxy collection engineering
is otherwise compatible.

