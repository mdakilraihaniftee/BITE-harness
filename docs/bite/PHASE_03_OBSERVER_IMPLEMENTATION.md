# Phase 03 — Passive BITE evidence observer

**Status: SUCCESS.** The observer is implemented, opt-in, question-local and
passive. Deterministic provider replays preserve model payloads, native messages,
tool dispatch arguments/results, evidence and predictions. The full suite passed
**569 tests and 449 subtests**, with zero failures. One real observer-enabled
ODinW execution completed and scored successfully. **Phase 4 was not started.**

Date: **2026-10-29, America/New_York**. Starting Git reference remained `main` at
`c530cdbdc6b7c4f486499eb7e5834ac2bd92692d`; implementation changes are in the
working tree, not committed. Existing audit reports were preserved. All **77
frozen reference-baseline artifacts** passed hash checks before and after the new
live run. No original baseline record, prediction or scoring output was changed.

## Implemented components and exact source changes

New package:

| File | Responsibility |
| --- | --- |
| [`__init__.py`](../../openvlharness/bite/__init__.py) | Public observer factory/type |
| [`observer.py`](../../openvlharness/bite/observer.py) | Passive lifecycle hooks, grounding extraction, finalization, error containment |
| [`state.py`](../../openvlharness/bite/state.py) | Per-question state and independent identity namespace |
| [`schemas.py`](../../openvlharness/bite/schemas.py) | `bite.observation.v1` envelope/event requirements and budget schema |
| [`provenance.py`](../../openvlharness/bite/provenance.py) | Image/binding/backend nodes, typed relationships, geometric ambiguity |
| [`geometry.py`](../../openvlharness/bite/geometry.py) | Exact existing crop reconstruction and nested translation composition |
| [`budget.py`](../../openvlharness/bite/budget.py) | Recording-only reference budget and separate counters |
| [`serialization.py`](../../openvlharness/bite/serialization.py) | JSON conversion, media hashes, credential redaction; no numeric truncation |

Modified existing runtime/evaluator files:

| File / function | Change |
| --- | --- |
| [`agent.py`, `MainAgent.generate`](../../openvlharness/agent/agent.py) | Creates optional question-local observer after memory initialization; adds `extra_records.bite_observer` on return |
| `MainAgent._run` | Records model/proposal/result events and observable context changes; preserves native declarations and result rendering |
| [`_base.py`, `BaseCapability.invoke`](../../openvlharness/capabilities/_base.py) | Captures actual resolved dispatch immediately before existing `execute`; observes caught exception types |
| [`runner.py`, `_make_committed_gen`](../../evaluation_kit/runner.py) | Atomically persists an observer sidecar before evaluator GT decoration; sidecar-only write failures do not block ordinary prediction commit |
| [`cli.py`, `main` cleanup branch](../../evaluation_kit/cli.py) | Retains canonical file-db records when observer sidecars exist, preserving raw evidence references |

No model adapters, native schema definitions, prompts, tool algorithms, grounding
thresholds, zoom backend, serving scripts, agent/judge YAML or scorer changed.
The observer uses the existing `coerce_xyxy` helper instead of refactoring the
original zoom implementation. Mutable state lives on the per-question observer
and memory, never on the shared `MainAgent` or a module-global active observer.

Tests added in [`tests/bite/test_observer.py`](../../tests/bite/test_observer.py),
with [`reference_trace.json`](../../tests/bite/fixtures/reference_trace.json)
containing actual Phase 02B numerical observations/proposals and no GT. Images
used by replay tests are synthetic. One additional CLI retention/scoring test
uses existing fixtures in
[`test_cli_end_to_end.py`](../../tests/evaluation/test_cli_end_to_end.py).

## Enablement, schema and integration boundaries

Default is disabled. Enable using `BITE_OBSERVER_ENABLED=true`; optional
`BITE_OBSERVER_REFERENCE_BUDGET` defaults to 15 and accepts `none`;
`BITE_OBSERVER_RUN_ID` optionally supplies an experiment identifier. No unknown
YAML key was added to the strict bootstrap schema. See
[OBSERVATION_SCHEMA_V1.md](OBSERVATION_SCHEMA_V1.md) and the exported
[JSON schema](observation_schema_v1.json) for every field and convention.

Events are `model_turn`, `context_change`, `tool_proposal`, `tool_dispatch`,
`tool_observation`, `finalization`, and `observer_error`. Local sequential event,
action, observation and detection IDs are scoped by run/question identity.
Native provider IDs remain separate and unchanged. Runtime data excludes GT,
matching labels, evaluator metrics, credentials and repeated image payloads.
The observer makes no additional model, perception or image-download request.

