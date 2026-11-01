# Phase 04A — Offline calibration preparation

**Engineering status: SUCCESS, with a data-acquisition blocker for calibrated
collection.** The offline pipeline, source/leakage audit, candidate association,
GT matching, action/outcome schemas and real debugging export are implemented.
No posterior, likelihood, confidence calibration or planner was fitted. **Phase
4B was not started.** No fresh model/perception inference was performed.

Date: **2026-10-29**. Work started on `main` at
`c530cdbdc6b7c4f486499eb7e5834ac2bd92692d`, preserving Phase 3's uncommitted
changes. The initial Git status and preserved file hashes are in
[initial_identity.json](../../outputs/bite/phase04a/initial_identity.json).
There was no reset, branch switch, commit or deletion of previous outputs.

## New files; existing runtime unchanged

All Task 4A implementation is outside the inference runtime:

| New path | Responsibility |
| --- | --- |
| [`evaluation_kit/bite_calibration/__init__.py`](../../evaluation_kit/bite_calibration/__init__.py) | Offline package boundary |
| `common.py` | Stable IDs, file hashes, finite geometry and evaluator-consistent clipping/sorting |
| `dataset_inventory.py` | Local TSV/annotation/image/license inventory without downloads |
| `split_integrity.py` | Hash/path/source/scene/parent/annotation overlap checks and frozen-manifest validation |
| `candidate_association.py` | Class/root-aware IoU comparisons and reversible tentative groups |
| `matching.py` | Explicit local ODinW/FSCD GT loaders, geometric labels, native COCO assignment and novelty |
| `outcomes.py` | Prior-state-dependent grounding outcomes and deterministic crop/artifact outcomes |
| `actions.py` | Five action templates, prerequisites and planned coverage/randomization designs |
| `records.py` | Observer/canonical verification, GT-free state construction and separate offline labeling |
| `validation.py` | `bite.calibration.v1` JSON schema, structural leakage and partition barriers |
| `cli.py` | Audit/build/validate command implementations |

Thin entry scripts are
[`scripts/bite/audit_calibration_sources.py`](../../scripts/bite/audit_calibration_sources.py),
[`build_calibration_records.py`](../../scripts/bite/build_calibration_records.py)
and [`validate_calibration_records.py`](../../scripts/bite/validate_calibration_records.py).
Tests and an explicitly identified observer-v1 replay fixture are under
[`tests/bite_calibration/`](../../tests/bite_calibration/).

No original agent, observer, evaluator, matching bridge, tool, prompt, YAML,
checkpoint, image, annotation, dependency or existing test file was changed in
this task. The runtime does not import the new offline package; an AST test
checks that boundary. Existing Phase 2B/3 manifests and frozen artifacts are
verified again at completion, rather than updated to conceal source differences.

## Dataset and split findings

The full audit is [CALIBRATION_DATA_AUDIT.md](CALIBRATION_DATA_AUDIT.md).

- Local ODinW: 13 domains, 26 val/test mappings, 25 annotation files; val TSV
  has 4,938 rows, and all mapped images exist in 6,091 file paths.
- Local FSC147: 1,286 **count** rows and 2,476 image files. The installed count
  TSV does not contain detection boxes. FSCD-147 bbox val/test and FSCD-LVIS
  bbox train/val/test/unseen prepared sources are absent.
- No genuine train mappings or train-named JSON annotations were found under
  accessible project `data/`; a TRAIN setting alone does not establish data.
- All 11,989 source entries were hashed, covering 8,567 image paths and 8,301
  content groups. PascalVOC val/test share the same annotations and 3,422 exact
  image hashes. Another 257 duplicated-content groups occur within partitions.
- No further cross-partition exact-byte overlap was found in this inventory.
  Unknown scene relationships and transformed near-duplicates remain unresolved.
- Local license metadata includes CC BY, Public Domain, MIT, ODbL and Unknown;
  complete per-source clearance is not established. FSCD's original publisher
  states research/education and nonredistribution conditions, documented with
  primary-source links in the data audit.

