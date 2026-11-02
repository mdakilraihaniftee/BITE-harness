# Task V semantic pilot research decision

Decision: **NONE. The pilot was not executed (authorization absent).** None of
`PROCEED_TO_LARGER_FIT_COLLECTION`, `REVISE_CONTRACT_AS_NEW_VERSION`,
`STOP_SEMANTIC_ACTION_FOR_TASK_V` or `INCONCLUSIVE` applies yet. An unexecuted
pilot is not an inconclusive result.

## Rule that will apply (fixed before data)

**Frozen Phase 4C-1E rule** (`semantic_comparison_design.classify_pilot`):

| Condition | Outcome |
| --- | --- |
| valid-response rate < 0.90 | `REVISE_CONTRACT_AS_NEW_VERSION` |
| D_semantic < 0 at both endpoints | `PROCEED_TO_LARGER_FIT_COLLECTION` |
| D_semantic ≥ 0 at both endpoints | `STOP_SEMANTIC_ACTION_FOR_TASK_V` |
| any other case, including a non-estimable endpoint | `INCONCLUSIVE` |

**Phase 4C-1F guard overlay** (`semantic_pilot_analysis.research_decision`). It
can only make the outcome more conservative. `PROCEED` becomes `INCONCLUSIVE`
in any of these cases:

- an endpoint is non-estimable;
- positives fall in fewer than 3 groups;
- removing one group erases the semantic Brier gain.

Neither outcome authorizes a further collection. `STOP` would not show that VLM
verification is ineffective in general. The pilot is designed to be
underpowered for significance, so an interval crossing zero does not by itself
justify a larger collection. Any recommendation must name the deficiency that
more data would fix.

## Research flexibility

If the semantic pilot ends in `STOP` or `INCONCLUSIVE`, the T1 presence task
(`TASK_V_AGENT_TASK_EXTENSION_PROPOSAL.md`) remains open. T1 asks whether the
queried object is present at all, and the semantic action addresses class
identity more naturally than bounding-box correctness at IoU 0.75. Note the
coverage requirement for exact replay corrected there.
