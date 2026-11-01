# Phase 04B-2A data-source readiness

Audit date: **2026-10-29**. Status: **DATA_SOURCE_PENDING**. No dataset archive
was downloaded, extracted, or accepted under new terms. The only network
retrieval was public repository/API metadata and HTTP headers.

## ODinW-13 official distribution

The official [GLIP repository](https://github.com/microsoft/GLIP) says that
Roboflow hosts the original datasets, that GLIP also hosts archives, and that all
ODinW datasets use COCO detection format. At GLIP commit
`9dda9558c1ef59bb6cdc8e896e2bcab775a68ff0`, the actual script is
`odinw/download.py` (the README still names `download_datasets.py`). It defaults
to every listed ODinW-35 archive, shells out to `wget`, `unzip`, and `rm`, performs
no checksum validation, and constructs a Hugging Face `/tree/main/` URL rather
than the working `/resolve/main/` download URL. It must not be run as-is.

All 13 checked `configs/odinw_13/*.yaml` files declare a `train` mapping and a
COCO annotation path. The GLIPModel host exposes the following immutable LFS
objects at host commit `66ee3ae9a3b8cee0cf78f10ef5fc9a3725db02a1`.
This proves archive availability and expected bytes, not annotation
exhaustiveness, identity disjointness, or permission to use every image.

| OpenVLHarness domain | Declared train classes | Compressed bytes | Local export license claim | Readiness |
| --- | --- | ---: | --- | --- |
| AerialMaritimeDrone_large | boat, car, dock, jetski, lift | 47,681,829 | Public Domain | metadata verified; terms/contents pending |
| Aquarium_Aquarium_Combined.v2-raw-1024.coco | 7 aquatic classes | 70,037,905 | CC BY 4.0 | metadata verified; terms/contents pending |
| CottontailRabbits | Cottontail-Rabbit | 153,305,581 | Public Domain | metadata verified; terms/contents pending |
| EgoHands_generic | hand | 720,990,333 | CC BY 4.0 | metadata verified; terms/contents pending |
| NorthAmericaMushrooms_North_American_Mushrooms.v1-416x416.coco | CoW, chanterelle | 9,804,594 | Public Domain | metadata verified; terms/contents pending |
| Packages_Raw | package | 10,768,880 | Public Domain | metadata verified; terms/contents pending |
| PascalVOC | 20 VOC classes | 740,774,846 | CC BY 4.0 | metadata verified; known val/test alias |
| Raccoon_Raccoon.v2-raw.coco | raccoon | 27,092,904 | MIT | metadata verified; image terms pending |
| ShellfishOpenImages_raw | Crab, Lobster, Shrimp | 153,436,493 | CC BY 4.0 | metadata verified; OpenImages provenance review pending |
| VehiclesOpenImages_416x416 | 5 vehicle classes | 87,006,326 | CC BY 4.0 | metadata verified; OpenImages provenance review pending |
| pistols_export | pistol | 121,434,350 | Public Domain | metadata verified; terms/contents pending |
| pothole | pothole | 96,656,058 | ODbL v1.0 | metadata verified; database/image terms pending |
| thermalDogsAndPeople | dog, person | 10,072,076 | Unknown | blocked on license identification |

Total expected compressed transfer is **2,249,062,175 bytes (2.249 GB)**.
Every exact archive URL, size, and LFS SHA-256 is preserved in
`dataset_source_registry_v1.json`. The host does not require credentials. A safe
working reservation is at least twice the compressed total until extraction size
is measured. The 756 GB free-space snapshot is sufficient, but space is not
authorization.

The local Phase 4A inventory remains unchanged: only ODinW val/test annotations
and images are present. There is no local genuine train annotation. PascalVOC val
and test point to the same annotation and share 3,422 exact image hashes. The
previous `PascalVOC_val_262` image and its SHA-256 are permanently declared as
development-debug exclusions.

## Alternative sources

| Source | Official inputs and compressed size | Labels / suitability | Terms and domain shift | Status |
| --- | --- | --- | --- | --- |
| COCO 2017 train | `train2017.zip` 19,336,861,798 bytes; `annotations_trainval2017.zip` 252,907,541 bytes | 80-class COCO boxes; suitable for Task V and Task D within declared categories | Annotations/website CC BY 4.0; images retain Flickr terms. Natural-image distribution differs from many ODinW domains. | metadata verified; not local or approved |
| LVIS v1 train | `lvis_v1_train.json.zip` 350,264,821 bytes plus the same 19,336,861,798-byte COCO image archive | 1,203-category boxes/masks. Suitable for Task V. Task D negatives require LVIS per-image positive/negative/not-exhaustive metadata. | Uses COCO images and their terms; large-vocabulary/federated annotation differs from ODinW. | metadata verified; not local or approved |

COCO terms explicitly state that its annotations are CC BY 4.0 while the
Consortium does not own image copyrights. LVIS v1 documents about 100k training
images and uses COCO imagery. Dataset-name difference is never used as proof of
scene disjointness: after acquisition, exact hashes and declared source/scene/
parent identities must be compared with all ODinW held-out images.

## Approval gate and exact next action

No source is `approved_for_calibration`. Approval requires all of:

1. user review of the per-domain/source terms and intended internal research use;
2. download authorization for exact registry objects and destination;
3. archive checksum verification before extraction;
4. COCO/LVIS structure, image existence, box, class-map, and completeness review;
5. exact image and declared scene/parent comparison against held-out data;
6. grouped partition freeze with an immutable manifest checksum.

The recommended smallest acquisition is a reviewed subset of ODinW-13 domains,
not all domains automatically. `thermalDogsAndPeople` should remain excluded
until its source terms are identified. The metadata-only dry run is:

```bash
.venv/bin/python scripts/bite/prepare_calibration_source.py \
  --source-id odinw13:Packages_Raw \
  --destination data/calibration_sources --dry-run
```

This prints the exact URL, bytes, hash and destination and cannot download data.
