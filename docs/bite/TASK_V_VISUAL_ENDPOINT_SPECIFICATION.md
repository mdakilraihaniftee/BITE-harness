# Task V visual endpoint specification

Version: **`bite.visual_plausibility.v1`**.

Visual plausibility asks whether the proposed region visibly corresponds to the
queried object: `supported`, `unsupported`, `ambiguous`, or
`insufficient_evidence`. Visual localization separately asks whether the region
qualitatively localizes that visually identified object: `adequate`,
`inadequate`, `ambiguous`, or `insufficient_evidence`.

The research binary projection is defined only when evidence is decisive:

- `H_visual=1`: plausibility supported, localization adequate, and all class,
  localization, and evidence ambiguity controls are `no`.
- `H_visual=0`: plausibility unsupported and all ambiguity controls are `no`.
- otherwise: unknown/abstained.

This endpoint is separate from `H_annotation_0.50` and `H_annotation_0.75`.
Subjective localization is never converted automatically to either IoU label.

An optional human reference box records image dimensions, finite in-frame pixel
xyxy, class, identity note, occlusion/truncation, reviewer, and timestamp.
Independent boxes can support research-only IoU and disagreement analyses, but
a single box is not authoritative GT. Threshold-specific corrected visual
labels remain unknown unless an independently approved adjudication procedure
establishes them. Original COCO files remain unchanged.

