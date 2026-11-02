# SAM 3 loaded-checkpoint provenance

Classification: **CACHE_CONFIG_VERIFIED_ONLY**.

No SAM 3 worker process was active during the read-only audit. Current configuration
names `facebook/sam3`; the upstream loader calls `hf_hub_download` without an
immutable revision argument. The installed SAM 3 source is commit
`2345a4ad109ac29c569da749c91d84f10dc08c40` with Torch `2.10.0+cu128` and
Torchvision `0.25.0+cu128`.

The local cache `refs/main` resolves to
`3c879f39826c281e95690f02c7821c4de09afae7`. Cached files include:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `sam3.pt` | 3,450,062,241 | `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e` |
| `model.safetensors` | 3,439,938,512 | `6d06f0a5f84e435071fe6603e61d0b4cc7b40e0d39d487cfd4d67d8cc11cc14a` |
| `config.json` | 25,843 | `4616385e4b21f2e5e22c875b65679185cbccfa95de42542b9166f7dc3d57160f` |
| `processor_config.json` | 1,712 | `6420cf2671fa9309ea95bc0144a8b9861666d1c5f43c8db09e410dacda974fce` |

Historical logs show a healthy worker and 58 successful segmentation requests, but
they contain no resolved revision, load-time weight hash, preprocessing identity,
or link from process to cache snapshot. The current source reconstructs an upstream
processor with presence weighting disabled, IoM threshold 0.3, and left-to-right
ordering; it does not prove what the historical worker loaded.

Consequently, historical fit observations and any future attested worker cannot be
declared checkpoint-equivalent. Before blind validation, either explicitly approve
that transport limitation or authorize a matched-service fit-only consistency or
recollection experiment. No such experiment, worker restart, model load, network
access, or GPU inference occurred here.

Future workers should capture at model-load time the immutable revision; resolved
weight paths, sizes and SHA-256 hashes; processor/local overrides; worker source and
config digests; library/CUDA/Python versions; session ID; and initialization time.
New attestation cannot retroactively prove an older load. The machine audit is
`outputs/bite/phase04c1c_revised/worker_provenance/sam3_provenance.json`.

