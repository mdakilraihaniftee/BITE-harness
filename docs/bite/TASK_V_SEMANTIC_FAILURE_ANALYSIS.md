# Task V semantic failure and error-pattern analysis

Status: **NOT PERFORMED. No semantic observations exist.**

## Planned descriptive analysis (fixed before data)

**GT-free, before labels** (`failure_analysis/gt_free_descriptive.json`):

- response status: valid, empty, malformed JSON, schema violation, timeout,
  execution failure;
- compatibility with the query: match, taxonomic overlap, dataset-category
  conflict, other object, background, unclear, unavailable;
- `object_visible`, `region_localization`, `multiple_objects` and
  `evidence_status`.

The raw `finish_reason` and token usage are also available in each
`raw_response.json`, for example to find responses truncated at the 256-token
cap.

**After labels** (`failure_analysis/iou_0_5.json` and `iou_0_75.json`): the same
counts, cross-tabulated by stratum and by query class.

| Stratum | Definition |
| --- | --- |
| `annotation_positive` | original candidate matches an annotation at IoU ≥ τ |
| `negative_queried_class_annotated_or_other` | negative, and the image has an annotated instance of the queried class elsewhere (or another diagnostic) |
| `negative_no_queried_class_annotation` | negative, and no annotated instance of the queried class exists |

Reporting rules:

- **Annotation absence is not visual absence.** A "match" in the third stratum
  may be a missed annotation, not a VLM error.
- **Semantic agreement is not localization.** Report semantic matches
  cross-tabulated with `region_localization` and label. The aim is to see
  whether Qwen identifies the class while the SAM 3 box still fails IoU 0.75.
- If any Brier gain comes mainly from background or unrelated-object responses
  in class-absent negatives, state that explicitly.
