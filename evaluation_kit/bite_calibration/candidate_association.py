"""Class-aware, reversible association hypotheses; no GT inputs."""
from .common import identity, iou, valid_box


def compare(a, b, same_threshold=.8, distinct_threshold=.1):
    if not 0 <= distinct_threshold < same_threshold <= 1:
        raise ValueError("Association thresholds must satisfy 0 <= distinct < same <= 1")
    if a.get("source_group_id") and b.get("source_group_id") and a["source_group_id"] != b["source_group_id"]:
        return {"status": "distinct_source", "iou": None}
    if (not a.get("source_group_id") or not b.get("source_group_id") or
            a.get("source_image_sha256") != b.get("source_image_sha256") or
            a.get("root_image_id") != b.get("root_image_id") or
            not valid_box(a.get("bbox_root_xyxy")) or not valid_box(b.get("bbox_root_xyxy"))):
        return {"status": "unavailable_frame", "iou": None}
    overlap = iou(a["bbox_root_xyxy"], b["bbox_root_xyxy"])
    if not a.get("class_name") or not b.get("class_name"):
        return {"status": "unavailable_class", "iou": overlap}
    if a["class_name"].strip().casefold() != b["class_name"].strip().casefold():
        return {"status": "incompatible_class", "iou": overlap}
    status = "likely_same_object" if overlap >= same_threshold else "spatially_distinct" if overlap <= distinct_threshold else "ambiguous_overlap"
    return {"status": status, "iou": overlap}


def associate(candidate, prior, same_threshold=.8, distinct_threshold=.1):
    comparisons = [{"other_candidate_id": p["candidate_id"], **compare(candidate, p, same_threshold, distinct_threshold)} for p in prior]
    same = [c["other_candidate_id"] for c in comparisons if c["status"] == "likely_same_object"]
    ambiguous = any(c["status"] in {"ambiguous_overlap", "unavailable_class", "unavailable_frame"} for c in comparisons)
    conflict = any(c["status"] == "incompatible_class" and c["iou"] > distinct_threshold for c in comparisons)
    unavailable = not valid_box(candidate.get("bbox_root_xyxy"))
    status = ("unavailable_frame" if unavailable else "conflicting_candidate" if conflict else
              "ambiguous_association" if ambiguous or len(same) > 1 else
              "likely_duplicate" if same else "new_distinct_candidate")
    return {"association_version": "class_box_iou.v1", "status": status, "comparisons": comparisons,
            "likely_same_candidate_ids": same, "same_threshold": same_threshold, "distinct_threshold": distinct_threshold,
            "irreversible_merge": False}


def association_groups(proposals, same_threshold=.8, distinct_threshold=.1):
    """Return tentative connected components plus all pair evidence, not merged boxes."""
    groups = [{p["candidate_id"]} for p in proposals]
    pairs = []
    for i, a in enumerate(proposals):
        for b in proposals[:i]:
            result = compare(a, b, same_threshold, distinct_threshold)
            pairs.append({"left": a["candidate_id"], "right": b["candidate_id"], **result})
            if result["status"] == "likely_same_object":
                left = next(g for g in groups if a["candidate_id"] in g)
                right = next(g for g in groups if b["candidate_id"] in g)
                if left is not right:
                    left.update(right); groups.remove(right)
    return {"version": "class_box_iou.v1", "same_threshold": same_threshold, "distinct_threshold": distinct_threshold,
            "pairs": pairs, "groups": [{"association_group_id": identity(sorted(g), "association_group"),
                                         "candidate_ids": sorted(g), "status": "tentative_not_object_identity"} for g in groups]}
