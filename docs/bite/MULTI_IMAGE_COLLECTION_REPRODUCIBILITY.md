# Multi-image collection reproducibility

## Frozen inputs

- Source: `odinw13:Aquarium_Aquarium_Combined.v2-raw-1024.coco`
- Partition manifest: `outputs/bite/phase04b2b1a/manifests/calibration_partition_manifest.json`
- Canonical manifest digest: `61df2e5f2a817b022f07358ec5b63438c8cfb56973009cf854c7b460c86aebd4`
- Selection seed: 417
- Groups / queries per group: 20 / 2
- Agent-system config used only for public capability construction:
  `configs/agent/qwen3_8b_paper.yaml`, SHA-256
  `19f737475b048a8a025002ba3642a70d6611b9c97c4b67e45d9630e0700a4431`
- Backend: `sam3_segment`; Zoom: `zoom_in_image_by_bbox`; orchestrator: none

## Commands

Run from the repository root with the existing environment and healthy router /
SAM3 services:

```bash
.venv/bin/python scripts/bite/collect_calibration_pilot.py --stage preflight
.venv/bin/python scripts/bite/collect_calibration_pilot.py --stage canary
.venv/bin/python scripts/bite/collect_calibration_pilot.py --stage pilot --resume
.venv/bin/python scripts/bite/collect_calibration_pilot.py --stage pilot --resume
.venv/bin/python scripts/bite/collect_calibration_pilot.py --stage audit
```

The second pilot command is an idempotency check: all 40 states must report
`resumed_complete`, `newly_completed: 0`, and the dispatch total must remain 154.
Do not delete a partial state and silently retry it. The ledger deliberately
reports partial work as requiring explicit new execution.

Tests:

```bash
.venv/bin/python -m pytest tests/bite tests/bite_calibration tests/bite_collection -q \
  --junitxml=outputs/bite/phase04b2b2/validation/targeted_pytest.xml
.venv/bin/python -m pytest tests -q \
  --junitxml=outputs/bite/phase04b2b2/validation/pytest.xml
```

## Artifact map

- `preflight/sample_selection_manifest.json`: frozen selected groups, images,
  queries, identities, and maximum cost.
- `preflight/preflight_report.json`: source, service, GPU, storage, and config gate.
- `canary/canary_gate.json`: two-group gate and measured canary audit.
- `pilot/initial_execution.json`: 36 new + 4 resumed-state continuation record.
- `pilot/execution.json`: zero-dispatch all-resume verification.
- `observations/aquarium_task_v_seed417_g20/`: per-state raw snapshots, branches,
  operational states, completion hashes, and post-raw labels.
- `offline_labels/`: consolidated original-candidate labels and branch records.
- `audits/pilot_audit.json`: scientific and resource summary.
- `validation/`: integrity report and JUnit results.

The checkpoint name is configured as `facebook/sam3`, but
`checkpoint_verified_by_worker=false` because the worker health/result contract
does not expose an exact revision. Transport retries are configured at eight;
physical attempt counts remain unavailable and logical dispatches are the cost
unit. No source image is redistributed in documentation.

