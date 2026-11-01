# Aquarium held-out leakage audit

All 448 acquired training images were compared with all 9,513 installed ODinW
validation/test identities. Identity evidence included file SHA-256, stable source
name, derived original parent, Aquarium video-scene lineage and dHash-64 candidates.

| Finding | Count |
| --- | ---: |
| Exact image-SHA train/held-out overlaps | 0 |
| Exact source-image-ID overlaps | 0 |
| Exact source-parent overlaps | 0 |
| Shared Aquarium video-scene identities | 15 |
| Training images in shared scenes | 42 |
| dHash candidates at distance ≤4 | 2 |
| Confirmed additional near-duplicate training images | 1 |
| Cleared dHash collisions | 1 |
| Unresolved candidates | 0 |
| Unique quarantined training images | 43 |
| Quarantined source/scene groups | 16 |
| Clean training images | 405 |

The confirmed dHash pair (`IMG_8527` train versus `IMG_8528` validation) depicts
the same aquarium tank with the same rocks, logs and substrate. The other pair—a
dark shark frame versus a road pothole—was visually cleared as a hash collision.
One of the cleared pair's Aquarium images remains excluded independently because
its video scene crosses the source train/validation boundary.

All 42 images from 15 shared video-scene groups plus the confirmed adjacent tank
image are quarantined. No unresolved near-duplicate remains in the frozen pool.
The existing PascalVOC finding—3,422 exact shared val/test images—is preserved,
as is the development exclusion for `PascalVOC_val_262` with SHA-256
`a18039d3edc2c8ae46fb2b8347318c79f91f5643c3811181d366ed4a4403e1b5`.

Machine evidence:

- [heldout_leakage_audit.json](../../outputs/bite/phase04b2b1a/leakage/heldout_leakage_audit.json)
- [quarantine.json](../../outputs/bite/phase04b2b1a/leakage/quarantine.json)
- [final_evaluation_reference.json](../../outputs/bite/phase04b2b1a/manifests/final_evaluation_reference.json)
