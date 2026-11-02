# BITE action cost comparison

Status: **Zoom costs MEASURED (archived). Semantic costs ESTIMATED ONLY; no
semantic call has been made.**

Cost dimensions are kept separate and never summed across units.

| Dimension | Zoom (crop + focused SAM 3) | Semantic inspection (Qwen3-VL-8B) |
| --- | --- | --- |
| Logical dispatches per candidate | 2 | 1 |
| Wall-clock latency (client side) | **measured** over 203 branches: median 218 ms, p90 385 ms, max 772 ms; crop median 75 ms (local PIL), focused SAM 3 median 147 ms | not measured; recorded per request once executed |
| Pilot-subset latency (101 states) | median 234 ms, total 26.3 s | not measured |
| Model tokens | not applicable | estimated: about 1,012 visual (832–1,536) + 509 text input tokens per request; ≤ 256 output |
| GPU time | not measured | not measured |
| Monetary cost | unknown (local hardware) | unknown (local hardware) |
| Initial SAM 3 grounding (shared baseline) | measured: median 514 ms over 210 states | — |

Sources:

- `outputs/bite/phase04c1f/preflight/zoom_measured_costs.json`, from the
  client-side `latency_ms` in Phase 4B-2B-3 GT-free branch records;
- `preflight/request_estimate.json`.

The latencies were recorded on a different date, under a different service load
and on different serving stacks. They are only approximately comparable to any
future VLM latency.

## Utility convention for the post-pilot decision screen

*U_a(λ) = R_0 − R_a − λ c(a)*. *R* is the binary decision error, or separately
the Brier loss, and *c(a)* is the **logical** dispatch count. For each fixed
policy (Always-MZ, Always-MS, Always-MZS versus stop with M0), the screen reports:

- errors avoided and errors introduced;
- additional calls;
- break-even λ;
- the λ grid from Phase 4C-1E;
- influence diagnostics.

These come from `action_utility_screen.screen_action` with seed 467. Token and
latency costs are reported next to the logical-call utility, never converted
into its units without a declared normalization.

If semantic evidence improves calibration but changes no thresholded decision,
no decision-policy improvement is claimed. If it changes decisions, both the
avoided and the introduced errors are reported. This is an offline fixed-action
comparison, not a planner.
