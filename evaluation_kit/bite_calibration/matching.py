"""Offline class-aware validity and native COCO assignment, explicitly separated."""
import contextlib
import copy
import csv
from dataclasses import dataclass
import io
import json
import math
from pathlib import Path

import numpy as np
from .common import clip_box, file_hash, iou, valid_box


@dataclass
class GroundTruth:
    image: dict
    categories: list
    annotations: list
    provenance: dict
    dropped_annotation_ids: list

    @property
    def class_map(self):
        result, ambiguous = {}, set()
        for category in self.categories:
            name = str(category["name"]).strip().casefold()
            if name in result and result[name] != category["id"]:
                ambiguous.add(name)
            result[name] = category["id"]
        return {name: cid for name, cid in result.items() if name not in ambiguous}


def load_coco(path, image_id):
    """Load one actual image and annotations, retaining original IDs including zero."""
    path = Path(path)
    doc = json.loads(path.read_text())
    if not all(isinstance(doc.get(k), list) for k in ["images", "categories", "annotations"]):
        raise ValueError("Invalid COCO annotation structure")
    images = [i for i in doc["images"] if i.get("id") == image_id]
    if len(images) != 1 or any(not isinstance(images[0].get(k), (int, float)) or not math.isfinite(images[0][k])
                               or images[0][k] <= 0 for k in ["width", "height"]):
        raise ValueError("Missing, duplicate or invalid COCO image")
    category_ids = {c["id"] for c in doc["categories"]}
    if len(category_ids) != len(doc["categories"]):
        raise ValueError("Duplicate category IDs")
    annotations, dropped, ids = [], [], set()
    for raw in doc["annotations"]:
        if raw.get("image_id") != image_id:
            continue
        if raw["id"] in ids:
            raise ValueError("Duplicate annotation IDs")
        ids.add(raw["id"])
        box = raw.get("bbox")
        if (not isinstance(box, list) or len(box) != 4 or
                not all(isinstance(x, (int, float)) and math.isfinite(x) for x in box) or box[2] <= 0 or box[3] <= 0):
            dropped.append(raw["id"])
            continue
        if raw["category_id"] not in category_ids:
            raise ValueError("GT category ID not declared")
        ann = copy.deepcopy(raw)
        ann.setdefault("iscrowd", 0)
        ann.setdefault("ignore", 0)
        ann.setdefault("area", box[2]*box[3])
        ann["bbox_xyxy"] = [box[0], box[1], box[0]+box[2], box[1]+box[3]]
        annotations.append(ann)
    return GroundTruth(images[0], doc["categories"], annotations,
                       {"annotation_file": str(path.resolve()), "annotation_sha256": file_hash(path),
                        "image_id": image_id, "source": "original_COCO"}, dropped)


def load_dataset_ground_truth(data_root, dataset, sample_id):
    """Use explicit local paths only, never a dataset constructor/download helper."""
    root = Path(data_root)
    tsv = root/(dataset+".tsv")
    with tsv.open(newline="") as stream:
        rows = [r for r in csv.DictReader(stream, delimiter="\t") if r["index"] == sample_id]
    if len(rows) != 1:
        raise ValueError("Sample must resolve to exactly one TSV row")
    row = rows[0]
    from ..dataset.eval_bridge import parse_image_id_from_index
    image_id = parse_image_id_from_index(sample_id)
    if image_id is None:
        raise ValueError("Cannot resolve annotation image ID")
    if dataset.startswith("ODinW"):
        from ..dataset.odinw import _build_odinw_gt_path_map
        mappings = _build_odinw_gt_path_map([row["domain"]], glip_root=str(root/"GLIP"))
        path = mappings.get((row["domain"], row["split"]))
        if path is None:
            raise FileNotFoundError("No local annotation mapping for the requested domain/split")
        result = load_coco(path, image_id)
        if row.get("dataset_classes"):
            # Match the actual prompted labels to existing numeric GT categories.
            names = {c["id"]: c["name"] for c in json.loads(row["dataset_classes"])}
            result.categories = [{**c, "name": names.get(c["id"], c["name"])} for c in result.categories]
    elif dataset.startswith("FSCD_") and "_bbox_" in dataset:
        from ..dataset.fscd import _build_synthetic_gt_from_meta
        required = ["image_width", "image_height", "category_id", "category_name", "answer"]
        if any(k not in row for k in required):
            raise ValueError("FSCD bbox TSV lacks required detection fields")
        box_answers = json.loads(row["answer"])
        if not isinstance(box_answers, list):
            raise ValueError("Counting labels cannot substitute for detection boxes")
        doc = _build_synthetic_gt_from_meta([{**row, "image_id": image_id,
                "image_width": int(row["image_width"]), "image_height": int(row["image_height"]),
                "category_id": int(row["category_id"])}])
        annotations = [{**a, "ignore": 0, "bbox_xyxy": [a["bbox"][0], a["bbox"][1],
                        a["bbox"][0]+a["bbox"][2], a["bbox"][1]+a["bbox"][3]]} for a in doc["annotations"]]
        result = GroundTruth(doc["images"][0], [{"id": int(row["category_id"]), "name": row["category_name"]}],
                             annotations, {"source": "prepared_FSCD_TSV_boxes", "image_id": image_id,
                                           "annotation_file": str(tsv.resolve()), "annotation_sha256": file_hash(tsv)}, [])
    else:
        raise ValueError("Dataset has no supported detection GT loader; count TSVs are not bbox annotations")
    result.provenance.update(dataset=dataset, sample_id=sample_id, tsv_sha256=file_hash(tsv))
    family = "ODinW" if dataset.startswith("ODinW") else "FSC147" if dataset.startswith("FSCD_147") else "LVIS"
    image_path = root/"images"/family/row["image_path"]
    if not image_path.is_file():
        raise FileNotFoundError("Annotation image is absent; cannot verify observer/source identity")
    result.provenance.update(source_image_path=str(image_path.resolve()), source_image_sha256=file_hash(image_path))
    return result


