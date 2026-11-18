"""Deterministic test fixtures for the multi-agent runtime and the Studio.

THIS MODULE IS FOR TESTS AND DEMONSTRATIONS ONLY. It never performs inference.

Each actor is a real :class:`~openvlharness.agent.agent.MainAgent` with a real
:class:`~openvlharness.services.models.ModelAdapter` (Qwen chat protocol,
answer-tag extraction, tool-call parsing, per-question ``MemoryStore``, budget
guard, and Studio event emission). Only two things are scripted:

* the model endpoint: a deterministic *policy* reads the exact request the
  agent sent (prompt, tool results, optional notebook text, peer claims) and
  returns a protocol-valid response; and
* the tools: deterministic visual tools operating on a synthetic image whose
  object count is fixed by construction.

Because decisions are computed from the request content, runtime policies have
real effects: with optional worker memory OFF the notebook text is absent from
follow-up prompts and the policy cannot re-locate an uncertain region; with
peer communication OFF no peer claims arrive. Nothing in this module reads a
benchmark label, and the construction count is exposed only through
:func:`write_fixture_reference`, which a test calls after a run has finished.
"""

from __future__ import annotations

import base64
import copy
import json
import os
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from ..agent.agent import MainAgent
from ..capabilities._base import failure
from ..contracts import ArtifactRef, CapabilityResult
from ..memory.store import MemoryStore
from ..services.models import ModelAdapter
from .actors import AgentFactory

SCENE_SIZE = (360, 220)
LARGE_OBJECTS = [(24, 40, 94, 110), (120, 30, 190, 100), (214, 52, 284, 122), (64, 128, 134, 198)]
SMALL_OBJECT = (300, 150, 330, 180)
UNCERTAIN_REGION = [290, 140, 340, 190]
# Count fixed by construction of the synthetic scene. Exposed to evaluators only.
_CONSTRUCTION_COUNT = len(LARGE_OBJECTS) + 1
FIXTURE_TASK = (
    "How many marked objects are in the image? Your final answer should be a single integer."
)
FIXTURE_SYSTEM = (
    "You are a visual investigator. Use tools when they resolve a specific evidence gap. "
    "Always place the final answer inside <answer> and </answer>."
)
_TOOL_PREFIX = "TOOL_RESULT "


def create_scene(path: Path) -> Path:
    """Synthetic scene: four clear objects and one small, faint object."""
    image = Image.new("RGB", SCENE_SIZE, "#16231f")
    draw = ImageDraw.Draw(image)
    colors = ["#6ee7a4", "#64b5f6", "#f1b95b", "#e889c4"]
    for box, color in zip(LARGE_OBJECTS, colors):
        draw.ellipse(box, fill=color, outline="white", width=3)
    draw.ellipse(SMALL_OBJECT, fill="#2f4a40", outline="#7c9a8f", width=1)
    draw.text((8, 4), "Deterministic test fixture (not a benchmark image)", fill="#c9d6d0")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def write_fixture_reference(reference_dir: Path, run_id: str) -> Path:
    """Evaluator-side reference for a finished fixture run (never agent-visible)."""
    reference_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = reference_dir / f"{run_id}.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "studio.reference.v1",
                "run_id": run_id,
                "dataset": "deterministic_fixture",
                "split": "test",
                "row": "synthetic_scene_v1",
                "answer_type": "integer_count",
                "reference": str(_CONSTRUCTION_COUNT),
                "reference_source": "Synthetic scene construction (test fixture label)",
                "normalization_rule": "fsc147_parse_count_exact_match",
                "note": "Deterministic test fixture; not a benchmark annotation.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)
    return path


# ---------------------------------------------------------------------------
# Deterministic tools


