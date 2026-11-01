# Passive observation schema v1

The observer records execution evidence without selecting, blocking or changing
actions. The envelope version is **`bite.observation.v1`**. The executable JSON
schema is [observation_schema_v1.json](observation_schema_v1.json); its source is
[`schemas.py`](../../openvlharness/bite/schemas.py). This schema describes observed
interfaces, not calibrated probabilities or a statistical dependence model.

## Enable and retrieve

Disabled by default; no YAML keys or model-facing schemas were added.

```bash
source scripts/env.sh
export BITE_OBSERVER_ENABLED=true
export BITE_OBSERVER_REFERENCE_BUDGET=15
export BITE_OBSERVER_RUN_ID=my_experiment
```

`BITE_OBSERVER_ENABLED` accepts true/1/yes/on and false/0/no/off/empty,
case-insensitively. Invalid values fail configuration. The reference budget is
a nonnegative integer or `none`; default 15. It is **recording only**. Remaining
budget may become negative without changing execution. The optional experiment
run ID defaults to a fresh UUID when absent. Do not put secrets in identifiers.

`MainAgent.generate()` returns the envelope under `extra_records.bite_observer`.
The evaluator additionally atomically writes
`<dataset-run>/bite_observations/<sample-id>.json`, alongside the normal canonical
`results/<shard>/<sample-id>/record.json`. Presence of observer sidecars prevents
normal successful-run file-db cleanup, retaining the raw evidence they reference.
Default-off runs keep the previous cleanup behavior. A sidecar write failure is
recorded as incomplete capture; it does not prevent the normal prediction commit.

The schema and origin-labeled example are exported without changing the agent's
prediction, prompts, native messages, tools, backend results or scorer. No observer
hook calls a model, worker, image download, or other external API.

## Identity and envelope

| Field | Meaning |
| --- | --- |
| `schema_version` | Exact version string above |
| `run_id` | User-supplied experiment ID or UUID |
| `sample_id` | String form of `task_id`, or null |
| `question_id` | Fresh UUID for every generate invocation, including repeated sample IDs |
| `budget` | Counters, reference limit, remaining budget, and unsupported attempt metadata |
| `events` | Ordered event objects, with sequential `event_0001` IDs |
| `artifacts` | Image metadata/geometry and binding references; no repeated image bytes |
| `provenance_nodes` | Image, action, observation, detection, binding and backend nodes |
| `provenance_edges` | Directed typed relationships with optional evidence basis |
| `capture_complete` | False if an observer hook or sidecar write failed |
| `capture_errors` | Hook and exception type only; no exception text containing possible secrets |

Event/action/observation numbers restart for each question. Scope identities by
`(run_id, question_id, local_id)`; sample ID or image ID alone is insufficient.
Logical action IDs are `action_0001`, observations `observation_0001`, and detection
IDs `<observation_id>:detection_0000` (zero-based rank). Provider-native call IDs
are copied unchanged into separate fields; observer IDs never enter native history.
Image artifact IDs are `image:<memory-id>`, bindings `binding:<binding-id>`, and
backend nodes `backend:<backend-name>`. Unknown custom backends get action-specific
nodes so unrelated unknown backends are not falsely associated.

## Events

Every event has `event_id` and `type`. Fields below are exhaustive for the current
producer, including nullable and diagnostic fields. Version 1 permits additional
diagnostic fields without changing the original agent result.

### `model_turn`

`iteration` is one-based, including Qwen's extra final text-only request.
`model` is the orchestrator's served model identity; `phase` is `regular` or
`final_text_only`. `status` starts as `requesting`, becomes `responded`, or becomes
`request_failed` when the ordinary agent returns after a request failure.
`tools_proposed`, `final_response`, and `parsing_failed` are null before a response;
after parsing they are booleans. Parsing failure means a returned proposal has
the adapter's `parse_error`. Final response means the adapter extracted an answer
with no tool calls, not a claim of task correctness. Provider retries/context-error
fallback within a model turn do not create another logical model iteration.

### `context_change`

`iteration`, `reason`, `before_digest`, `after_digest`, `tools_enabled` record
observable adapter changes. For in-place compaction/replacement, digests are
SHA-256 of sanitized history snapshots; history is not copied into the event.
For provider context-length fallback, the two fields contain the diagnostic
markers `context_error` and `vanilla_fallback`, with reason
`provider_context_error_fallback`. This is an observed control-flow event, not
an extra observer model request. It does not repair existing adapter behavior.

### `tool_proposal`

