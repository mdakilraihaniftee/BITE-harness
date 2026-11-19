"""Deterministic plan fixture: read a small sign (OCR on the original vs. on a crop).

TEST FIXTURE ONLY — no model inference. Agents are real ``MainAgent``s with the
real ``OCR_Tool``, ``Visual_Grounding_Tool`` and ``Zoom_In_Tool`` capabilities;
only transports are local and the model is a scripted policy:

* Zoom: the repository's crop implementation, in process.
* Grounding: the visual fixture's pixel detector (bright connected components).
* OCR: a declared rule over the pixels it receives — the sign's text is readable
  when sign-coloured pixels cover at least ``READABLE_FRACTION`` of the image
  (true for a crop around the sign, false for the full scene). This stands in
  for "small text is unreadable at full resolution"; it is not a real OCR model.

The scripted worker issues ``Execute_Action_Plan`` with a fixed plan, then
answers with the text its observations contain. The scene's text is exposed to
evaluators only.
"""

from __future__ import annotations

import base64
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from ..agent.agent import MainAgent
from ..capabilities import grounding, ocr, zoom
from ..memory.store import MemoryStore
from ..multi_agent.actors import AgentFactory
from ..multi_agent.testing import FIXTURE_SYSTEM, ScriptedPolicy, _answer, _response, _text_of
from ..multi_agent.visual_fixture import LocalZoomClient, PixelDetectorClient

SIGN_TEXT = "EXIT 42"
SIGN_BOX = (40, 40, 200, 110)          # pixels in a 640x400 scene
SIGN_RGB = (236, 214, 92)
READABLE_FRACTION = 0.12
TASK = "What does the sign say? Answer with the exact text."

# Fixed plans (origin_type "fixture" when built directly; "model" when the scripted policy calls the tool).
PARALLEL_PLAN = {
    "objective": "Read the sign.",
    "actions": [
        {"id": "ocr_full", "tool": "OCR_Tool", "arguments": {"image_id": "input_image_1"}},
        {"id": "g", "tool": "Visual_Grounding_Tool", "arguments": {"image_id": "input_image_1", "query": "sign"}, "expect": "detections"},
        {"id": "z", "tool": "Zoom_In_Tool", "arguments": {"image_id": "input_image_1", "coords": "$g.boxes_normalized.0"}, "depends_on": ["g"]},
        {"id": "ocr_crop", "tool": "OCR_Tool", "arguments": {"image_id": "$z.image"}, "depends_on": ["z"], "expect": "text"},
    ],
    "rationale": "Read the full image and, in parallel, the zoomed sign.",
}
FALLBACK_PLAN = {
    "objective": "Read the sign.",
    "actions": [{"id": "ocr_full", "tool": "OCR_Tool", "arguments": {"image_id": "input_image_1"}, "expect": "text"}],
    "alternatives": [{"actions": [
        {"id": "g", "tool": "Visual_Grounding_Tool", "arguments": {"image_id": "input_image_1", "query": "sign"}, "expect": "detections"},
        {"id": "z", "tool": "Zoom_In_Tool", "arguments": {"image_id": "input_image_1", "coords": "$g.boxes_normalized.0"}, "depends_on": ["g"]},
        {"id": "ocr_crop", "tool": "OCR_Tool", "arguments": {"image_id": "$z.image"}, "depends_on": ["z"], "expect": "text"},
    ]}],
    "rationale": "Try OCR on the full image; if unreadable, zoom into the sign.",
}
PLANS = {"parallel": PARALLEL_PLAN, "fallback": FALLBACK_PLAN}


def create_sign_scene(path: Path, readable: bool = False) -> Path:
    """A dark scene with one small sign; ``readable=True`` makes the sign fill the frame."""
    size = (240, 120) if readable else (640, 400)
    image = Image.new("RGB", size, "#14211c")
    draw = ImageDraw.Draw(image)
    box = (10, 10, 230, 110) if readable else SIGN_BOX
    draw.rectangle(box, fill=SIGN_RGB, outline="white", width=2)
    draw.text((box[0] + 12, box[1] + 18), SIGN_TEXT, fill="#1b1b1b")
    draw.ellipse((420, 220, 470, 270), fill="#2b4a3f")  # a dim object the detector ignores
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


