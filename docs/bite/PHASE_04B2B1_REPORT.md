# Phase 04B-2B-1 — verified acquisition engineering and protocol refinement

**Status: ENGINEERING_SUCCESS / AWAITING_DATA_APPROVAL.** Engineering, dry-run
validation and protocol refinement are complete. No researcher-supplied approval
record was present, so no archive was downloaded, no source directory was
created, and no training annotation, held-out-overlap or near-duplicate result is
claimed. Phase 04B-2B-2 was not started.

Baseline identity remained branch `main` at
`c530cdbdc6b7c4f486499eb7e5834ac2bd92692d`. The existing dirty worktree and
frozen artifacts were preserved. Initial identity is recorded in
[`initial_identity.json`](../../outputs/bite/phase04b2b1/initial_identity.json).

## Research refinements

The versioned amendment
[`bite.calibration_research_amendment.v1`](calibration_research_amendment_v1.json)
separates the following quantities:

- Task V candidate belief `p_t=P(H_V=1|s_t)`, which is not a raw SAM 3 score;
- the operational conditional outcome model
  `K_a(o|H_V,s_t)=P(O_a=o|H_V,s_t,do(a))`;
- probability calibration (Brier score/NLL), forced candidate-decision error,
  and unchanged official end-to-end ODinW AP.

The frozen runtime feature projection records task/class/domain, relative size,
score availability, overlap/crowding, image frame, prior outcome, backend/query
dependency, ambiguity and remaining logical budget. Exact source/image
identities remain audit/cluster fields and are excluded from predictive features.
The projection is not claimed to contain the hidden world, and the future kernel
is not yet a fully identified physical-world causal distribution.

`bite.target_aligned_outcome.v1` adds GT-free Task V summaries while preserving
the complete joint proposal set and all earlier records. Ambiguous focused
detections remain ambiguous. `bite.discovery_outcome.v1` separately represents
Task D proposal-set discovery and requires later offline labels. Exact repeat,
modified same-backend query, derived-crop grounding and distinct verified
backend are separate dependency classes; only the first three are currently
available. A repeated false positive retains the original evidence lineage and
may provide zero incremental information. Zoom can alter scale and framing, but
does not add new raw-image information.

The class schedule is amended as `bite.query_schedule.v2`:

```python
scheduled_count = min(requested_classes_per_group, available_verified_classes)
```

Seed 417 hash ordering is preserved, GT presence is not consulted, and the
actual query count is recorded. The frozen Phase 4B-2A protocol was not edited.
No probability, posterior, planner, online decision rule or certificate was
implemented or fitted.

## Acquisition engineering and approval gate

The acquisition utility is dry-run by default, accepts only its explicit
registered allowlist, and requires a separate researcher-attested approval
record for execution. It downloads only the exact registered URL, streams into
a temporary file, validates byte length and SHA-256, fsyncs and atomically
installs the preserved archive. It has no mirror fallback. Existing content is
an error unless explicit verified reuse is requested.

ZIP preflight/extraction rejects absolute and parent paths, drive paths,
backslashes, NULs, symlinks, special/encrypted members, duplicate or
case-conflicting paths, unsupported extensions, and configured count, expanded
size and compression limits. Extraction is isolated under
`data/calibration_sources/odinw13`; it never writes benchmark TSV/image roots.

The two requested source candidates are:

| Source | Registered bytes | Registered SHA-256 | Current gate |
| --- | ---: | --- | --- |
| `odinw13:AerialMaritimeDrone_large` | 47,681,829 | `4bf97c0e0f0264bc2c778114d8da70114ab01be3ccb71033e8cea30201f874bd` | Current publisher page says MIT while installed export metadata says Public Domain/CC0; researcher resolution/acceptance required. |
| `odinw13:Aquarium_Aquarium_Combined.v2-raw-1024.coco` | 70,037,905 | `4affbfd66ef640b6154c694da3f2e730a97fe0fb0f8a22aa7ec8d32c2f04a536` | CC BY 4.0 attribution/license/modification obligations require researcher acceptance. |

The exact URLs, terms evidence, intended internal non-redistributed use,
destination, hashes and post-approval commands are in
[`approval_request.json`](../../outputs/bite/phase04b2b1/acquisition/approval_request.json).
The two dry-run plans made no network request. Downloaded bytes: **0**. Approved
sources: **0**. The requested destination remains absent.

## Data validity and readiness

The new annotation auditor validates COCO/LVIS structure, IDs, category maps,
image references/dimensions, in-bounds positive boxes, ignore/crowd fields,
empty images and missing/invalid labels. It reports structural completeness,
class-conditional exhaustiveness and visual completeness independently. Manual
QA selection is deterministic by source-group/image hash with seed 417, never by
favorable detector output.

Because no source was approved/acquired, both sources currently have:

- structural completeness: `not_checked`;
- class-conditional exhaustiveness: `unknown`;
- visual completeness: `not_reviewed`;
- Task V readiness: `blocked`;
- Task D readiness: `blocked`.

The exact held-out and perceptual near-duplicate audits are implemented but not
run without acquired train pixels. Exact SHA/path/parent/scene evidence reuses
the Phase 4A partition audit. dHash matches are only quarantined review
candidates, never automatic identity claims. Dataset names do not establish
disjointness. The prior PascalVOC val/test finding of 3,422 exact shared images
and the inspected `PascalVOC_val_262` development-image exclusion are retained.

Consequently, `calibration_fit`, `calibration_validation`, `internal_test`,
`final_evaluation_reference` and development exclusions have not been frozen as
a real-data split. The provisional manifest correctly has `frozen_ready=false`.

## Collector interface

Mock validation confirms that Phase 4B-1 can consume a future approved manifest
to construct an original image, permitted class query, shared prefix,
tool-executable snapshot, isolated eligible paths, logical budget at most three,
raw-before-label persistence and a GT-free target-aligned summary. Initial Task V
selection and action construction do not need GT.

The remaining integration gaps are a dataset-manifest iterator, acquired-source
adapter, automatic manual-QA workflow and physical retry-attempt telemetry.
Therefore real multi-image collection is not authorized yet.

## Verification

- BITE-targeted suite: **168 passed, 0 failed**.
- Full suite: **700 passed, 449 subtests passed, 0 failures/errors/skips**
  (`1,149` JUnit cases), compared with the prior 677 + 449 baseline.
- New Phase 04B-2B-1 tests: **23**.
- Fatal/static Ruff checks, Python bytecode compilation, CLI help checks and
  `git diff --check`: passed.
- No GPU inference, model request, data download, probability fitting, baseline
  scoring change or Git commit was performed.

## Next authorized step

A researcher must review the license evidence and submit
`outputs/bite/phase04b2b1/acquisition/researcher_approval.json` for one or both
exact registered sources. Only then may the corresponding documented command be
run. Acquisition must then be followed by archive verification, structural and
manual annotation review, Task V/Task D readiness decisions, exact/near-duplicate
audits and grouped manifest freezing. Automated multi-image conditional tool
collection cannot begin until those gates pass.
