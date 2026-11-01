# Task V negative-label audit

**Status: PASS.** Audit date: 2026-10-30. This is an offline audit of the
Phase 4B-2B-2 development cohort; it does not change any historical label.

All 38 candidate-present states were reconstructed from source image bytes,
full-precision root-frame boxes, detector scores, candidate ranks, transforms,
class maps, and COCO annotations. Image hashes, annotation image IDs, dimensions,
class IDs, root/local transforms, normalized 0–1000 boxes, clipping, and best
eligible IoU all reproduced exactly. An independent xyxy IoU implementation
agreed with the existing matcher for every candidate. No systematic coordinate,
width/height, category, or matching defect was found.

At IoU 0.50, 4 candidates are positive and 34 are negative. Primary diagnostic
precedence is: implementation defect, no annotated same-class instance,
same-class insufficient localization, different-class overlap, then wrong
location. The 34 negatives split as follows:

| Primary explanation | Count |
| --- | ---: |
| `no_annotated_instance` | 32 |
| `insufficient_localization` | 2 |
| `wrong_instance_or_class_confusion` | 0 |
| `wrong_location` | 0 |
| geometry/matching defect | 0 |

Secondary facts are retained and can include overlap with another annotated
class. COCO emptiness is described only as `no_annotated_instance`; it is not a
claim that the object is visually absent. Thirty-three cases remain in a
manual-review queue. No automated process fabricated a visual judgment or
promoted an uncertain negative to positive.

Internal overlays cover all 38 candidates and show the query, proposal, score,
same-class GT, nearby GT, best IoU, and audit label. They remain under
`outputs/bite/phase04b2b3/audit_existing/overlays/` and are not redistributed.
The machine table is `audit_existing/negative_diagnostics.jsonl`; the summary
and review queue are adjacent.

The audit cleared the mandatory expansion gate because every label was
reconstructed, independent geometry passed, and no suspected implementation
defect remained.

Source attribution: Aquarium Combined (Roboflow), obtained through the
GLIP-curated archive, licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The diagnostic overlays are internal derived research artifacts and contain
source imagery; no redistribution is authorized by this report.
