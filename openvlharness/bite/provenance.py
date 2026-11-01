"""Image identities may have several geometric lineages after pixel deduplication."""
import base64
import io
from PIL import Image
from .geometry import translation
from .serialization import digest


class Provenance:
    def __init__(self, state):
        self.state = state
        self.frames = {}
        self.producers = {}

    def node(self, identity, kind, **data):
        self.state.nodes.setdefault(identity, {"id": identity, "kind": kind, **data})
        return identity

    def edge(self, source, target, relation, **data):
        edge = {"source": source, "target": target, "relation": relation, **data}
        if edge not in self.state.provenance_edges:
            self.state.provenance_edges.append(edge)

    def image(self, image_id, memory, *, original=False):
        entry = memory.state.images.registry.get(image_id, {})
        artifact_id = "image:" + image_id
        if artifact_id not in self.state.artifacts:
            info = {"artifact_id": artifact_id, "kind": "image", "image_id": image_id,
                    "sha256": None, "width": None, "height": None,
                    "metadata_reason": "Pixels not locally registered", "aliases": sorted(entry.get("aliases", []))}
            url = entry.get("data_url")
            if isinstance(url, str) and url.startswith("data:image/"):
                pixels = base64.b64decode(url.split(",", 1)[1])
                with Image.open(io.BytesIO(pixels)) as image:
                    info.update(sha256=digest(pixels), width=image.width, height=image.height, metadata_reason=None)
            self.state.artifacts[artifact_id] = info
            self.node(artifact_id, "original_image" if original else "generated_image", image_id=image_id)
            self.frames[image_id] = []
        info = self.state.artifacts[artifact_id]
        if info["width"] is None and isinstance(entry.get("data_url"), str):
            pixels = base64.b64decode(entry["data_url"].split(",", 1)[1])
            with Image.open(io.BytesIO(pixels)) as image:
                info.update(sha256=digest(pixels), width=image.width, height=image.height, metadata_reason=None)
        if original:
            self.add_frame(image_id, {"root_image_id": image_id, "child_to_root_transform": translation()})
        return info

    def add_frame(self, image_id, frame):
        frames = self.frames.setdefault(image_id, [])
        if frame not in frames:
            frames.append(frame)
        self.state.artifacts["image:" + image_id]["coordinate_frames"] = frames.copy()

    def frame(self, image_id):
        frames = self.frames.get(image_id, [])
        if len(frames) == 1 and frames[0].get("child_to_root_transform") is not None:
            return frames[0], None
        return None, "ambiguous_deduplicated_lineage" if frames else "unknown_geometry"
