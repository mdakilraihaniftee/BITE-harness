# Calibration source and leakage audit

Audit date: **2026-10-29**. Scope: accessible project `data/`, its local GLIP
configuration/annotation tree, prepared TSVs, image bytes and preparation scripts.
No dataset constructor, download, model request or new data collection was used.
Machine evidence is under
[`outputs/bite/phase04a/audit/`](../../outputs/bite/phase04a/audit/), with compact
[audit_summary.json](../../outputs/bite/phase04a/audit_summary.json).

## Available labels and images

| Source | Verified local state | Detection-calibration readiness |
| --- | --- | --- |
| `ODinW13_bbox_val_qwen3.tsv` | 4,938 rows; image/box/class metadata; TSV SHA-256 `6d82b735b3fe0032aaa661f5d7451efaa646e44e151a3d98d2ebea381ae67509` | Local COCO GT available; already-used validation/development data |
| ODinW GLIP mappings | 13 domains × val/test = 26 mappings, 25 distinct annotation files; 4,938 val and 4,575 test image entries | Labels exist for both split names, with PascalVOC alias below |
| `data/images/ODinW` | 6,091 distinct file paths covering all mapped annotation images | Exact byte identities audited; not an approved calibration-fit source |
| `FSC147_val.tsv` | 1,286 rows with **counts**, not instance boxes; only `index,image_path,question,answer` | Cannot substitute for FSCD detection GT |
| `data/images/FSC147` | 2,476 files: 1,286 referenced by count-val TSV, 1,190 not assigned by any installed TSV | Extra filenames alone do not verify an official labeled test partition |
| `FSCD_147_bbox_{val,test}` | Prepared TSVs absent | Box annotations not installed; counting labels/exemplars are insufficient |
| FSCD-LVIS bbox train/val/test and unseen variants | Prepared TSVs absent; no verified local LVIS detection source | Not ready |
| Genuine training annotations | No train REGISTER entries in the 13 local mappings; no train-named annotation JSON anywhere under project `data/` | Acquisition/preparation required |

Local `DATASETS.TRAIN: ("train",)` text does not establish a real train mapping.
The audit found **zero** such annotation files; it did not search unrelated users'
directories or misclassify previously generated output GT as training data.

