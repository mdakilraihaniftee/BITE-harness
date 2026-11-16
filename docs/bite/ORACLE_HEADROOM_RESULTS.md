# Oracle headroom results (Phase 4C-1G, Stage A)

**Status: NOT EXECUTED. There are no results.**

As of 2026-11-04, no final-answer inference has been run:

- 0 of 404 final-answer units;
- 0 of 101 semantic observations.

Neither researcher authorization exists (see `PHASE_04C1G_REPORT.md`). No count
labels have been opened. This document deliberately contains no result tables.

## What will be computed (frozen in `oracle_headroom.py` and `protocol/analysis_plan.json`)

Rows are the 101 tasks. Each row carries the official count and, for each
branch, `correct ∈ {0,1}` (an invalid answer counts as 0).

| Statistic | Definition |
| --- | --- |
| Branch accuracy `A_b` | mean exact-count correctness, case-level and group-balanced; also presence accuracy and invalid count |
| Paired difference | `A_b − A_B0`, group-bootstrap interval |
| Best fixed branch (hindsight) | `argmax_b A_b`; ties go to the cheaper branch. Descriptive only, not a trained policy |
| Hindsight oracle | mean of `max_b correct_{i,b}`; **not deployable** |
| Oracle adaptivity gap | `H_oracle = A_oracle − A_fixed*` (the central RQ1 statistic), in proportion and in cases |
| Single-action oracle | oracle over `{B0, B1, B2}` |
| Combined-evidence oracle gap | `H_combined = A_oracle − A_oracle,1`; the B3-only cases and source groups are listed |
| Budget-adjusted | `U = −L − λC_b` with `C = (0, 2, 1, 3)` and `λ ∈ {0, 0.001, 0.0025, 0.005, 0.01}`. The shared initial SAM 3 call and the single final-answer call are excluded from `C_b` for every branch |
| Strata | count = 0 versus count > 0, and per query class |
| Influence | leave-one-source-group-out recomputation of `H_oracle` and `H_combined`, plus changes of the best fixed branch |
| Uncertainty | paired percentile source-group bootstrap: 2,000 replicates, seed 467. The hindsight maximizations are repeated inside each replicate, and invalid replicates are counted |

## Interpretation constraints fixed in advance

- The oracle and the best fixed branch both use outcomes. They bound the
  opportunity **within the tested branch set** only.
- There are 15 groups, so intervals are feasibility descriptions, not
  significance tests.
- If most oracle-improving cases have official count 0, the result concerns
  presence and false-positive suppression, not general counting.
- `H_combined > 0` is not evidence of synergy (see
  `COMBINED_EVIDENCE_ANALYSIS.md`).
