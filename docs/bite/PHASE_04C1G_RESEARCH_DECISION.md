# Phase 4C-1G research decision

Date: 2026-11-04.

**Outcome: `EXPERIMENT_INSUFFICIENT_OR_INVALID`.**

**Blocker: tool and model execution is not authorized.** This is the
predeclared outcome E condition.

## Evidence

| Item | State |
| --- | --- |
| Phase 4C-1F semantic-pilot authorization | absent (`outputs/bite/phase04c1f/authorization/`) |
| Phase 4C-1G final-answer authorization | absent (`outputs/bite/phase04c1g/authorization/`) |
| Qwen service at `127.0.0.1:8222` | not running |
| Semantic observations (needed for B2/B3) | 0 / 101 |
| Final-answer units | 0 / 404 |
| Real model calls this phase | **0** |
| Count labels opened | no |

No oracle gap, selector value, transition count or combined-evidence count
exists, so none can be reported. The predeclared screen
(`task_level_decision_analysis.DECISION_RULE`) returns outcome E by
construction. No result was inferred from the earlier candidate-correctness
experiments.

## What is ready

- A frozen, reproducible Protocol A probe: 101 tasks, 4 branches, with prompt,
  parser, renderer and analysis plan all digested.
- Both live runners with cumulative caps, a combined 505 ceiling and
  raw-before-GT finalization.
- A 202-unit mock B0/B1 contract run over every real input, with no network and
  no labels.
- The complete post-collection analysis, tested on synthetic signal and null
  data.

## Answers to the next-research questions (given that no data exist)

1. **Is there enough opportunity to justify a new BITE controller?**
   Unknown. This phase produced no measurement. The prior evidence is weak:
   - 4C-1D Zoom changed candidate-correctness decisions by −2 and +1 net
     errors over 203 candidates;
   - the Brier changes were negligible.

   That is a weak prior for large task-level headroom from Zoom alone.
2. **Does the opportunity require a method beyond single-call acquisition and
   value-of-information baselines?** Nothing shows that it does. P1–P3 are
   exactly such baselines. A new method would be motivated only by outcome D,
   that is, headroom that P2/P3 cannot capture.
3. **Would another task family be needed?** Possibly, but only as a future,
   preregistered version.
   - The 7-class query schedule makes many tasks class-absent queries on which
     SAM 3 nevertheless returned a candidate. The count-zero stratum may
     dominate, which would make this a presence and false-positive study rather
     than a counting study.
   - That is to be checked after data exist. No family is added now.
4. **Is a larger paired experiment scientifically justified?** Not yet. It
   would be justified only if this pilot reaches outcome D, with gains spread
   over several source groups and surviving λ = 0.01. Outcomes A, B and C all
   argue against scaling this design.
5. **What exact missing result prevents a research novelty claim?** Everything
   downstream of execution, namely:
   - a measured oracle adaptivity gap with group-level uncertainty;
   - evidence that a group-held-out pre-call selector captures part of it;
   - evidence that a material residual remains beyond simple selectors, at
     matched cost, not concentrated in one group and not explained by
     presentation length;
   - replication of the above on independent groups.

   Even then, oracle headroom, VOI-style selection and combined evidence are
   established concepts and not novel in themselves.

## To change this decision

The researcher must:

1. start the Qwen service;
2. write both authorizations;
3. run the canaries and resumes;
4. run `analyze_oracle_headroom.py`.

The commands are listed in `TASK_LEVEL_PROBE_PROTOCOL.md` §7. Once the analysis
has run, this document should be superseded by a dated addendum. The analysis
plan must not be edited.
