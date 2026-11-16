"""Deterministic evidence rendering for the Phase 4C-1G counting probe.

Every branch receives the same system prompt, the same common header (question
and category definition) and footer (answer instructions), and the original
photograph as Image 1. Only the tool-result section, and Image 2 for branches
that contain the Zoom crop, differ. Tool results are rendered from stored
records only. Absent or failed observations are reported as such and are never
replaced by a successful-looking value.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from .semantic_observation_schema import (
    ACTION_NAME as SEMANTIC_ACTION,
)
from .semantic_observation_schema import (
    REQUIRED_FIELDS as SEMANTIC_FIELDS,
)
from .semantic_observation_schema import (
    canonical_sha256,
)
from .task_level_probe_protocol import (
    BRANCH_EVIDENCE,
    EVIDENCE_HEADER,
    SYSTEM_PROMPT,
    common_footer,
    common_header,
)

RENDERER_VERSION = "bite.task_level_branch_renderer.v1"
SCORE_DECIMALS = 3
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
RENDERER_CONTRACT = {
    "schema_version": RENDERER_VERSION,
    "image_1": "original source image bytes, unmodified, inline base64 data URL",
    "image_2": "stored Zoom crop artifact bytes, unmodified; only when the branch contains Zoom and the crop succeeded",
    "content_order": ["Image 1 caption", "Image 1", "[Image 2 caption", "Image 2]", "text"],
    "text_order": ["common header", "tool results", "common footer"],
    "tool_order_within_branch": ["initial grounding", "zoom crop", "focused grounding", "semantic inspection"],
    "boxes": "[x0, y0, x1, y1] pixel coordinates rounded to integers",
    "scores": f"rounded to {SCORE_DECIMALS} decimals",
    "proposal_names": "P<k> initial (detector rank k-1), Q<k> focused (detector rank k-1)",
    "masks": "omitted from text; their presence is stated",
    "semantic_fields": list(SEMANTIC_FIELDS),
    "semantic_raw_text_on_failure": "not shown; status only",
    "correctness_or_reference_information": "never rendered",
}
RENDERER_SHA256 = canonical_sha256(RENDERER_CONTRACT)


def renderer_contract():
    return {**RENDERER_CONTRACT, "renderer_sha256": RENDERER_SHA256}


def _box(box):
    return "[" + ", ".join(str(round(float(v))) for v in box) + "]"


def _score(value):
    return f"{float(value):.{SCORE_DECIMALS}f}"


def _proposal_lines(proposals, prefix, *, extra=None):
    lines = []
    for proposal in proposals:
        text = f"  {prefix}{proposal['rank'] + 1}: box {_box(proposal['box_xyxy'])}"
        if extra is not None:
            text += f" (Image 1: {_box(extra[proposal['rank']]['box_xyxy'])})"
        lines.append(text + f", score {_score(proposal['score'])}")
    return lines


def initial_block(task, number):
    grounding = task["initial_grounding"]
    arguments = {"image": "Image 1", "query": grounding["arguments"]["query"]}
    lines = [f"[Tool call {number}] Visual_Grounding_Tool (backend: {grounding['backend']})",
             f"Arguments: {json.dumps(arguments)}"]
    if not grounding["success"]:
        lines.append("Status: failed (no proposals were returned)")
        return "\n".join(lines)
    proposals = grounding["proposals"]
    lines.append("Status: success")
    lines.append(f"Returned {len(proposals)} proposal(s); boxes are in Image 1 pixel coordinates "
                 f"(Image 1 is {task['image_width']}x{task['image_height']}); segmentation masks were also "
                 "returned but are not shown:")
    lines.extend(_proposal_lines(proposals, "P"))
    return "\n".join(lines)


def zoom_blocks(task, number):
    zoom = task["zoom"]
    crop, focused = zoom["crop"], zoom["focused"]
    rank = task["initial_grounding"]["selected_detector_rank"]
    arguments = {"image": "Image 1", "coords": [round(float(v)) for v in crop["arguments"]["coords"]],
                 "padding": crop["arguments"].get("padding")}
    lines = [f"[Tool call {number}] Zoom_In_Tool (backend: {crop['backend']})",
             f"Arguments: {json.dumps(arguments)} (coords on a 0-1000 normalized scale; region of proposal P{rank + 1})"]
    has_image = bool(crop["success"] and crop["crop_image_path"])
    if has_image:
        x0, y0 = crop["crop_rectangle_root_xyxy"][:2]
        lines += ["Status: success",
                  (f"Returned Image 2: the region {_box(crop['crop_rectangle_root_xyxy'])} of Image 1 "
                   f"({crop['crop_width']}x{crop['crop_height']} pixels, not resized). "
                   f"Image 1 pixel = Image 2 pixel + ({x0}, {y0}).")]
    else:
        lines.append(f"Status: failed ({crop.get('outcome_category') or 'no crop returned'}); no Image 2")
    focus = [f"[Tool call {number + 1}] Visual_Grounding_Tool (backend: {focused['backend']})"]
    if not has_image:
        focus.append("Not executed: its input image (Image 2) does not exist")
    else:
        focus.append(f"Arguments: {json.dumps({'image': 'Image 2', 'query': focused['arguments']['query']})}")
        if not focused["success"]:
            focus.append(f"Status: failed ({focused.get('outcome_category') or 'no result'})")
        else:
            proposals = focused["proposals_crop_frame"]
            focus.append("Status: success")
            focus.append(f"Returned {len(proposals)} proposal(s); boxes are in Image 2 pixel coordinates, "
                         "converted to Image 1 coordinates in parentheses; masks not shown:")
            focus.extend(_proposal_lines(proposals, "Q", extra=focused["proposals_root_frame"]))
    return "\n".join(lines) + "\n\n" + "\n".join(focus), has_image


def validate_semantic_observation(task, observation):
    """Lineage check binding one stored semantic observation to its task."""
    if observation is None:
        raise ValueError("Semantic observation is absent; the branch cannot be constructed")
    lineage = observation["lineage"]
    checks = {
        "action": observation.get("action_name") == SEMANTIC_ACTION,
        "case": observation.get("case_id") == task["semantic_case_id"],
        "state": observation.get("state_id") == task["state_id"],
        "candidate": lineage["original_candidate_id"] == task["initial_grounding"]["selected_candidate_id"],
        "image": lineage["source_image_sha256"] == task["source_image_sha256"],
        "render": lineage["region_render"]["render_sha256"] == task["semantic_region_render_sha256"],
        "labels_not_accessed": observation.get("offline_labels_accessed") is False,
    }
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise ValueError(f"Semantic observation lineage mismatch for {task['state_id']}: {failed}")
    return observation


def semantic_block(task, observation, number):
    rank = task["initial_grounding"]["selected_detector_rank"]
    box = task["initial_grounding"]["selected_candidate_box_root_xyxy"]
    lines = [(f"[Tool call {number}] {SEMANTIC_ACTION} (backend: {observation['backend']['model_id']}, "
              "separate visual-inspection prompt)"),
             f"Arguments: {json.dumps({'image': 'Image 1', 'region': f'proposal P{rank + 1} {_box(box)}'})}"]
    status = observation["response_status"]
    if status == "valid" and observation.get("parsed_observation"):
        parsed = observation["parsed_observation"]
        lines.append("Status: success")
        lines.append("Returned: " + json.dumps({field: parsed[field] for field in SEMANTIC_FIELDS}))
    else:
        lines.append(f"Status: failed ({status}); no valid structured output was returned")
    return "\n".join(lines)


def _image_part(path):
    data = Path(path).read_bytes()
    mime = MIME[Path(path).suffix.lower()]
    return ({"type": "image_url", "image_url": {"url": f"data:{mime};base64," + base64.b64encode(data).decode()}},
            hashlib.sha256(data).hexdigest())


def render_branch(task, branch, *, root, semantic_observation=None):
    """Return ``(messages, record)`` for one task and branch."""
    components = BRANCH_EVIDENCE[branch]
    root = Path(root)
    blocks = [initial_block(task, 1)]
    number = 2
    has_crop = False
    if "zoom" in components:
        text, has_crop = zoom_blocks(task, number)
        blocks.append(text)
        number += 2
    semantic_digest = None
    if "semantic" in components:
        observation = validate_semantic_observation(task, semantic_observation)
        blocks.append(semantic_block(task, observation, number))
        semantic_digest = canonical_sha256(observation)
        number += 1
    header, footer = common_header(task["query"]), common_footer(task["query"])
    evidence = EVIDENCE_HEADER + "\n\n" + "\n\n".join(blocks)
    text = header + "\n\n" + evidence + "\n\n" + footer
    image_1, image_1_sha = _image_part(root / task["source_image_path"])
    if image_1_sha != task["source_image_sha256"]:
        raise ValueError("Source image digest mismatch")
    content = [{"type": "text", "text": "Image 1 (full original photograph):"}, image_1]
    image_shas = [image_1_sha]
    if has_crop:
        image_2, image_2_sha = _image_part(root / task["zoom"]["crop"]["crop_image_path"])
        if image_2_sha != task["zoom"]["crop"]["crop_image_sha256"]:
            raise ValueError("Zoom crop digest mismatch")
        content += [{"type": "text", "text": "Image 2 (returned by Zoom_In_Tool, tool call 2):"}, image_2]
        image_shas.append(image_2_sha)
    content.append({"type": "text", "text": text})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]
    record = {
        "schema_version": RENDERER_VERSION,
        "renderer_sha256": RENDERER_SHA256,
        "task_id": task["task_id"],
        "branch": branch,
        "evidence_components": list(components),
        "tool_calls_rendered": number - 1,
        "common_header_sha256": hashlib.sha256(header.encode()).hexdigest(),
        "common_footer_sha256": hashlib.sha256(footer.encode()).hexdigest(),
        "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "evidence_text": evidence,
        "evidence_characters": len(evidence),
        "user_text_characters": len(text),
        "image_sha256": image_shas,
        "image_count": len(image_shas),
        "semantic_observation_sha256": semantic_digest,
        "reference_count_rendered": False,
    }
    record["messages_sha256"] = canonical_sha256(_digest_messages(messages))
    return messages, record


def _digest_messages(messages):
    """Messages with inline images replaced by their byte digests."""
    def redact(value):
        if isinstance(value, dict):
            if value.get("type") == "image_url":
                encoded = value["image_url"]["url"].split(",", 1)[1]
                return {"type": "image_url", "image_sha256": hashlib.sha256(base64.b64decode(encoded)).hexdigest()}
            return {key: redact(child) for key, child in value.items()}
        if isinstance(value, list):
            return [redact(child) for child in value]
        return value
    return redact(messages)


redacted_messages = _digest_messages
