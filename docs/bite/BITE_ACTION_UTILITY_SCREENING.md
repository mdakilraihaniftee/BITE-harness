# BITE action-utility screening (Phase 4C-1E Stage A)

Status: **EXPLORATORY DEVELOPMENT SCREEN — NOT A POLICY, NOT A GUARANTEE**.

## Question

Is another Zoom-only calibration-fit collection justified for Task V candidate
verification? The screen reuses the frozen Phase 4C-1D out-of-fold predictions
(`initial_score_only_m0` versus `zoom_restricted_m1`). No model was refit. Each
input digest was checked against `outputs/bite/phase04c1d/manifest_checksums.json`
before use.

## Definitions

For candidate *i* with fixed original-candidate label *H_i*, decisions
*d = 1[p ≥ 0.5]*, and logical Zoom cost *c_z = 2* (crop + focused SAM 3):

- error utility: *u_i(λ) = 1[d0_i ≠ H_i] − 1[dz_i ≠ H_i] − λ c_z*
- Brier utility: *u^B_i(λ_B) = (p0_i − H_i)² − (pz_i − H_i)² − λ_B c_z*

Positive values favor acting. *λ* is in decision-error units per logical call
and *λ_B* is in squared-probability units per logical call. The two are never
added or compared. Because the cost is the same for every candidate, each net
interval is the gross interval shifted by exactly *2λ*.

Uncertainty comes from a paired percentile source-group bootstrap: 2,000
replicates, seed 463, whole groups resampled, no refitting. Candidate rows are
never resampled independently. The share of bootstrap replicates above zero is
reported as a descriptive number only. It is not a posterior probability.

## Primary expansion results (203 candidates, 30 groups, 406 extra calls)

| Quantity | IoU 0.50 | IoU 0.75 |
| --- | ---: | ---: |
| Errors avoided / introduced | 0 / 2 | 1 / 0 |
| Gross error utility (case-level) | −0.009852 [−0.025126, 0.000000] | +0.004926 [0.000000, +0.015306] |
| Gross Brier utility (case-level) | −0.000235 [−0.001262, +0.000760] | +0.000688 [−0.000188, +0.001732] |
| Gross Brier utility (group-balanced) | −0.000187 [−0.001228, +0.000793] | +0.000650 [−0.000202, +0.001654] |
| Break-even λ (error, per call) | none (already worse at λ = 0) | 0.002463 |
| Break-even λ_B (Brier, per call) | none | 0.000344 |

The error-utility intervals are percentiles of a discrete statistic. An endpoint
of exactly 0 means many replicates contain no changed decision at all.

### λ grid for error loss (mean net utility, case-level)

| λ | IoU 0.50 | prefer | IoU 0.75 | prefer |
| ---: | ---: | --- | ---: | --- |
| 0 | −0.009852 | stop | +0.004926 | act |
| 0.001 | −0.011852 | stop | +0.002926 | act |
| 0.0025 | −0.014852 | stop | −0.000074 | stop |
| 0.005 | −0.019852 | stop | −0.005074 | stop |
| 0.01 | −0.029852 | stop | −0.015074 | stop |

These preferences are based on the observed mean. At IoU .75 the interval
includes zero for every λ up to 0.005.

## Group contribution and influence

- IoU .50: the two introduced errors come from two different groups. No
  leave-one-group-out estimate of error utility changes sign. One
  leave-one-group-out Brier estimate turns slightly positive (+0.000016).
- IoU .75: the single avoided error comes from one group. Dropping that group
  makes the error utility exactly 0. The Brier gain falls to +0.000319,
  +0.000098 and −0.000007 after dropping the 1, 2 and 3 most favorable groups.
  Three groups out of 30 account for the entire observed .75 Brier gain.

## Squared-loss identity diagnostic

For each candidate, *(p0 − H)² − (pz − H)² = (pz − p0)² + 2(pz − p0)(H − pz)*
holds exactly. If *pz* were the true conditional expectation, the cross term
would have mean zero. In the expansion cohort, M1 moves probabilities very
little: the mean squared movement is 8.4e-5 at .50 and 1.05e-4 at .75, about
0.01 RMS. If these fitted probabilities were the true conditional
probabilities, the expected gain would equal that movement, about 1e-4. This is
a property of the fitted model, **not a ceiling** on what other models using the
same Zoom evidence could achieve (Phase 4C-1F correction; see
`BITE_DEPENDENT_EVIDENCE_VALUE_THEORY.md` §3). At .50 the cross term is negative (−0.000319): the
movement goes against the labels. At .75 it is positive (+0.000583). That fits a
small correction of M0's misspecification as well as a Zoom signal, and these
data cannot tell the two apart. Machine output:
`outputs/bite/phase04c1e/theory/zoom_squared_loss_identity_diagnostic.json`.

## Futility projection (planning heuristic)

Suppose the observed effect were true and the standard error shrank as
1/√groups. At IoU .50 no number of groups could show a benefit, because the
observed effect points the other way. At IoU .75, about 118 groups would be
needed for the error interval to exclude zero, and 59 for the Brier interval.
That is feasible within the 227 unused calibration-fit groups. But the benefit
being chased is about one avoided error per 203 candidates. Its break-even cost
of 0.0025 error units per call is economically negligible.

## Decision

`ZOOM_ONLY_COLLECTION_NOT_JUSTIFIED_FOR_TASK_V_VERIFICATION`.

The rule was written down before this screen was computed but after the Phase
4C-1D results were known. It requires positive observed gross error utility and
positive Brier utility at every endpoint, plus a feasible projection. IoU .50
fails all three conditions.

This decision does **not** say Zoom is useless in general. Zoom may still help
localization refinement, small objects, other domains or other tasks. It also
makes no claim of statistical action dominance. It only says that further
Zoom-only collection is a poor use of budget for this Task V verification
endpoint.

Pilot cohort (sensitivity only): no decision changes at either endpoint. The
Brier utility is −0.000912 at .50 and −0.000534 at .75.

Artifacts: `outputs/bite/phase04c1e/utility_screening/`. Code:
`evaluation_kit/bite_calibration/action_utility_screen.py`,
`scripts/bite/evaluate_zoom_action_utility.py`.
