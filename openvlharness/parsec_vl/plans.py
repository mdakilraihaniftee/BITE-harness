"""Validated action plans: independent actions, dependencies, and alternative branches.

An ``ActionPlan`` is what one investigation decision authorizes. It has one
*primary* branch and optional *alternative* branches. Inside a branch, actions
form a DAG through explicit ``depends_on``; an action may take values from a
completed ancestor through a binding string ``"$<action_id>.<path>"`` such as
``"$a2.boxes_normalized.0"`` (a grounding box) or ``"$a3.image"`` (a crop's
registry ID). Bindings are only legal for ancestors listed in ``depends_on``.

Alternatives are mutually exclusive ways to reach the same *operational goal*
(for example "a readable OCR result"): an alternative is needed only when the
primary branch's goal action is not satisfied. Executing an alternative before
that is known is speculation (``controller.py``).

Every plan records where it came from (``origin_type``):

* ``model``                — a worker's own ``Execute_Action_Plan`` call (real or scripted policy);
* ``coordinator``          — reserved: the coordinator has no tool access in this runtime;
* ``controller_heuristic`` — alternatives added by a declared rule (``heuristic_alternatives``)
  that sees only the plan and the current memory, never results;
* ``fixture``              — a deterministic scripted plan in a benchmark.

Actions use the existing tool schemas: the same public tool names and argument
names the model already sees. Validation reuses each capability's JSON schema.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .dag import GraphError, Task, validate_graph

PLAN_TOOL = "Execute_Action_Plan"
ORIGINS = ("model", "coordinator", "controller_heuristic", "fixture")
GOALS = {"text": "a non-empty OCR transcription", "detections": "at least one detection",
         "image": "an output image", "ok": "a successful result"}
# Tools whose calls only read their inputs and produce new evidence: safe to run
# speculatively and to discard. Coding executes generated code over memory bindings;
# web/search tools contact third parties. Neither is ever speculated.
SPECULATION_SAFE = {"OCR_Tool", "Visual_Grounding_Tool", "Zoom_In_Tool", "Depth_Estimation_Tool", "Camera_Trajectory_Tool"}
# Values a later action may bind from an earlier one, by producing tool.
BINDABLE = {
    "Visual_Grounding_Tool": re.compile(r"^(boxes_normalized\.\d+|rendered_image)$"),
    "Zoom_In_Tool": re.compile(r"^image$"),
    "Depth_Estimation_Tool": re.compile(r"^(depth_image|image)$"),
    "OCR_Tool": re.compile(r"^text$"),
}
BINDING = re.compile(r"^\$([A-Za-z][\w-]{0,31})\.([\w.]+)$")
_ids = itertools.count(1)


@dataclass(frozen=True)
class PlanAction:
    action_id: str
    tool: str
    arguments: Mapping[str, Any]
    depends_on: tuple[str, ...] = ()
    expect: str | None = None  # operational goal check for this action's result

    def bindings(self) -> list[tuple[str, str, str]]:
        """(argument, producer action, path) for every binding argument."""
        found = []
        for key, value in self.arguments.items():
            match = BINDING.match(value) if isinstance(value, str) else None
            if match:
                found.append((key, match.group(1), match.group(2)))
        return found

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.action_id, "tool": self.tool, "arguments": dict(self.arguments),
                "depends_on": list(self.depends_on), "expect": self.expect}


@dataclass
class Branch:
    branch_id: str                 # run-scoped: <plan_id>.<name>
    name: str                      # "primary", "alt1", ...
    actions: list[PlanAction]
    goal: str | None = None        # action whose result decides whether the branch succeeded
    origin_type: str = "model"
    status: str = "planned"        # planned | running | speculative | satisfied | unsatisfied | adopted | pruned
    pruning_reason: str | None = None

    @property
    def speculation_safe(self) -> bool:
        return all(a.tool in SPECULATION_SAFE for a in self.actions)

    def to_dict(self) -> dict[str, Any]:
        return {"branch_id": self.branch_id, "name": self.name, "goal": self.goal, "origin_type": self.origin_type,
                "status": self.status, "pruning_reason": self.pruning_reason,
                "speculation_safe": self.speculation_safe, "actions": [a.to_dict() for a in self.actions]}


@dataclass
class ActionPlan:
    plan_id: str
    origin_agent_id: str
    origin_type: str
    branches: list[Branch]
    objective: str = ""
    rationale: str = ""            # short public rationale supplied with the plan, if any
    parent_plan_id: str | None = None
    input_artifact_refs: tuple[str, ...] = ()
    estimates: dict[str, Any] = field(default_factory=dict)
    status: str = "proposed"       # proposed | valid | rejected | executing | done

    @property
    def primary(self) -> Branch:
        return self.branches[0]

    @property
    def alternatives(self) -> list[Branch]:
        return self.branches[1:]

    def actions(self) -> Iterable[tuple[Branch, PlanAction]]:
        for branch in self.branches:
            for action in branch.actions:
                yield branch, action

    def to_dict(self) -> dict[str, Any]:
        return {"plan_id": self.plan_id, "origin_agent_id": self.origin_agent_id, "origin_type": self.origin_type,
                "parent_plan_id": self.parent_plan_id, "objective": self.objective, "rationale": self.rationale,
                "input_artifact_refs": list(self.input_artifact_refs), "status": self.status,
                "estimates": self.estimates, "branches": [b.to_dict() for b in self.branches]}


class PlanError(ValueError):
    """A plan failed validation; ``reason`` is a short machine-readable code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class PlanLimits:
    max_plan_depth: int = 3          # longest dependency chain inside a branch
    max_candidate_plans: int = 6     # branches per plan (primary + alternatives)
    max_actions: int = 8             # actions per plan
    beam_width: int = 4              # alternatives the evaluator compares