Schema validation happens in the original capability lifecycle. The observer
records dispatch **after validation, resolution and argument translation**, so
reaching `invoke` alone is not charged. Unknown/invalid/malformed/multi-call or
unresolved-image proposals cost zero. Actual successful, empty, timeout,
backend-error and invalid-result dispatches each cost one. Retries stay within
that logical call. Physical attempts remain null because the transport/provider
subattempts are not instrumented. The reference budget is never enforced, and
negative remaining budget is tested.

Latency uses a monotonic timer from the resolved execution boundary through
normal result processing, not complete download/billed latency. Finalization
records the original result digest and aggregate main-agent usage. Its validity
flag means nonempty/nonfailure response, explicitly not task correctness or
general JSON validation. Observer hook errors mark capture incomplete without
changing normal model/tool behavior. Capability exceptions retain their existing
propagation behavior while their dispatched observation is closed where possible.

## Grounding, geometry and provenance

Grounding records every retained box/score/label, source frame and dimensions,
mask hash/encoding/dimensions/reference, query and reported worker ID. Root boxes
are additional metadata; raw local coordinates, including negative or oversized
values, are preserved without rounding or clamping. Scores are detector scores,
not posterior probabilities. Empty successful results and unavailable/malformed
optional fields remain distinct. Canonical/raw result references point to the
same sample's original agent result in retained `record.json`.

Crop reconstruction reproduces padding **before** sorting, clamping and integer
rounding. For `[50,100,650,950]`, padding 50, source 600×320, tests recover
`(0,16,420,320)` and 420×304 pixels. Nested translations compose child-to-parent
and parent-to-root matrices; grounding on a second crop is exercised end to end
with a local deterministic backend and mapped to root pixels. Crop pixels are
checked against reconstructed dimensions. The original tool result is unchanged.

The graph distinguishes shared image, shared backend and known consumed-artifact
dependencies. It includes original/generated images, actions, observations,
detections, bindings and backend identities. A unique prior image producer or
binding supplied to execution context can establish a labeled provenance edge;
the latter is not proof that generated code actually read that binding. Temporal
adjacency or numeric box similarity does not establish selection intent.

Deduplicated image IDs can represent several coordinate frames. The observer
retains those alternatives and returns unknown/ambiguous root geometry instead
of using the most recent transform. Full-image, boundary, padded, reversed,
floating-rounding, nested, alias, fallback-resolution and pixel-deduplication
cases are covered. Generic non-crop generated images have unknown geometry;
same-canvas grounding visualizations inherit known geometry only when dimensions
agree. No candidate tracking or statistical dependence estimation was added.

## Compatibility and regression evidence

Command:

```bash
.venv/bin/python -m pytest tests -q \
  --junitxml=outputs/bite/phase03/pytest.xml
```

Final result: **569 passed, 449 subtests passed, 0 failed**, in 22.79 seconds.
The three warnings are existing pandas downcasting FutureWarnings in counting
evaluator tests. No GPU workers are launched by unit tests; existing HTTP fixture
tests use loopback with external traffic blocked. Logs:
[pytest.log](../../outputs/bite/phase03/pytest.log),
[pytest.xml](../../outputs/bite/phase03/pytest.xml).

There are **37 tests under `tests/bite`** and one new end-to-end CLI test. They
cover sequential/concurrent isolation; normal/empty/failed/invalid-result calls;
parse/schema/unknown/multi-call/image rejections; timeout classification;
recording past budget zero; internal attempts versus logical calls; no-tool and
extra-finalization paths; capability exceptions and capture failures; context
fallback/compaction; exact crop pixels and root transforms; masks and optional
fields; privacy; sidecar writes and write failure; and original scorer behavior.

Deterministic disabled/enabled replays use the **same fixed responses**, rather
than comparing independent model generations, across:

- `qwen3-vl-8b-instruct` Chat Completions;
- `gpt-6-luna` Responses;
- `kimi-k3` Chat Completions with native reasoning content.

All three preserve full request payloads, native call declarations/results, tool
arguments, tool results/evidence, final predictions and original canonical outputs
after removing only the observer metadata. Compaction has a separate equality
check. Results: [replay_protocol_validation.json](../../outputs/bite/phase03/replay_protocol_validation.json).
Existing adapter limitations, including Responses reasoning-item retention, were
not repaired or changed in this phase.

`ruff check --isolated --select E9,F63,F7,F82` on changed source/tests and
`git diff --check` both passed. The end-to-end no-tool counting CLI test preserves
the existing metrics while verifying canonical records survive without
`--keep-file-db` when observing is enabled. Default-off cleanup behavior is
covered by the original regression suite.

