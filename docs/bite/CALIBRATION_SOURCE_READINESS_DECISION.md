# Calibration source readiness decision

**Decision: READY_FOR_TASK_V_PILOT. Task D remains blocked.**

The approval, archive integrity, structural annotation, deterministic QA,
held-out leakage and grouped partition gates passed for a restricted candidate-
verification pilot. The clean pool contains 405 images in 399 identity groups.

## Frozen Task V partitions

The existing grouped SHA-256 bucket algorithm uses salt `seed-417` and target
ratios 70/15/15. Related video frames remain in one group; quarantined and debug
identities cannot enter any calibration partition.

| Partition | Images | Groups |
| --- | ---: | ---: |
| calibration_fit | 277 | 277 |
| calibration_validation | 78 | 72 |
| internal_test | 50 | 50 |
| total | 405 | 399 |

Manifest SHA-256:
`61df2e5f2a817b022f07358ec5b63438c8cfb56973009cf854c7b460c86aebd4`.
Every partition contains all seven classes. Detailed image/annotation coverage is
in
[`partition_coverage.json`](../../outputs/bite/phase04b2b1a/manifests/partition_coverage.json).
The original source `valid`/`test` splits are not repurposed as internal test;
the complete installed ODinW inventory remains a separate final-evaluation
reference.

Task V labels are permitted at IoU 0.50 and 0.75 for clean groups, with unknown
retained for visually ambiguous or plausibly omitted instances. This is pilot
readiness, not probability calibration or a completeness theorem.

Task D is blocked because a publisher class list plus an 11-image review does not
establish class-absence exhaustiveness over all images. Missing COCO boxes cannot
be treated as proof that no discoverable object exists.

The Phase 4B-1 collector passed a real-image CPU-only mock: one GT-free class
schedule constructed a shared prefix and complete snapshot; repeat, Zoom→focus
and alternative root-query branches cost 1, 2 and 1 logical calls; raw branches
were persisted before four offline calibration records were produced. No GPU or
SAM 3 collection ran.

Artifacts:

- [frozen partition manifest](../../outputs/bite/phase04b2b1a/manifests/calibration_partition_manifest.json)
- [query schedules](../../outputs/bite/phase04b2b1a/protocol/query_schedules.json)
- [collector compatibility](../../outputs/bite/phase04b2b1a/collector_mock/collector_compatibility.json)
