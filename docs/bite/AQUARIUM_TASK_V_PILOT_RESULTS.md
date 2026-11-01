# Aquarium Task V pilot results

These are measured Phase 04B-2B-2 observations, not fitted probabilities.

## Sample and actions

| Quantity | Observed |
| --- | ---: |
| Source groups / images | 20 / 20 |
| Scheduled query states | 40 |
| Successful initial grounding | 40 |
| Candidate-present / no-candidate states | 38 / 2 |
| Prefix / repeat / Zoom / focused calls | 40 / 38 / 38 / 38 |
| Failed dispatches / partial compositions | 0 / 0 |
| Actual / maximum logical calls | 154 / 160 |

The two no-candidate states came from the same frozen source group for `starfish`
and `fish`. They were retained without replacement and did not run Task V
continuations.

## Runtime outcomes

| Outcome | Count |
| --- | ---: |
| Repeat boxes, scores, and masks all exactly identical | 38 |
| Focused unique target alignment | 32 |
| Focused aligned box changed | 32 |
| Focused aligned score changed | 32 |
| Ambiguous target association | 5 |
| No target-aligned focused proposal | 1 |

Exact repetition therefore added no observed output diversity under the current
worker configuration. It remains dependent evidence and must not be counted as
an independent Bernoulli replicate. Zoom changed every uniquely aligned proposal,
but its association was not always identifiable from runtime geometry alone.

## Original candidate labels

| Threshold | Positive | Negative | Unknown |
| --- | ---: | ---: | ---: |
| IoU 0.50 | 4 | 34 | 0 |
| IoU 0.75 | 3 | 35 | 0 |

At IoU 0.50, small candidates were 1 positive / 18 negative, medium candidates
3 / 14, and large candidates 0 / 2. Jellyfish, puffin, starfish, and fish had no
positive original candidate in this small sample. The per-query and per-size
tables are preserved in `pilot_audit.json`.

## Latency and storage

| Action | Median ms | p95 ms | Maximum ms |
| --- | ---: | ---: | ---: |
| Prefix grounding | 580.2 | 1459.5 | 1682.2 |
| Exact repeat | 558.5 | 1229.6 | 1424.2 |
| Zoom | 81.6 | 179.1 | 208.7 |
| Focused grounding | 153.9 | 285.6 | 332.6 |

The run directory contains 671 measured state files totaling 166,055,510 bytes;
191 content artifacts account for 97,263,925 bytes. Consolidated offline output
contains 40 initial-candidate records and 226 branch calibration rows. Aquarium
images are retained only as internal content-addressed run artifacts and are not
embedded in these reports. Source attribution remains Aquarium Combined
(Roboflow), CC BY 4.0, via the GLIP-curated archive.

