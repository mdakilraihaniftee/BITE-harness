# Frozen calibration protocol v1

Machine configuration: [calibration_protocol_v1.json](calibration_protocol_v1.json).
Schema: [calibration_protocol_schema_v1.json](calibration_protocol_schema_v1.json).
Envelope: **`bite.calibration_protocol.v1`**. Current state:
**`FROZEN_SOURCE_PENDING`**.

## Original task and schedule

The source manifest supplies the only permitted class vocabulary. Images are
sampled by `source_group_id`. For each group, class names are sorted and two are
selected by SHA-256 of group, class and seed `417`; per-image GT presence is not
read. Positive, negative and ambiguous strata are computed offline only. Empty
and failed initial groundings are retained.

Each image/query state receives one root `Visual_Grounding_Tool` prefix. Candidate
verification uses the highest retained score with stable detector-rank ties.
Discovery uses the fixed 2×2 root grid. Boxes are original-image pixel xyxy;
nested crop coordinates return through exact integer translation transforms.

## Action paths

| Path | Same hypothesis | Calls | Logical continuation cost | Dependence / eligibility |
| --- | --- | --- | ---: | --- |
| `V_repeat` | same candidate/class | repeat root grounding | 1 | same backend/pixels/query; explicitly dependent |
| `V_zoom_focus` | same candidate/class | Zoom, focused grounding | 2 | requires valid candidate frame and actual registered crop |
| `V_alias_query` | same class/object | root grounding with frozen alias | 1 | only when source-level alias exists; never image/GT generated |
| `D_repeat_broad` | same region/class discovery event | repeat broad grounding | 1 | redundancy measurement |
| `D_grid_focus` | same region/class discovery event | fixed-grid Zoom, focused grounding | 2 | requires actual registered grid crop |

Alternative-backend verification is unavailable. A horse query after a person
proposal switches hypotheses and is not a Task V branch.

The maximum continuation budget is 3 public capability dispatches. Dispatched
failures cost one; pre-dispatch rejections cost zero. Zoom→focus costs two.
Physical transport attempts, latency, and model usage are distinct telemetry.

## Selection and failures

The engineering pilot uses `deterministic_coverage.v1`. Later expansion may use
`uniform_without_replacement.v1`, recording the frozen eligible set, seed,
MT19937 identity, marginal `k/N`, and conditional `1/remaining` probabilities.
Every branch starts from the same `bite.collection_state.v1` snapshot.

The reference client permits eight retries after the initial attempt for timeout,
connection, and configured transient HTTP classes, retaining one logical action
identity. The tool timeout is 600 seconds and configured worker timeout is 30
seconds. No new adaptive retries are introduced. Empty results, backend failure,
invalid result, missing observation, ineligibility, and a failed prerequisite are
different outcomes. A failed prerequisite ends the composition as partial.

## Identity and persistence

No Qwen or other orchestrator call is planned. The grounding backend is
`sam3_segment`. Phase 1 observed cached repository revision
`3c879f39826c281e95690f02c7821c4de09afae7`, but the worker contract does not
attest its exact loaded checkpoint; `checkpoint_verified_by_worker=false` is
frozen. Scores are retained post-threshold sigmoid scores, not full logits.

Snapshots and raw branches are persisted before offline labels. Source hashes,
resolved image/frame, crop transforms, capability/config/source digests and
failures are retained. GT is admitted only to the later `bite.calibration.v1`
label export. This protocol cannot become `FROZEN_READY` without an approved,
checksummed grouped partition manifest.
