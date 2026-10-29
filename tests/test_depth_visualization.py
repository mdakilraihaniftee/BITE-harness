"""Exercise the worker's real colormap path without loading GPU weights."""
import sys

import numpy as np
import pytest

from openvlharness.services.tools.depth_estimation.visualization import apply_colormap


def test_inferno_renders_rgb_on_supported_matplotlib_versions():
    pytest.importorskip("matplotlib")
    colors, name = apply_colormap(np.array([[0.0, 0.5, 1.0]], dtype=np.float32), "inferno")
    assert name == "inferno"
    assert colors.dtype == np.uint8
    assert colors.shape == (1, 3, 3)
    assert int(colors[0, 0].sum()) < int(colors[0, -1].sum())
    assert len({tuple(pixel) for pixel in colors[0]}) == 3
    assert colors[0, 1, 0] != colors[0, 1, 1], "Inferno should retain color, not grayscale"


def test_missing_matplotlib_falls_back_to_grayscale(monkeypatch):
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    colors, name = apply_colormap(np.array([[0.0, 1.0]], dtype=np.float32), "inferno")
    assert name == "grayscale"
    assert colors.tolist() == [[[0, 0, 0], [255, 255, 255]]]


def test_unknown_colormap_is_rejected():
    with pytest.raises(ValueError, match="colormap must be"):
        apply_colormap(np.zeros((2, 2)), "unknown")
