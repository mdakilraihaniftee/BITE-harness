# Task V matched-worker bridge protocol

Protocol: `bite.task_v_matched_worker_bridge.v1`. Status: **PREPARED, NOT
AUTHORIZED, NOT EXECUTED**.

The bridge replays only the original 30 expansion `calibration_fit` groups and
exact seven-class query schedule. Initial-only execution is capped at 210
grounding calls. If focused branches receive separate authorization, the total
cap is 630 logical calls. These are planning maxima, not calls made in this
phase.

The future worker must first emit a valid load-time attestation for pinned
revision `3c879f39826c281e95690f02c7821c4de09afae7` and `sam3.pt` hash
`9999e234...c9e`. Source hashes, input dimensions, candidate presence, selected
rank, proposal count and failure category must agree exactly. Frozen numerical
tolerances are maximum box-coordinate difference `1e-4` pixels, matched box IoU
at least `0.999999`, and maximum score difference `1e-6`.

Missing attestation, identity/query mismatch, categorical mismatch, numerical
disagreement outside tolerance, unauthorized focused calls, or failed resource,
storage and resume preflight is NO-GO. Thresholds may not be changed after
seeing bridge results.

Agreement supports functional consistency on the tested fit sample; it does not
retroactively prove identical historical weights. Material disagreement requires
a versioned fit-only recollection and refit plan before blind validation. The
bridge does not access calibration-validation or internal-test data.

Machine protocol:
`outputs/bite/phase04c1d/matched_worker_bridge/protocol.json`.
