"""Offline entry points; commands never start services, download data or fit models."""
import argparse
import json
from pathlib import Path
from .actions import ACTION_SPEC
from .common import save_json
from .dataset_inventory import audit_sources
from .matching import load_dataset_ground_truth
from .records import build_records, load_trace
from .validation import CALIBRATION_SCHEMA, validate_records


def audit_main(argv=None):
    parser = argparse.ArgumentParser(description="Audit local calibration sources and exact split identity overlaps")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--output-dir", default="outputs/bite/phase04a/audit")
    args = parser.parse_args(argv)
    out = Path(args.output_dir)
    inventory, integrity = audit_sources(args.data_root)
    save_json(out/"dataset_inventory.json", inventory)
    save_json(out/"split_integrity.json", integrity)
    save_json(out/"provisional_groups.json", {"schema_version": "bite.partition_manifest.v1", "status": "unassigned_provisional",
              "reason": inventory["partition_decision"], "groups": integrity["groups"], "approved_calibration_entries": []})
    save_json(out/"action_space_v1.json", ACTION_SPEC)
    print(json.dumps({"odinw_mappings": len(inventory["odinw_mappings"]), "entries": integrity["entry_count"],
                      "hashed_entries": integrity["hashed_entry_count"], "cross_partition_overlap_count": integrity["cross_partition_overlap_count"],
                      "duplicate_identity_counts": integrity["duplicate_identity_counts"],
                      "missing_detection_tsvs": inventory["missing_prepared_detection_tsvs"], "output": str(out)}, indent=2))


def build_main(argv=None):
    parser = argparse.ArgumentParser(description="Build development/debug calibration labels from a retained observer trace")
    parser.add_argument("--observer", required=True)
    parser.add_argument("--canonical")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--iou-thresholds", nargs="+", type=float, default=[.5, .75])
    parser.add_argument("--assignment-scope", choices=["per_observation", "trajectory"], default="per_observation")
    parser.add_argument("--score-mode", choices=["retained", "constant"], default="retained")
    parser.add_argument("--partition", default="development_debug")
    parser.add_argument("--partition-manifest")
    parser.add_argument("--output-dir", default="outputs/bite/phase04a/smoke")
    args = parser.parse_args(argv)
    observer, canonical, evidence = load_trace(args.observer, args.canonical)
    gt = load_dataset_ground_truth(args.data_root, args.dataset, observer["sample_id"])
    partition_manifest = json.loads(Path(args.partition_manifest).read_text()) if args.partition_manifest else None
    rows, summary = build_records(observer, gt, evidence=evidence, thresholds=args.iou_thresholds,
                                   assignment_scope=args.assignment_scope, score_mode=args.score_mode,
                                   partition=args.partition, partition_manifest=partition_manifest)
    report = validate_records(rows)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out/"calibration_records.jsonl").write_text("".join(json.dumps(row, sort_keys=True, allow_nan=False)+"\n" for row in rows))
    save_json(out/"matching_summary.json", summary)
    save_json(out/"validation.json", report)
    save_json(out/"calibration_schema_v1.json", CALIBRATION_SCHEMA)
    lines = ["# Offline labeling smoke test", "", "Development/debug data only; no probabilities fitted.", "",
             f"Sample: `{observer['sample_id']}`; source SHA: `{gt.provenance.get('source_image_sha256')}`.", "",
             "| Candidate | Class | Threshold | Best eligible IoU | GT ID | Geometric | Official TP | Novel GT | Outcome |",
             "| --- | --- | ---: | ---: | --- | --- | --- | --- | --- |"]
    for row in rows:
        candidate = row["runtime_features"]["candidate"]
        if not candidate:
            continue
        for label in row["offline_labels"]["labels"]:
            lines.append(f"| `{candidate['candidate_id']}` | {candidate['class_name']} | {label['iou_threshold']} | {label['max_eligible_iou']} | "
                         f"{label['best_eligible_gt_id']} | {label['geometric_valid']} | {label['official_tp']} | {label['novel_gt_instance']} | {row['outcome']['category']} |")
    lines += ["", "Label semantics, score ordering, clipping and scope are preserved in matching_summary.json and each record.",
              "GT IDs/labels appear only in offline_labels; candidate geometry and action outcomes were constructed before loading these labels."]
    (out/"MATCHING_REPORT.md").write_text("\n".join(lines)+"\n")
    print(json.dumps({**report, "candidate_count": summary["candidate_count"], "sample": observer["sample_id"],
                      "uncovered_eligible_gt_ids": summary["uncovered_eligible_gt_ids"], "output": str(out)}, indent=2))


def validate_main(argv=None):
    parser = argparse.ArgumentParser(description="Validate calibration JSONL schemas, identities and runtime/offline separation")
    parser.add_argument("records")
    args = parser.parse_args(argv)
    rows = [json.loads(line) for line in Path(args.records).read_text().splitlines() if line.strip()]
    print(json.dumps(validate_records(rows), indent=2))
