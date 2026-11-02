# Task-level extension proposal: from candidate correctness to user-task success

Status: **FUTURE PROPOSAL ONLY. No agent or VLM inference was run.**

## Why

Task V asks whether one SAM 3 box matches an annotation at IoU ≥ τ. A user task
asks something else. Candidate correctness and task success can disagree:

- A wrong box can still lead to a correct "yes, there is a shark."
- A correct box for a fish can sit next to a wrong answer to "how many fish?"

So *H_τ* is not task success, and BITE's eventual claim must be measured on a
task loss.

## T1 (first task family): queried-object presence verification

**Task.** Given an image *x* and a class *q* from the 7-class vocabulary, answer
`present`, `absent` or `abstain`.

**Offline target.** *Y_q(x) = 1[G_q(x) ≠ ∅]*: some annotated instance of *q*
exists. This is still an annotation proxy. `absent` means "no annotated
instance", and the protocol amendment's limits on annotation completeness
apply.

**Why T1 first.** It reuses data that already exist:

- The expansion (30 groups) already contains SAM 3 outputs for **all seven
  queries** on every representative image (210 states), including the 7
  no-candidate states. The original pilot used two GT-blind queries per group,
  so it covers presence only for those query pairs. No new SAM 3 calls are
  needed for T1 on the expansion.
- The semantic pilot will add one VLM observation on the top candidate for
  101 states.
- Because the coverage design ran every *recorded* action from the same frozen
  state, some policies can be replayed exactly. This only holds for policies
  whose every reachable action, observation and transition is represented in
  the recorded branches (see the correction below).

> **Correction (Phase 4C-1F, 2026-11-02).** An earlier wording said "any
> deterministic policy over {stop, Zoom, semantic} can be evaluated offline
> exactly". That is too broad. Exact replay holds only under all of these
> assumptions:
>
> 1. The policy acts on states in the recorded population (the 101 semantic
>    pilot states, or the 203 Zoom states for Zoom-only policies).
> 2. It uses only the recorded actions, each at most once, applied to the
>    original frozen state with their recorded inputs.
> 3. Each recorded observation does not depend on what other actions ran
>    before it. Here that is true by construction: Zoom and the semantic action
>    branch independently from the same snapshot, and the semantic input never
>    uses Zoom output.
> 4. The single recorded draw of each tool output is treated as *the*
>    observation. Under deterministic serving this is exact. Under stochastic
>    serving the replay evaluates one realization only.
>
> Replay does **not** evaluate adaptive policies that:
>
> - feed one action's output into another (for example, semantic inspection of
>   the Zoom-refined box, or a crop of a focused detection);
> - re-query with a different class or prompt;
> - repeat a stochastic action;
> - act on no-candidate states with unrecorded actions;
> - interact with the agent's own language reasoning.
>
> Those policies need new collection or an explicit off-policy design with
> logged propensities.

**Policies to compare.** Each is fixed before outcomes are seen.

| Policy | Rule |
| --- | --- |
| P0 stop | `present` iff a candidate exists and *p0 ≥ t* |
| P-Z | always Zoom, then decide with the MZ model |
| P-S | always run the semantic action, then decide with the MS model |
| P-band(δ) | run the semantic action only if *\|p0 − t\| < δ*, motivated by the threshold effect in `BITE_DEPENDENT_EVIDENCE_VALUE_THEORY.md` §4 |
| P-abstain | any of the above, with abstention when evidence is `unclear`, `insufficient` or unavailable |

The grid for *t* and *δ* is fixed on calibration-fit data. Final numbers are
reported only on a held-out partition after separate authorization.

**Metrics.**

- task error and selective risk at matched coverage;
- abstention rate;
- logical calls, VLM tokens and latency;
- net utility under a declared per-call penalty, with error and token costs
  kept in separate units.

All intervals use the source-group bootstrap.

**Population caveat.** Asking all seven classes about every image makes absence
dominate. In the combined data, 191 of the 206 annotation negatives at .50 have
no annotated instance of the queried class. T1 results under this design must be
reported separately from the agent-selected query regime
(`TASK_V_AGENT_SELECTED_QUERY_PROTOCOL_PROPOSAL.md`). There, the frozen agent
picks queries from the task context and the prevalence will differ.

## T2: region category verification

Given a fixed region, which dataset category is it, if any? The offline target
is the category of the best class-agnostic annotation match at IoU ≥ 0.5, or
"none". The semantic action's `region_content` answers this directly. T2 also
separates *recognition* from *localization*: report the localization field
against IoU ≥ 0.75 on its own.

## T3: conflict resolution (needs a new action design)

T3 starts when SAM 3 support is high and the semantic observation conflicts, or
the other way round. The agent then chooses between a further action and
abstaining. Candidate further actions are a second semantic view at a different
context scale, or a whole-image VLM presence question. Each would need its own
frozen contract and dependence analysis. T3 is deferred until the pilot shows
how common conflicts are.

## Deferred: counting

Counting needs complete annotations. The 20 completed human reviews cannot
estimate how often annotations are missing, and the probability sample is
incomplete. Counting stays out of scope until completeness is assessed.

## Task-level uncertainty sources to record

- whether the object exists;
- class identity, including the taxonomic overlaps fish/shark/stingray;
- localization adequacy;
- missed objects, which a candidate-level hypothesis cannot see;
- whether the right tool was chosen;
- unresolved ambiguity (`unclear`, `ambiguous`);
- final-answer correctness.

## Prerequisites before any task-level run

1. Live semantic pilot executed and analyzed (separate authorization).
2. T1 policy grid, metrics and loss units frozen in a versioned protocol.
3. SAM 3 matched-worker bridge, or attested worker, for any new SAM 3 calls.
4. Separate authorization for held-out (calibration-validation) evaluation. The
   internal test stays locked.