def new_plan_id(run_id: str, agent_id: str) -> str:
    return f"{run_id or 'run'}.{agent_id or 'agent'}.plan{next(_ids):04d}"


def parse_plan(arguments: Mapping[str, Any], *, run_id: str, agent_id: str, origin_type: str,
               parent_plan_id: str | None = None) -> ActionPlan:
    """Build a plan from the ``Execute_Action_Plan`` arguments (structure only; see ``validate_plan``)."""
    if origin_type not in ORIGINS:
        raise PlanError("bad_origin", f"unknown plan origin {origin_type!r}")
    if not isinstance(arguments, Mapping):
        raise PlanError("malformed", "plan arguments must be an object")
    plan_id = new_plan_id(run_id, agent_id)

    def actions_of(raw: Any, where: str) -> list[PlanAction]:
        if not isinstance(raw, list) or not raw:
            raise PlanError("empty", f"{where} must list at least one action")
        result = []
        for item in raw:
            if not isinstance(item, Mapping) or not isinstance(item.get("id"), str) or not isinstance(item.get("tool"), str):
                raise PlanError("malformed", f"every action in {where} needs a string id and tool")
            arguments_ = item.get("arguments", {})
            depends = item.get("depends_on", [])
            if not isinstance(arguments_, Mapping) or not isinstance(depends, list) or not all(isinstance(d, str) for d in depends):
                raise PlanError("malformed", f"action {item['id']}: arguments must be an object and depends_on a list of ids")
            expect = item.get("expect")
            if expect is not None and expect not in GOALS:
                raise PlanError("malformed", f"action {item['id']}: expect must be one of {sorted(GOALS)}")
            # A "$<id>.<value>" argument is an explicit data dependency on <id>; add it to depends_on
            # if the model left it out (recorded below), rather than rejecting an unambiguous plan.
            refs = [m.group(1) for m in (BINDING.match(v) for v in arguments_.values() if isinstance(v, str)) if m]
            missing = [r for r in refs if r not in depends]
            if missing:
                inferred.append({"action": item["id"], "depends_on": missing})
            result.append(PlanAction(item["id"], item["tool"], dict(arguments_), tuple(dict.fromkeys([*depends, *refs])), expect))
        return result

    inferred: list[dict[str, Any]] = []

    primary = Branch(f"{plan_id}.primary", "primary", actions_of(arguments.get("actions"), "actions"),
                     arguments.get("goal"), origin_type)
    branches = [primary]
    alternatives = arguments.get("alternatives") or []
    if not isinstance(alternatives, list):
        raise PlanError("malformed", "alternatives must be a list")
    for index, alt in enumerate(alternatives, start=1):
        if not isinstance(alt, Mapping):
            raise PlanError("malformed", "each alternative must be an object")
        branches.append(Branch(f"{plan_id}.alt{index}", f"alt{index}", actions_of(alt.get("actions"), f"alternative {index}"),
                               alt.get("goal"), origin_type))
    plan = ActionPlan(plan_id, agent_id, origin_type, branches, str(arguments.get("objective") or "")[:300],
                      str(arguments.get("rationale") or "")[:300], parent_plan_id)
    if inferred:
        plan.estimates["inferred_dependencies"] = inferred
    return plan


