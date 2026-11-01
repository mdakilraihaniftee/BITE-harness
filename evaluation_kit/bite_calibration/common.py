"""Deterministic identities and explicit geometry validation."""
import hashlib
import json
import math
from pathlib import Path


def identity(value, prefix="id"):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return prefix + ":" + hashlib.sha256(encoded.encode()).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_box(box):
    return (isinstance(box, (list, tuple)) and len(box) == 4
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in box)
            and box[2] > box[0] and box[3] > box[1])


def clip_box(box, width, height):
    if (not isinstance(box, (list, tuple)) or len(box) != 4 or
            not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in box)
            or width <= 0 or height <= 0):
        return None
    # Match eval_bridge._xyxy_pixel_to_clipped_xywh: clip, sort, reject zero area.
    x1, x2 = sorted([min(max(box[0], 0), width), min(max(box[2], 0), width)])
    y1, y2 = sorted([min(max(box[1], 0), height), min(max(box[3], 0), height)])
    clipped = [x1, y1, x2, y2]
    return clipped if valid_box(clipped) else None


def iou(a, b):
    if not valid_box(a) or not valid_box(b):
        return None
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection/union


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
