# Calibration research amendment v1

Envelope: **`bite.calibration_research_amendment.v1`**. This amendment extends,
but does not rewrite, the Phase 4A/4B records or frozen Phase 4B-2A protocol.
Machine form: [calibration_research_amendment_v1.json](calibration_research_amendment_v1.json).

## Belief, observation kernel and decision risk

For Task V and threshold `tau` in `{0.50, 0.75}`, `H_V` is the existing binary
candidate-validity label. The runtime belief is

\[
p_t=P(H_V=1\mid s_t).
\]

The retained SAM 3 score is a post-threshold detector output, not `p_t`. A higher
score after Zoom can coexist with the same incorrect object, altered scale, score
censoring, or association ambiguity; it is therefore not automatically a higher
posterior probability.

For eligible action `a`, the later conditional model targets

\[
K_a(o\mid H_V,s_t)=P(O_a=o\mid H_V,s_t,do(a)).
\]

This is an operational intervention distribution over collected tool actions. It
is not automatically a fully identified physical-world causal kernel. Support,
selection, unmeasured state, annotation completeness and source shift remain
assumptions to validate.

`s_t=phi(H_t)` uses `bite.operational_state.v1`. Predictive features are task and
candidate class, source domain, relative size, raw score and availability,
proposal overlap/crowding, root/crop frame, previous outcome, shared backend,
repeat status, derived-artifact dependency, localization/provenance ambiguity and
remaining logical budget. Source-group and image hashes are stored separately for
clustering/audit and are forbidden as memorized predictive answers. This is a
restricted runtime-visible projection, not the complete hidden world.

Brier score and negative log likelihood evaluate probabilities. Initial Task V
decision analysis uses forced binary error `1[hat(H_V) != H_V]`. Official ODinW
AP remains an end-to-end ranked detection metric and is unchanged. Brier score is
not AP, and AP is not treated as a decomposable one-candidate Bayes loss. Later
work may add prespecified per-image localization/recall loss alongside the
original evaluator.

## Target-aligned outcomes

`bite.target_aligned_outcome.v1` retains the complete joint proposal set and
adds a runtime-only summary about one original candidate:

- `target_aligned_supporting_proposal`;
- `same_geometry_repeated`;
- `localization_disagreement`;
- `ambiguous_target_association`;
- `no_target_aligned_proposal`;
- `successful_empty_detection`;
- `backend_failure`;
- `invalid_or_missing_result`.

Association uses only class, source lineage and root-frame geometry. Multiple
plausible focused detections remain ambiguous; the strongest crop score is never
assumed to identify the original object. GT identity is absent. Existing Phase
4A outcome fields remain intact.

Task D uses the separate `bite.discovery_outcome.v1`, which summarizes runtime
proposal-set novelty/redundancy/ambiguity and still requires an offline discovery
label. Verification failure for one candidate does not imply a missing-object
region is empty, and a new runtime proposal does not prove an eligible unseen GT
instance exists.

## Dependency and incremental information

The protocol distinguishes exact repeat, modified same-backend query, derived
crop plus same backend, and genuinely different verified backend. Only the first
three are currently available; none is declared independent.

An exact repeated false positive can reproduce the same box and score while
`H_V=0`. The repeated record preserves its original observation ID, image hash,
backend, query and dependency lineage. A future conditional model must estimate
incremental value through `P(E2|E1,H,s)`, not multiply marginal detector scores.
Perfect repetition may have zero incremental information.

Zoom is operationally useful because it changes scale, crop framing and the
backend input. It creates no new photons or independent raw-image evidence. Its
value belongs to the Zoom→focused-grounding composition and must be estimated
conditional on the parent pixels and selection rule.

Full identifiability certificates are deliberately deferred. They require
validated outcome models, statistical uncertainty sets, support/selection and
shift assumptions, bounded solver error, and a theorem establishing the direction
of attainable/impossibility bounds. No probability, posterior, planner or
certificate is implemented here.

## Query-schedule amendment

The Phase 4B-2A request for two classes is amended without modifying its frozen
file:

```python
scheduled_count = min(requested_classes_per_group, available_verified_classes)
```

Classes are ordered by SHA-256 of seed `417`, source-group ID and case-folded
class. GT presence is never read. One-class domains schedule one class; no extra
class or false absence label is fabricated. The actual count is recorded under
`bite.query_schedule.v2`.
