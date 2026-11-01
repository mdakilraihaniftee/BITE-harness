# Task V exploratory annotation-proxy prior results

These are cross-fitted `calibration_fit` development results, not blind
validation and not estimates of visual truth.

## Primary seven-class expansion

| Endpoint / model | Brier | Log loss | Error @ 0.5 | Group-balanced Brier | Group-bootstrap Brier 95% interval |
| --- | ---: | ---: | ---: | ---: | ---: |
| IoU .50 constant | 0.129805 | 0.428961 | 0.152709 | 0.127457 | [0.108688, 0.153219] |
| IoU .50 score | **0.085108** | 0.261622 | **0.142857** | **0.083045** | [0.070286, 0.102171] |
| IoU .50 score + area | 0.085152 | **0.256624** | 0.147783 | 0.083244 | [0.070625, 0.101487] |
| IoU .75 constant | 0.106045 | 0.376608 | **0.113300** | 0.104589 | [0.085080, 0.128887] |
| IoU .75 score | **0.075511** | **0.229662** | 0.123153 | **0.073862** | [0.060080, 0.091632] |
| IoU .75 score + area | 0.075872 | 0.230632 | 0.118227 | 0.074200 | [0.060519, 0.092358] |

Support is 203 candidates in 30 groups: 31 positives across 25 groups at IoU
.50 and 23 across 20 groups at .75. Fold evaluation positives are 10/10/11 at
.50 and 8/8/7 at .75.

Score-only materially improves Brier/log loss over constant prevalence. Adding
relative area is not a consistent improvement: at .50 its Brier worsens by
0.000044 and error by 0.004926 while log loss improves by 0.004998; at .75 it
worsens Brier by 0.000361 and log loss by 0.000970 while improving error by
0.004926. Model C therefore has no demonstrated general advantage over B.

Twenty-seven IoU-.50 annotation-negative expansion candidates have initial
score at least .90. Their score-model probabilities average 0.416 and range
0.291–0.615; compact-model probabilities average 0.419 and range 0.127–0.629.
Thus a near-one detector score is not automatically emitted as a near-one proxy
probability. These remain possible annotation omissions, not visually verified
false detections.

## Pilot sensitivity

| Endpoint / model | Brier | Log loss | Error | Brier 95% interval | Invalid single-class bootstrap replicates / 2000 |
| --- | ---: | ---: | ---: | ---: | ---: |
| .50 constant | 0.106236 | 0.389120 | 0.105263 | [0.048384, 0.178625] | 33 |
| .50 score | **0.092133** | **0.308762** | 0.131579 | [0.039134, 0.159104] | 23 |
| .50 score + area | 0.100036 | 0.325500 | 0.131579 | [0.037409, 0.179433] | 24 |
| .75 constant | 0.073752 | 0.281940 | **0.078947** | [0.032398, 0.135782] | 72 |
| .75 score | **0.061282** | **0.213721** | **0.078947** | [0.022469, 0.122606] | 78 |
| .75 score + area | 0.071145 | 0.234192 | 0.105263 | [0.024130, 0.135630] | 70 |

Only four pilot groups bear a .50 positive and three bear a .75 positive. These
intervals are unstable sensitivity results, not support for pilot-specific
deployment. Class, size, annotation-scope, and score-saturation tables remain
descriptive and were not used for model selection.