def _native_assign(candidates, gt, thresholds, score_mode, max_dets):
    """Run installed COCOeval without modifying its ignore/crowd semantics."""
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval
    annotations = []
    original_ids = {}
    for index, annotation in enumerate(gt.annotations, 1):
        original_ids[index] = annotation["id"]
        annotations.append({**copy.deepcopy(annotation), "id": index})
    predictions = []
    for index, candidate in enumerate(candidates, 1):
        x1, y1, x2, y2 = candidate["bbox_for_matching"]
        predictions.append({"image_id": gt.image["id"], "category_id": gt.class_map[candidate["class_name"].casefold().strip()],
                            "bbox": [x1, y1, x2-x1, y2-y1], "score": 1.0 if score_mode == "constant" else candidate["raw_scores"][0]})
    if not predictions:
        return {}
    with contextlib.redirect_stdout(io.StringIO()):
        coco = COCO()
        coco.dataset = {"info": {}, "images": [copy.deepcopy(gt.image)], "categories": gt.categories, "annotations": annotations}
        coco.createIndex()
        evaluator = COCOeval(coco, coco.loadRes(predictions), "bbox")
        evaluator.params.imgIds = [gt.image["id"]]
        evaluator.params.iouThrs = np.array(thresholds)
        evaluator.params.areaRng = [[0, 1e10]]
        evaluator.params.areaRngLbl = ["all"]
        evaluator.params.maxDets = [max_dets]
        evaluator.evaluate()
    labels = {}
    for image_result in evaluator.evalImgs:
        if image_result is None:
            continue
        for pos, dt_id in enumerate(image_result["dtIds"]):
            candidate_id = candidates[int(dt_id)-1]["candidate_id"]
            for ti, threshold in enumerate(thresholds):
                match = int(image_result["dtMatches"][ti, pos])
                ignored = bool(image_result["dtIgnore"][ti, pos])
                labels[(candidate_id, threshold)] = {
                    "official_tp": None if ignored else bool(match), "official_ignored": ignored,
                    "official_unmatched": None if ignored else not bool(match),
                    "official_matched_gt_id": original_ids.get(match), "official_reason": "ignored_by_native_COCO" if ignored else None}
    return labels


