"""CPU-only depth visualization helpers, independent of the model worker."""
import numpy as np


def apply_colormap(depth_norm, colormap_name):
    """Return uint8 RGB colors; use grayscale when Matplotlib is unavailable."""
    colormap_name = (colormap_name or "inferno").lower()
    if colormap_name == "inferno":
        try:
            import matplotlib

            matplotlib.use("Agg")
        except ImportError:
            colormap_name = "grayscale"
        else:
            colors = matplotlib.colormaps["inferno"](depth_norm)[:, :, :3]
            return (colors * 255).astype(np.uint8), "inferno"

    if colormap_name == "grayscale":
        gray = (depth_norm * 255.0).astype(np.uint8)
        return np.repeat(gray[:, :, None], 3, axis=2), "grayscale"

    raise ValueError("colormap must be inferno or grayscale")
