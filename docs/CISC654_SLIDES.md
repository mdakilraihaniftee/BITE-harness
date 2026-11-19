# PARSEC-VL: presentation outline (12 slides, ~15 minutes)

These slides go with the course report [CISC654_REPORT.md](CISC654_REPORT.md). Every
number on them was measured; the evidence label (**REAL**, **FIXTURE**, or
**SYNTHETIC**) appears on every result slide. Figures are in `docs/figures/`, and
screenshots are from a real browser run in `docs/images/parsec/`.

---

## 1. Title

**Slide content**
- PARSEC-VL: Parallel Scheduling, Planning, and Speculation for a multi-agent
  visual-reasoning harness
- CISC 654 course project

**Speaker note:** we added parallel computing to an existing system without rebuilding it.

## 2. The system and the problem

**Slide content**
- A vision-language model (VLM) agent answers questions about images by calling
  tools (grounding, zoom, OCR, depth), **one call per model turn**. Up to four agents
  run together.
- Phase 1 profile (REAL):
  - model busy / wall = 0.95;
  - tool busy / wall = 0.26;
  - 0 of 90 turns made more than one call.

**Visual:** the screenshot `parsec-16-overview-light.png`.

**Speaker note:** where can parallelism come from at all?

## 3. Three parallel-computing questions

**Slide content**
1. Task parallelism: overlap independent tool calls inside a DAG, with resource
   pools and a global budget.
2. Data parallelism: multicore Monte Carlo to choose between candidate plans.
3. Speculation: start alternative branches early, without wasting GPU or budget.

**Speaker note:** each answer must include its overhead.

## 4. Design: scheduler and plans

**Slide content**
- Show the pseudocode `SCHEDULE` from report §4.1.
- Policies:
  - E0: sequential FIFO;
  - E1: parallel FIFO;
  - E2: critical-path (bottom-level) priority.
- `Execute_Action_Plan` declares actions with dependencies. A `$id` reference implies
  a dependency, and that inference is recorded.

**Visual:** the plan DAG screenshot `parsec-05-plan-dag.png`.

## 5. Work and span

**Slide content**
- Sign plan: OCR ‖ (ground → zoom → OCR). T₁ = 4d, T∞ = 3d, so T₁/T∞ = 1.33.
- Measured (FIXTURE): **1.31×**, 98% of the equal-delay idealisation; actual image-processing costs are unequal.
- 32 independent tasks (SYNTHETIC): 7.90× on 8 workers, efficiency 0.99.
  Chain: 1.00×.

**Visual:** `fig1_speedup_efficiency.png` and `fig2_policy_makespan.png`.

**Speaker note:** E2 loses to E1 when estimates are wrong (workload M), and CPU-bound
tools reach only 0.48× because of the GIL.

## 6. Multicore Monte Carlo

**Slide content**
- Pseudocode `EVALUATE`: fixed batches, with seeds set by rollout index. The
  estimates are identical for 0–16 processes.
- Results (SYNTHETIC): 12.5× on 16 processes, efficiency 0.78. The Amdahl fit gives a
  serial fraction f ≈ 0.02.
- Overhead: pool start-up 0.25 s; 0.12 s per evaluation.

**Visual:** `fig3_montecarlo_scaling.png`.

## 7. Is planning worth it? (Phase 3 fix)

**Slide content**
- Phase 2 started a pool in every planned run, costing 0.25 s even when no plan came.
- Phase 3 changes:
  - lazy, shared, or eager pool;
  - an **overhead-aware gate** that chooses heuristic, sequential, or parallel from
    predicted cost vs stakes.
- Result (FIXTURE, 1 agent): E5 run 1.337 → **1.073 s**. With no plan proposed, no
  pool starts.
- Under a 0.05 s budget, parallel Monte Carlo chooses *worse* than sequential
  (SYNTHETIC).

**Visual:** `fig8_planning_overhead.png` and `fig4_planning_budget.png`.

## 8. Speculation

**Slide content**

| Scenario (SYNTHETIC, decision latency) | Result |
|---|---|
| First branch often fails | S1 −20% (0.364 → 0.291 s) |
| First branch rarely fails | S1 +75% tool calls for −9%; S2 avoids the waste |
| One GPU slot | No gain; with capacity 2, S1 −26% |

**Visual:** `fig5_speculation_tradeoff.png` and `fig6_budget_sensitivity.png`.

## 9. Visualization in the Investigation Studio

**Slide content**
- A Gantt chart with lanes by slot, pool, or agent: queue vs execution, the critical
  path, and evidence links.
- A DAG with origin labels; budget and resources from the single ledger.
- A comparison tab labelled REAL/FIXTURE/SYNTHETIC.
- Replay never shows future events. Checked by 55 browser assertions.

**Visual:** `parsec-01-gantt-parallel-plan.png`, `parsec-08-speculative-plan-decision.png`,
`parsec-13-comparison.png`, and `parsec-14-gantt-dark.png`.

**Live demo:** `python scripts/parsec.py demo --studio`.

## 10. Whole harness and the real model

**Slide content**
- FIXTURE run wall at 4 agents:

  | OFF | E0 | E1 | E2 | E3 | E4 | E5 |
  |---|---|---|---|---|---|---|
  | 1.78 | 4.05 | 1.86 | 1.85 | 1.86 | **1.74** | 2.01 |

- REAL model:
  - natural questions: 0/20 plans;
  - when asked to plan: 10/10 valid, but the executed plans were **serial chains**,
    with 0 overlapping tool calls.
- SAM 3 throughput at 4 concurrent requests: 0.91× (REAL).

**Visual:** `fig7_whole_harness.png`.

## 11. Negative results

**Slide content**
- The real model does not plan in parallel.
- Monte Carlo is rarely worth it inside a 1 s decision; heuristic-only E5 was fastest.
- The gate's fixed cost constants made S2 slower than Phase 2's warm-pool S2.
- E2 is fragile under wrong estimates; threads give no CPU speedup; SAM 3 does not
  scale in the probe, while OCR does.

**Speaker note:** we kept these negative findings because they are the honest answer
to question 2.

## 12. Conclusions and next steps

**Slide content**
- Conclusions:
  - The scheduler reaches the work/span bound whenever the plan exposes parallelism.
  - The limit is the model's planning behaviour and the cost of model inference, not
    the scheduler.
- Next steps:
  - online calibration of the gate;
  - a speculation objective that includes model turns;
  - prompting or tuning the model for independent actions;
  - batched GPU services.
- Reproduce: `python scripts/parsec.py demo`, then `python scripts/parsec.py figures`
  (see `docs/REPRODUCIBILITY.md` §8).
