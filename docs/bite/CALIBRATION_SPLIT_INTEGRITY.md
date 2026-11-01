# Calibration split integrity — Phase 4B-2B-1

No train images were acquired, so no 70/15/15 assignment was made. The current
manifests remain provisional and `FROZEN_READY=false`.

The exact audit reuses Phase 4A grouping by image SHA-256, stable path/identifier,
declared parent and scene. Acquired train entries will be compared with the full
installed ODinW validation/test inventory, including cross-domain comparisons.
Confirmed train/held-out overlap is quarantined and cannot enter any calibration
partition.

Optional dHash-64 supplies near-duplicate *candidates*. A distance threshold does
not prove identity: candidates are quarantined for manual review, then explicitly
confirmed or cleared. Recompression, resizing, crops, adjacent video frames and
augmentations remain review risks. Dataset names never establish disjointness.

The existing PascalVOC finding remains: validation/test are one population with
3,422 exact shared images. `PascalVOC_val_262` and SHA-256
`a18039d3edc2c8ae46fb2b8347318c79f91f5643c3811181d366ed4a4403e1b5`
remain development exclusions and cannot be called blind.

After source approval, annotation readiness and duplicate adjudication, groups
will be assigned deterministically 70/15/15 to calibration fit, calibration
validation and internal test. Every crop/branch inherits its original group.
Freeze requires no known held-out or quarantined overlap, stable per-domain/class
coverage and a cryptographic manifest checksum. Download success alone cannot
advance the status.

Machine status: [split_integrity.json](../../outputs/bite/phase04b2b1/validation/split_integrity.json).
