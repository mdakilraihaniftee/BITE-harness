# Task V Zoom cost and risk analysis

Status: **OFFLINE OBSERVED DECISION DIAGNOSTIC — NOT A POLICY**.

At IoU .50, stop-only makes 29 errors (8 false positives, 21 false negatives).
Always-Zoom makes 31 (8 false positives, 23 false negatives): zero errors are
avoided and two are introduced. At IoU .75, stop-only makes 25 errors (6/19),
while Always-Zoom makes 24 (5/19): one error is avoided and none introduced.

Always-Zoom consumes 406 incremental logical calls for the 203 expansion cases.
Stop-only consumes zero. With loss `error + 2*lambda`, .50 has no nonnegative
break-even penalty because Zoom is already worse at zero cost. The .75
break-even penalty is 0.002463 per logical call. On the prespecified grid,
Always-Zoom is preferred at .75 only for `lambda` 0 and 0.001; stop-only is
preferred by 0.005. No latency or monetary value is inferred from `lambda`.

These are decisions over a fixed, pre-existing original-candidate label. The
action changes observed information, not correctness. Recorded branches do not
identify an observation distribution or causal policy value. The result omits
missed objects, answer quality, agent feasibility and all other end-to-end task
losses. No online action selector, posterior or budgeted planner was implemented.

Machine tables are in
`outputs/bite/phase04c1d/cost_analysis/stop_vs_always_zoom.json`.
