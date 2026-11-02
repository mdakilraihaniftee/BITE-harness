# Task V Zoom incremental-prediction results

Status: **ZOOM INCREMENTAL SIGNAL INCONCLUSIVE**. These are source-group-
disjoint cross-fitted `calibration_fit` results, not validation.

| Endpoint | Model | Brier | Log loss | Error @ .5 | Group-balanced Brier |
| --- | --- | ---: | ---: | ---: | ---: |
| IoU .50 | M0 score-only | 0.085108 | 0.261622 | 0.142857 | 0.083045 |
| IoU .50 | M1 score + Zoom | 0.085342 | 0.262718 | 0.152709 | 0.083233 |
| IoU .75 | M0 score-only | 0.075511 | 0.229662 | 0.123153 | 0.073862 |
| IoU .75 | M1 score + Zoom | 0.074823 | 0.228207 | 0.118227 | 0.073211 |

Signed differences are M1 minus M0; negative favors Zoom.

| Endpoint | Brier difference [95% grouped CI] | Log-loss difference [95% grouped CI] | Error difference [95% grouped CI] |
| --- | ---: | ---: | ---: |
| IoU .50 | +0.000235 [-0.000737, +0.001254] | +0.001096 [-0.001986, +0.004327] | +0.009852 [0.000000, +0.024752] |
| IoU .75 | -0.000688 [-0.001734, +0.000168] | -0.001455 [-0.003839, +0.000624] | -0.004926 [-0.015000, 0.000000] |

Both Brier intervals cross zero and the endpoints point in opposite directions.
The prespecified primary comparison therefore provides no reliable incremental
signal. Prediction coverage is 203/203 at each threshold: 31/172 positives and
negatives at .50 and 23/180 at .75 across 30 groups. There are 176 valid unique
observations and 27 explicit ambiguous/missing observations.

The one-feature geometry comparator had Brier 0.084291 at .50 and 0.075717 at
.75. Its M0 differences were -0.000817 [-0.003826, +0.002981] and +0.000206
[-0.001783, +0.002064]. It is an exploratory secondary result, not a rescued
positive result. The pilot sensitivity also did not resolve the question: M1
worsened Brier by 0.000912 at .50 and 0.000534 at .75 on only four/three
positives.

The deterministic within-query shuffled-Zoom control worsened .50 M1 Brier to
0.090992 but yielded 0.074588 at .75. This mixed control behavior reinforces
that sparse correlations and endpoint structure can produce small apparent
changes; it was not used to revise features. The synthetic injected-signal test
confirms the pipeline can detect a strong known conditional signal.

Machine results are under `outputs/bite/phase04c1d/paired_metrics/`,
`crossfit_predictions/`, `models/` and `grouped_uncertainty/`.