**No calibration-fit partition was created.** The provisional manifest leaves
all source groups unassigned. Recommended Phase 4B path is acquisition of genuine
training labels with source-specific permission checks and disjointness audit;
a separately licensed labeled development source is an alternative. Reusing
validation for fitting would require an explicit Option C decision and surrender
the corresponding full validation set as an untouched benchmark. No blind final
holdout is currently established.

## Candidate, action and label semantics

The [schema documentation](CALIBRATION_SCHEMA_V1.md) separates:

1. **Runtime features:** immutable proposals from observer detections, root/local
   frames, raw scores and mask references, prior candidate/outcome state and
   runtime-only context. GT never generates proposals or regions.
2. **Action/outcome:** exact public capability/backend/arguments, prior state,
   branch/source identities, unknown observational action propensity, logical cost,
   measured observer latency and available provenance.
3. **Offline labels:** same-class eligible-GT overlap, native COCO one-to-one
   assignment and history-dependent novel-GT evidence at IoU 0.50 and 0.75.

Association retains raw proposals and pairwise evidence rather than irreversibly
merging boxes. Same-class IoU ≥0.8 is a tentative same-object suggestion; ≤0.1
is distinct; other/conflicting/multiple/unknown-frame cases remain uncertain.
Crowded objects may defeat these heuristics. Root geometry is checked against
recorded transforms, with inconsistent/ambiguous frames excluded from matching.

Offline matching preserves raw geometry separately from clipped/sorted geometry
used for assignment. Proposal pixels are not rounded to the model's final 0–1000
answer grid. Original annotation ID zero is retained outside temporary COCO
IDs. Scope defaults to per observation with retained scores, explicit maxDets=100;
trajectory/constant-score alternatives are available and recorded. These labels
do not re-score the final answer or calculate AP.

Geometric validity and official assignment are not interchangeable. Duplicate
proposals can both overlap GT while only one receives the ordinary one-to-one
assignment. Repeated calls can each be per-observation TPs without providing a
novel instance. Native installed bbox COCOeval overwrites source `ignore` with
`iscrowd`; the pipeline exposes both original and effective behavior. Ignored/
crowd contexts are flagged for exclusion from naive validity fitting rather than
silently being treated as negatives.

Grounding outcomes are new, duplicate, conflicting, empty, ambiguous, execution
failure and invalid/unavailable observation under documented GT-free rules.
Zoom reports crop/artifact/geometry status, not confidence gain. Alternative
backend verification remains unavailable; no DINO model was configured or run.

Missing results are not negative examples: a dispatched action with no retained
observation has null outcome/observation ID and an explicit reason, retaining its
real cost. An unexecuted action has no observed outcome. Incomplete captures are
debuggable but cannot be exported to non-debug calibration partitions.

## Real-data labeling smoke test

The pipeline read the **existing Phase 3 observer sidecar and retained canonical
record** for `ODinW13_bbox_val_qwen3 / PascalVOC_val_262`. It verified their
agreement, scores, boxes and mask hashes, then loaded the actual original
PascalVOC COCO annotations. Source-image SHA and dimensions agree. GT was not
inferred from the old AP or hard-coded as expected positives.

The three raw proposals remain unchanged. Only offline matching clips the small
negative/oversized horse coordinates. Results:

| Proposal | Original eligible GT ID | Maximum eligible IoU | Valid at .50 / .75 | Native TP at .50 / .75 | Novel GT at .50 / .75 |
| --- | ---: | ---: | --- | --- | --- |
| person | 593 | 0.915691634684089 | True / True | True / True | True / True |
| horse, left | 594 | 0.9834018108482859 | True / True | True / True | True / True |
| horse, right | 592 | 0.9273454493303628 | True / True | True / True | True / True |

Output: **3 candidate rows, 6 threshold-label records, 1 source group, 2 unique
cost-accounting actions**. No eligible GT remains uncovered at either threshold.
All observed outcomes are `new_distinct_candidate` relative to their recorded
preceding proposal state. Selection probabilities remain null with an explicit
observational-trace reason. No calibration probability or statistical accuracy
estimate is computed from these three debugging rows.

