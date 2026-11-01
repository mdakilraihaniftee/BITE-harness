# Task V annotation-proxy prior calibration experiment

Status: **`ANNOTATION_PROXY_EXPLORATORY`**. Hyperparameters and features were
fixed before evaluation. Only existing `calibration_fit` evidence is used.

The primary target population is candidate-present states from the expansion's
all-seven-class query schedule. The two-query pilot is a separate sensitivity
cohort. Neither represents naturally selected VLM queries. IoU 0.50 and 0.75
annotation endpoints are fitted separately and are not visually verified truth.

## Frozen models

- A: fold-training prevalence with Beta(1,1) smoothing,
  `(n_positive + 1)/(n + 2)`.
- B: L2 logistic regression on retained initial SAM 3 score.
- C: L2 logistic regression on score and natural-log relative candidate area.

For B/C, lambda is 1.0, the intercept is unpenalized, score is unchanged in
`[0,1]`, and feature mean/scale are fitted only on the training fold. Newton
optimization uses a 100-iteration bound and `1e-9` step tolerance. Missing or
invalid initial features are unsupported rather than imputed.

Forbidden inputs include GT IoU/identity, label as a feature, annotation
presence, focused/Zoom outcomes, future scores, source-group/image identity,
human review, and hashes. Source group is retained solely for splitting and
uncertainty.

Three deterministic grouped folds use seed 431. Every source group appears in
exactly one evaluation fold, and every training fold contains both classes.
Metrics are paired on identical out-of-fold cases: Brier, log loss, forced
decision error at 0.5, fixed reliability bins, and group-balanced sensitivity.
No hyperparameter was selected on evaluation folds.

