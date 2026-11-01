# Phase 4C paired prior-model comparison

Status: **development-only paired analysis complete**. All numbers were
recomputed from the frozen Phase 4C-1A out-of-fold records; no model was
refitted. Differences are model loss minus baseline loss, so negative values
favor the first model. Intervals are paired 95% percentile intervals from
2,000 source-group bootstrap draws. Every model uses the identical draw in a
replicate. Candidate rows are never resampled independently.

## Seven-class expansion (primary)

| Endpoint | Comparison | Brier difference [95% CI] | Log-loss difference [95% CI] | Error difference [95% CI] |
| --- | --- | ---: | ---: | ---: |
| .50 | score − constant | -0.044698 [-0.060112, -0.028660] | -0.167339 [-0.207006, -0.125506] | -0.009852 [-0.043478, 0.024510] |
| .50 | compact − constant | -0.044653 [-0.060105, -0.028592] | -0.172336 [-0.212280, -0.132319] | -0.004926 [-0.033654, 0.024390] |
| .50 | compact − score | 0.000044 [-0.004915, 0.005501] | -0.004998 [-0.017074, 0.008068] | 0.004926 [-0.015000, 0.025924] |
| .75 | score − constant | -0.030534 [-0.044531, -0.015740] | -0.146947 [-0.184056, -0.108762] | 0.009852 [-0.019512, 0.042862] |
| .75 | compact − constant | -0.030173 [-0.044698, -0.015761] | -0.145977 [-0.185467, -0.106885] | 0.004926 [-0.024876, 0.035757] |
| .75 | compact − score | 0.000361 [-0.002464, 0.003518] | 0.000970 [-0.006840, 0.009892] | -0.004926 [-0.026645, 0.015002] |

The group-balanced score-minus-constant Brier differences are -0.044411
[-0.059431, -0.028657] at .50 and -0.030727 [-0.044571, -0.016411] at .75.
All group-balanced model/metric comparisons are retained in the machine
artifacts. Score-only has a robust development Brier/log-loss advantage over
constant prevalence under this fixed evaluation. Error differences cross zero.
The compact model has no resolved advantage over score-only.

## Two-query pilot sensitivity

| Endpoint | Comparison | Brier difference [95% CI] | Log-loss difference [95% CI] | Error difference [95% CI] |
| --- | --- | ---: | ---: | ---: |
| .50 | score − constant | -0.014103 [-0.058159, 0.038524] | -0.080358 [-0.194250, 0.049914] | 0.026316 [-0.078947, 0.157895] |
| .50 | compact − constant | -0.006199 [-0.057287, 0.058491] | -0.063620 [-0.189861, 0.091496] | 0.026316 [-0.078947, 0.157895] |
| .50 | compact − score | 0.007904 [-0.000432, 0.021166] | 0.016738 [-0.001988, 0.045257] | 0.000000 [0.000000, 0.000000] |
| .75 | score − constant | -0.012470 [-0.045545, 0.014341] | -0.068219 [-0.171124, 0.018959] | 0.000000 [0.000000, 0.000000] |
| .75 | compact − constant | -0.002607 [-0.040039, 0.038742] | -0.047748 [-0.156947, 0.061868] | 0.026316 [0.000000, 0.078947] |
| .75 | compact − score | 0.009863 [0.000041, 0.025949] | 0.020471 [0.000013, 0.054029] | 0.026316 [0.000000, 0.078947] |

The pilot query regime is not pooled with expansion. Its score-versus-constant
intervals are inconclusive. Selecting score-only after viewing these same
development observations creates selection optimism; paired resampling does not
remove it. Independent validation must apply the already frozen selection rule.

