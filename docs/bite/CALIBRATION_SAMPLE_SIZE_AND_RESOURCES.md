# Calibration sample-size and resource plan

No outcome prevalence, variance, power, or universal throughput is claimed from
the one Phase 4B-1 debug image.

## Engineering pilot

After source approval, use 20–40 source groups, two GT-independent class queries
per group, one prefix per state, and at most three continuation dispatches. This
is 40–80 states and at most **160–320 logical public dispatches** including the
prefix. It is only an infrastructure and support pilot. The independence count is
20–40 source groups, not 40–80 states, branch count, detections, or JSONL rows.

Phase 4B-1 measured about 0.19–0.29 seconds for individual warmed calls on one
easy image. Applying that range mechanically gives roughly 30–93 seconds summed
tool latency for 160–320 calls, but this is not a wall-clock guarantee. Dense
masks, crop sizes, GPU contention, cold starts, transient failures and persistence
can dominate. Reserve several minutes and measure action-specific quantiles.
No model inference cost is planned.

Mask/artifact storage is unmeasured. The pilot must record compressed JSON,
content-addressed crop/overlay bytes and mask counts, then project storage from
observed upper quantiles before expansion. Dataset transfer is 2.249 GB compressed
for all ODinW-13 archives, 19.590 GB for COCO detection train, or 19.687 GB for
LVIS annotations plus COCO train images. Extracted size remains unknown; reserve
at least 2× compressed bytes until measured.

## Later calibration scale

Required strata include threshold-specific Task V positives/negatives/unknowns;
root versus crop; small/medium/large proposals; crowded/overlapping proposals;
repeat versus focus; success, no-detection, ambiguous, failure and invalid
outcomes; class/domain; and Task D novel-present/absent/unknown regions. Rare
execution failures, ambiguous associations, class-negative pairs and novel
discoveries must not be silently pooled as ordinary negatives.

For a binomial event with no prevalence assumption, the worst-case 95% Wald
half-width is approximately `0.98/sqrt(n)` independent source groups: about 0.22
at `n=20`, 0.155 at 40, 0.098 at 100, 0.049 at 400, and 0.031 at 1,000. These
are planning bounds, not a recommended estimator and not valid if correlated
candidate rows are substituted for source groups. Rare events need substantially
more data; exact/group-bootstrap intervals will be selected after the pilot.

The final size will be chosen from measured group-level prevalence, missingness,
failure rate, calibration error uncertainty and supported context cells. Sparse
class/context cells should be hierarchically merged under a prespecified rule or
return an unsupported/abstain result. They must not receive invented smoothed
certainty. Calibration validation selects complexity; internal test stays locked.

## Phase 4B-2B command shape

The existing runner currently executes a supplied snapshot/action plan, not a
dataset-wide scheduler. After an approved manifest is supplied, the next phase
should add a thin manifest iterator around the existing invocation:

```bash
.venv/bin/python scripts/bite/collect_tool_branches.py \
  --snapshot <approved-state.json> \
  --plan <frozen-action-plan.json> \
  --output-dir outputs/bite/phase04b2b/pilot/<source-group-id>
```

Do not run this template across multiple images until source approval and the
iterator have separate tests for resume, grouping and budget enforcement.
