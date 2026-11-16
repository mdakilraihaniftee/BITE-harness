# Learnable headroom results (Phase 4C-1G, Stage B)

**Status: NOT EXECUTED. There are no results.** No branch outcomes exist, so no
selector was fitted or evaluated. The selectors have been tested on synthetic
data only:

- a known-signal case, where P2 and P3 recover more than 85% of the headroom
  and the outcome is classified as `SIMPLE_POLICY_SUFFICIENT`;
- a null case, where P3 − P1 has a bootstrap lower bound ≤ 0 and is never
  classified as `PROMISING_PREDICTABLE_HEADROOM`.

## Frozen design (`learnable_headroom.py`, `SELECTOR_SPEC`)

**Pre-call features.** There are four, all available after the initial SAM 3
call and before any extra action (`task_manifest/precall_features.jsonl`):

| Feature | Definition |
| --- | --- |
| `initial_score` | score of the selected (highest-scoring) candidate |
| `log_proposal_count` | `log(number of initial proposals)` |
| `top_box_relative_area` | selected box area / image area |
| `score_gap` | top score − second score (top score when there is one proposal) |

Excluded:

- source group, entry or image identifiers;
- official count;
- any Zoom or semantic output;
- oracle choice;
- query class (seven levels over 14 training groups are too sparse);
- remaining budget (constant);
- image size (almost constant).

`validate_features` rejects any other key.

**Policies.** All are fitted with leave-one-source-group-out (15 folds, 14
training groups each). Preprocessing, thresholds and coefficients use training
groups only.

| Policy | Rule |
| --- | --- |
| P0 stop-only | always B0 |
| P1 training-fold fixed | branch with the best training-fold mean utility |
| P2 score threshold | B0 if `initial_score ≥ τ`, else action `a`; `(τ, a)` maximize training utility over `τ ∈ {0.3, …, 0.9}` and `a ∈ {B1, B2, B3}` |
| P3 action-value | per-branch ridge logistic (L2 = 1, intercept unpenalized) of `P(correct \| x)`; choose `argmax_b p̂_b − λC_b`. A constant training target gives an intercept-only model; P3 is reported `NON_ESTIMABLE` if more than half of the fold × branch fits are intercept-only |
| P4 direct VLM choice | **not run**; it needs separate authorization, and its calls would count as cost |

**Reported for each λ:**

- utility, accuracy and group-balanced utility;
- mean incremental cost and the branch distribution;
- differences against P0, P1 and the hindsight best fixed branch;
- the hindsight oracle (labelled `UNATTAINABLE_HINDSIGHT_ORACLE`);
- the recovery fraction `(U_sel − U_fixed*) / (U_oracle − U_fixed*)`. It is
  undefined when the denominator is below 0.02;
- group-bootstrap intervals for selector − P0, selector − P1 and P3 − P2, with
  the LOGO predictions held fixed (no refit inside the bootstrap);
- leave-one-group-out influence with the selections held fixed.

A simple selector that works well is **evidence against** needing a new
controller. It is not a BITE contribution.