class FixtureOCRClient:
    """Declared OCR rule (see module docstring); records each call's interval."""

    def __init__(self, delay: float = 0.0, log: list | None = None) -> None:
        self.delay = delay
        self.log = log if log is not None else []

    def execute(self, tool_name, args, *, tool_call_id):
        began = time.monotonic()
        if self.delay:
            time.sleep(self.delay)
        data = args.get("image_base64") or ""
        image = Image.open(BytesIO(base64.b64decode(data.split(",", 1)[-1]))).convert("RGB")
        pixels = np.asarray(image, dtype=np.int32)
        sign = (np.abs(pixels - np.array(SIGN_RGB)).sum(axis=2) < 60).mean()
        text = SIGN_TEXT if sign >= READABLE_FRACTION else ""
        self.log.append({"call": tool_call_id, "tool": "ocr", "start": began, "end": time.monotonic(),
                         "size": image.size, "readable": bool(text)})
        return {"ok": True, "tool_name": tool_name, "tool_call_id": tool_call_id, "error": None, "meta": {},
                "result": {"text": text, "model_id": "fixture-ocr-rule"}}


class _Timed:
    """Wrap a fixture transport to record execution intervals."""

    def __init__(self, inner, name: str, log: list) -> None:
        self.inner, self.name, self.log = inner, name, log

    def execute(self, tool_name, args, *, tool_call_id):
        began = time.monotonic()
        result = self.inner.execute(tool_name, args, tool_call_id=tool_call_id)
        self.log.append({"call": tool_call_id, "tool": self.name, "start": began, "end": time.monotonic()})
        return result


_SIGN = re.compile(r"transcribed the following text from the image:\s*\n\n(.+)")


class PlanPolicy(ScriptedPolicy):
    """Worker: one Execute_Action_Plan call (or, in legacy mode, the same steps one call at a time)."""

    def __init__(self, actor_id: str, plan: str = "fallback", legacy: bool = False, delay: float = 0.0) -> None:
        super().__init__(actor_id, "standard", delay)
        self.plan, self.legacy = plan, legacy

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.actor_id == "coordinator":
            return super().__call__(payload)
        self.requests.append(payload)
        if self.delay:
            time.sleep(self.delay)
        messages = payload.get("messages") or []
        step = sum(len(m.get("tool_calls") or []) for m in messages if m.get("role") == "assistant")
        seen = "\n".join(_text_of(m.get("content")) for m in messages if m.get("role") == "user")
        found = _SIGN.findall(seen)
        if self.legacy:  # the original protocol: OCR the full image; if unreadable, ground, zoom, OCR the crop
            if found:
                return _answer(found[-1].strip())
            refs = re.findall(r"refer to (?:it )?as (tool_generated_image_\d+)", seen)
            boxes = re.findall(r'"bbox_2d": \[(\d+), (\d+), (\d+), (\d+)\]', seen)
            if step == 0:
                return _response("Read the sign.", ("OCR_Tool", {"image_id": "input_image_1"}), step)
            if step == 1:
                return _response("Locate the sign.", ("Visual_Grounding_Tool", {"image_id": "input_image_1", "query": "sign"}), step)
            if step == 2 and boxes:
                return _response("Zoom in.", ("Zoom_In_Tool", {"image_id": "input_image_1", "coords": [int(v) for v in boxes[0]]}), step)
            if step == 3 and refs:
                return _response("Read the crop.", ("OCR_Tool", {"image_id": refs[-1]}), step)
            return _answer("unreadable", "The sign could not be read.")
        if step == 0:
            return _response("Read the sign with a plan.", ("Execute_Action_Plan", PLANS[self.plan]), step)
        return _answer(found[-1].strip()) if found else _answer("unreadable", "The sign could not be read.")


