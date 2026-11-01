# Task V grouped uncertainty

Source group is the unit for folds and uncertainty. Queries and candidates from
one image/group never cross train/evaluation boundaries.

For each model/endpoint, 2,000 bootstrap replicates resample source groups with
replacement and retain every candidate in each sampled group. Reported
percentile intervals are conditional on the frozen out-of-fold predictions;
the model is not refitted inside each bootstrap. Replicates containing only one
target class are invalid and counted rather than assigned artificial metrics.

All primary expansion replicates were valid because positives span 25 groups at
IoU .50 and 20 at .75. Pilot invalid counts ranged from 23–33 at .50 and 70–78
at .75 because only four/three positive-bearing groups exist. The wide pilot
intervals and invalid replicates are substantive support limitations.

Case-level metrics describe the declared candidate-state distribution under
each query schedule. Group-balanced metrics average group-specific scores and
are reported as sensitivity results. Neither treats candidate rows as
independent. No confidence interval is presented as evidence about another
dataset, natural VLM query distribution, or visual correctness.