class _FixtureTool:
    backend = "deterministic_fixture"
    name = ""
    description = ""
    parameters: dict[str, Any] = {}

    def __init__(self, image_path: Path) -> None:
        self.image_path = image_path

    def public_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def _ok(self, call, data, *, result=None, image_ref=None, image_url=None):
        result = result if result is not None else data
        evidence = [{"type": "text", "text": _TOOL_PREFIX + self.name + " " + json.dumps(data)}]
        if image_url:
            evidence.append({"type": "image_url", "image_url": {"url": image_url}})
        return CapabilityResult(
            ok=True,
            data=data,
            evidence=evidence,
            artifact_refs=[ArtifactRef("image", image_ref)] if image_ref else [],
            prepared={"image_refs": [image_ref] if image_ref else []},
            processor_info={"status": "ok", "processor": "deterministic_fixture"},
            payload={
                "ok": True,
                "tool_name": call.name,
                "tool_call_id": call.call_id,
                "result": result,
                "error": None,
                "meta": {"backend": self.backend},
            },
        )


class FixtureGroundingTool(_FixtureTool):
    name = "Visual_Grounding_Tool"
    description = "Localize objects matching a text query (deterministic fixture)."
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    def invoke(self, call, memory):
        data = {
            "boxes": [list(box) for box in LARGE_OBJECTS],
            "scores": [0.97, 0.95, 0.96, 0.93],
            "count": len(LARGE_OBJECTS),
            "low_confidence_regions": [UNCERTAIN_REGION],
            "coordinate_system": "source_pixels",
            "orig_img_w": SCENE_SIZE[0],
            "orig_img_h": SCENE_SIZE[1],
        }
        return self._ok(call, data)


class FixtureZoomTool(_FixtureTool):
    name = "Zoom_In_Tool"
    description = "Crop and enlarge a source-pixel region (deterministic fixture)."
    parameters = {
        "type": "object",
        "properties": {
            "bbox": {"type": "array", "items": {"type": "number"}},
            "purpose": {"type": "string"},
        },
        "required": ["bbox"],
    }

    def invoke(self, call, memory):
        bbox = call.arguments.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            return failure(call, "invalid_arguments", "bbox must contain four numbers")
        x1, y1, x2, y2 = (int(v) for v in bbox)
        with Image.open(self.image_path) as source:
            crop = source.convert("RGB").crop((x1, y1, x2, y2)).resize(((x2 - x1) * 3, (y2 - y1) * 3))
        buffer = BytesIO()
        crop.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        data_url = f"data:image/png;base64,{encoded}"
        ref = memory.register_image(data_url, provenance=f"tool_output:{self.name}")
        sx1, sy1, sx2, sy2 = SMALL_OBJECT
        found = int(x1 <= sx1 and y1 <= sy1 and x2 >= sx2 and y2 >= sy2)
        data = {
            "crop_bounds": [x1, y1, x2, y2],
            "candidates_found": found,
            "candidate_boxes": [list(SMALL_OBJECT)] if found else [],
            "observation": (
                "The enlarged crop shows one small, faint marked object."
                if found
                else "The enlarged crop shows no additional marked object."
            ),
            "coordinate_system": "source_pixels",
            "orig_img_w": SCENE_SIZE[0],
            "orig_img_h": SCENE_SIZE[1],
            "image_ref": ref,
        }
        return self._ok(call, data, result={**data, "rendered_image_b64": encoded}, image_ref=ref, image_url=data_url)


class FixtureDepthTool(_FixtureTool):
    name = "Depth_Estimation_Tool"
    description = "Estimate relative depth (deterministic fixture; always unavailable)."
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}}

    def invoke(self, call, memory):
        return failure(call, "service_unavailable", "Fixture depth service is offline.")


# ---------------------------------------------------------------------------
# Scripted model policy


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return ""