Source preparation code is in
[`evaluation_kit/dataset/scripts/prepare_odinw.py`](../../evaluation_kit/dataset/scripts/prepare_odinw.py),
`prepare_odinw_qwen3.py`, `prepare_fscd147_box.py` and `prepare_fscdlvis_box.py`.
ODinW preparation accepts external COCO training annotations. FSCD-147 bbox
preparation explicitly skips train: its training supervision is points plus
exemplars, rather than exhaustive detection boxes. FSCD-LVIS train registration
does not establish that those files or full labels are present locally.
The original [GLIP instructions](https://github.com/microsoft/GLIP#the-object-detection-in-the-wild-benchmark)
identify Roboflow/original ODinW data and COCO split preparation; they do not
make the absent local training files available automatically.

## Exact overlap findings

The audit hashed **11,989 source entries**, representing **8,567 distinct image
paths** and **8,301 unique content groups**. Every inventoried image existed and
was hashed; image bytes were not copied into audit JSON.

**PascalVOC val and test both point to:**

```text
data/GLIP/DATASET/odinw/PascalVOC/valid/annotations_without_background.json
```

They share **3,422 exact image hashes**, paths and original source filenames,
plus the same annotation path/hash. No other cross-partition exact-content
overlap was found among these inspected source entries. There are additionally
**257 duplicated-content hash groups confined within partitions**, accounting for
266 duplicate file paths beyond the unique-content count. These groups must also
stay together in any future partitioning.

The full report lists 13,690 **identity-key findings**, not 13,690 different
images: the same PascalVOC alias is detected independently by hash, path, source
ID and parent identity (3,422 each), plus one shared annotation path and one hash.
Do not count these repeated evidence channels as independent leakage events.

`split_integrity.audit_partitions` also accepts explicit scene and parent IDs to
group known crops/augmentations, detects identical image bytes under different
names/directories, and detects copied annotation files by hash. Annotation-file
sharing is reported separately; it does not assert all images in one COCO file
depict the same object or scene. Numeric annotation image IDs are namespaced and
are not automatically considered global source identities.

### Limits of the audit

Exact hashing does not detect recompression, resized copies, different frames of
one video, crops without parent metadata, or semantically near-duplicate photos.
No authoritative scene/video/augmentation-parent metadata was present in this
inventory. An optional later audit should combine declared parent/scene metadata,
perceptual hashes and image-similarity retrieval, then manually adjudicate likely
duplicates before freezing groups. Similarity thresholds and false positives need
their own validation; none was fitted or applied here.

## License evidence and planned use

The local annotation exports declare the following **metadata claims**, not an
independent verification of every underlying image owner's rights:

| Domain | Local annotation license name |
| --- | --- |
| AerialMaritimeDrone_large | Public Domain |
| Aquarium | CC BY 4.0 |
| CottontailRabbits | Public Domain |
| EgoHands_generic | CC BY 4.0 |
| NorthAmericaMushrooms | Public Domain |
| Packages_Raw | Public Domain |
| PascalVOC | CC BY 4.0 |
| Raccoon | MIT |
| ShellfishOpenImages | CC BY 4.0 |
| VehiclesOpenImages | CC BY 4.0 |
| pistols_export | Public Domain |
| pothole | ODbL v1.0 |
| thermalDogsAndPeople | Unknown |

Original license URLs, export source URLs and metadata are preserved per mapping
in `dataset_inventory.json`. A code repository's MIT/BSD license is not blanket
permission for every distributed photograph or annotation. CC BY 4.0 permits
reuse subject to its attribution/notice terms, but does not warrant all other
rights; see the [license publisher's terms](https://creativecommons.org/licenses/by/4.0/).
The Unknown thermal license and the different ODbL/database terms require
source-specific resolution before treating the full collection as cleared.

The [Counting-DETR dataset instructions](https://github.com/VinAIResearch/Counting-DETR#training-and-testing)
explicitly limit FSCD dataset use to research/education, prohibit redistribution
of the original or modified data, and require citation for published results.
Those are dataset conditions, distinct from the repository's BSD code license.
The [original FSC147 project](https://github.com/cvlab-stonybrook/LearningToCountEverything#dataset-download)
provides image/density-map sources; its code license alone does not establish
permission to redistribute every image. No FSCD data was downloaded in this task.

The intended internal research calibration is consistent with FSCD's stated
research-use category if acquired under its conditions, but dataset access,
annotation completeness, source identity and dissemination permissions still
need confirmation. **Complete dataset-license clearance is not established.**
This task exports local debugging records/references, not a redistributable image
dataset. Source pages were checked on the audit date; no broad legal clearance
is claimed from export metadata alone.

## Partition decision

No calibration-fit, calibration-validation or blind final-evaluation partition
was silently created. `provisional_groups.json` assigns **all 8,301 groups null**
with `unassigned_provisional` status. It is an identity inventory, not permission
to fit on validation data. Non-debug record export requires an explicitly frozen
manifest with verified hashes/groups and no cross-partition image/scene/parent
overlap. The smoke sample remains `development_debug`.

Preferred order:

1. **Option A:** obtain genuine official ODinW training sources, verify each
   domain's terms, prepare exhaustive labels, and compare content/scene groups
   against all held-out data, including val/test aliases. This is recommended.
2. **Option B:** use a separately licensed, exhaustively labeled development
   dataset, audit overlap with ODinW, and report domain shift explicitly. This is
   a legitimate alternative; no such source is approved or installed here.
3. **Option C:** deliberately reserve grouped validation images for development
   fit/validation/internal-test use. This would surrender the corresponding full
   official validation set as an untouched benchmark. It requires a documented
   decision, not an automatic random row split.

**A clean final holdout is not currently established.** Some validation images
and previous smoke outputs have already been inspected. Exact disjointness is
necessary but not sufficient for a blind scientific holdout, and model pretraining
exposure is not audited here. Missing clean training labels/licensing is a
**data-acquisition blocker for Phase 4B**, not a failure of the offline engineering
and development-only labeling pipeline.
