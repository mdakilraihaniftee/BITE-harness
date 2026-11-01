# BITE controlled collection schema v1

Phase 4B-1 defines two contracts: `bite.collection_state.v1` for a frozen,
tool-executable prefix and `bite.collection.v1` for one isolated continuation
branch. Executable schemas are exported as
[`collection_state_schema_v1.json`](collection_state_schema_v1.json) and
[`collection_schema_v1.json`](collection_schema_v1.json). The source of truth is
[`schemas.py`](../../evaluation_kit/bite_collection/schemas.py).

These contracts generate research data. They do not fit probabilities, update a
belief state, select actions for `MainAgent`, or establish causal effects on a
subsequent VLM policy.

## Snapshot identity and completeness

`snapshot_id` is `snapshot:<state_digest>`. The digest is SHA-256 over canonical,
sorted JSON for the task, complete serialized `MemoryStore`, capability
fingerprints, ordered prefix actions/observations/candidates, provenance,
prefix cost and preserved native history. Image bytes participate in the digest.
Persisted images are externalized by raw-byte SHA-256; loading rehydrates the
exact data URL and verifies both the artifact and state digest.

The digest deliberately excludes live Python client/socket objects, credentials,
service process state, transport retry subattempts, wall-clock timestamps and
unobservable model hidden state. Capability compatibility is instead checked by
public-schema, backend, concrete-name and service-config digests before cloning.
The environment-update builder in `MemoryRunState.scratch` is ephemeral and is
reconstructed empty; it is not needed by direct public capability invocation.

`snapshot_completeness=tool_execution_complete` means every registered image has
locally frozen bytes and the memory/capability state needed for a direct tool
continuation can be restored. Any lazy image without bytes makes the snapshot
`incomplete`, and the branch cloner rejects it. Provider-native history, when
available, is preserved with `history_mode=preserved_not_extended`; collection
actions never append fabricated assistant calls. Complete VLM continuation is
explicitly unavailable in v1.

## Branch identity and controlled actions

`branch_id` is a stable digest of collection run, parent snapshot, declared
selection design, selected path and branch index. Every branch records the parent
snapshot ID and state digest. `selected_path` is ordered and keeps zoom and
focused grounding as two actions. Each action has
`origin=controlled_collection_action`, public capability/backend/arguments,
dependency metadata, estimated cost, controlled call ID, dispatch state and
actual logical cost.

`eligible_actions` is the complete declared alternative set supplied to the
design. `ineligible_actions` preserves excluded templates and reasons such as
`required_crop_not_available`, `insufficient_branch_budget` or
`alternative_backend_not_configured`. Ground truth is never an eligibility input.

For deterministic declared coverage, path inclusion probability is `1`. For
uniform sampling without replacement, `selection_probability` is the marginal
inclusion probability `k/N`, `path_draw_probability` is the conditional
probability at that draw, and `selection_steps` records the remaining population.
The RNG and seed are separate from VLM decoding randomness. Ordinary observer
traces retain null propensities under the Phase 4A schema.

## Observations and outcomes

One dispatched capability call produces one `joint_observation_id`, regardless
of the number of detections. Candidate rows share its logical cost-accounting ID.
Each joint observation preserves canonical boxes/scores, mask hashes, raw-result
media hashes, resolved source image/frame, artifacts, latency, success/failure and
the Phase 4A outcome taxonomy. Missing physical-attempt telemetry remains null.
An ineligible action is not dispatched and costs zero. A dispatched backend
failure costs one. Empty detections, missing observations, invalid results and
planning-ineligible actions remain distinct.

Generated crops and overlays are persisted once under content-addressed
`observations/artifacts/` files. Branch JSON contains immutable references rather
than repeated image bytes. Crop geometry records integer parent rectangle,
parent/child dimensions and child-to-parent/root transforms.

## Cost semantics

- `prefix_cost`: logical dispatches used to create the shared snapshot.
- `branch_cost`: actual continuation dispatches in this branch.
- `hypothetical_path_cost = prefix_cost + branch_cost`: cost for an agent that
  followed this one path.
- `experimental_expenditure_contribution = branch_cost`: actual additional work
  spent collecting this alternative.

The collection manifest sums branch continuation costs once. Candidate count
never multiplies tool cost. Model calls, when absent, are reported as zero;
physical backend attempts remain null until transport-level instrumentation exists.

## Offline label boundary

Runtime snapshots and branches contain `offline_gt_used=false` and are validated
against GT-like field names. After persistence, `build_collection_records` in the
existing Phase 4A package applies the same native COCO matcher independently per
counterfactual branch. It preserves branch, snapshot, propensity, joint
observation and logical cost identities in `bite.calibration.v1`. GT lives only
under `offline_labels` and cannot affect an already saved action or observation.