## Live integration

The original Qwen/router/SAM3 and other configured workers were healthy. They
were reused without restart or serving changes. Readiness results are in
[service_health.json](../../outputs/bite/phase03/service_health.json).

One new run, separate from the frozen reference, executed:

```bash
source scripts/env.sh
BITE_OBSERVER_ENABLED=true BITE_OBSERVER_RUN_ID=bite_observer_phase03 \
openvlharness-eval \
  --config configs/agent/qwen3_8b_paper.yaml \
  --judge-config configs/judge_no_judge.yaml \
  --data ODinW13_bbox_val_qwen3 \
  --num-examples 1 --shuffle --seed 42 --num-proc 1 \
  --save-html all --keep-file-db \
  --run-tag bite_observer_phase03 \
  --work-dir outputs/bite/phase03/live
```

Actual run ID:
`agent_paper_v1_judge_direct_metrics_v1_20261029_173555_bite_observer_phase03`.
Exit code 0; actual selected sample **`PascalVOC_val_262`**. The original sample
prompt and model/tool configuration were used unchanged. Outcomes:

| Check | Observed result |
| --- | --- |
| Model iterations / public dispatches | 3 / 2 |
| Successful / failed / rejected calls | 2 / 0 / 0 |
| Events | 10, capture complete with no observer errors |
| Grounding | Person score `0.984375`; horse scores `0.9765625`, `0.96484375` |
| Root frame | Both calls resolve to `input_image_1`, 500×333 |
| Native IDs | `chatcmpl-tool-ba1311d3d2b35a6c`, `chatcmpl-tool-b4c04f1636dc4aec`, each paired correctly |
| Numeric evidence | All 3 boxes/scores exactly match canonical values; all 3 mask hashes match retained counts |
| Graph | Both actions link to the root image and `sam3_segment`; no invented direct relationship between these two calls |
| Reference budget | 15 − 2 = 13 remaining, no enforcement |
| Prediction | Valid JSON with one person and two horses, root-frame 0–1000 boxes |
| Original official scorer | AP 92.52, AP50 100, AP75 100; APs/APm unavailable |

The sidecar exactly matches `extra_records.bite_observer` in the new canonical
record. The AP values happen to match the old run; **that is not the proof of
equivalence**. Fixed-response replays above provide the controlled comparison.
The new live trace has no zoom, empty result or failure; those are tested with
CPU fixtures rather than inducing benchmark failures.

Full paths and validation:
[live_validation.json](../../outputs/bite/phase03/live_validation.json).
The new run retains canonical data, observer JSON, detections, compact trajectory,
images, HTML and official scoring files. Reference integrity evidence is in
`reference_integrity_before.json` and `reference_integrity_after.json`.

## Example outputs and remaining limits

- [bite_observations.json](../../outputs/bite/phase03/bite_observations.json):
  explicitly labeled **deterministic replay**, using original numerical evidence
  with synthetic test pixels; not described as new live model execution.
- [live_bite_observations.json](../../outputs/bite/phase03/live_bite_observations.json):
  labeled copy from the real new execution, with canonical record path.
- [OBSERVATION_SCHEMA_V1.md](OBSERVATION_SCHEMA_V1.md) and
  [observation_schema_v1.json](observation_schema_v1.json): schema documentation.
- [implementation_manifest.json](../../outputs/bite/phase03/implementation_manifest.json):
  source/artifact identity, test results and live paths for review.

Runtime checkpoint revisions remain null with a reason: current worker APIs do
not attest loaded revisions. Physical attempts and full billed latency/cost remain
unmeasured. Generated-image geometry is limited to verified original/crop/overlay
cases; ambiguous deduplication and literal crop-selection intent remain unknown.
Only explicit artifact consumption establishes direct provenance; a graph does
not estimate statistical correlations. No complete live Python memory snapshot
or general task-correctness judgment is exported. Scientific numerical values
are retained in the observer or canonical records, not silently truncated.

Before constructing calibration data, review this schema, choose disjoint
image/scene manifests (including PascalVOC split aliases), define offline matching
and task-loss labels, and design prescribed/randomized action collection with
recorded selection probabilities. Keep GT-bearing evaluator artifacts outside
runtime policy inputs. Candidate association, calibrated joint outcome models,
controlled counterfactual collection and checkpoint/attempt telemetry need
separate specifications. No posterior fitting, planner, identifiability bound,
tool blocking, benchmark-wide comparison or Phase 4 work was performed.
