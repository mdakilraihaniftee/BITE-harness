# Grouped label-uncertainty analysis

Candidate budgets alone do not represent clustered image-level annotation
defects. This analysis therefore treats a source group as the dependency unit.

For an unrestricted group budget, each group's favorable effect is the sum of
all strictly objective-improving eligible candidate effects in that group.
Selecting the `g` most favorable group sums is exact by the same exchange
argument used for candidate effects. No within-group independence is assumed.

For simultaneous candidate and group caps, an exact dynamic program processes
groups and indexes states by `(candidate_count, group_count)`. Within a chosen
group the `k` best effects give the optimal option for each `k`; the DP retains
the best cumulative effect for every supported state. Both minimum and maximum
are solved. No heuristic or unavailable-solver qualification applies here.

## Suspected-missing-annotation group budgets

| Cohort / endpoint | Observed | g=1 interval | g=2 interval | g=5 interval | Minimum groups to reverse |
| --- | ---: | ---: | ---: | ---: | ---: |
| Expansion .50 | -0.044698 | [-0.050068, -0.036285] | [-0.055200, -0.028237] | [-0.067375, -0.005415] | 6 |
| Expansion .75 | -0.030534 | [-0.036077, -0.021168] | [-0.040791, -0.012724] | [-0.049491, 0.011644] | 4 |
| Pilot .50 | -0.014103 | [-0.034197, 0.001194] | [-0.046399, 0.014542] | [-0.065345, 0.052680] | 1 |
| Pilot .75 | -0.012470 | [-0.024971, -0.002007] | [-0.031524, 0.008376] | [-0.038169, 0.037544] | 2 |

For expansion, allowing any negative rather than suspected-missing negatives
does not change the minimum reversal group counts (6 and 4). The two-sided
scenario needs 4 and 3 groups. These are conditional endpoint stress tests;
they do not estimate clustering or assert that an affected group exists.

Full grids through 40 groups, exact combined `(m,g)` solutions, chosen group and
candidate identities, and clipped budgets are under
`outputs/bite/phase04c1b/grouped_sensitivity/`.

