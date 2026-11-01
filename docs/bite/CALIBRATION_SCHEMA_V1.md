# Offline calibration schema v1

Envelope: **`bite.calibration.v1`**, one JSONL row per observed detection proposal,
or one row for an observed action with no detection candidate. Machine schema:
[calibration_schema_v1.json](calibration_schema_v1.json). Source:
[`evaluation_kit/bite_calibration/`](../../evaluation_kit/bite_calibration/).
The runtime observer never imports this package or receives its labels.

## The two calibration questions

Candidate verification asks whether a proposal corresponds to a correctly
classified annotated object. Tool-outcome calibration asks what an action returns
given a prior state/hypothesis. A new observed proposal can be false or repeat a
previously represented GT object. These tasks need different labels; no likelihood,
posterior, independence assumption or probability fit is implemented here.

## Identity and record groups

Top-level fields are `schema_version`, `partition`, `record_id`, `run_id`,
`question_id`, `sample_id`, `state_id`, `branch_id`, `source_group_id`,
`joint_observation_id` (nullable for a missing result), `runtime_features`, `action`, `outcome`, `offline_labels`,
`evidence`, `matching_protocol`. IDs are deterministic SHA-256 identities of
recorded runtime evidence; repeated processing of identical inputs is stable.

`partition` is development_debug, calibration_fit, calibration_validation,
internal_test or final_evaluation. Current real exports are **development_debug**.
Non-debug export requires a frozen manifest covering the exact image hash and
source group; shared scene/parent/hash groups cannot cross partitions. Merely
having train/val/test in a filename is insufficient.

`state_id` is the action's pre-observation state projection scoped by run,
question and source group. `branch_id` identifies the existing observed trajectory;
it is not a claim that counterfactual branches were collected. The projection is
not a complete model/history/MemoryStore snapshot. A future branch collector must
freeze the complete prior state and explicitly link independent branch clones.

### Group A: `runtime_features`

Contains `candidate`, `association`, `preceding_candidate_ids`, `prior_outcomes`
and `context`. No GT IDs/boxes, annotation files, correctness labels or scoring
information enter this group.

Candidate version **`bite.candidate.v1`** fields:

| Fields | Meaning |
| --- | --- |
| `candidate_id`, `sample_id` | Immutable raw proposal identity, not an asserted physical-object ID |
| `class_name` | Recorded detector label or recorded query fallback; never obtained from GT |
| `source_observation_id`, `source_detection_ids` | Original observer identities |
| `bbox_local_xyxy` | Raw submitted-frame coordinates |
| `bbox_root_xyxy` | Verified root geometry usable for comparison, or null |
| `bbox_root_reported_xyxy`, `frame_reason` | Preserved reported root coordinates and missing/inconsistent-transform reason |
| `root_image_id`, `resolved_image_id` | Recorded frame identity; transform must be known, finite and translation-compatible |
| `source_group_id`, `source_image_sha256` | Independence unit and original-image byte identity |
| `source_backend`, `raw_scores`, `mask_ref` | Retained scores and existing mask hash/reference; no raw image/mask duplication |
| `candidate_origin`, `association_status` | Grounding origin and reversible association status |

Candidate comparison requires common root coordinates, source-image identity and
class compatibility. Default same-object suggestion threshold is IoU ≥0.8;
spatially distinct is IoU ≤0.1; the intermediate band is ambiguous. Incompatible
classes with overlap are conflicting proposals, not proof that either is false.
Unknown frames/classes remain uncomparable. Multiple plausible prior matches
are ambiguous. These are **heuristics**, especially in crowded scenes.

`association_groups` in the summary preserves every raw proposal and pairwise
comparison plus tentative connected components. Connectedness is not an
irreversible identity merge, and transitive links need not form a clique. Changing
thresholds can be tested without changing original boxes/scores or proposal IDs.
The official pooled-score matcher is not used for candidate association.

`context` contains class, raw relative box area, retained score, preceding proposal
count, known overlap/uncomparable counts, root/crop/unknown action frame, shared
backend flag, prior outcomes, pre-action remaining reference budget, source hash,
root dimensions and frame-validity indicator. `state_completeness` explicitly
marks either the Phase 4A observer projection or the backward-compatible Phase
4B-1 `tool_execution_complete_snapshot` producer. These are proposed conditioning variables, not
learned risk features. Relative area is calculated from raw geometry and can
exceed 1 for out-of-bounds proposals.

Proposals are processed in event order then detection-rank order. Earlier proposals
in the same joint observation can appear in `preceding_candidate_ids`. All rows
from that action retain the same action-start `state_id`; these per-proposal
associations are not independent action outcomes.

### Group B: `action` and `outcome`

Actions preserve template name, capability, configured backend, concrete original
arguments, resolved image ID, native call ID, logical action ID, prior state,
execution flag, observation/event reference, latency and physical attempts.
The [action specification](calibration_action_space_v1.json) distinguishes:

| Template | Prerequisite / availability |
| --- | --- |
| `root_grounding` | Registered original image and runtime query; does not require Zoom |
| `repeated_grounding` | Prior same root/query/backend; redundancy measurement, not an independent trial |
| `crop_generation` | Registered image and permitted region from runtime-visible evidence |
| `focused_grounding` | Actual previously registered crop plus query |
| `alternative_backend_verification` | **Not available**; standard config selects one grounding backend; DINO not launched |

Interface support is not a fresh service-health guarantee. Root/alias resolution
and actual crop prerequisites must be checked against the frozen branch state
before later collection. A backend cannot be changed through public task args.
Literal VLM crop-selection intent can remain unknown.