`iteration`, `provider_tool_call_id`, `capability`, `raw_arguments`,
`parsed_arguments` preserve model proposals, subject only to privacy/media
exclusion. `validation_status` starts as `schema_valid_resolution_pending` or
`rejected`; it becomes `dispatchable` only at the actual execution boundary.
`eligible_for_dispatch` is null while resolution is pending, then boolean.
`rejection_reasons` records native parse/multiple-call errors, unknown tools,
schema failures, unresolved images or forbidden final-text-only proposals.
`logical_action_id` remains null for rejected proposals. Rejections never get a
synthetic native ID or an executed-action event.

### `tool_dispatch`

`iteration`, `logical_action_id`, `provider_tool_call_id`, `capability`, `backend`,
`backend_node_id` identify the dispatched action. `image_inputs` is a list of:

```text
requested_image_id, resolved_image_id, resolution_mode,
width, height, sha256, frame, frame_reason
```

Resolved IDs come from the original resolver's metadata, including aliases and
its sole-image fallback. Metadata uses locally registered pixels only. If there
is no resolved registry image, the list is empty and `source_image_reason`
explains the absence; no extra image fetch is performed.

`started_at` is UTC ISO time after validation/resolution/translation, immediately
before backend execution. `logical_tool_cost` is 1; `physical_attempts` is null.
`selection_dependency` is `unknown`: a literal coordinate equal to a previous
detection is not proof that the model used that detection to select the action.

### `tool_observation`

`iteration`, `logical_action_id`, `observation_id`, `provider_tool_call_id`,
`capability`, `backend`, `image_inputs` join to dispatch. `success` is the original
capability's `ok`, not a new semantic success judgment. `error_category`, `error`,
`exception_type` record original failure fields and observable exception type;
timeouts caught at the capability boundary use `transport_timeout`.
`ended_at` is UTC ISO time and `latency_ms` measures backend execution plus normal
result validation/registration/consumption after the dispatch hook. It excludes
pre-dispatch image resolution and is not total billed service time.
`physical_attempts` remains null.

`canonical_result_type` identifies the returned type. `canonical_result_ref` and
`raw_result_ref` are dotted/bracketed paths into this sample's original agent
result in `record.json`, **not RFC 6901 JSON pointers**. For example:

```text
extra_records.trajectory.chat_history[0].memory_outputs[0].canonical_result
extra_records.trajectory.chat_history[0].tool_responses[0]
```

`artifact_refs` copies `(kind,id)` pairs. An invocation that raises before normal
trajectory commit gets null result references with `result_ref_reason`; its
dispatch is still charged and closed as a failed observation, while the original
exception behavior is preserved.

Grounding adds `grounding`:

| Field | Meaning |
| --- | --- |
| `query`, `model_id` | Canonical query and reported worker identity |
| `size_height_width` | Submitted image dimensions, not automatically root dimensions |
| `detections` | Complete retained list, never silently truncated |
| `boxes_reason` | Null or missing/malformed box reason |
| `masks_available`, `masks_reason` | Presence/type of optional mask list; empty valid list is distinct from missing |
| `score_semantics` | `retained_detector_score_not_posterior` |
| `empty_detection` | True for a successful canonical empty box list |

Each detection contains `detection_id`, `detection_rank`, nullable `label`, raw
`bbox_local_xyxy`, additional `bbox_root_xyxy`, nullable `root_frame_reason`,
retained `score`, `score_reason`, and nullable `mask`. Raw pixel boxes/scores are
not rounded, clamped or recalibrated. A mask record has `sha256` over UTF-8 COCO
RLE counts, `encoding`, `size_height_width`, and `canonical_ref` to the existing
mask value. Hash plus dimensions describe the encoded mask; this is not a hash
of a decoded dense array. Missing/malformed optional scores or masks are explicit
null/reason values, not fabricated zeros. DINO's absent masks remain absent.

Zoom adds `crop` with all of:

```text
parent_image_id, child_image_id, parent_width, parent_height,
child_width, child_height, crop_rectangle_parent_xyxy,
child_to_parent_transform, child_to_root_transform, root_image_id,
geometry_version, root_frame_reason, selection_dependency
```

### `finalization`

`final_model_iteration`, `logical_tool_calls`, `remaining_budget` summarize
execution. `final_output_sha256` hashes the original prediction string.
`original_agent_final_response_valid` means a nonempty result without an original
failure sentinel/error; `validity_semantics` explicitly states this is **not**
task-specific JSON validation or correctness. `model_token_usage` copies the
agent's recorded aggregate usage; `agent_error_present` is boolean. Auxiliary
backend model usage is not automatically included in the agent's existing totals.

### `observer_error`

`hook` and `exception_type` identify capture failure without changing tool/model
execution. `capture_complete=false` prevents silently treating partial evidence
as complete. Scientific numerical values are not silently shortened to recover
from errors. As before, an uncaught agent exception may prevent any result from
being returned; the observer does not turn it into a new successful API response.

## Budget semantics

