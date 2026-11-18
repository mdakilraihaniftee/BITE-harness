"""Deterministic visual-chain fixture: original -> ROI -> Zoom -> detection on the crop.

TEST FIXTURE ONLY; it never performs model inference. The agents are real
``MainAgent`` instances with real ``Zoom_In_Tool`` and ``Visual_Grounding_Tool``
capabilities (argument validation, image-ID resolution, output registration and
model-visible evidence all run unchanged). Only the transports are local:

* Zoom executes the repository's own crop implementation
  (``services/tools/zoom_in_image_by_bbox``) in process.
* Grounding runs a small deterministic detector on the pixels it is given:
  connected bright components whose area is at least 1.5% of the processed
  image. Small objects are therefore missed on the full image and found on a
  zoomed crop, so crop detections are computed from the crop itself.

The scripted model policy reads the actual tool evidence (registry IDs and
0-1000 boxes rendered by the real capability processors) to choose its next
call. The scene's object count is exposed only to evaluators after a run.
"""

from __future__ import annotations

import base64
import json
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from ..agent.agent import MainAgent
from ..capabilities import grounding, zoom
from ..memory.store import MemoryStore
from ..services.models import ModelAdapter
from ..services.tools.zoom_in_image_by_bbox.tool import Zoom_In_Tool
from .actors import AgentFactory
from .testing import FIXTURE_SYSTEM, ScriptedPolicy, _answer, _response, _text_of

SCENE_SIZE = (640, 400)
LARGE = [(40, 60, 150, 170), (190, 40, 300, 150), (360, 90, 470, 200), (80, 250, 190, 360)]
SMALL = [(505, 285, 533, 313), (552, 322, 578, 348)]
OBJECT_COUNT = len(LARGE) + len(SMALL)
VISUAL_TASK = "How many marked objects are in the image? Your final answer should be a single integer."
ROI_A = [734, 625, 969, 950]   # lower-right region, 0-1000 scale (agent's chosen ROI)
ROI_W2 = [297, 100, 469, 375]  # worker 2's region around the blue object
MIN_AREA_FRACTION = 0.015


