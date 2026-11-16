# Combined-evidence analysis (Phase 4C-1G, exploratory)

**Status: NOT EXECUTED. There are no results.** B2 and B3 cannot be built until
the Phase 4C-1F semantic pilot has run live. That needs the researcher's 4C-1F
authorization. No B3 answer exists.

## What B3 is, and what it is not

B3 presents the recorded Zoom evidence followed by the recorded semantic
observation. Both are anchored to the **same original SAM 3 candidate**:

- the semantic action renders the original image with the original box;
- it does not consume the Zoom crop;
- neither action makes the other executable.

B3 is therefore a **combined-evidence condition**. It is not:

- a test of a sequential enabling dependency;
- a demonstration of non-myopic planning;
- an estimate of an interaction or synergy value.

No interaction formula is computed. Feature interactions and non-myopic
acquisition are established concepts, and no novelty is claimed from them.

## Planned programmatic per-case diagnostics (`task_level_decision_analysis.combined_evidence`)

1. Did B1 succeed?
2. Did B2 succeed?
3. Did B3 succeed?
4. Was B3 the only successful branch (B0, B1 and B2 all wrong)?
5. Was B3's success redundant with a cheaper correct branch? (Its extra cost
   bought nothing.)
6. Did B3 fail where B1 or B2 succeeded? (Combining evidence broke a correct
   single-evidence answer.)

Counts, together with `H_combined` from Stage A and the B3-only case list by
source group and query, are the whole analysis.

A further control would separate the order and presentation effect: the same
two records in reverse order. It is **not** in the primary pilot; it would need
a separately authorized budget.

## Enabling dependencies found in the code audit (future experiments only)

- **Zoom → focused SAM 3** is a genuine enabling edge. The focused grounding
  call takes `image_id: $last_crop`, which does not exist before the crop. It
  sits *inside* B1 and is not separated here.
- No other enabling edge between the available actions was found. The other
  actions are repeated grounding, the unconfigured alternative backend and
  semantic inspection.

A future experiment that wants a real dependency effect would need a branch
whose second action consumes an artifact produced by the first, for example
semantic inspection of the Zoom crop or of focused proposals. Such a branch
would have to be preregistered as a new version. These notes are not findings.