`reference_limit` defaults to 15 or can be null. `remaining_budget` is exactly
limit minus `logical_tool_calls` (or null with no limit). `enforced` is always
false. Counters are `model_iterations`, `logical_tool_calls`,
`successful_tool_calls`, `failed_tool_calls`, `rejected_proposals`.
`physical_backend_attempts` is null with `physical_attempts_reason`.

One charge occurs at a public capability's **execution boundary after original
schema validation, image resolution and argument translation**, not merely entry
into `BaseCapability.invoke`. Successful, empty, backend-failed, timeout and
invalid-backend-result dispatches each cost 1. Pre-dispatch parse/schema/image
rejections, unknown tools and all rejected multi-call proposals cost 0. Transport
retries remain within one logical call. A custom non-BaseCapability implementation
is observed at its public invocation boundary; internal validation/transport
details are unavailable. This observer never introduces or enforces a limit.

## Geometry and artifact identity

`geometry_version=zoom_padding_before_sort_round_v1` reproduces the existing
zoom calculation, using the original `coerce_xyxy` helper. Padding is applied
before clamping/sorting/rounding; reversed coordinates retain the existing,
occasionally surprising behavior. Pixel size is checked against returned crop
pixels. No crop backend or result contract was changed.

Transforms are 3×3 **translation-only** homogeneous matrices. For integer crop
left/top `(l,t)`, child pixels map to parent `(x+l,y+t)`. Nested transforms compose
as `parent_to_root @ child_to_parent`. Boxes are translated as raw local pixels;
normalized coordinates must first be converted using that frame's own dimensions.
The 600×320 smoke crop `[50,100,650,950]`, padding 50, is `(0,16,420,320)` and
420×304 pixels. Unit tests cover boundaries, rounding and nested crops.

Image artifact fields are `artifact_id`, `kind`, `image_id`, encoded-file-byte
`sha256`, nullable `width`/`height`, `metadata_reason`, aliases and
`coordinate_frames`. Hashes identify encoded bytes, not semantic image identity.
Original inputs have identity transforms. Crop outputs get composed geometry;
same-canvas grounding overlays inherit source geometry when dimensions match.
Other generated images have unknown geometry. No resizing/homography inference
is attempted.

Memory can deduplicate identical image bytes from different crops. The observer
retains all distinct `(root,transform)` possibilities. It does not replace the
old lineage with the last action: multiple incompatible frames produce null root
boxes and `ambiguous_deduplicated_lineage`. Repeated observation IDs remain
distinct even when image artifacts are reused. Bindings contain identity and
their canonical evidence reference, not another copy of all live Python values.

## Provenance relationships

Nodes have `id`, `kind` and applicable identifiers. Backends retain their name,
reported model ID when available, and null checkpoint revision with a reason;
the worker API does not attest a checkpoint revision. Reading a cache ref alone
would not establish which weights a remote process actually loaded.

| Relation | Direction / interpretation |
| --- | --- |
| `uses_image` | Action → resolved input image |
| `produces_image` | Action → registered image, even if deduplicated |
| `derived_from_image` | Generated image → parent image; self-edge omitted for deduplication |
| `produces_observation` | Action → its observation |
| `produces_detection` | Observation → each ranked detection |
| `uses_backend` | Action/observation → identified backend |
| `shares_root_image` | Action → known root image; shared target makes common source explicit |
| `derived_from_observation` | Action → unique prior producer when it consumes an image artifact or supplied binding |
| `produces_artifact` | Action → registered binding |
| `supplied_binding` | Action → binding supplied in its execution context |

An edge's `basis` distinguishes image consumption from a binding supplied to code
context; the latter does not prove that generated code read the binding. If an
artifact has several possible producers or is also an original input, no unique
direct-producer edge is invented. Sequential calls, common pixels, common
checkpoints and numeric box similarity alone never imply a direct dependency.
Graph relationships are not probabilities, causal certificates or estimates of
statistical dependence. Crop-selection intent remains unknown with literal args.

## Privacy, retention and limitations

Observer output excludes the question/GT, evaluator scores/matches, service
configuration, authentication headers and environment values. Credential-shaped
keys and known environment secrets are redacted; inline image data is replaced
with hashes. Scientific numeric arrays are not truncated. Raw masks/media remain
in the existing canonical record instead of being repeated in each event.
No generic sanitizer can certify absence of arbitrary unknown secrets in user
tool text; keep credentials out of task arguments and review artifacts before
publication.

No planner, confidence calibration, posterior update, identifiability bound,
automatic candidate association or enforcement exists. Frame ambiguity, missing
checkpoint attestations, physical attempts and unavailable metadata remain
explicit. The observer does not repair existing Responses reasoning-item
limitations or alter official score-sidecar matching.