def create_visual_scene(path: Path) -> Path:
    image = Image.new("RGB", SCENE_SIZE, "#16231f")
    draw = ImageDraw.Draw(image)
    for box, color in zip(LARGE, ["#6ee7a4", "#64b5f6", "#f1b95b", "#e889c4"]):
        draw.ellipse(box, fill=color, outline="white", width=3)
    for box in SMALL:
        draw.ellipse(box, fill="#9fb8ad", outline="#d7e4de", width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def _decode(data_url: str) -> Image.Image:
    return Image.open(BytesIO(base64.b64decode(data_url.split(",", 1)[1]))).convert("RGB")


def detect_components(image: Image.Image) -> list[tuple[list[float], float]]:
    """Bright connected components (4-neighbour) above the minimum area fraction."""
    pixels = np.asarray(image, dtype=np.int32)
    mask = pixels.sum(axis=2) > 300
    height, width = mask.shape
    seen = np.zeros_like(mask)
    found = []
    minimum = MIN_AREA_FRACTION * width * height
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        stack = [(y0, x0)]
        seen[y0, x0] = True
        xs, ys, brightness = [], [], 0
        while stack:
            y, x = stack.pop()
            xs.append(x); ys.append(y); brightness += int(pixels[y, x].sum())
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if len(xs) >= minimum:
            score = round(min(0.99, 0.55 + brightness / len(xs) / 1600), 3)
            found.append(([float(min(xs)), float(min(ys)), float(max(xs) + 1), float(max(ys) + 1)], score))
    return sorted(found, key=lambda item: (item[0][1], item[0][0]))


class LocalZoomClient:
    """Runs the repository's Zoom implementation in process."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay  # paces live demonstrations only

    def execute(self, tool_name, args, *, tool_call_id):
        if self.delay:
            time.sleep(self.delay)
        try:
            result = Zoom_In_Tool().execute(image_base64=args.get("image_base64"), coords=args.get("coords"),
                                            padding=args.get("padding", 50))
            return {"ok": True, "tool_name": tool_name, "tool_call_id": tool_call_id, "result": result, "error": None, "meta": {}}
        except Exception as exc:  # noqa: BLE001 - mirror the router's structured failure
            return {"ok": False, "tool_name": tool_name, "tool_call_id": tool_call_id, "result": None,
                    "error": {"code": "tool_error", "message": str(exc)}, "meta": {}}


class PixelDetectorClient:
    """Deterministic SAM3-shaped detector over the supplied pixels."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay  # paces live demonstrations only

    def execute(self, tool_name, args, *, tool_call_id):
        if self.delay:
            time.sleep(self.delay)
        image = _decode(args["image_base64"])
        found = detect_components(image)
        rendered = image.copy()
        draw = ImageDraw.Draw(rendered)
        for index, (box, _score) in enumerate(found, start=1):
            draw.rectangle(box, outline="#ffeb3b", width=2)
            draw.text((box[0] + 2, box[1] + 1), str(index), fill="#ffeb3b")
        buffer = BytesIO()
        rendered.save(buffer, format="PNG")
        return {"ok": True, "tool_name": tool_name, "tool_call_id": tool_call_id, "error": None, "meta": {},
                "result": {"model": "deterministic-pixel-detector (fixture)", "prompt": args.get("query", ""),
                           "orig_img_w": image.size[0], "orig_img_h": image.size[1],
                           "pred_boxes": [box for box, _ in found], "pred_scores": [score for _, score in found],
                           "pred_masks": [], "num_masks": len(found),
                           "rendered_image_b64": base64.b64encode(buffer.getvalue()).decode("ascii")}}


_REF = re.compile(r"refer to (?:it )?as (tool_generated_image_\d+)")
_BBOX = re.compile(r'"bbox_2d": \[(\d+), (\d+), (\d+), (\d+)\]')
_TOOL_TEXT = re.compile(r"^(Tool `\w+`|\w+ grounded \d+ objects)")


class VisualPolicy(ScriptedPolicy):
    """Scripted decisions computed from the real capabilities' evidence messages."""

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.actor_id == "coordinator":
            return super().__call__(payload)
        self.requests.append(payload)
        if self.delay:
            time.sleep(self.delay)
        messages = payload.get("messages") or []
        step = sum(len(m.get("tool_calls") or []) for m in messages if m.get("role") == "assistant")
        # One evidence message per completed call, in call order (rendered by the real processors).
        texts = [t for t in (_text_of(m.get("content")) for m in messages if m.get("role") == "user") if _TOOL_TEXT.match(t)]
        ref = lambda i: (_REF.findall(texts[i]) or [None])[0] if i < len(texts) else None  # noqa: E731
        boxes = lambda i: [[int(v) for v in b] for b in _BBOX.findall(texts[i])] if i < len(texts) else []  # noqa: E731
        call = lambda note, tool, args: _response(note, (tool, args), step)  # noqa: E731
        if self.actor_id == "worker_01":
            if step == 0:
                return call("Locate the marked objects first.", "Visual_Grounding_Tool", {"query": "marked object", "image_id": "input_image_1"})
            if step == 1:
                return call("The lower-right region may hide small objects; zoom in.", "Zoom_In_Tool", {"image_id": "input_image_1", "coords": ROI_A, "padding": 50})
            if step == 2 and ref(1):
                return call("Ground objects on the zoomed crop.", "Visual_Grounding_Tool", {"query": "marked object", "image_id": ref(1)})
            if step == 3 and ref(1) and boxes(2):
                return call("Inspect the last detected candidate more closely.", "Zoom_In_Tool", {"image_id": ref(1), "coords": boxes(2)[-1], "padding": 50})
            if step == 4 and ref(3):
                return call("Confirm the candidate on the closer crop.", "Visual_Grounding_Tool", {"query": "marked object", "image_id": ref(3)})
            if step >= 5:
                return _answer(str(len(boxes(0)) + len(boxes(2))))
            return _answer(str(len(boxes(0))), "The planned zoom inspection could not be completed.")
        if step == 0:
            return call("Check the upper object closely.", "Zoom_In_Tool", {"image_id": "input_image_1", "coords": ROI_W2, "padding": 50})
        if step == 1 and ref(0):
            return call("Ground objects on this crop.", "Visual_Grounding_Tool", {"query": "marked object", "image_id": ref(0)})
        return _answer("4", "Only the upper region was inspected; small objects elsewhere were not checked.")

    def _coordinator(self, text: str) -> dict[str, Any]:
        if "Decompose the immutable original task" in text:
            workers = json.loads(re.search(r"Workers: (\[.*\])", text).group(1))
            scopes = {"worker_01": "Count all marked objects; zoom into regions that may hide small ones.",
                      "worker_02": "Verify the large objects' shapes with a close inspection."}
            return _answer(json.dumps({"assignments": [{"worker_id": w, "scope": scopes.get(w, "Count the marked objects.")} for w, _ in workers]}))
        return super()._coordinator(text)


class VisualAgentBuilder:
    def __init__(self, image_path: Path, delay: float = 0.0, tool_delay: float = 0.0) -> None:
        self.image_path = image_path
        self.delay = delay
        self.tool_delay = tool_delay
        self.policies: dict[str, VisualPolicy] = {}

    def __call__(self, _config, actor_id, tool_access):
        policy = VisualPolicy(actor_id, "standard", self.delay)
        self.policies[actor_id] = policy
        adapter = ModelAdapter({"alias": "qwen3-vl-8b-instruct", "base": "http://fixture.invalid/v1", "max_tokens": 1024},
                               requester=policy)
        tools = {}
        if tool_access:
            tools["Zoom_In_Tool"] = zoom.Capability(backend="zoom_in_image_by_bbox", client_config={}, client=LocalZoomClient(self.tool_delay))
            tools["Visual_Grounding_Tool"] = grounding.Capability(backend="sam3_segment", client_config={}, client=PixelDetectorClient(self.tool_delay))
        agent = MainAgent(adapter, tools, MemoryStore, FIXTURE_SYSTEM, "Question: {user_query}", max_iterations=8)
        if actor_id == "coordinator":
            from importlib.resources import files

            agent.system_prompt = files("openvlharness.prompts").joinpath("coordinator_system.txt").read_text()
        agent.studio_topology = {"model_client": {"kind": "fixture", "model_id": "scripted fixture policy (Qwen chat protocol)"}}
        return agent

    def factory(self) -> AgentFactory:
        return AgentFactory(self)


def write_visual_reference(reference_dir: Path, run_id: str) -> Path:
    reference_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = reference_dir / f"{run_id}.json"
    path.write_text(json.dumps({
        "schema_version": "studio.reference.v1", "run_id": run_id, "dataset": "deterministic_fixture",
        "split": "test", "row": "visual_chain_scene_v1", "answer_type": "integer_count",
        "reference": str(OBJECT_COUNT), "reference_source": "Synthetic scene construction (test fixture label)",
        "normalization_rule": "fsc147_parse_count_exact_match", "note": "Deterministic test fixture; not a benchmark annotation.",
    }, indent=2) + "\n", encoding="utf-8")
    return path
