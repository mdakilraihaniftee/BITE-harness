"""Exact existing zoom geometry, and pixel-frame translations for its observer."""
from ..services.tools.image_utils import coerce_xyxy


def crop_rectangle(coords, padding, width, height):
    # Match Zoom_In_Tool's padding-before-sorting behavior, including reversed boxes.
    x1, y1, x2, y2 = map(float, coords)
    padding = float(padding)
    if padding < 50:
        raise ValueError("padding must be at least 50")
    return coerce_xyxy([x1-padding, y1-padding, x2+padding, y2+padding],
                       width, height, "normalized_xyxy")


def translation(left=0, top=0):
    return [[1, 0, left], [0, 1, top], [0, 0, 1]]


def compose(parent_to_root, child_to_parent):
    return [[sum(parent_to_root[i][k] * child_to_parent[k][j] for k in range(3))
             for j in range(3)] for i in range(3)]


def transform_box(box, transform):
    if transform is None:
        return None
    x1, y1, x2, y2 = box
    return [x1 + transform[0][2], y1 + transform[1][2],
            x2 + transform[0][2], y2 + transform[1][2]]


def normalized_to_pixels(box, width, height):
    return [box[0]*width/1000, box[1]*height/1000,
            box[2]*width/1000, box[3]*height/1000]
