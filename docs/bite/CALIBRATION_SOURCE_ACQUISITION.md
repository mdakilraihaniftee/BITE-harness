# Calibration source acquisition and approval request

**Status: AWAITING RESEARCHER APPROVAL.** No approval record was found and no
network transfer or destination directory was created.

## Requested sources

| Source | Exact official archive | Bytes | LFS SHA-256 | Terms evidence |
| --- | --- | ---: | --- | --- |
| `odinw13:AerialMaritimeDrone_large` | `https://huggingface.co/GLIPModel/GLIP/resolve/main/odinw_35/AerialMaritimeDrone.zip` | 47,681,829 | `4bf97c0e0f0264bc2c778114d8da70114ab01be3ccb71033e8cea30201f874bd` | Installed export says Public Domain/CC0; current publisher page says MIT. Researcher must resolve/accept this discrepancy. |
| `odinw13:Aquarium_Aquarium_Combined.v2-raw-1024.coco` | `https://huggingface.co/GLIPModel/GLIP/resolve/main/odinw_35/Aquarium.zip` | 70,037,905 | `4affbfd66ef640b6154c694da3f2e730a97fe0fb0f8a22aa7ec8d32c2f04a536` | Publisher and export say CC BY 4.0: attribution/license link and modification notice are required; other rights may remain. |

Publisher pages: [Aerial Maritime](https://universe.roboflow.com/jacob-solawetz/aerial-maritime),
[Aquarium Combined](https://universe.roboflow.com/brad-dwyer/aquarium-combined).
License references: [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/),
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Intended use is internal, non-redistributed academic calibration research. No
image/archive redistribution is planned. Destination is isolated from benchmark
data:

```text
<repository-root>/data/calibration_sources/odinw13/
```

## Required approval record

Review the generated
`outputs/bite/phase04b2b1/acquisition/approval_request.json`, then create its
`bite.source_acquisition_approval.v1` template as
`outputs/bite/phase04b2b1/acquisition/researcher_approval.json`. It must name a
researcher authority, exact source URL/bytes/hash, intended use, no-redistribution
decision, reviewed terms and destination. An assistant-generated recommendation
is rejected.

After approval, execute only the selected source command:

```bash
.venv/bin/python scripts/bite/acquire_calibration_sources.py \
  --source-id odinw13:AerialMaritimeDrone_large \
  --destination data/calibration_sources/odinw13 \
  --approval-record outputs/bite/phase04b2b1/acquisition/researcher_approval.json \
  --execute \
  --output outputs/bite/phase04b2b1/acquisition/AerialMaritimeDrone_large_acquisition.json
```

```bash
.venv/bin/python scripts/bite/acquire_calibration_sources.py \
  --source-id odinw13:Aquarium_Aquarium_Combined.v2-raw-1024.coco \
  --destination data/calibration_sources/odinw13 \
  --approval-record outputs/bite/phase04b2b1/acquisition/researcher_approval.json \
  --execute \
  --output outputs/bite/phase04b2b1/acquisition/Aquarium_Aquarium_Combined.v2-raw-1024.coco_acquisition.json
```

The utility has no mirror fallback. It streams into a temporary partial file,
rejects incomplete length or SHA mismatch, fsyncs and atomically installs the
verified archive, preserves it, then safely extracts to a separate directory.
Existing archives/destinations are errors unless explicit verified reuse is
requested. ZIP preflight rejects traversal, absolute/drive paths, backslashes,
symlinks, special/encrypted members, duplicate/case-conflicting paths, unexpected
extensions and configured member/count/expanded-size/compression limits.

Downloading does not grant calibration approval. Annotation, terms, held-out
identity and grouped split gates remain separate.
