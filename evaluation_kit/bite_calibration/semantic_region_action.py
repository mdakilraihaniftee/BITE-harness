"""Offline ``semantic_region_inspect_v1`` action: neutral rendering, one frozen VLM
request through the existing ``ModelAdapter``, and a lineage-complete record.

This module never constructs a live client itself. Callers inject an adapter;
tests and dry runs inject one whose ``requester`` is a local function. Production
agent capabilities and the tool registry are untouched.
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
import time
from pathlib import Path

import PIL
from PIL import Image, ImageDraw

from openvlharness.services.models import ModelAdapter, load_profile

from .semantic_observation_schema import (
    ACTION_NAME,
    OBSERVATION_SCHEMA_VERSION,
    ONTOLOGY_SHA256,
    ONTOLOGY_VERSION,
    PROMPT_SHA256,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    USER_PROMPT,
    canonical_sha256,
    consistency_flags,
    parse_response,
)

RENDER_VERSION = "bite.semantic_region_render.v1"
OUTLINE_RGB = (255, 0, 255)
OUTLINE_FRACTION = 0.004
MINIMUM_OUTLINE_PIXELS = 2
CONTEXT_MARGIN_FRACTION = 0.5
MINIMUM_CONTEXT_MARGIN_PIXELS = 32
MAXIMUM_IMAGE_EDGE = 1024
LOGICAL_ACTION_COST = 1
MODEL_ALIAS = "qwen3-vl-8b-instruct"
INFERENCE_OPTIONS = {"max_tokens": 256, "temperature": 0.0}
INFERENCE_SEED = 0

# Whitelist of case fields an execution may receive; nothing GT-derived and no
# detector score is admitted.
CASE_FIELDS = frozenset({
    "case_id", "state_id", "source_group_id", "source_entry_id", "partition", "query",
    "source_image_sha256", "source_image_path", "image_width", "image_height",
    "original_candidate_id", "candidate_bbox_root_xyxy", "initial_observation_id",
    "initial_controlled_call_id", "initial_action_id", "parent_snapshot_id",
    "region_render_sha256",
})


def build_adapter(base, *, key="", timeout=120, requester=None):
    """Existing ModelAdapter pinned to the frozen alias with transport retries off,
    so one logical dispatch is exactly one physical request."""
    return ModelAdapter(
        {"alias": MODEL_ALIAS, "base": base, "key": key, "timeout": timeout, "retry": 0,
         **INFERENCE_OPTIONS},
        requester=requester,
    )


def validate_case(case):
    unexpected = set(case) - CASE_FIELDS
    if unexpected:
        raise ValueError(f"Case carries fields outside the runtime whitelist: {sorted(unexpected)}")
    missing = CASE_FIELDS - {"region_render_sha256"} - set(case)
    if missing:
        raise ValueError(f"Case is missing required fields: {sorted(missing)}")
    if case["partition"] != "calibration_fit":
        raise ValueError("Semantic pilot cases must come from the calibration-fit partition")
    box = case["candidate_bbox_root_xyxy"]
    if len(box) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box):
        raise ValueError("Candidate box must be four finite coordinates")
    return case


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=6)
    return buffer.getvalue()


def _clipped_box(box, width, height):
    x0, y0, x1, y1 = (float(value) for value in box)
    x0, x1 = max(0.0, min(x0, width)), max(0.0, min(x1, width))
    y0, y1 = max(0.0, min(y0, height)), max(0.0, min(y1, height))
    if x1 - x0 < 1 or y1 - y0 < 1:
        raise ValueError("Candidate box has no visible area inside the image")
    return x0, y0, x1, y1


def render_region(image_path, box, *, expected_sha256=None):
    """Return deterministic full-frame and context-crop PNGs with a neutral outline.

    The outline is drawn just outside the candidate box so that no box pixel is
    covered. The context crop adds a margin of half the larger box side (at least
    32 px) and never upsamples. Images larger than 1024 px are downsampled.
    """
    raw = Path(image_path).read_bytes()
    if expected_sha256 is not None and _sha256(raw) != expected_sha256:
        raise ValueError("Source image digest does not match the frozen identity")
    with Image.open(io.BytesIO(raw)) as opened:
        image = opened.convert("RGB")
    width, height = image.size
    x0, y0, x1, y1 = _clipped_box(box, width, height)
    stroke = max(MINIMUM_OUTLINE_PIXELS, round(OUTLINE_FRACTION * max(width, height)))
    outlined = image.copy()
    ImageDraw.Draw(outlined).rectangle(
        [math.floor(x0) - stroke, math.floor(y0) - stroke,
         math.ceil(x1) + stroke - 1, math.ceil(y1) + stroke - 1],
        outline=OUTLINE_RGB, width=stroke,
    )
    margin = max(MINIMUM_CONTEXT_MARGIN_PIXELS, CONTEXT_MARGIN_FRACTION * max(x1 - x0, y1 - y0))
    crop_box = (
        max(0, math.floor(x0 - margin)), max(0, math.floor(y0 - margin)),
        min(width, math.ceil(x1 + margin)), min(height, math.ceil(y1 + margin)),
    )
    crop = outlined.crop(crop_box)
    images = {}
    for name, rendered in (("full_frame_with_outline", outlined), ("context_crop_with_outline", crop)):
        scale = min(1.0, MAXIMUM_IMAGE_EDGE / max(rendered.size))
        if scale < 1.0:
            rendered = rendered.resize(
                (max(1, round(rendered.width * scale)), max(1, round(rendered.height * scale))),
                Image.Resampling.LANCZOS,
            )
        data = _png_bytes(rendered)
        images[name] = {"png": data, "sha256": _sha256(data), "width": rendered.width,
                        "height": rendered.height, "downsample_scale": scale}
    metadata = {
        "schema_version": RENDER_VERSION,
        "source_image_sha256": _sha256(raw),
        "source_width": width,
        "source_height": height,
        "candidate_box_clipped_xyxy": [x0, y0, x1, y1],
        "outline_rgb": list(OUTLINE_RGB),
        "outline_pixels": stroke,
        "outline_placement": "outside_candidate_box",
        "context_margin_pixels": margin,
        "context_crop_xyxy": list(crop_box),
        "upsampling": False,
        "maximum_image_edge": MAXIMUM_IMAGE_EDGE,
        "pillow_version": PIL.__version__,
        "image_sha256": {name: entry["sha256"] for name, entry in images.items()},
        "image_sizes": {name: [entry["width"], entry["height"]] for name, entry in images.items()},
    }
    metadata["render_sha256"] = canonical_sha256(metadata)
    return images, metadata


def build_messages(images):
    """Chat Completions messages; the only case-specific content is the image bytes."""
    parts = [
        {"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(images[name]["png"]).decode()}}
        for name in ("full_frame_with_outline", "context_crop_with_outline")
    ]
    parts.append({"type": "text", "text": USER_PROMPT})
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": parts}]


def redacted_payload(payload):
    """Payload copy with inline images replaced by their digests for persistence."""
    def redact(value):
        if isinstance(value, dict):
            if value.get("type") == "image_url":
                url = value["image_url"]["url"]
                encoded = url.split(",", 1)[1]
                return {"type": "image_url", "image_sha256": _sha256(base64.b64decode(encoded))}
            return {key: redact(child) for key, child in value.items()}
        if isinstance(value, list):
            return [redact(child) for child in value]
        return value
    return redact(payload)


def _is_timeout(error):
    names = {cls.__name__ for cls in type(error).__mro__}
    return bool(names & {"Timeout", "TimeoutError", "ReadTimeout", "ConnectTimeout"})


def inspect_region(case, adapter, *, clock=time.perf_counter, mock=False):
    """Execute one frozen semantic inspection and return ``(observation, raw_response)``.

    Exactly one adapter request is issued. Failures are recorded, not retried or
    converted into an observation value.
    """
    validate_case(case)
    if adapter.model != load_profile(MODEL_ALIAS)["model_id"]:
        raise ValueError("Adapter model does not match the frozen model alias")
    images, render = render_region(
        case["source_image_path"], case["candidate_bbox_root_xyxy"],
        expected_sha256=case["source_image_sha256"],
    )
    if case.get("region_render_sha256") and case["region_render_sha256"] != render["render_sha256"]:
        raise ValueError("Rendered region does not match the frozen pilot manifest")
    messages = build_messages(images)
    payload = adapter.payload(messages, options=dict(INFERENCE_OPTIONS), seed=INFERENCE_SEED)
    started = clock()
    response = None
    text = None
    error_type = None
    error_detail = None
    try:
        response = adapter.request(messages, options=dict(INFERENCE_OPTIONS), seed=INFERENCE_SEED)
        text, _, _ = adapter.parse(response, 0)
        status, parsed, detail = parse_response(text)
    except Exception as error:  # noqa: BLE001 - every failure is recorded, never converted to evidence
        status = "timeout" if _is_timeout(error) else "execution_failure"
        parsed, detail = None, None
        error_type, error_detail = type(error).__name__, str(error)[:500]
    latency_ms = (clock() - started) * 1000.0
    usage = response.get("usage") if isinstance(response, dict) else None
    identity = {
        "action_name": ACTION_NAME,
        "state_id": case["state_id"],
        "original_candidate_id": case["original_candidate_id"],
        "render_sha256": render["render_sha256"],
        "prompt_sha256": PROMPT_SHA256,
        "model_id": adapter.model,
        "inference_options": INFERENCE_OPTIONS,
        "seed": INFERENCE_SEED,
    }
    observation = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "observation_id": "semantic_observation:" + canonical_sha256(identity),
        "action_name": ACTION_NAME,
        "mock": bool(mock),
        "case_id": case["case_id"],
        "state_id": case["state_id"],
        "source_group_id": case["source_group_id"],
        "query": case["query"],
        "query_sent_to_model": False,
        "lineage": {
            "source_image_sha256": case["source_image_sha256"],
            "original_candidate_id": case["original_candidate_id"],
            "candidate_bbox_root_xyxy": case["candidate_bbox_root_xyxy"],
            "initial_observation_id": case["initial_observation_id"],
            "initial_controlled_call_id": case["initial_controlled_call_id"],
            "initial_action_id": case["initial_action_id"],
            "parent_snapshot_id": case["parent_snapshot_id"],
            "region_render": render,
        },
        "dependence": {
            "shares_source_image_with_initial_grounding": True,
            "region_derived_from_initial_proposal": True,
            "shares_backend_with_initial_grounding": False,
            "statistically_independent_of_initial_evidence_assumed": False,
            "likelihood_multiplication_permitted": False,
        },
        "prompt": {"version": PROMPT_VERSION, "sha256": PROMPT_SHA256},
        "ontology": {"version": ONTOLOGY_VERSION, "sha256": ONTOLOGY_SHA256},
        "backend": {
            "model_id": adapter.model,
            "protocol": adapter.protocol,
            "inference_options": INFERENCE_OPTIONS,
            "seed": INFERENCE_SEED,
            "served_model_reported": response.get("model") if isinstance(response, dict) else None,
            "checkpoint_attested": False,
            "checkpoint_attestation_reason": "OpenAI-compatible endpoint exposes no load-time weight identity",
        },
        "request": {
            "payload_redacted": redacted_payload(payload),
            "payload_redacted_sha256": canonical_sha256(redacted_payload(payload)),
            "physical_requests_issued": 1,
        },
        "execution": {
            "status": status,
            "latency_ms": latency_ms,
            "token_usage": usage,
            "error_type": error_type,
            "error_detail": error_detail,
            "logical_cost": LOGICAL_ACTION_COST,
        },
        "raw_text": text,
        "response_status": status,
        "parse_detail": detail,
        "parsed_observation": parsed,
        "consistency_flags": consistency_flags(parsed) if parsed else [],
        "correctness_probability_requested": False,
        "offline_labels_accessed": False,
    }
    return observation, response
