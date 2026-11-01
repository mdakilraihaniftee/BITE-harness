# Phase 04B-1 — controlled tool collection infrastructure

**Status: SUCCESS.** A complete tool-executable snapshot can be frozen from a
live `MemoryStore`, cloned into isolated branches, executed through the existing
public capability lifecycle and labeled only afterward by the Phase 4A matcher.
Complete VLM-continuation cloning is intentionally unavailable and not claimed.

Date: **2026-10-29 (America/New_York)**. Starting Git reference: `main` at
`c530cdbdc6b7c4f486499eb7e5834ac2bd92692d`. Existing uncommitted Phase 3/4A
work was preserved. `MainAgent`, model adapters, prompts, tool algorithms,
workers, evaluator metrics and service configurations were not modified.

## Implementation

New package [`evaluation_kit/bite_collection`](../../evaluation_kit/bite_collection/)
contains versioned schemas, snapshot serialization/restoration, clone isolation,
GT-free eligibility/action selection, exact dispatch observation, branch running,
cost accounting, atomic persistence, validation, a CPU demonstration and the
explicit live pilot. New commands:

```bash
.venv/bin/python scripts/bite/collect_tool_branches.py \
  --synthetic-demo --output-dir outputs/bite/phase04b1/synthetic

.venv/bin/python scripts/bite/validate_collected_branches.py \
  outputs/bite/phase04b1/synthetic/manifests/collection_manifest.json
```

The only Phase 4A source extensions are a backward-compatible
`tool_execution_complete_snapshot` context value and
`build_collection_records`, which reuses `label_candidates`. No second matcher
or metric was introduced.

Supported paths are root grounding, repeat grounding, zoom generation and
focused grounding on the actual registered crop. Zoom→grounding remains two
calls. Grounding DINO verification is recorded ineligible and was not started.
Deterministic coverage and seeded uniform sampling without replacement record
both marginal inclusion and per-draw probabilities.

## CPU-only demonstration

The mandatory synthetic run uses a 200×120 generated image and deterministic
mock grounder while executing the real zoom implementation and real capability
lifecycle. One person grounding creates the common prefix. Three branches then
run repeat, zoom→focused grounding, and alternative root `horse` grounding.

Results: three branches share one snapshot; branch continuation costs are
`1, 2, 1`; actual continuation expenditure is 4; hypothetical total costs are
`2, 3, 2` including the one-call prefix. Multiple horse detections share one
joint observation and one cost identity. Snapshot, sibling branches, aliases,
bindings, arrays, counters and candidate histories remain isolated. Five
`bite.calibration.v1` rows validate after separate synthetic GT matching.

Artifacts:

- [synthetic manifest](../../outputs/bite/phase04b1/synthetic/manifests/collection_manifest.json)
- [branch-isolation validation](../../outputs/bite/phase04b1/synthetic/validation/branch_isolation.json)
- [offline calibration export](../../outputs/bite/phase04b1/synthetic/offline_labels/calibration_records.jsonl)

## Real development-only pilot

The existing router and workers were healthy and were reused without restart.
The pilot used `PascalVOC_val_262` solely for debugging. The original task
vocabulary supplied `person` and `horse`; no GT was loaded until the raw
snapshot/branches were atomically persisted. No Qwen/model call occurred.

The shared prefix grounded one person on the 500×333 root image: box
`[201.7684, 131.7963, 285.5702, 332.9205]`, score `0.984375`. Controlled branches:

| Path | Dispatches | Result | Measured continuation latency |
| --- | ---: | --- | ---: |
| Repeat `person` | 1 | same retained box/score | 220.28 ms |
| Zoom→focused `person` | 2 | crop `[177,115,311,333]`, 134×218; focused score `0.9921875` | 191.83 ms |
| Root `horse` | 1 | two boxes, scores `0.9765625`, `0.96484375` | 288.45 ms |

The prefix took 230.48 ms. Actual execution was five logical dispatches total:
one prefix plus four branch continuations. The continuation latency sum was
700.55 ms; transport physical attempts remain unknown. Random selection with
seed 417 chose the horse path at probability 1/3, but that RNG check launched no
duplicate tool work. All three branch parent IDs/digests match; five offline
calibration records validate.

Artifacts:

- [live collection manifest](../../outputs/bite/phase04b1/live/manifests/collection_manifest.json)
- [live validation and latency](../../outputs/bite/phase04b1/live/validation/live_pilot.json)
- [live offline calibration export](../../outputs/bite/phase04b1/live/offline_labels/calibration_records.jsonl)
- [service health](../../outputs/bite/phase04b1/service_health.json)

## Tests

Targeted command:

```bash
.venv/bin/python -m pytest tests/bite tests/bite_calibration tests/bite_collection -q
```

Result: **121 passed, 0 failed**. This includes 35 Phase 4B-1 test cases after
parameter expansion. The tests cover complete/incomplete snapshots, content
rehydration, native-history preservation, image/binding/array/counter isolation,
reused bytes, exact and nested crops, root/repeat/focus eligibility, unsupported
backends, invalid queries/images, insufficient budgets, failed prerequisites,
deterministic/random selection, multi-detection joint outcomes, empty/failed/
invalid results, pre/post-dispatch charging, partial captures, GT exclusion and
Phase 3/4A schema compatibility.

Full command:

```bash
.venv/bin/python -m pytest tests -q \
  --junitxml=outputs/bite/phase04b1/pytest.xml
```

Result: **653 passed and 449 subtests passed, 0 failures/errors**, with the same
three existing pandas `FutureWarning`s. Ruff fatal/static checks and
`git diff --check` passed.

## Compatibility and scientific boundary

The normal agent/evaluator imports no collection package. Controlled execution is
a separate CLI and never extends native history. Existing `bite.observation.v1`
fixtures and Phase 4A `bite.calibration.v1` outputs validate unchanged. Collection
validation recursively rejects GT-like runtime fields. Empty, failure, invalid,
missing and planning-ineligible outcomes remain distinct. Repeated evidence and
branches from one image are explicitly dependent observations, not independent
source samples.

No calibrated probability, posterior, identifiability bound, planner, Bellman
optimization, online policy or benchmark metric was added.

## Resource estimate and Phase 4B-2 gate

At the demonstrated design, 20–40 approved images would imply 100–200 logical
dispatches (one prefix plus four continuation calls per image) and 20–40 source
independence units, not 60–120 independent branch samples. Using the warmed pilot
latencies gives a rough **planning estimate** of 19–38 seconds of summed tool
latency for this exact easy sample profile; operational overhead, GPU contention,
denser masks, failures and persistence can materially increase it. A conservative
pilot reservation is several minutes, plus artifact storage. This is not a power
analysis or measured large-run throughput.

Phase 4B-2 still requires an approved, licensed, scene-disjoint labeled source and
frozen partition manifest. Phase 4A found no suitable local train detection split,
and that data-acquisition blocker remains. Before collection, also freeze queries,
action paths, retry policy, checkpoint identity, failure handling, sample size and
privacy/retention rules. Do not fit on PascalVOC validation/debug artifacts.
