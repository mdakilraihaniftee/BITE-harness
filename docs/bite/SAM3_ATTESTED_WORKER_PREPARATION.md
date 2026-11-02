# SAM 3 attested-worker preparation

Status: **PREPARED / NOT STARTED / HISTORICAL COMPARABILITY UNVERIFIED**.

An isolated opt-in load plan now pins `facebook/sam3` revision
`3c879f39826c281e95690f02c7821c4de09afae7`. It verifies and passes the actual
expected `sam3.pt` artifact to `build_sam3_image_model(checkpoint_path=...,
load_from_HF=False)`. It does not substitute `model.safetensors`, access the
network, import/load SAM 3, launch a process or use a GPU.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `sam3.pt` | 3,450,062,241 | `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e` |
| `config.json` | 25,843 | `4616385e4b21f2e5e22c875b65679185cbccfa95de42542b9166f7dc3d57160f` |
| `processor_config.json` | 1,712 | `6420cf2671fa9309ea95bc0144a8b9861666d1c5f43c8db09e410dacda974fce` |

The plan records worker source/config digests, SAM 3 source commit
`2345a4ad109ac29c569da749c91d84f10dc08c40`, Torch `2.10.0+cu128`,
Torchvision `0.25.0+cu128`, Hugging Face Hub `2.3.0`, and the intended processor
overrides. A future successful initialization must emit a UUID session,
process/start/load times, resolved path and weight hash, processor configuration,
worker digests, actual library versions and actual preprocessing. Mock tests
validate this event contract.

The production startup path was not modified because importing its server loads
the model immediately. Future instrumentation therefore requires a separately
authorized isolated entrypoint or production patch review. A new attestation can
identify the new process; it cannot prove what the historical worker loaded.
Historical status remains `CACHE_CONFIG_VERIFIED_ONLY` and cross-run
comparability remains unverified.

Machine preparation:
`outputs/bite/phase04c1d/worker_attestation/preparation.json`.
