# Phase 04B-2B-1A — approved Aquarium acquisition and validation

**Status: READY_FOR_TASK_V_PILOT.** Task D is blocked. Multi-image collection,
probability fitting, planning and identifiability analysis were not started.

Researcher approval `aquarium-research-2026-10-30`, supplied by stable identifier
`ai5377`, validates against `bite.source_acquisition_approval.v1`. It authorizes
only the official Aquarium archive for internal non-redistributed research. The
approval canonical SHA-256 is
`bc0998105b520d6eaca95f2ac5284bdc19b790af8470ac031f5a27ee41dc7cd9`.

The existing acquisition CLI downloaded exactly 70,037,905 bytes from the
registered Hugging Face GLIP URL. SHA-256 matched
`4affbfd66ef640b6154c694da3f2e730a97fe0fb0f8a22aa7ec8d32c2f04a536`.
Safe extraction accepted 681 members totaling 74,391,505 expanded bytes. The
archive remains preserved under the isolated calibration source root; benchmark
images, annotations and TSVs were not overwritten.

Actual source inventory:

- train: 448 images, 3,324 annotations, seven classes, one annotation-empty image;
- valid: 127 images and 909 annotations;
- test: 63 images and 584 annotations;
- no missing image, malformed ID, invalid box, dimension mismatch, crowd flag or
  ignored annotation.

Leakage analysis found no byte-identical train/held-out image but found 15 shared
Aquarium video scenes containing 42 training frames. One additional adjacent-tank
near duplicate was confirmed; one cross-domain dHash collision was cleared.
Forty-three images were quarantined, leaving 405 images in 399 clean groups.

The frozen Task V manifest assigns 277/78/50 images and 277/72/50 groups to
fit/validation/internal-test. All partitions cover every class. Task V is ready
only as a constrained pilot with ambiguous proposals retained as unknown. Task D
remains blocked because exhaustive negative-region labels are not established.

The existing Phase 4B-1 collector was exercised with one real frozen image and
CPU-only mocked tool responses. Snapshot capture, isolated branches, budget
accounting, raw-first persistence and offline GT labeling all validated. No GPU
service or model endpoint was called.

Primary machine outputs are under
[`outputs/bite/phase04b2b1a`](../../outputs/bite/phase04b2b1a/). This phase stops
before dataset-wide collection.
