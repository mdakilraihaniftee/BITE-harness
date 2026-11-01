# Calibration estimands and hypotheses

This specification separates proposal verification from missed-object discovery.
It defines offline labels and future probability targets; it does not fit a model.

## Task V — candidate verification

Let candidate `j` be a proposal produced from runtime-visible evidence for class
`c`, mapped to verified root-image box `b_j`. For endpoint
`tau in {0.50, 0.75}`:

\[
H_V(j,c,\tau)=1
\iff
\exists g\in G_c^{eligible}: IoU(b_j,b_g)\ge\tau.
\]

`H_V=0` only when the proposal is matchable and fails that event. Unknown frame,
invalid geometry, unmapped class, or compatibility only with ignored/crowd GT is
`null`, not zero. The 0.50 and 0.75 endpoints stay separate. Native COCO
score-ordered `official_tp` remains an additional assignment label; it is not
silently substituted for geometric validity.

The initial candidate is selected after a prescribed root grounding call by
retained score descending with stable detector-rank ties. GT never selects it.
The pilot uses the first candidate; empty calls are retained as no-candidate
states. The primary future probability target is `P(H_V=1 | s)` with Brier score
as primary loss and log loss/group-aware calibration diagnostics as secondary.

Same-hypothesis interventions are: exact repeat on the same pixels/query/backend;
Zoom around the runtime candidate followed by the same class query; and a
source-level prespecified referring-expression alias when one exists. A different
class query is not candidate verification. A second SAM 3 query is dependent
evidence, not an independent perception model.

## Task D — object discovery

The root image is partitioned into the fixed normalized cells
`[0,0,500,500]`, `[500,0,1000,500]`, `[0,500,500,1000]`, and
`[500,500,1000,1000]`. The boundary rule assigns an eligible object to a cell
by the center of its root-frame GT box, with half-open left/top and closed outer
right/bottom image bounds. For region `r`, class `c`, and prior proposal history
`E_t`:

\[
H_D(r,c,t)=1
\iff
\exists g\in G_c^{eligible}: center(g)\in r
\land g\text{ is not unambiguously represented in }E_t.
\]

`H_D=0` requires that class `c` is exhaustively annotated for that image/region
and no eligible unrepresented instance satisfies the rule. Federated or
not-exhaustive annotations, invalid frames, and ambiguous prior associations are
unknown. Regions and queries are fixed before GT loading. GT supplies labels only
after raw branches are saved.

Discovery actions are broad same-class grounding, its exact repeat, and
fixed-grid Zoom followed by same-class focused grounding. Task D supports the
eventual missed-object objective. Task V alone does not establish recall or
absence of undiscovered objects.

## Observable state and joint outcomes

Future conditioning variables are runtime-visible: source domain/class, raw
score, proposal size, root/crop frame, overlap/crowding among proposals, complete
prior joint outcomes, backend/checkpoint identity, artifact dependency,
repeat/query flags, coordinate provenance and remaining logical budget. GT fields
and post-scoring diagnostics are excluded.

One grounding action retains its complete joint proposal set. Action-level
summaries may use the existing taxonomy (`new_distinct_candidate`,
`duplicate_existing_candidate`, `conflicting_candidate`, `no_detection`,
`ambiguous_association`, `execution_failure`, and
`invalid_or_unavailable_observation`) but must not reduce a multi-detection call
to several independent Bernoulli trials.

Phase 4C may estimate `P(H=1|s)` and `K_a(o|H,s)`. It must distinguish
`P(E2|H)` from `P(E2|E1,H)`, cluster uncertainty by `source_group_id`, and treat
Zoom as an artifact-producing prerequisite rather than an automatic confidence
increment.
