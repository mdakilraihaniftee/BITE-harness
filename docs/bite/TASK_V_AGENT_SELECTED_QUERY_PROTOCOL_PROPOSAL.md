# Task V agent-selected query protocol proposal

Status: **FUTURE ONLY — NOT EXECUTED**.

The controlled regime queries all seven source-vocabulary classes on one frozen
representative image per source group. A separate natural-query regime would freeze
a VLM agent, prompt, decoding, task population and query parser; let the agent see
the original task; and persist the exact context and generated grounding query
before any GT access.

Eligible class vocabulary and query-to-annotation mapping must be prespecified.
Unmappable, compound, or ambiguous queries remain in coverage reports rather than
being silently dropped. Mapping adjudication cannot see correctness outcomes. SAM 3
outputs use the declared COCO annotation policy, source-group-disjoint development
and evaluation, and attested VLM/SAM 3 identities.

The regimes are distinct populations: equal prevalence or a shared calibration
curve is not assumed. No Qwen/VLM call was made and the original agent loop was not
changed. Machine proposal:
`outputs/bite/phase04c1c_revised/conditional_evidence_design/agent_selected_query_proposal.json`.