`selection_probability=null`, `selection_seed=null` and
`sampling_design=observational_agent_trace` are used for current traces. The VLM's
temperature or image-sampling seed is not an action-selection propensity. Future
controlled collection must save its actual eligibility set, design, seed and
known positive probability.

Cost is one per dispatched public capability, not per detection row.
`cost_accounting_id` is shared across rows of the same logical action; aggregate
cost by distinct IDs, **not by summing repeated per-row cost fields**. For this
smoke test three candidate rows represent two dispatches. Latency is observer
dispatch/result latency; physical backend attempts remain null with a reason.

Grounding outcome vocabulary:

| Category | Definition without GT |
| --- | --- |
| `new_distinct_candidate` | Valid root proposal with no conflicting/ambiguous/likely-duplicate preceding proposal |
| `duplicate_existing_candidate` | One documented likely-same prior proposal and no competing association |
| `conflicting_candidate` | Overlapping incompatible-class proposal under the association rule |
| `no_detection` | Successful, explicitly empty grounding result |
| `ambiguous_association` | Intermediate overlap, missing comparison information, or multiple plausible associations |
| `execution_failure` | Actual dispatched failure, with recorded subtype |
| `invalid_or_unavailable_observation` | Missing/malformed grounding data, unverified geometry, or unsupported result type |

Zoom outcomes are `crop_created`, `crop_geometry_unavailable`,
`crop_artifact_unavailable`, `execution_failure`, and
`invalid_or_unavailable_observation`. Zoom produces an artifact, not a confidence
gain or independent binary object measurement.

An unexecuted action has `observed=false`, `category=null`, `reason=not_executed`.
It is **not** an empty detection, failure, or collected counterfactual sample.
An actual dispatch with no retained result is kept as `executed=true`,
`observed=false`, null observation ID/category and
`reason=dispatch_without_retained_result`. Its real logical cost remains charged;
no physical outcome or detection is invented. Incomplete traces are retained for
debugging but rejected for non-debug calibration export.

### Group C: `offline_labels`

Contains per-threshold `labels`, an unavailable-label reason when there is no
candidate, and annotation provenance. Thresholds default to **0.50 and 0.75**;
every label retains its threshold. These binary events are not COCO AP over
0.50–0.95.

The three distinct definitions are:

1. **`geometric_valid`:** overlap with any same-class eligible GT at threshold.
   Eligible means valid positive-area annotations excluding source ignore/crowd.
2. **`official_tp`:** assignment of these proposals under installed native
   `pycocotools.COCOeval` bbox matching, score-ordered, stable ties, one-to-one for
   ordinary GT, repeatable crowd matching and default maxDets=100 per image/class.
3. **`novel_gt_instance`:** unique eligible valid GT not previously represented by
   an unambiguous proposal in chronological/rank history. Multiple compatible GT
   objects or ambiguous candidate association produce null, not forced labels.

Also retained: maximum eligible IoU, best eligible GT ID, same-class GT presence,
best compatible annotation including ignored/crowd flags, raw root box, box used
for matching, raw ordering validity, duplicate GT evidence, unmatched/ignored
status, official assignment ID and all unknown reasons. GT annotation ID zero is
preserved externally while positive temporary IDs avoid COCO's zero sentinel.

Matching clips root pixels to image bounds, sorts reversed endpoints and drops
zero area, following the existing evaluator's pixel-box conversion. Raw values
remain unchanged; no 0–1000 rounding is introduced in these proposal labels.
These are **raw proposal labels**, not a re-score of the agent's rounded final
answer. Default assignment scope is **per observation**, with retained detector
scores. Optional trajectory scope pools proposals explicitly; constant score
mode uses stable rank ties. Scope/score/geometry/cap are recorded. Repeated calls
can each be per-observation TPs while later evidence is not novel.

**Native ignore caveat:** this installed bbox COCOeval overwrites `ignore` with
`iscrowd` during preparation. Geometric labels exclude original ignored GT,
while official assignment follows that unmodified implementation. Both original
flags and effective native ignore are exposed. Ignored/crowd contexts are not
silently used as validity-training negatives; `validity_label_usable` marks the
default exclusion rule. Invalid frame/class/box labels are null, not measured
zeros. Unknown score ordering makes that batch's official assignments unknown.

The summary exports eligible GT not covered by any geometrically valid candidate
at each threshold. This can assess discovery offline, but their coordinates/IDs
never create runtime proposals. Proposal verification does not solve discovery.
The action spec reserves a future region-level discovery-hypothesis schema with
runtime-only origin and no GT-generated regions; no discovery algorithm exists.

## Validation, retention and limitations

`load_trace` validates the observer schema, finds exactly one retained canonical
record (or accepts an explicit path), checks sidecar/canonical agreement and
verifies raw boxes/scores/mask hashes. Source image SHA and dimensions must agree
with the offline dataset sample. Unknown/inconsistent root transforms are not
matched. Full image/mask payloads remain in existing reference artifacts.

Record validation enforces group fields, source/partition consistency, unique
record IDs, strict JSON and structural GT/credential-field exclusions from runtime,
action and outcome groups. It cannot prove that arbitrary coordinates manually
placed into a legitimate field were not chosen using hindsight; GT-free
construction and independent labels are the semantic barrier. Tests vary GT while
requiring identical runtime features, states, actions and outcomes.

Statistical limits remain: retained-score censoring, source/scene correlation,
heuristic association error, incomplete annotation assumptions, unknown action
propensities and distribution shift. Multiple detections/calls from one source
are not independent calibration units. No causal/interventional kernel is
identified from these observational traces, and no probabilities were fitted.
