# Phase 04B-2A — data readiness and protocol freeze

**Status: ENGINEERING_SUCCESS / DATA_SOURCE_PENDING.** Date: 2026-10-29
(America/New_York). Baseline Git reference: `main` at
`c530cdbdc6b7c4f486499eb7e5834ac2bd92692d`. Existing uncommitted BITE work was
preserved. No archive, checkpoint or large data was downloaded; no GPU tool or
model inference ran; no probability model, posterior, planner, or Phase 4B-2B
collection was started.

## Source result

The official GLIP metadata was inspected at commit
`9dda9558c1ef59bb6cdc8e896e2bcab775a68ff0`. All 13 ODinW configs declare genuine
train paths in addition to validation/test paths, and the official GLIPModel host
contains all 13 named archives. Exact compressed total is 2,249,062,175 bytes;
each archive's URL, LFS SHA-256 and host revision is registered. The documented
downloader should not be executed blindly: its current filename differs from the
README, its default includes the larger set, it uses shell extraction/removal,
does not verify checksums, and constructs a browse rather than resolve URL.

Archive metadata does not prove that labels are exhaustive, that train images are
scene-disjoint from installed held-out data, or that all image rights share the
license string recorded in a Roboflow export. Consequently every ODinW source is
`metadata_verified` plus `license_review_required`; none is
`approved_for_calibration`. The local environment still has zero genuine ODinW
train sources. COCO 2017 and LVIS v1 are separately registered alternatives,
also unapproved and not local.

The Phase 4A leakage result remains authoritative: PascalVOC val and test share
3,422 exact images and one annotation population. `PascalVOC_val_262`, SHA-256
`a18039d3edc2c8ae46fb2b8347318c79f91f5643c3811181d366ed4a4403e1b5`,
is frozen as development-only and is neither calibration fit nor blind test.

## Implementation

The offline package now includes:

- `source_registry.py`: versioned publisher, archive, split, class, license,
  access, status and approval metadata;
- `source_verification.py`: local COCO/LVIS structure, image, box, class mapping,
  completeness gate, SHA-256 and held-out overlap verification;
- `source_preparation.py`: exact non-executing acquisition plans;
- `manifest_freeze.py`: provisional manifests, source-approval gate,
  source-group hashing, deterministic 70/15/15 assignment and checksum validation;
- `protocol_validation.py`: `bite.calibration_protocol.v1`, GT leakage barriers,
  hypothesis/loss, action/prerequisite, cost, propensity and checkpoint-claim
  checks.

Commands were added for source discovery, local verification, acquisition dry
runs, manifest freeze, protocol validation and reproducible artifact generation.
They do not import the runtime agent or download data. The existing Phase 4A
hashing/split audit and Phase 4B-1 snapshot/branch schemas are reused.

## Frozen research design

Task V is threshold-specific candidate validity at IoU 0.50 or 0.75, with
ignored/crowd/unknown-coordinate cases remaining unknown. Task D is fixed-grid,
class-conditional presence of an eligible instance not previously represented.
GT labels both only after raw persistence.

Two classes per source group are chosen by a frozen hash schedule with seed 417,
without per-image GT. One root grounding is the prefix. Same-hypothesis Task V
paths are repeat, Zoom→same-class focus, and a prespecified source-level alias
when available. Task D paths are repeat broad query and fixed-grid Zoom→focus.
A different class query is not verification; a second SAM 3 call is not an
independent backend.

Continuation budget is three logical dispatches. A dispatched failure costs one;
pre-dispatch rejection costs zero; Zoom→focus costs two. Deterministic coverage is
the pilot design. Uniform-without-replacement expansion requires frozen
eligibility and recorded `k/N` and per-draw propensities. Configured transient
transport behavior remains eight retries after the initial request, tool timeout
600 seconds and worker timeout 30 seconds. Empty, failure, invalid, missing and
ineligible outcomes remain distinct.

No orchestrator call is planned. SAM 3 cache revision observed in Phase 1 is
recorded, but current worker checkpoint attestation is explicitly false rather
than inferred.

## Manifests and next-phase gate

Separate `calibration_fit`, `calibration_validation`, and `internal_test`
manifests exist with zero entries and `SOURCE_PENDING`. The final-evaluation
reference records the ODinW population and PascalVOC alias; the debug-exclusion
manifest records prior exposure. The provisional manifest assigns no data.
All generated files have SHA-256 entries in `manifest_checksums.json`.

The Phase 4B-2B plan is present but `launch_authorized=false`. A first approved
pilot is planned for 20–40 source groups, two class queries per group and at most
160–320 public dispatches. This is infrastructure scale, not a power result.

The smallest next task is human review/approval of one or more exact ODinW domain
archives and terms, followed by checksum-verified acquisition, local annotation
and image verification, held-out identity audit, and grouped manifest freeze.
Only then may the multi-image iterator/collection task begin.

## Validation

Targeted:

```bash
.venv/bin/python -m pytest tests/bite tests/bite_calibration tests/bite_collection -q \
  --junitxml=outputs/bite/phase04b2a/targeted_pytest.xml
```

Result: **145 passed** (including 24 new Phase 4B-2A tests), zero failures.

Full suite, with loopback access required by existing HTTP tests:

```bash
.venv/bin/python -m pytest tests -q \
  --junitxml=outputs/bite/phase04b2a/pytest.xml
```

Result: **677 passed and 449 subtests passed**, zero failures/errors/skips, in
23.45 seconds. The three warnings are the existing pandas downcasting warnings.
Ruff fatal/static checks and `git diff --check` passed.

Tests cover source metadata and total bytes, permission/approval separation,
missing/incomplete annotations, missing images, invalid boxes/classes, exact-byte
held-out overlap, duplicate group assignment, exclusions, immutable manifest
hashes, Task V/D semantics, GT-free scheduling, unsupported actions, budgets,
prerequisites, randomized propensity, checkpoint uncertainty and compatibility
with all existing observer/calibration/collection tests.
