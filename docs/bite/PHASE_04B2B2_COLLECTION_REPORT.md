# Phase 04B-2B-2 — multi-image conditional tool-evidence collection

Date: **2026-10-30 (America/New_York)**. Status: **SUCCESS**.
Source baseline: Git commit `c530cdbdc6b7c4f486499eb7e5834ac2bd92692d`, branch `main`.
Existing uncommitted Phase 01–04B work was preserved; no commit or reset was made.

## Scope completed

This phase added a dataset adapter, deterministic source-group iterator, Task V
batch runner, content-verified resume ledger, collection audit, and a staged CLI.
It reuses the Phase 4B-1 `execute_prefix`, `freeze_state`, `BranchRunner`, public
capability lifecycle, Phase 4A COCO matcher, and `bite.target_aligned_outcome.v1`.
The OpenVLHarness agent loop, evaluator, SAM3 worker, and scoring implementation
were not changed.

No Qwen request, training, probability fitting, posterior update, planner, or
certificate was executed. Existing router/SAM3 services and serving parameters
were reused without stopping unrelated GPU work.

## Frozen source gate

The collector verified `odinw13:Aquarium_Aquarium_Combined.v2-raw-1024.coco`
against researcher approval `aquarium-research-2026-10-30`, archive size
70,037,905 bytes, archive SHA-256
`4affbfd66ef640b6154c694da3f2e730a97fe0fb0f8a22aa7ec8d32c2f04a536`,
and manifest canonical digest
`61df2e5f2a817b022f07358ec5b63438c8cfb56973009cf854c7b460c86aebd4`.
The complete manifest file SHA-256 is
`ea32301c5c0a613f60ebb7dfe6f64ea93f1f55ee589e1b6d262de1ae45a5846a`.

Preflight rechecked 277/78/50 images and 277/72/50 identity groups in
calibration fit/validation/internal test. Every planned entry was
`calibration_fit`, byte-identical to its frozen image hash, outside the 43-entry
quarantine, and resolved by the verified inventory rather than a guessed path.
No group crossed partitions. The previous PascalVOC debug sample was not used.

Queries came only from the frozen seven-class source vocabulary and the existing
`lowest sha256(seed:source_group_id:casefolded_class)` schedule. Annotation boxes,
image-level class presence, and tool outcomes were unavailable to selection.

## Execution protocol

Seed 417 selected 20 source groups, one deterministic representative image per
group, and two queries per group (40 Task V states). Each prefix selected the
highest retained SAM3 score with stable detector-rank tie-breaking. A complete
tool-executable snapshot was then frozen. Exact-repeat and Zoom→focused-grounding
branches were cloned independently from that same snapshot. The continuation
budget was three calls and the global cap was 160.

Raw snapshots, actions, observations, crops, masks, scores, target-aligned
runtime outcomes, and operational features were atomically persisted before the
COCO annotation loader was invoked. Offline labels then applied the existing
matcher to the original selected candidate at IoU 0.50 and 0.75. Branch labels
were exported separately; a better continuation never redefined the original
candidate's H_V label.

## Canary and pilot result

The first two groups were the first two groups in the frozen 20-group sample.
Their four states completed 16 calls, exercised both branches, preserved parent
snapshot equality, persisted raw records before labels, and passed the canary
gate. The same run resumed into the remaining 18 groups.

The completed pilot contains 40 successful prefix calls, 38 exact-repeat calls,
38 Zoom calls, and 38 focused-grounding calls: **154 logical public dispatches**.
Two successful prefix observations returned zero detections; they were retained,
charged once each, and created four explicit ineligible Task V branches. No
replacement images were selected. There were zero backend failures and zero
partial Zoom compositions.

All 38 repeat results had exactly identical boxes, scores, masks, and proposal
counts. Focused grounding produced 32 unique target-aligned proposals, all with
changed root geometry and score; five associations were ambiguous and one had no
target-aligned proposal.

Original-candidate labels were 4 positive / 34 negative / 0 unknown at IoU 0.50,
and 3 positive / 35 negative / 0 unknown at IoU 0.75. These counts describe 38
candidate-present states; the two no-candidate states are observations, not
negative H_V labels.

## Fault tolerance and validation

Each state has an immutable configuration digest, raw-completion marker,
content hashes, label-completion marker, and deterministic logical identities.
Partial state directories are rejected as requiring explicit new execution;
corrupt completed artifacts are rejected. A second full `--resume` pass verified
all 40 states, dispatched zero new calls, preserved the total at 154, and did not
rewrite state artifacts.

Tests:

- BITE targeted: **177 passed**, zero failures.
- Full repository: **709 passed, 449 subtests passed**, zero failures/errors/skips;
  three pre-existing pandas warnings.
- Ruff on all Phase 04B-2B-2 source/test files, Python compilation, and
  `git diff --check`: passed.

The authoritative machine audit is
`outputs/bite/phase04b2b2/audits/pilot_audit.json`. Phase 4C was not started.

