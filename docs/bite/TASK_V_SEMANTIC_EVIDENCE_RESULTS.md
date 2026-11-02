# Task V semantic evidence results

Status: **NO RESULTS. The pilot was not executed because authorization is
absent.** This document intentionally contains no result tables. None may be
added until a researcher-authorized live run exists and has been analyzed.

## What will be reported (frozen before data)

`scripts/bite/analyze_semantic_pilot.py` (module `semantic_pilot_analysis.py`)
produces the results, separately for IoU 0.50 (primary) and IoU 0.75
(secondary).

**Support**

- candidates, source groups, positives and negatives, and groups that contain a
  positive;
- leave-one-group-out estimability.

**Observation reliability**

- response coverage and the valid-response rate;
- counts of each response status: valid, empty, malformed, schema violation,
  timeout, execution failure.

**Models** (the frozen 4C-1E design, refit on the same leave-one-group-out
folds over the same 101 states)

- M0: `m0_initial_score`
- MZ: `mz_zoom`
- MS: `ms_semantic`
- MZS: `mzs_zoom_semantic`
- MS-loc: `ms_semantic_localization_secondary`

**Metrics per model**

- Brier score, log loss and decision error at 0.5;
- group-balanced Brier;
- reliability bins with counts.

**Paired contrasts** (paired source-group bootstrap, seed 467, 2,000
replicates, no refitting; invalid draws are reported and are 0 by
construction)

- MS − M0: primary, *D_semantic*
- MZ − M0
- MZS − MS
- MZS − MZ
- MS − MZ: added in 4C-1F *before any data* (a contrast between existing
  models, not a new model)
- MS-loc − MS

Each contrast reports Brier, log-loss and decision-error differences at case
level and group-balanced level.

## Population rules

- All 101 attempted states stay in the analysis. Invalid, ambiguous and failed
  responses enter as the declared `semantic_observation_unavailable` or
  reference categories; none is dropped.
- Labels are the canonical, checksum-verified 4C-1D annotation-proxy labels for
  the original candidate. They are joined by `state_id` with a `candidate_id`
  check, and only after the GT-free table digest is finalized.
- If any leave-one-group-out training split lacks a class, the endpoint is
  reported `NON_ESTIMABLE`. The sample and the folds are never changed.

The frozen 30-group 4C-1A out-of-fold scores, and the full-fit frozen prior, are
**not** used as predictions in this 15-group comparison.

Output locations after an authorized run: `paired_metrics/`,
`grouped_uncertainty/`, `crossfit_predictions/` and `offline_labels/`, all
under `outputs/bite/phase04c1f/`.
