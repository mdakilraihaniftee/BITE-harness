# Branch isolation design

## Frozen state

The collector freezes a live `MemoryStore`; it does not reconstruct execution
state from `bite.observation.v1` or a Phase 4A `state_id`. `freeze_state` deep
copies and serializes the following fields:

| Component | Covered fields |
| --- | --- |
| Store configuration | `modules`, `emit_policy`, `webpage_env_update_limit` |
| `ImagesState` | complete registry entries and pixels, aliases, reverse URL/data indexes, `tool_generated_counter`, `last_snapshot` |
| `BindingsState` | Python values including typed NumPy arrays, binding-name counters, descriptors/field descriptors, `last_descriptors_count` |
| `UrlsState` | webpage registry, reverse URL index, webpage counter and last emitted counter |
| Run history | ordered prefix actions, successful/failed observations, candidate history and logical cost |
| Provenance | nodes, edges and exact crop-frame transforms |
| Execution context | allowed action types and capability/schema/backend/service-config fingerprints |
| Task/history | dataset/sample, question, permitted vocabulary, source group/hash, root ID, configuration identity and optional native messages |

`MemoryRunState.scratch` contains only a transient environment-update builder in
the current repository. It is restored empty so branches do not share a mutable
builder. Direct controlled capability calls do not consume that builder. If a
future tool gives scratch durable execution semantics, the schema must be revised.

## Clone algorithm

`clone_snapshot` verifies snapshot completeness and capability fingerprints, then
constructs a new `MemoryStore` and independently decodes every mutable registry,
set, descriptor, binding value, counter, history list and provenance mapping.
NumPy values are reconstructed with dtype and shape. Immutable image bytes may be
shared on disk by content hash, but each branch receives independent registry and
alias metadata. A branch never holds a mutable reference to the frozen record or
another branch.

The source snapshot is compared before and after multi-branch execution. Tests
mutate an image alias, crop, binding, NumPy value and counters in one clone and
verify the sibling and source are unchanged. Reused identical image bytes still
have branch-local aliases. Candidate IDs include branch and joint-observation
identity, preventing collisions even when geometry is identical.

## Execution boundary

Controlled actions call `BaseCapability.invoke` with the branch's real
`MemoryStore`. This retains JSON-schema validation, image resolution, argument
translation, public router transport, backend-result validation, image/binding
registration and canonical result normalization. A branch-local dispatch probe
records the exact post-validation execution boundary. It is removed after the
call and is not the passive agent observer.

No `MainAgent` or provider adapter is called. Preserved native messages remain
byte-for-byte data only; controlled actions do not invent assistant declarations
or tool-result messages. Thus v1 supports complete tool-level interventions, not
counterfactual VLM continuations.

## Geometry and dependency isolation

Root images start with an identity transform. Zoom reconstructs the original
padding-before-sort/clamp/round recipe. A generated crop receives its own
child-to-parent and composed child-to-root transform. Focused grounding can run
only after the branch has registered that crop. Nested crop composition is
supported by the same frame map. A failed prerequisite stops the path as partial;
the next action is never executed to manufacture a failure sample.

Branch histories include the common prefix but only their own continuation.
Candidate association uses runtime-visible class/root geometry and is explicitly
tentative. Repeats are labeled dependent on the prior matching action and are not
treated as independent source images or Bernoulli trials.

## Remaining limitations

- Complete provider continuation cloning is unavailable; model hidden/KV state and
  Responses reasoning items are not represented.
- Physical retry attempts and billed latency are not exposed by the transport.
- Capability fingerprints attest configuration, not the worker's loaded checkpoint.
- File permissions provide practical immutability; v1 does not use an OS-level
  write-once store.
- The collector validates exact hashes, not scene-level independence. Approved
  calibration partitions remain a separate data-governance prerequisite.
