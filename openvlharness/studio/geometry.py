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
