# Collection integrity revalidation

The collector now derives integrity claims from persisted evidence instead of
literal booleans. Each new state records a hash-chained sequence:

1. `runtime_started` with GT closed;
2. `raw_finalized` with the raw completion digest;
3. `offline_gt_open_authorized` referencing that digest;
4. `labels_finalized` with label-file digests.

Validation reads completion hashes, the parent snapshot, each branch record,
parent IDs/digests, branch terminal snapshots, source/crop provenance,
operational-state keys, and logical costs. Reused branch-local counter names are
correctly interpreted in their isolated branch namespaces; artifact content and
terminal digests—not counter spelling alone—determine contamination.

## Historical pilot

All 40 states, content hashes, parent identities, operational-state leakage
checks, branch costs, and source provenance pass. Sibling contamination count is
zero. The old run predates stage events, so raw-before-label ordering cannot be
independently reconstructed and is explicitly reported as a historical
limitation; timestamps are not substituted as proof.

## Expansion

All 210 states pass content-hash, parent-snapshot, branch-isolation, GT-free
operational-state, logical-cost, and stage-order validation. Raw-before-GT is
independently reconstructible for 210/210 states. The two-group canary passed
14/14 states with 40 dispatches; one no-candidate state correctly had no branch.

A completed resume performed 0 new dispatches, resumed all 210 states, retained
the 651-call total, and left the complete state-tree digest unchanged at
`af25baee5fabc8c4b9271650ff3752809954b7ec2af30dcc3d1e414816b07823`.
Artifact corruption tests fail closed.

The audit command was run with router and SAM3 URLs set to dead port 9 inside
the restricted sandbox and still succeeded. Live preflight is therefore
separate from artifact-only auditing.

Machine reports are `validation/existing_pilot_integrity_v2.json`,
`validation/expansion_integrity_v2.json`, and `canary/canary_gate_v2.json` under
`outputs/bite/phase04b2b3/`.

Source attribution: Aquarium Combined (Roboflow), GLIP-curated archive,
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
