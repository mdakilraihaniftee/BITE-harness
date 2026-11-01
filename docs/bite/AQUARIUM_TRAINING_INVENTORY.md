# Aquarium training inventory

Source: `odinw13:Aquarium_Aquarium_Combined.v2-raw-1024.coco`. The official
archive was acquired under approval `aquarium-research-2026-10-30` for internal,
non-redistributed academic calibration research. The preserved archive is
70,037,905 bytes with SHA-256
`4affbfd66ef640b6154c694da3f2e730a97fe0fb0f8a22aa7ec8d32c2f04a536`.
The extracted release identifies Roboflow as the source and CC BY 4.0 as the
license; attribution, license reference and modification notices must accompany
internal derived documentation and any later permitted outputs.

The archive contains 638 images and 4,817 annotations across the original train,
valid and test directories. The calibration source is the actual `train` split,
not the publisher's total-image count.

| Split | Images | Annotations | Empty images | Min/max boxes | Crowd | Ignore |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| train | 448 | 3,324 | 1 | 0 / 56 | 0 | 0 |
| valid | 127 | 909 | 0 | 1 / 44 | 0 | 0 |
| test | 63 | 584 | 0 | 1 / 45 | 0 | 0 |

All 638 referenced JPEGs exist, decode as RGB, and match their declared
dimensions. No duplicate image/category/annotation identifier, missing category,
invalid reference, nonpositive/out-of-bounds box, malformed flag, or dimension
mismatch was found. The supported pixel sizes are 768×1024, 1024×768, 576×1024
and 1024×576. The background-inclusive JSON adds category `creatures` with ID 0;
the official detection annotations used here contain the seven foreground
categories only.

## Training class inventory

| Class | Annotations | Images containing class |
| --- | ---: | ---: |
| fish | 1,961 | 240 |
| jellyfish | 385 | 32 |
| penguin | 330 | 47 |
| puffin | 175 | 45 |
| shark | 259 | 134 |
| starfish | 78 | 37 |
| stingray | 136 | 91 |

Machine inventory:
[`aquarium_inventory.json`](../../outputs/bite/phase04b2b1a/inventory/aquarium_inventory.json).
The verified source entries are preserved separately so identity grouping does
not depend on reconstructed TSV rows.