def label_candidates(candidates, gt, thresholds=(.5, .75), *, assignment_scope="per_observation", score_mode="retained", max_dets=100):
    if not thresholds or any(not 0 < t <= 1 for t in thresholds) or len(set(thresholds)) != len(thresholds):
        raise ValueError("Unique IoU thresholds in (0,1] required")
    if assignment_scope not in {"per_observation", "trajectory"} or score_mode not in {"retained", "constant"} or max_dets < 1:
        raise ValueError("Invalid assignment protocol")
    candidates = copy.deepcopy(candidates)
    ids = [c["candidate_id"] for c in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate candidate IDs")
    batches = {}
    for c in candidates:
        c["bbox_for_matching"] = clip_box(c.get("bbox_root_xyxy"), gt.image["width"], gt.image["height"])
        c["matching_status"] = ("unknown_coordinate_frame" if c.get("bbox_root_xyxy") is None else
                                "invalid_box" if c["bbox_for_matching"] is None else
                                "unknown_class_mapping" if str(c.get("class_name", "")).strip().casefold() not in gt.class_map else "matchable")
        if c["matching_status"] == "matchable":
            batches.setdefault(c["source_observation_id"] if assignment_scope == "per_observation" else "trajectory", []).append(c)
    official, unavailable = {}, set()
    for batch in batches.values():
        if score_mode == "retained" and any(not c.get("raw_scores") or not isinstance(c["raw_scores"][0], (int, float)) or
                                            not math.isfinite(c["raw_scores"][0]) for c in batch):
            unavailable.update(c["candidate_id"] for c in batch)
        else:
            official.update(_native_assign(batch, gt, list(thresholds), score_mode, max_dets))
    seen = {threshold: set() for threshold in thresholds}
    covered = {threshold: set() for threshold in thresholds}
    labels = {}
    for c in candidates:
        per_threshold = []
        for threshold in thresholds:
            label = {"iou_threshold": threshold, "matching_status": c["matching_status"],
                     "bbox_raw_root_xyxy": c.get("bbox_root_xyxy"), "bbox_for_matching_xyxy": c["bbox_for_matching"],
                     "geometry_policy": "clip_and_sort_raw_root_pixels_v1_no_norm1k_rounding",
                     "raw_box_order_valid": valid_box(c.get("bbox_root_xyxy")),
                     "max_eligible_iou": None, "best_eligible_gt_id": None, "class_compatible": None,
                     "geometric_valid": None, "novel_gt_instance": None, "duplicate_gt_evidence": None,
                     "unmatched_eligible_gt": None, "validity_label_usable": None,
                     "novelty_reason": c["matching_status"] if c["matching_status"] != "matchable" else None,
                     "best_compatible_gt_including_ignored": None,
                     "official_tp": None, "official_ignored": None, "official_matched_gt_id": None,
                     "official_unmatched": None,
                     "official_reason": c["matching_status"] if c["matching_status"] != "matchable" else None}
            if c["matching_status"] == "matchable":
                cid = gt.class_map[c["class_name"].strip().casefold()]
                compatible = [a for a in gt.annotations if a["category_id"] == cid]
                eligible = [a for a in compatible if not a.get("ignore") and not a.get("iscrowd")]
                matches = [(iou(c["bbox_for_matching"], a["bbox_xyxy"]), a) for a in eligible]
                matches.sort(key=lambda p: -p[0])
                passing = [a for overlap, a in matches if overlap >= threshold]
                label.update(max_eligible_iou=matches[0][0] if matches else 0.0,
                             best_eligible_gt_id=matches[0][1]["id"] if matches else None,
                             class_compatible=bool(compatible), geometric_valid=bool(passing), unmatched_eligible_gt=not bool(passing))
                all_matches = sorted([(iou(c["bbox_for_matching"], a["bbox_xyxy"]), a) for a in compatible], key=lambda p: -p[0])
                if all_matches:
                    overlap, best = all_matches[0]
                    label["best_compatible_gt_including_ignored"] = {"gt_id": best["id"], "iou": overlap,
                        "dataset_ignore": bool(best.get("ignore")), "iscrowd": bool(best.get("iscrowd"))}
                ignore_context = any((a.get("ignore") or a.get("iscrowd")) and overlap >= threshold for overlap, a in all_matches)
                covered[threshold].update(a["id"] for a in passing)
                if len(passing) == 1 and c.get("association_status") not in {"ambiguous_association", "conflicting_candidate", "unavailable_frame"}:
                    gt_id = passing[0]["id"]
                    label.update(novel_gt_instance=gt_id not in seen[threshold], duplicate_gt_evidence=gt_id in seen[threshold])
                    seen[threshold].add(gt_id)
                elif len(passing) > 1 or c.get("association_status") in {"ambiguous_association", "conflicting_candidate", "unavailable_frame"}:
                    label["novelty_reason"] = "ambiguous_GT_or_candidate_association"
                else:
                    label["novelty_reason"] = "no_eligible_valid_instance"
                label.update(official.get((c["candidate_id"], threshold), {
                    "official_tp": None, "official_ignored": None, "official_matched_gt_id": None,
                    "official_unmatched": None,
                    "official_reason": "score_order_unavailable" if c["candidate_id"] in unavailable else "max_detections_excluded"}))
                label["validity_label_usable"] = not ignore_context and not label["official_ignored"]
            per_threshold.append(label)
        labels[c["candidate_id"]] = per_threshold
    eligible_ids = {a["id"] for a in gt.annotations if not a.get("ignore") and not a.get("iscrowd")}
    summary = {"thresholds": list(thresholds), "assignment_scope": assignment_scope, "score_mode": score_mode,
               "max_detections_per_image_class": max_dets, "assignment_engine": "native_pycocotools_COCOeval_bbox",
               "explicit_ignore_semantics": "Geometric labels exclude dataset ignore; native bbox COCOeval overwrites ignore with iscrowd. Both flags are exposed, not silently reconciled.",
               "uncovered_eligible_gt_ids": {str(t): sorted(eligible_ids-covered[t]) for t in thresholds},
               "eligible_gt_count": len(eligible_ids), "ignored_gt_ids": [a["id"] for a in gt.annotations if a.get("ignore")],
               "crowd_gt_ids": [a["id"] for a in gt.annotations if a.get("iscrowd")],
               "dropped_invalid_gt_ids": gt.dropped_annotation_ids, "ground_truth": gt.provenance}
    return labels, summary