def _placeholder(schema: Mapping[str, Any]) -> Any:
    kind = schema.get("type")
    return {"string": "input_image_1", "array": [0, 0, 1000, 1000], "number": 0, "integer": 0,
            "boolean": False, "object": {}}.get(kind, "x")


def _depth(actions: list[PlanAction]) -> int:
    by_id = {a.action_id: a for a in actions}
    memo: dict[str, int] = {}

    def depth(aid: str) -> int:
        if aid not in memo:
            memo[aid] = 1 + max((depth(d) for d in by_id[aid].depends_on if d in by_id), default=0)
        return memo[aid]
    return max((depth(a.action_id) for a in actions), default=0)


def validate_plan(plan: ActionPlan, capabilities: Mapping[str, Any], available_images: set[str] | None,
                  limits: PlanLimits = PlanLimits()) -> ActionPlan:
    """Check tools, arguments, inputs, geometry, dependencies, bindings, and limits.

    ``available_images`` are the registry IDs/aliases in the agent's memory at
    the decision point; literal image references must name one of them (no
    images from other runs, no outputs that do not exist yet). Raises PlanError.
    """
    if len(plan.branches) > limits.max_candidate_plans:
        raise PlanError("too_many_branches", f"at most {limits.max_candidate_plans} branches per plan")
    total = sum(len(b.actions) for b in plan.branches)
    if total > limits.max_actions:
        raise PlanError("too_many_actions", f"at most {limits.max_actions} actions per plan")
    seen: set[str] = set()
    refs: set[str] = set()
    for branch in plan.branches:
        ids = [a.action_id for a in branch.actions]
        if len(set(ids)) != len(ids) or seen & set(ids):
            raise PlanError("duplicate_id", f"action ids must be unique across the plan ({branch.name})")
        seen |= set(ids)
        by_id = {a.action_id: a for a in branch.actions}
        for action in branch.actions:
            if action.tool == PLAN_TOOL:
                raise PlanError("nested_plan", "a plan cannot contain another plan")
            capability = capabilities.get(action.tool)
            if capability is None:
                raise PlanError("unknown_tool", f"action {action.action_id}: unknown tool {action.tool}")
            if not getattr(capability, "parallel_safe", False) or not hasattr(capability, "prepare"):
                raise PlanError("unsupported_tool", f"action {action.action_id}: {action.tool} cannot run inside a plan")
            for dep in action.depends_on:
                if dep not in by_id:
                    raise PlanError("unknown_dependency", f"action {action.action_id} depends on {dep}, not in its branch")
            properties = capability.schema["function"]["parameters"].get("properties", {})
            unknown = set(action.arguments) - set(properties)
            if unknown:
                raise PlanError("bad_arguments", f"action {action.action_id}: unsupported arguments {sorted(unknown)}")
            concrete = dict(action.arguments)
            for key, producer, path in action.bindings():
                if producer not in action.depends_on:
                    raise PlanError("unbound_reference", f"action {action.action_id}: ${producer} must be listed in depends_on")
                pattern = BINDABLE.get(by_id[producer].tool)
                if pattern is None or not pattern.match(path):
                    raise PlanError("bad_binding", f"action {action.action_id}: {by_id[producer].tool} has no value {path!r}")
                concrete[key] = _placeholder(properties.get(key, {}))
            errors = sorted(capability.validator.iter_errors(concrete), key=lambda e: str(e.path))
            if errors:
                raise PlanError("bad_arguments", f"action {action.action_id}: {errors[0].message}")
            for key, value in action.arguments.items():
                if key in ("image_id",) and isinstance(value, str) and not value.startswith("$"):
                    if available_images is not None and value not in available_images:
                        raise PlanError("missing_input", f"action {action.action_id}: image {value} is not in this agent's memory")
                    refs.add(value)
                if key == "image_ids" and isinstance(value, list):
                    for item in value:
                        if available_images is not None and item not in available_images:
                            raise PlanError("missing_input", f"action {action.action_id}: image {item} is not in this agent's memory")
                        refs.add(item)
                if key in ("coords", "bbox") and isinstance(value, list):
                    if len(value) != 4 or not all(isinstance(v, (int, float)) and 0 <= v <= 1000 for v in value) \
                            or not (value[0] < value[2] and value[1] < value[3]):
                        raise PlanError("bad_geometry", f"action {action.action_id}: {key} must be x1<x2, y1<y2 within 0..1000")
        try:  # cycles and dependency order, with the scheduler's own DAG validator
            validate_graph([Task(task_id=a.action_id, operation=a.tool, dependency_ids=a.depends_on) for a in branch.actions])
        except GraphError as exc:
            raise PlanError("cycle", f"{branch.name}: {exc}") from exc
        if _depth(branch.actions) > limits.max_plan_depth:
            raise PlanError("too_deep", f"{branch.name}: dependency chains longer than {limits.max_plan_depth}")
        if branch.goal is None:
            goals = [a.action_id for a in branch.actions if a.expect]
            branch.goal = goals[-1] if goals else branch.actions[-1].action_id
        elif branch.goal not in by_id:
            raise PlanError("bad_goal", f"{branch.name}: goal {branch.goal} is not one of its actions")
    plan.input_artifact_refs = tuple(sorted(refs))
    plan.status = "valid"
    return plan


