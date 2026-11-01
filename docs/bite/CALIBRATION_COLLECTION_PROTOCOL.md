# Proposed controlled calibration collection — Phase 4B design

**Design only. Phase 4B has not started.** No alternative actions, new datasets,
probability fits or planner were executed in Task 4A. The machine-readable
[action space](calibration_action_space_v1.json) records interface support and
both proposed selection designs; it is not an executor.

## Before collection

1. Approve a labeled source and its terms. Prefer genuine ODinW train annotations
   after per-domain verification; otherwise a separate labeled development source.
   Current validation/debug traces are not a clean calibration-fit partition.
2. Freeze source-image/scene/parent groups, hashes and fit/validation/final manifests.
   Audit aliases, byte duplicates, crop ancestry and near-duplicate candidates.
   Keep all trajectories and crops from a source group in one partition. Resolve
   PascalVOC's val/test alias explicitly. Record prior development exposure.
3. Predeclare task/hypothesis semantics, target loss, class vocabulary, eligible
   actions, scoring/association/IoU policies, resource budget and failure handling.
   Detection AP is an official reporting metric, not automatically a per-task
   Bayesian loss. Proposal verification and unseen-object discovery need separate
   estimands. No fitted hypothesis/prior model is supplied by Task 4A.
4. Record source code/config/worker/checkpoint identities, preprocessing and service
   health. Do not silently configure DINO or change the original deployment.

## Initial state without hindsight

Select calibration images by a frozen source-level design, stratified by declared
domain/class metadata where appropriate. Choose initial queries from the permitted
task vocabulary using a fixed or recorded randomized schedule, including negative
class/image combinations. Do not choose query presence, regions or hypotheses from
per-image GT boxes or post-scoring diagnostics.

Run the prescribed initial grounding procedure once, retain raw outcomes including
empty/failure results, and construct the candidate/evidence state from observer
data only. Record class, raw score range, root/crop frame, relative box size,
overlap and nearby counts, shared backend, prior outcomes, remaining logical
budget and provenance validity. The current observer projection is not a full
branch snapshot: additional collection infrastructure is required below.

## Eligible actions

- **A1 root grounding:** registered original image plus runtime query; no Zoom
  prerequisite.
- **A2 repeated grounding:** same root/query/backend as the declared prior action.
  Record repeat index; repeated errors are not independent Bernoulli draws.
- **A3 crop generation:** region selected by a frozen rule using existing runtime
  proposals or permitted image/VLM evidence. Save the selecting evidence ID,
  requested coords/padding, actual integer rectangle and resulting image hash.
- **A4 focused grounding:** query on an actual registered crop produced by A3.
  It is a composition with cost 2 when a new crop is required, not one free action.
- **A5 alternative backend verification:** **not available** until separately
  configured, allowlisted and tested. Existing public grounding selects one
  backend; deployment fields must not become public tool arguments.

Zoom's immediate outcome is artifact/geometry availability. Its usefulness is
measured by subsequent proposals or prespecified task loss; do not manufacture
an immediate confidence gain. Unknown/ambiguous frames cannot provide root-box
correctness labels until provenance is resolved.

## Branch isolation

Freeze the **same complete prior state** before comparing alternatives. A later
collector must snapshot native provider history at a closed call/result boundary,
MemoryStore images/aliases/URLs/bindings and arrays, observer prefix, exact crop
frames, action eligibility, budget and all required file/content identities.
Hash the original task/input and snapshot. Exclude every offline GT/score artifact.

For each branch, deep-copy mutable state and create a separate branch namespace
and observer suffix. Preserve native declaration/result pairs within each copied
history; do not splice another branch's messages or predictions into it. Prefix
evidence is shared, suffix observations are separate. Save parent snapshot ID,
branch ID, selected action and terminal state. Do not let branch A's crop, binding,
query refinement or observations reach branch B. A state-ID string alone does
not perform or prove this cloning; no branch runner exists yet.

Separately report prefix collection cost, each branch's logical composition cost,
physical attempts where measured, model usage, latency and money. Calibration
JSONL has several candidate rows per action: deduplicate `cost_accounting_id`
instead of summing repeated per-row cost. Preserve unsuccessful attempts and
unexecuted actions explicitly; an unexecuted branch has no observed outcome.

## Two selection designs

**Deterministic coverage:** execute the prespecified affordable alternatives on
every eligible selected state, from isolated clones. The scheduled inclusion
probability is 1 within that declared coverage design; unavailable/ineligible
actions are not failed observations. Save coverage rules and exclusions. This
does not imply support for all possible states, actions or hypotheses.

**Randomized selection:** freeze the eligible action list first, then sample with
a saved seed and known positive probabilities, for example uniform `1/N` over
the N eligible alternatives. Save the complete list, design ID, selected action,
probability, RNG/seed and parent state before execution. If stratified or adaptive,
save those rules and conditional probabilities too. Do not substitute VLM token
probabilities, temperature, or the dataset-sampling seed for action propensity.

The same output may be new before any proposal exists and redundant after a
matching proposal appears. Record the prior state and the **joint** observation;
do not treat each detection row as an independent randomized action trial.
Selecting only states where a VLM expresses uncertainty would induce selection
bias; either cover those and ordinary states by design or record the selection
stratum and support limitations.

## Offline labels and dependence checks

After raw evidence is saved, an isolated offline step loads GT, verifies image
identity and labels candidates at IoU 0.50/0.75 under explicit scope/score rules.
Retain geometric validity, native one-to-one assignment and history-dependent
novel-GT evidence separately. Discard/flag ignored/crowd/unknown cases according
to the declared estimand rather than inventing negative labels. Keep missed-GT
diagnostics outside all runtime state.

Use image/crop hashes, backend/checkpoint identity, query, association comparisons,
mask references and prior producers to identify repeats and shared evidence.
These records establish provenance, not a numerical correlation model. Estimate
uncertainty later with source-group-aware splits/resampling, not shuffled tool-call
rows. Ordinary VLM histories alone do not identify an interventional kernel;
randomization, support, branch isolation, state adequacy and distributional
assumptions still require review before causal or probability claims.

## Pilot size and resources — planning estimates only

A first engineering pilot could use **20–40 approved source images**, two fixed
initial queries per image, and up to three eligible branch alternatives per state.
Depending on crop compositions, this could require **hundreds of public tool
dispatches**, not one dispatch per JSONL candidate row. Three repeats may expose
deterministic/redundant outcomes but do not create three independent source images.
These are planning examples, not a power calculation, coverage guarantee or
measured hardware/time requirement. No such pilot was run.

Measure per-action costs on that pilot before expanding. Preserve the official
model context, precision, detector thresholds and metric configuration; coordinate
GPU allocations and provider credits rather than oversubscribing. Verify licenses
before acquisition and permissions before distributing data-derived artifacts.
Publish code/schema/synthetic fixtures separately from restricted original data.

Phase 4B needs an approved data source, frozen manifests, complete snapshot/clone
runner, action-propensity metadata, explicit region-selection provenance and
negative/failure policies. It must be authorized separately; this document does
not start collection or fit the eventual BITE probability model.
