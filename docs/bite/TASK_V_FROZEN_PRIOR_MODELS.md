# Task V frozen annotation-proxy prior models

Status: **FROZEN FIT-ONLY RESEARCH ARTIFACTS**. They are not deployment models.

The full seven-query expansion calibration-fit cohort was used once: 30 source
groups and 203 valid candidate-present states. The pilot, calibration-validation,
and internal-test cohorts were excluded. Official counts are 31/172 at IoU .50
and 23/180 at .75.

The primary model is L2-regularized score-only logistic regression (`lambda=1`,
unpenalized intercept). Comparators are Beta(1,1)-smoothed constant prevalence
and score-plus-log-relative-area logistic regression with the same regularization.
The original retained SAM 3 score is used on its native finite `[0,1]` scale and
standardized using fit-cohort statistics. Relative area is root-frame candidate
area divided by source-image area and transformed by natural log. Missing features
produce an unsupported prediction; they are not imputed. GT, Zoom, focused, class
outcome, and post-action features are forbidden.

| Endpoint/model | Intercept and coefficients | Model-payload SHA-256 |
| --- | --- | --- |
| .50 constant | `p=0.156097560976` | `5ea81b8748243f38746dd383d68a6802b6ba67b0cd0bcdc94141442e9033c230` |
| .50 score-only | `[-3.225431689244, 2.515077600064]` | `acbbe9e29f4aa42ecd9b7c040ead9fed54ceb10b6a9427da2cf8ee45e8babe10` |
| .50 compact | `[-3.338412297002, 2.712279185549, -0.515698788933]` | `b164ef94c41b7ebb7f83f9037baa9dd85c32a5c5bb2c546d6bf5a06863b3cbdd` |
| .75 constant | `p=0.117073170732` | `319bf83595c84a738720f7d935503301ea69fba9a6db5358947fc44cce9acd58` |
| .75 score-only | `[-3.789006234704, 2.615792067873]` | `75c829e08fa2577a264129e8d3dc2e21bd7d09290715c4471c254f660784a97d` |
| .75 compact | `[-3.836836676494, 2.720324780636, -0.305260406688]` | `221e4c7d2a6e5ab568eb3cc294c103089440c4fb67ccc3153d99cbcf45dc5e27` |

The score mean/scale are `0.786965055419 / 0.128936414484`. Compact
log-area mean/scale are `-3.598291276214 / 1.397159914564`. Every serialized model
reproduced its in-memory predictions on all 203 fit rows and deterministic synthetic
inputs. The index and individual model cards are under
`outputs/bite/phase04c1c_revised/frozen_priors/`.

Independent validation metrics are frozen: candidate Brier (primary), log loss,
equal-cost error, group-balanced Brier, source-group intervals, counted reliability
bins, class support, unsupported coverage, and score distributions. Comparisons use
paired source-group evaluation. Validation outcomes may not tune transformations or
models; internal test remains locked.