def heuristic_alternatives(plan: ActionPlan, capabilities: Mapping[str, Any]) -> list[Branch]:
    """Declared controller rule: an unreadable OCR may succeed on a zoomed text region.

    For a primary goal ``OCR_Tool(image)`` with no alternatives, add
    ``Visual_Grounding_Tool(image, "text") -> Zoom_In_Tool(box 0) -> OCR_Tool(crop)``.
    It uses only the plan itself, never any result, and is recorded as
    ``controller_heuristic``.
    """
    if plan.alternatives or not {"OCR_Tool", "Visual_Grounding_Tool", "Zoom_In_Tool"} <= set(capabilities):
        return []
    goal = next((a for a in plan.primary.actions if a.action_id == plan.primary.goal), None)
    if goal is None or goal.tool != "OCR_Tool" or str(goal.arguments.get("image_id", "")).startswith("$"):
        return []
    image = goal.arguments.get("image_id", "input_image_1")
    actions = [
        PlanAction("h_ground", "Visual_Grounding_Tool", {"image_id": image, "query": "text"}, (), "detections"),
        PlanAction("h_zoom", "Zoom_In_Tool", {"image_id": image, "coords": "$h_ground.boxes_normalized.0"}, ("h_ground",), "image"),
        PlanAction("h_ocr", "OCR_Tool", {"image_id": "$h_zoom.image"}, ("h_zoom",), "text"),
    ]
    return [Branch(f"{plan.plan_id}.h1", "h1", actions, "h_ocr", "controller_heuristic")]