def _observations(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ordered tool calls the agent made in this conversation, with outcomes."""
    calls: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                calls.append({"name": call["function"]["name"], "ok": None, "data": None})
        elif role == "tool" and calls:
            pending = [c for c in calls if c["ok"] is None]
            if pending:
                pending[0]["ok"] = message.get("content") == "ok"
                pending[0]["error_text"] = message.get("content")
        elif role == "user":
            text = _text_of(message.get("content"))
            if text.startswith(_TOOL_PREFIX):
                name, _, payload = text[len(_TOOL_PREFIX):].partition(" ")
                for call in reversed(calls):
                    if call["name"] == name and call["data"] is None:
                        try:
                            call["data"] = json.loads(payload)
                        except json.JSONDecodeError:
                            call["data"] = {}
                        break
    return calls


def _response(text: str, call: tuple[str, dict[str, Any]] | None = None, index: int = 0) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if call:
        name, arguments = call
        message["tool_calls"] = [
            {
                "id": f"call_{name.lower()}_{index}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ]
    return {
        "choices": [{"message": message}],
        "usage": {"prompt_tokens": 400 + 50 * index, "completion_tokens": 24, "total_tokens": 424 + 50 * index},
    }


def _answer(value: str, limitation: str | None = None) -> dict[str, Any]:
    text = f"<answer>{value}</answer>"
    if limitation:
        text += f"\n<limitations>{limitation}</limitations>"
    return _response(text)


_REGION = re.compile(r"low_confidence_regions\W+\[\[(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]\]")


class ScriptedPolicy:
    """Deterministic decisions computed from the actual request content."""

    PROFILES = ("grounding", "zoom_verifier", "failure_tolerant", "budget_limited")

    def __init__(self, actor_id: str, scenario: str = "standard", delay: float = 0.0) -> None:
        self.actor_id = actor_id
        self.scenario = scenario
        self.delay = delay
        self.requests: list[dict[str, Any]] = []
        self.reassessments = 0
        index = int(actor_id.split("_")[-1]) if actor_id.startswith("worker_") else 0
        self.profile = self.PROFILES[(index - 1) % len(self.PROFILES)] if index else "coordinator"

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(copy.deepcopy(payload))
        if self.delay:
            time.sleep(self.delay)  # paces live demonstrations only
        messages = payload.get("messages") or []
        text = "\n".join(_text_of(m.get("content")) for m in messages if m.get("role") == "user")
        if self.actor_id == "coordinator":
            return self._coordinator(text)
        return self._worker(text, _observations(messages))

    # ---- coordinator ---------------------------------------------------
    @staticmethod
    def _section(text: str, label: str) -> Any:
        match = re.search(re.escape(label) + r": (\[.*?\])\.?\n", text + "\n", re.DOTALL)
        if not match:
            return []
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return []

    def _judge(self, results: list[dict[str, Any]]) -> tuple[str | None, list[str]]:
        completed = [r for r in results if r.get("status") == "COMPLETED" and r.get("candidate_answer")]
        if not completed:
            return None, []
        verified = [r for r in completed if not r.get("uncertainty_or_limitations")]
        chosen = (verified or completed)[0]["candidate_answer"]
        uncertain = [r["agent_id"] for r in completed if r.get("uncertainty_or_limitations")]
        return str(chosen), uncertain

    def _coordinator(self, text: str) -> dict[str, Any]:
        if "Decompose the immutable original task" in text:
            workers = json.loads(re.search(r"Workers: (\[.*\])", text).group(1))
            scopes = {
                "grounding": "Count the marked objects with visual grounding.",
                "zoom_verifier": "Verify low-confidence regions with zoomed inspection.",
                "failure_tolerant": "Check depth cues, then count with grounding.",
                "budget_limited": "Make a quick count with at most one tool call.",
            }
            assignments = []
            for worker_id, _role in workers:
                profile = ScriptedPolicy(worker_id).profile
                assignments.append({"worker_id": worker_id, "scope": scopes[profile]})
            return _answer(json.dumps({"assignments": assignments}))
        results = self._section(text, "All worker results") or self._section(text, "Worker results")
        estimate, uncertain = self._judge(results)
        if "reassess the immutable original task" in text:
            self.reassessments += 1
            allowed = self._section(text, "using these worker IDs")
            if self.scenario == "withdrawal" and self.reassessments >= 2:
                return _answer(json.dumps({
                    "estimate": None, "status": "unresolved",
                    "summary": "The reports conflict and no value is currently supported.",
                    "reason": "New reports contradicted the earlier estimate.", "follow_up": []}))
            follow = [
                {"worker_id": worker_id,
                 "scope": f"Re-inspect the low-confidence region you flagged and confirm whether it contains a marked object."}
                for worker_id in uncertain[:1] if worker_id in allowed
            ]
            if estimate is None:
                return _answer(json.dumps({"estimate": None, "status": "unresolved",
                                           "summary": "No completed worker report supports an answer yet.",
                                           "reason": None, "follow_up": []}))
            return _answer(json.dumps({
                "estimate": estimate, "status": "provisional",
                "summary": f"Current reports best support {estimate} marked objects.",
                "reason": "Preferred the report without stated limitations." if uncertain else "Reports agree.",
                "follow_up": follow}))
        # synthesis
        return _answer(estimate if estimate is not None else "Unable to determine")

    # ---- workers -------------------------------------------------------
    def _worker(self, text: str, calls: list[dict[str, Any]]) -> dict[str, Any]:
        step = len(calls)
        phase = (
            "follow_up" if "assigned you a follow-up" in text
            else "peer_review" if "Review these peer claims" in text
            else "initial"
        )
        grounding = next((c["data"] for c in calls if c["name"] == "Visual_Grounding_Tool" and c["data"]), None)
        zoom = next((c["data"] for c in calls if c["name"] == "Zoom_In_Tool" and c["data"]), None)
        denied = any(c["ok"] is False and "budget" in str(c.get("error_text", "")).lower() for c in calls)
        if phase == "initial":
            return self._initial(step, calls, grounding, zoom, denied)
        prior = re.search(r"(?:prior candidate was|candidate \(public record\) was) '([^']*)'", text)
        prior_value = prior.group(1) if prior else "4"
        region = _REGION.search(text)
        if phase == "peer_review":
            peers = re.findall(r'\\"claim\\": \\"([^"\\]+)\\"', text) or re.findall(r'"claim": "([^"]+)"', text)
            if all(p == prior_value for p in peers):
                return _answer(prior_value)
            # The notebook (memory ON) may already hold this worker's own zoom check.
            if step == 0 and re.search(r"candidates_found\W+1", text):
                return _answer(prior_value)
        if zoom is not None:
            return _answer("5" if zoom.get("candidates_found") else prior_value)
        if denied:
            return _answer(prior_value, "Tool budget exhausted before the region could be re-verified.")
        if region:
            # From the notebook (memory ON) or from a fresh grounding call (memory OFF).
            return _response("Re-inspecting the low-confidence region.",
                             ("Zoom_In_Tool", {"bbox": [int(v) for v in region.groups()], "purpose": f"{phase} verification"}), step)
        if grounding is None:
            return _response("No notes identify the earlier region; localizing candidates again.",
                             ("Visual_Grounding_Tool", {"query": "marked objects"}), step)
        return _answer(prior_value, "Could not re-identify the uncertain region.")

    def _initial(self, step, calls, grounding, zoom, denied) -> dict[str, Any]:
        profile = self.profile
        if profile == "failure_tolerant" and step == 0:
            return _response("Checking depth cues first.", ("Depth_Estimation_Tool", {"query": "marked objects"}), step)
        if grounding is None and not denied:
            return _response("Localizing candidate objects.", ("Visual_Grounding_Tool", {"query": "marked objects"}), step)
        if grounding is None:
            return _answer("Unable to determine", "Tool budget exhausted before any evidence was gathered.")
        region = grounding.get("low_confidence_regions", [[]])[0]
        if profile in {"zoom_verifier", "budget_limited"} and zoom is None and not denied:
            return _response("Zooming into the low-confidence region.",
                             ("Zoom_In_Tool", {"bbox": region, "purpose": "verify low-confidence region"}), step)
        if zoom is not None:
            return _answer(str(grounding["count"] + zoom.get("candidates_found", 0)))
        count = str(grounding["count"])
        if denied:
            return _answer(count, f"Tool budget exhausted before verifying the low-confidence region {region}.")
        failed = [c["name"] for c in calls if c["ok"] is False]
        note = f"{', '.join(failed)} failed; " if failed else ""
        return _answer(count, f"{note}one low-confidence region {region} was not verified.")


class ScriptedAgentBuilder:
    """AgentFactory builder producing real MainAgents with scripted endpoints."""

    def __init__(self, image_path: Path, scenario: str = "standard", delay: float = 0.0) -> None:
        self.image_path = image_path
        self.scenario = scenario
        self.delay = delay
        self.policies: dict[str, ScriptedPolicy] = {}
        self.capabilities: dict[str, dict[str, Any]] = {}

    def __call__(self, _config: Any, actor_id: str, tool_access: bool) -> MainAgent:
        policy = ScriptedPolicy(actor_id, self.scenario, self.delay)
        self.policies[actor_id] = policy
        adapter = ModelAdapter(
            {"alias": "qwen3-vl-8b-instruct", "base": "http://fixture.invalid/v1", "max_tokens": 1024},
            requester=policy,
        )
        tools: dict[str, Any] = {}
        if tool_access:
            for cls in (FixtureGroundingTool, FixtureZoomTool, FixtureDepthTool):
                tools[cls.name] = cls(self.image_path)
        self.capabilities[actor_id] = tools
        agent = MainAgent(adapter, tools, MemoryStore, FIXTURE_SYSTEM, "Question: {user_query}", max_iterations=6)
        if actor_id == "coordinator":
            from importlib.resources import files

            agent.system_prompt = (
                files("openvlharness.prompts").joinpath("coordinator_system.txt").read_text()
            )
        # Honest topology: no physical model service exists for a scripted policy.
        agent.studio_topology = {
            "model_client": {"kind": "fixture", "model_id": "scripted fixture policy (Qwen chat protocol)"},
        }
        return agent

    def factory(self) -> AgentFactory:
        return AgentFactory(self)

    def all_requests_text(self) -> str:
        return json.dumps({k: p.requests for k, p in self.policies.items()}, default=str)


def fixture_config(
    output_dir: Path,
    *,
    workers: int,
    memory: bool,
    peer: bool,
    mode: str = "cooperative",
    estimate_updates: bool = True,
    max_reassessments: int = 3,
    follow_up_rounds: int = 1,
    global_tool_calls: int = 40,
) -> dict[str, Any]:
    from .config import load_multi_agent_config

    return load_multi_agent_config(
        {
            "multi_agent": {
                "num_agents": workers,
                "max_agents": 4,
                "execution": {"mode": mode, "max_concurrent_workers": 4,
                              "task_timeout_seconds": 120, "peer_review_rounds": 1},
                "coordinator": {
                    "agent_config": "fixture", "tool_access": False, "max_rounds": 2,
                    "model_requests": 2 + max_reassessments,
                    "estimate_updates": {"enabled": estimate_updates, "max_reassessments": max_reassessments},
                    "max_follow_up_rounds": follow_up_rounds,
                },
                "workers": {
                    "default": {"agent_config": "fixture", "role": "visual investigator",
                                "tool_calls": 4, "model_requests": 12},
                    "overrides": {"worker_04": {"tool_calls": 1}},
                },
                "communication": {"enabled": True, "peer_to_peer": peer,
                                  "max_messages_per_actor": 20, "max_inbox_per_actor": 40},
                "memory": {"optional_worker_memory": memory},
                "budget": {"global_tool_calls": global_tool_calls, "global_model_requests": 120,
                           "global_messages": 100},
                "output": {"directory": str(output_dir)},
            }
        }
    )