class PlanAgentBuilder:
    """AgentFactory builder for the plan fixture; records tool intervals in ``self.log``."""

    def __init__(self, image_path: Path, *, plan: str = "fallback", legacy: bool = False, tool_delay: float = 0.0,
                 ocr_delay: float | None = None) -> None:
        self.image_path, self.plan, self.legacy = image_path, plan, legacy
        self.tool_delay = tool_delay
        self.ocr_delay = tool_delay if ocr_delay is None else ocr_delay
        self.log: list[dict[str, Any]] = []
        self.policies: dict[str, PlanPolicy] = {}

    def __call__(self, _config, actor_id, tool_access):
        policy = PlanPolicy(actor_id, self.plan, self.legacy)
        self.policies[actor_id] = policy
        from ..services.models import ModelAdapter

        adapter = ModelAdapter({"alias": "qwen3-vl-8b-instruct", "base": "http://fixture.invalid/v1", "max_tokens": 1024},
                               requester=policy)
        tools = {}
        if tool_access:
            tools["OCR_Tool"] = ocr.Capability(backend="ocr", client_config={}, client=FixtureOCRClient(self.ocr_delay, self.log))
            tools["Visual_Grounding_Tool"] = grounding.Capability(
                backend="sam3_segment", client_config={}, client=_Timed(PixelDetectorClient(self.tool_delay), "grounding", self.log))
            tools["Zoom_In_Tool"] = zoom.Capability(
                backend="zoom_in_image_by_bbox", client_config={}, client=_Timed(LocalZoomClient(self.tool_delay), "zoom", self.log))
        agent = MainAgent(adapter, tools, MemoryStore, FIXTURE_SYSTEM, "Question: {user_query}", max_iterations=8)
        if actor_id == "coordinator":
            from importlib.resources import files

            agent.system_prompt = files("openvlharness.prompts").joinpath("coordinator_system.txt").read_text()
        agent.studio_topology = {"model_client": {"kind": "fixture", "model_id": "scripted plan policy (Qwen chat protocol)"}}
        return agent

    def factory(self) -> AgentFactory:
        return AgentFactory(self)


def write_reference(reference_dir: Path, run_id: str) -> Path:
    import json

    reference_dir.mkdir(parents=True, exist_ok=True)
    path = reference_dir / f"{run_id}.json"
    path.write_text(json.dumps({"run_id": run_id, "answer": SIGN_TEXT, "source": "plan fixture scene (synthetic)"}))
    return path


def run_plan_fixture(output_dir: Path, *, policy: str = "e5", workers: int = 2, plan: str = "fallback",
                     legacy: bool | None = None, tool_delay: float = 0.3, run_id: str | None = None,
                     memory: bool = True, peer: bool = False, planning_processes: int = 2, rollouts: int = 400,
                     global_tool_calls: int | None = None, capacities: dict | None = None, mode: str = "concurrent",
                     reference: bool = False, planning: dict | None = None, plan_dispatch: str | None = None,
                     planning_config: dict | None = None, readable: bool = False, scheduler_workers: int | None = None):
    """One whole multi-agent run of the sign task (deterministic; no model)."""
    import json
    from datetime import UTC, datetime

    from ..multi_agent import MultiAgentOrchestrator
    from ..multi_agent.config import apply_run_options
    from ..multi_agent.testing import fixture_config

    output_dir.mkdir(parents=True, exist_ok=True)
    scene = create_sign_scene(output_dir / ("sign_scene_readable.png" if readable else "sign_scene.png"), readable=readable)
    legacy = policy in ("off", "e0", "e1", "e2") if legacy is None else legacy
    builder = PlanAgentBuilder(scene, plan=plan, legacy=legacy, tool_delay=tool_delay)
    config = fixture_config(output_dir, workers=workers, memory=memory, peer=peer, mode=mode, estimate_updates=False)
    config["workers"]["overrides"] = {}
    config["workers"]["default"]["tool_calls"] = 8
    if global_tool_calls is not None:
        config["budget"]["global_tool_calls"] = global_tool_calls
    config = apply_run_options(config, tool_scheduler=policy, planning_processes=planning_processes,
                               scheduler_workers=scheduler_workers)
    config["execution"]["planning"]["rollouts"] = rollouts
    config["execution"]["planning"].update(planning or {})
    config["execution"]["planning"].update(planning_config or {})
    if plan_dispatch:
        config["execution"]["scheduler"]["plan_dispatch"] = plan_dispatch
    if capacities:
        config["execution"]["scheduler"]["capacities"] = dict(capacities)
    run_id = run_id or f"plan_{policy}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}"
    orchestrator = MultiAgentOrchestrator(config, factory=builder.factory(), run_id=run_id)
    if reference:
        write_reference(output_dir / ".references", run_id)
    result = orchestrator.run(TASK, [{"type": "image", "value": str(scene)}, {"type": "text", "value": TASK}])
    events = [json.loads(line) for line in (orchestrator.run_dir / "events.jsonl").read_text().splitlines()]
    return orchestrator, builder, result, events