PLAN_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": PLAN_TOOL,
        "description": (
            "Run several tool actions as one plan. Independent actions run in parallel; an action can use an "
            "earlier action's output by listing it in depends_on and writing \"$<id>.<value>\" as an argument "
            "(\"$g.boxes_normalized.0\" = first grounding box, \"$z.image\" = a Zoom crop). Optionally give "
            "alternatives: other ways to reach the same goal, used if the main actions do not achieve it. "
            "Supported tools: OCR_Tool, Visual_Grounding_Tool, Zoom_In_Tool, Depth_Estimation_Tool. "
            "Each action is charged like a normal tool call."),
        "parameters": {
            "type": "object",
            "properties": {
                "objective": {"type": "string", "description": "What this plan should find out (one sentence)."},
                "actions": {"type": "array", "description": "Main actions.", "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "tool": {"type": "string"},
                        "arguments": {"type": "object"},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                        "expect": {"type": "string", "enum": sorted(GOALS)},
                    },
                    "required": ["id", "tool", "arguments"],
                }},
                "alternatives": {"type": "array", "description": "Optional fallback action lists for the same goal.",
                                 "items": {"type": "object", "properties": {"actions": {"type": "array"}}}},
                "rationale": {"type": "string", "description": "Short public reason (one sentence)."},
            },
            "required": ["actions"],
        },
    },
}


# ---- Phase 3: simpler model-facing schema -------------------------------------------------------
# Flat steps instead of a nested "arguments" object, short references ("$g.box", "$z.image"),
# and a single optional fallback list. Translated deterministically into the canonical plan
# above; validation and execution are unchanged.

SIMPLE_TOOLS = ["OCR_Tool", "Visual_Grounding_Tool", "Zoom_In_Tool", "Depth_Estimation_Tool"]
_SIMPLE_STEP = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Short name, e.g. g1."},
        "tool": {"type": "string", "enum": SIMPLE_TOOLS},
        "image_id": {"type": "string", "description": "input_image_1, or \"$<id>.image\" for a Zoom crop made by an earlier step."},
        "query": {"type": "string", "description": "What to find (Visual_Grounding_Tool only)."},
        "coords": {"description": "Zoom box [x1, y1, x2, y2] on a 0-1000 scale, or \"$<id>.box\" for the first box an earlier grounding step found."},
        "after": {"type": "array", "items": {"type": "string"}, "description": "Ids of steps whose output this step uses."},
    },
    "required": ["id", "tool"],
}
SIMPLE_PLAN_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": PLAN_TOOL,
        "description": (
            "Run several tool steps in one call. Steps without \"after\" run at the same time. A step that needs an "
            "earlier result lists it in \"after\" and refers to it as \"$<id>.box\" (first box found by grounding) or "
            "\"$<id>.image\" (a Zoom crop). Optional \"fallback\" steps run only if the last step does not give a result. "
            "Use a single normal tool call instead when there is only one useful next step."),
        "parameters": {
            "type": "object",
            "properties": {
                "steps": {"type": "array", "items": _SIMPLE_STEP, "description": "Steps to run."},
                "fallback": {"type": "array", "items": _SIMPLE_STEP, "description": "Optional other way to get the same result."},
            },
            "required": ["steps"],
        },
    },
}


def _expand_reference(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("$") and value.endswith(".box"):
        return value[: -len(".box")] + ".boxes_normalized.0"
    return value


def normalize_simple_plan(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Translate the simple schema into the canonical plan arguments (no validation here)."""
    if not isinstance(arguments, Mapping) or "steps" not in arguments:
        return dict(arguments) if isinstance(arguments, Mapping) else {}

    def convert(steps: Any) -> list:
        if not isinstance(steps, list):
            return steps
        result = []
        for step in steps:
            if not isinstance(step, Mapping):
                result.append(step)
                continue
            args = {k: _expand_reference(step[k]) for k in ("image_id", "query", "coords") if k in step}
            refs = [v[1:].split(".", 1)[0] for v in args.values() if isinstance(v, str) and v.startswith("$")]
            after = step.get("after") or []
            depends = list(dict.fromkeys([*(after if isinstance(after, list) else []), *refs]))
            tool = step.get("tool")
            result.append({"id": step.get("id"), "tool": tool, "arguments": args, "depends_on": depends,
                           "expect": {"OCR_Tool": "text", "Visual_Grounding_Tool": "detections"}.get(tool)})
        return result

    canonical = {"actions": convert(arguments.get("steps"))}
    if arguments.get("fallback"):
        canonical["alternatives"] = [{"actions": convert(arguments.get("fallback"))}]
    return canonical
