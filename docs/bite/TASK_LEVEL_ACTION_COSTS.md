# Task-level action costs (Phase 4C-1G)

Cost dimensions are reported **separately** and never converted into one
another. They are logical dispatches, wall-clock latency, tokens and GPU time.
No monetary cost and no GPU-seconds have been measured.

## Logical cost (frozen)

| Branch | Incremental logical dispatches | What they are |
| --- | ---: | --- |
| B0 | 0 | none |
| B1 | 2 | local Zoom crop + focused SAM 3 |
| B2 | 1 | `semantic_region_inspect_v1` (one Qwen3-VL request) |
| B3 | 3 | B1 + B2 |

Two calls are common to all branches and are excluded from `C_b`: the initial
SAM 3 grounding and the single final-answer request.

## Measured so far (archived, GT-free)

Client-side latencies of the 101 pilot states were recorded during the 4B-2B-3
collection (`outputs/bite/phase04c1f/preflight/zoom_measured_costs.json`):

| Component | Median ms | p90 ms | Max ms | Total ms |
| --- | ---: | ---: | ---: | ---: |
| Initial SAM 3 grounding (common) | 517.7 | 635.8 | 1590.4 | 55,456.7 |
| Zoom crop (local) | 82.3 | 144.9 | 262.7 | 8,941.3 |
| Focused SAM 3 | 151.4 | 242.7 | 512.9 | 17,357.8 |
| Zoom total (2 dispatches) | 233.5 | 383.3 | 772.0 | 26,299.1 |

These were measured on a different service state and date than any future VLM
call, so they are only approximately comparable.

## Estimated final-answer request sizes (`outputs/bite/phase04c1g/preflight/request_estimate.json`)

The estimate uses the Qwen-VL smart-resize rule and the cached tokenizer on the
rendered text. B2 and B3 add a 200-token allowance for the semantic block, whose
outputs do not exist yet.

| Branch | Visual tokens total | Text tokens total | Largest request (visual + text) |
| --- | ---: | ---: | ---: |
| B0 | 77,568 | 37,886 | 768 + 1,374 |
| B1 | 89,375 | 69,542 | 1,272 + 1,924 |
| B2 | 77,568 | ≈58,086 | 768 + ≈1,574 |
| B3 | 89,375 | ≈89,742 | 1,272 + ≈2,124 |

The largest request is about 3.6k tokens, including the 128-token output cap. It
fits the 168k context. The semantic action was estimated in 4C-1F at about 102k
visual and 51k text tokens over 101 requests.

## Not yet measured

The following will be added to `outputs/bite/phase04c1g/costs/measured_costs.json`
by `analyze_oracle_headroom.py` after a live run:

- final-answer latency and token usage per branch;
- semantic-action latency and tokens.

The B1/B3 presentation is longer (one extra image and about 2× the evidence
text), which is itself a confound for any accuracy difference.
