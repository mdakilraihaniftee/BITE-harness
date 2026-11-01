# Calibration annotation readiness

**Current status:** both candidate sources are `NOT_ACQUIRED`; Task V and Task D
are blocked. No annotation result is fabricated from publisher descriptions.

`annotation_readiness.inspect_detection_annotations` verifies COCO/LVIS list
structure, unique image/category/annotation IDs, required class mappings,
positive finite in-bounds boxes, positive image dimensions, annotation references,
crowd/ignore fields, every image file and content hash. Empty annotated images
are retained and reported.

Three claims remain separate:

1. **Structural completeness:** listed images, categories and boxes are internally
   valid and present.
2. **Class-conditional exhaustiveness:** the source declares and review confirms
   that relevant instances of each scheduled class should be labeled. Unknown
   declarations stay unknown.
3. **Visual completeness:** an independent image/box review finds no material
   omissions. This cannot be inferred from valid JSON.

Task V requires structural validity plus verified class-conditional
exhaustiveness for the scheduled class; otherwise an apparently incorrect
proposal could be an omitted object. Task D additionally requires visual
completeness/class-absence support because discovery negatives assert no eligible
unrepresented object exists.

Manual QA samples are chosen by the lowest SHA-256 of seed `417` and original
source-group/image identity. Detection count, score, correctness and favorable
examples are not selection inputs. Each review records missing boxes, class
coverage, box quality, ignore/crowd handling, scene/augmentation lineage and
whether empty images are genuine negatives.

Machine status: [annotation_readiness.json](../../outputs/bite/phase04b2b1/validation/annotation_readiness.json).