These IoUs need not equal old per-row diagnostic IoUs: this pipeline evaluates
raw clipped proposal pixels, while the reference final answer used rounded
normalized boxes and constant scores. Both policies are preserved and named;
the official scoring files were not touched.

Artifacts:

- [calibration_records.jsonl](../../outputs/bite/phase04a/smoke/calibration_records.jsonl)
- [MATCHING_REPORT.md](../../outputs/bite/phase04a/smoke/MATCHING_REPORT.md)
- [matching_summary.json](../../outputs/bite/phase04a/smoke/matching_summary.json)
- [validation.json](../../outputs/bite/phase04a/smoke/validation.json)

Every row is **development_debug**. This image has already been inspected and
is not an unseen independent final evaluation sample.

## Reproduction commands

From the project root:

```bash
.venv/bin/python scripts/bite/audit_calibration_sources.py \
  --data-root data --output-dir outputs/bite/phase04a/audit

.venv/bin/python scripts/bite/build_calibration_records.py \
  --observer outputs/bite/phase03/live/Qwen3-VL-8B-Instruct/mainagent/agent_paper_v1_judge_direct_metrics_v1_20261029_173555_bite_observer_phase03/ODinW13_bbox_val_qwen3/bite_observations/PascalVOC_val_262.json \
  --dataset ODinW13_bbox_val_qwen3 \
  --iou-thresholds 0.50 0.75 \
  --output-dir outputs/bite/phase04a/smoke

.venv/bin/python scripts/bite/validate_calibration_records.py \
  outputs/bite/phase04a/smoke/calibration_records.jsonl
```

All inputs are read-only. The CLI does not construct download-capable datasets
or issue model/tool requests. Outputs go into the new Phase 4A directory.

## Tests and compatibility

Executed:

```bash
.venv/bin/python -m pytest tests/bite tests/bite_calibration -q
.venv/bin/python -m pytest tests -q \
  --junitxml=outputs/bite/phase04a/pytest.xml
```

Targeted result: **86 passed** (37 observer + 49 calibration tests).
Full-suite result: **618 passed, 449 subtests passed, zero failures**. The three
warnings are the existing pandas downcasting FutureWarnings. Lint with
`ruff check --isolated --select E9,F63,F7,F82` on new source/scripts/tests and
`git diff --check` passed.

Tests cover image/annotation hash aliases, source/scene/crop grouping, partition
barriers, repeated and crowded proposals, score ordering, GT ID zero,
ignore/crowd/native quirks, invalid/missing annotations, maxDets and unavailable
scores, known nested crop frames and ambiguous/inconsistent transforms, empty/
failure/missing/unexecuted outcomes, stable generation, actual observer-v1
structure, raw coordinate retention, GT-free outcome construction, runtime
import isolation, supported action prerequisites and absence of hindsight
candidate generation. Changing GT while holding the same trace fixed leaves
runtime state/features, actions and outcomes identical.

Logs: [targeted_tests.log](../../outputs/bite/phase04a/targeted_tests.log),
[pytest.log](../../outputs/bite/phase04a/pytest.log),
[pytest.xml](../../outputs/bite/phase04a/pytest.xml).
New source/test/docs hashes, preserved-source checks, original artifact integrity
and exact output paths are in
[implementation_manifest.json](../../outputs/bite/phase04a/implementation_manifest.json).

## Requirements before Phase 4B

Review the [collection protocol](CALIBRATION_COLLECTION_PROTOCOL.md), approve a
disjoint licensed training/development source, and freeze grouped manifests.
Then separately implement complete state snapshots/isolated branches, explicit
runtime-region provenance, eligibility/propensity logging and failure policies.
The current observer projection and observational VLM histories do not identify
an interventional kernel. Source-group dependence, detector score censoring,
heuristic association ambiguity, annotation completeness and distribution shift
remain modeling obligations. No branch collection, probability fit, planner,
identifiability solver or Phase 4B work was performed.
