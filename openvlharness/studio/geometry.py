"""Strict coordinate transforms for Studio ROI overlays."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MappedBox:
    box: tuple[float, float, float, float] | None
    warning: str | None = None


def _positive(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return None


def map_box_to_source(
    box: Sequence[float],
    *,
    source_width: int,
    source_height: int,
    coordinate_system: str = "source_pixels",
    transform_metadata: dict[str, Any] | None = None,
) -> MappedBox:
    """Map a recorded box to source pixels, or return a precise warning.

    Supported systems are source pixels, normalized 0..1 / 0..1000, resized
    pixels, crop pixels, and padded resized model-input pixels. Boxes are
    clipped only after a complete transform can be established.
    """
    if source_width <= 0 or source_height <= 0:
        return MappedBox(None, "Invalid source image dimensions")
    if len(box) < 4 or any(
        not isinstance(value, (int, float)) or isinstance(value, bool)
        for value in box[:4]
    ):
        return MappedBox(None, "Box must contain four numeric coordinates")
    x1, y1, x2, y2 = (float(value) for value in box[:4])
    metadata = transform_metadata or {}

    if coordinate_system == "source_pixels":
        pass
    elif coordinate_system == "normalized_0_1":
        x1, x2 = x1 * source_width, x2 * source_width
        y1, y2 = y1 * source_height, y2 * source_height
    elif coordinate_system == "normalized_0_1000":
        x1, x2 = x1 * source_width / 1000, x2 * source_width / 1000
        y1, y2 = y1 * source_height / 1000, y2 * source_height / 1000
    elif coordinate_system == "resized_pixels":
        width = _positive(metadata.get("coordinate_width"))
        height = _positive(metadata.get("coordinate_height"))
        if width is None or height is None:
            return MappedBox(None, "Resized coordinates require coordinate dimensions")
        x1, x2 = x1 * source_width / width, x2 * source_width / width
        y1, y2 = y1 * source_height / height, y2 * source_height / height
    elif coordinate_system == "crop_pixels":
        bounds = metadata.get("crop_bounds")
        width = _positive(metadata.get("coordinate_width"))
        height = _positive(metadata.get("coordinate_height"))
        if (
            not isinstance(bounds, (list, tuple))
            or len(bounds) < 4
            or any(not isinstance(value, (int, float)) for value in bounds[:4])
            or width is None
            or height is None
        ):
            return MappedBox(
                None,
                "Crop coordinates require crop_bounds and coordinate dimensions",
            )
        crop_x1, crop_y1, crop_x2, crop_y2 = map(float, bounds[:4])
        crop_width, crop_height = crop_x2 - crop_x1, crop_y2 - crop_y1
        if crop_width <= 0 or crop_height <= 0:
            return MappedBox(None, "Crop bounds are invalid")
        x1, x2 = crop_x1 + x1 * crop_width / width, crop_x1 + x2 * crop_width / width
        y1, y2 = (
            crop_y1 + y1 * crop_height / height,
            crop_y1 + y2 * crop_height / height,
        )
    elif coordinate_system == "padded_resized_pixels":
        width = _positive(metadata.get("content_width"))
        height = _positive(metadata.get("content_height"))
        left = metadata.get("padding_left", 0)
        top = metadata.get("padding_top", 0)
        if (
            width is None
            or height is None
            or not isinstance(left, (int, float))
            or not isinstance(top, (int, float))
        ):
            return MappedBox(
                None, "Padded coordinates require content dimensions and padding"
            )
        x1, x2 = (x1 - left) * source_width / width, (x2 - left) * source_width / width
        y1, y2 = (
            (y1 - top) * source_height / height,
            (y2 - top) * source_height / height,
        )
    else:
        return MappedBox(None, f"Unsupported coordinate system: {coordinate_system}")

    x1, x2 = (
        max(0.0, min(float(source_width), x1)),
        max(0.0, min(float(source_width), x2)),
    )
    y1, y2 = (
        max(0.0, min(float(source_height), y1)),
        max(0.0, min(float(source_height), y2)),
    )
    if x2 <= x1 or y2 <= y1:
        return MappedBox(None, "Box is empty after mapping and clipping")
    return MappedBox((x1, y1, x2, y2))


# ---------------------------------------------------------------------------
# Unified transforms for visual lineage (original image -> crop -> crop ...).
#
# Every derived image frame is related to its parent frame by an axis-aligned
# affine map from child pixels to parent pixels: parent = offset + child * scale.
# Crops, resizes, letterbox padding and normalized coordinate frames are all of
# this form, so nested operations compose exactly. The frontend implements the
# same rules (static/geometry.js); tests/studio/geometry_vectors.json holds the
# shared reference cases.


@dataclass(frozen=True)
class Affine:
    """Child-frame pixels -> parent-frame pixels."""

    scale_x: float = 1.0
    scale_y: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0

    def apply_point(self, x: float, y: float) -> tuple[float, float]:
        return self.offset_x + x * self.scale_x, self.offset_y + y * self.scale_y

    def apply_box(self, box: Sequence[float]) -> tuple[float, float, float, float]:
        x1, y1 = self.apply_point(float(box[0]), float(box[1]))
        x2, y2 = self.apply_point(float(box[2]), float(box[3]))
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)

    def then(self, parent: Affine) -> Affine:
        """Compose: map with self (child -> this frame), then parent (-> its parent)."""
        return Affine(
            self.scale_x * parent.scale_x,
            self.scale_y * parent.scale_y,
            parent.offset_x + self.offset_x * parent.scale_x,
            parent.offset_y + self.offset_y * parent.scale_y,
        )

    def inverse(self) -> Affine:
        if self.scale_x == 0 or self.scale_y == 0:
            raise ValueError("Singular transform")
        return Affine(
            1 / self.scale_x,
            1 / self.scale_y,
            -self.offset_x / self.scale_x,
            -self.offset_y / self.scale_y,
        )


def crop_transform(crop_box: Sequence[float], output_size: Sequence[float]) -> Affine:
    """A crop of parent pixels ``crop_box`` stored at ``output_size`` (w, h) pixels."""
    left, top, right, bottom = (float(value) for value in crop_box[:4])
    width, height = float(output_size[0]), float(output_size[1])
    if right <= left or bottom <= top or width <= 0 or height <= 0:
        raise ValueError("Crop box and output size must be positive")
    return Affine((right - left) / width, (bottom - top) / height, left, top)


def resize_transform(child_size: Sequence[float], parent_size: Sequence[float]) -> Affine:
    """A whole-image resize from parent (w, h) to child (w, h)."""
    if min(map(float, (*child_size[:2], *parent_size[:2]))) <= 0:
        raise ValueError("Sizes must be positive")
    return Affine(
        float(parent_size[0]) / float(child_size[0]),
        float(parent_size[1]) / float(child_size[1]),
    )


def letterbox_transform(
    content_size: Sequence[float],
    padding: Sequence[float],
    parent_size: Sequence[float],
) -> Affine:
    """Model-input pixels with (left, top) padding around resized content -> parent pixels."""
    left, top = float(padding[0]), float(padding[1])
    scale = resize_transform(content_size, parent_size)
    return Affine(scale.scale_x, scale.scale_y, -left * scale.scale_x, -top * scale.scale_y)


def normalized_transform(scale: float, frame_size: Sequence[float]) -> Affine:
    """Normalized coordinates (0..scale) -> pixels of a (w, h) frame."""
    if scale <= 0 or min(float(frame_size[0]), float(frame_size[1])) <= 0:
        raise ValueError("Scale and frame size must be positive")
    return Affine(float(frame_size[0]) / scale, float(frame_size[1]) / scale)


def compose(chain: Sequence[Affine]) -> Affine:
    """Compose child->parent transforms ordered from the innermost frame outward."""
    result = Affine()
    for step in chain:
        result = result.then(step)
    return result


def clip_box(
    box: Sequence[float], width: float, height: float
) -> tuple[float, float, float, float] | None:
    x1 = max(0.0, min(float(width), float(box[0])))
    y1 = max(0.0, min(float(height), float(box[1])))
    x2 = max(0.0, min(float(width), float(box[2])))
    y2 = max(0.0, min(float(height), float(box[3])))
    return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None
