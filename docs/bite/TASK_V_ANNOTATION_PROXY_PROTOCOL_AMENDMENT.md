# Task V annotation-proxy protocol amendment

Protocol: `bite.task_v_annotation_proxy_protocol.v2`. Effective date: **2026-11-01**.

## Amendment and chronology

Human review was introduced as a label-quality safeguard because official COCO
annotations may omit visible objects. The project subsequently narrowed its
immediate target to reproducible benchmark-defined candidate correctness. The
researcher therefore made additional human review optional for annotation-proxy
experiments. Existing reviews and the earlier mandatory-gate reports remain
preserved. The numerical endpoint did not change; its interpretation did.

For a valid candidate-present state with image `x`, query `q`, original selected
box `b`, and official eligible same-class boxes `G_q(x)`, define

`H_tau = 1[max_{g in G_q(x)} IoU(b,g) >= tau]`.

`H_annotation_0.50` is primary and `H_annotation_0.75` is its stricter companion.
An empty `G_q(x)` is annotation-negative under the closed-world benchmark
convention. This is not proof that the queried object is visually absent.
`no_candidate` is a separate status and receives no candidate-correctness label.
The label remains attached to the original candidate after any later action.

The official source is Aquarium Combined (Roboflow), obtained through the
GLIP-curated archive under CC BY 4.0. The frozen annotation SHA-256 is
`5ca593fb53fc482790b51677fdd81b0e497d44e8bcdce00f8ec4275937ed097c`.
The primary fit cohort contains 30 source groups and 203 candidate-present states:
31/172 positive/negative at .50 and 23/180 at .75. Source groups are the
independence unit; they must not cross fitting and evaluation boundaries.

## Permitted interpretation

The protocol permits official-label calibration, candidate-level Brier/log loss,
conditional evidence analysis tied to the original candidate, and budget-aware
risk under the declared dataset/query population. It does not establish exhaustive
visual truth, zero omissions, human-verified probabilities, arbitrary-query
generalization, end-to-end agent success, or deployment calibration.

Human review is optional for COCO prior fitting, COCO validation, and a properly
designed COCO conditional-Zoom experiment. Separate independent visual evidence is
required for visual-truth calibration, omission-prevalence estimation, and claims
of visually verified correctness.

Held-out validation must use frozen models and queries, source-group-disjoint
calibration-validation data, paired group-aware comparisons, no validation tuning,
and a locked internal-test partition. The authoritative machine protocol is
`outputs/bite/phase04c1c_revised/protocol/task_v_annotation_proxy_protocol_v2.json`.

