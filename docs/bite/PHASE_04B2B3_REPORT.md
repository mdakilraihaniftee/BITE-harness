# Phase 4B-2B-3 report

**Status: SUCCESS.** Completed 2026-10-30. Phase 4C was not started.

The historical audit reconstructed 38/38 candidate labels and found no matcher
or coordinate defect. Its 34 IoU-0.50 negatives comprise 32 images with no
annotated queried-class instance and 2 insufficient-localization cases; 33 are
queued for visual review. Focused evidence was analyzed without retroactive
relabeling or probability fitting.

Hardcoded integrity claims were replaced by disk-derived content, parent,
provenance, cost, and stage-event validation. The historical 40-state run passes
all reconstructible checks but, correctly, cannot prove its raw-before-label
ordering after the fact. The expansion proves that ordering for all 210 states.

Protocol `bite.task_v_expansion.v1` froze 30 uniformly sampled, previously
unused `calibration_fit` groups from the verified 257-group frame, all seven
source classes per image, and five independently allocated repeat-control
groups. Protocol digest is
`6e090887606e23de1f3e69a89fe6c194ce93d22163e9dffd8d363e11125a6a1c`.

The 14-state real canary passed. Full collection completed 210/210 states with
203 candidates, 7 genuine empty results, 651/665 dispatches, zero failed
dispatches, 203 zoom-focused paths, and 35 exact repeats. Offline labels are
31/172/0 positive/negative/unknown at IoU 0.50 and 23/180/0 at IoU 0.75.
All labels independently reproduced; no systematic defect was found.

Resume was zero-dispatch and content-identical. Artifact-only audit succeeded
with deliberately dead service URLs. The configured checkpoint remains
`facebook/sam3`, but exact loaded revision is not worker-attested. Qwen, model
training, likelihood fitting, posteriors, planning, and certificates were not
used or implemented.

The evidence now supports engineering validation and restricted exploratory
model design, not a reliable general conditional kernel. Positive support is
class- and size-sparse, annotation-negative review is unfinished, and focused
outcomes do not cleanly separate hypothesis classes. The recommendation is to
complete targeted visual/annotation review and specify a group-aware restricted
model before authorizing any probability-fitting phase.

Key artifacts are under `outputs/bite/phase04b2b3/`: frozen protocol and
preflight, canary gate, resumable state tree, offline labels, negative overlays,
integrity reports, focused tables, and the design-aware support summary.

Final test counts and the implementation checksum manifest are recorded in
`outputs/bite/phase04b2b3/implementation_manifest.json`.

Source attribution: Aquarium Combined (Roboflow), obtained via the GLIP-curated
archive, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This phase
created internal derived diagnostics and records; it does not redistribute the
source images.
