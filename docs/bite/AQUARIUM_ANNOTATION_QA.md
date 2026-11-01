# Aquarium annotation QA

Structural completeness is verified: all listed images, identifiers, categories,
dimensions, boxes and flags passed the Phase 4B-2B-1 annotation audit.

The manual QA sample is deterministic and independent of SAM 3 output. Seed 417
selects prespecified dense, sparse, annotation-empty, tiny-object and per-class
strata using source-group/image hashes. Eleven images were inspected with COCO
boxes overlaid. The sample covers all seven classes.

No obvious material omission was observed:

- the 56-jellyfish dense frame covered the visible group;
- the annotation-empty frame showed no evident target-class animal;
- the sparse starfish, two-penguin, puffin, starfish/fish and three-stingray
  examples had corresponding boxes;
- dense fish/shark scenes included many small and partially occluded boxes.

This is limited pilot evidence, not proof of global visual exhaustiveness.
Reflections, extreme scale, dark water, edge truncation and occlusion make some
animals ambiguous. Candidate-verification labels must retain `unknown` for
plausible omitted, severely occluded, crowd-like or visually ambiguous proposals.
No annotations carry explicit `iscrowd` or `ignore`, so those cases cannot be
recovered from flags.

The publisher describes the seven target classes as labeled, and the deterministic
sample found no material omission. Together these support an initial Task V pilot
at IoU 0.50 and 0.75 on the clean source groups. They do not establish that every
class is absent wherever no box appears. Task D discovery negatives therefore
remain blocked.

Artifacts:

- [QA selection](../../outputs/bite/phase04b2b1a/qa/manual_qa_selection.json)
- [Manual review record](../../outputs/bite/phase04b2b1a/qa/manual_review.json)
- [Annotation readiness](../../outputs/bite/phase04b2b1a/validation/annotation_readiness.json)
- diagnostic overlays under `outputs/bite/phase04b2b1a/qa/overlays/`
