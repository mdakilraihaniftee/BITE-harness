"""Frozen ontology, neutral prompt and strict response contract for
``semantic_region_inspect_v1``.

The prompt is identical for every case: it never names the queried class, the
detector score, the annotation label or any expected answer. Only the rendered
images differ between cases. Query compatibility is computed after the response
is finalized, under the frozen dataset ontology below.
"""

from __future__ import annotations

import hashlib
import json
import re

ACTION_NAME = "semantic_region_inspect_v1"
OBSERVATION_SCHEMA_VERSION = "bite.semantic_region_observation.v1"
ONTOLOGY_VERSION = "bite.aquarium_semantic_ontology.v1"
PROMPT_VERSION = "bite.semantic_region_prompt.v1"

DATASET_CATEGORIES = ("fish", "jellyfish", "penguin", "puffin", "shark", "starfish", "stingray")
REGION_CONTENT_VALUES = DATASET_CATEGORIES + ("other_object", "background", "unclear")
FIELD_VALUES = {
    "region_content": REGION_CONTENT_VALUES,
    "object_visible": ("yes", "no", "uncertain"),
    "region_localization": ("adequate", "partial", "wrong_region", "uncertain"),
    "multiple_objects": ("yes", "no", "uncertain"),
    "evidence_status": ("supported", "ambiguous", "insufficient"),
}
DESCRIPTION_FIELD = "short_visual_description"
MAX_DESCRIPTION_CHARACTERS = 300
REQUIRED_FIELDS = tuple(FIELD_VALUES) + (DESCRIPTION_FIELD,)

# Dataset categories are mutually exclusive labels, not biological taxa. Sharks and
# stingrays are biologically fish, but the benchmark annotates them separately, so a
# "fish" report for a shark query is recorded as a taxonomic overlap, never a match.
BIOLOGICAL_FISH_SUBSUMES = ("shark", "stingray")
ONTOLOGY = {
    "schema_version": ONTOLOGY_VERSION,
    "dataset_categories": list(DATASET_CATEGORIES),
    "categories_mutually_exclusive_in_dataset": True,
    "category_definitions": {
        "fish": "bony fish that is not a shark or a ray; dataset category, not the biological class",
        "jellyfish": "jellyfish (medusa)",
        "penguin": "penguin",
        "puffin": "puffin",
        "shark": "shark",
        "starfish": "sea star / starfish",
        "stingray": "stingray or other ray",
    },
    "biological_overlaps": {
        "fish": list(BIOLOGICAL_FISH_SUBSUMES),
    },
    "compatibility_values": {
        "match": "reported content equals the queried dataset category",
        "taxonomic_overlap": "reported content and query differ as dataset categories but overlap biologically (fish vs shark/stingray)",
        "conflict_dataset_category": "reported content is a different dataset category",
        "conflict_other_object": "reported content is an object outside the dataset vocabulary",
        "background": "region reported as background without an object",
        "unclear": "model reported that the content is unclear",
        "unavailable": "no valid observation (parse or execution failure)",
    },
    "frozen_before_any_semantic_inference": True,
}

SYSTEM_PROMPT = (
    "You are a careful visual inspector. You describe only what is visible. "
    "You never guess when the image does not support an answer."
)
USER_PROMPT = """You are given two images of the same photograph.
Image 1 is the full photograph. Image 2 is an enlarged view around one region.
In both images the region of interest is outlined by a thin magenta rectangle.
The outline was drawn by software; it is not part of the scene.

Inspect the outlined region and identify the visible content. Do not assume it contains any particular animal or object. If the identity or the placement of the rectangle is unclear, report uncertainty instead of guessing.

Answer with exactly one JSON object and nothing else, using these fields:
{
  "region_content": one of "fish", "jellyfish", "penguin", "puffin", "shark", "starfish", "stingray", "other_object", "background", "unclear",
  "object_visible": one of "yes", "no", "uncertain",
  "region_localization": one of "adequate", "partial", "wrong_region", "uncertain",
  "multiple_objects": one of "yes", "no", "uncertain",
  "evidence_status": one of "supported", "ambiguous", "insufficient",
  "short_visual_description": a plain description of at most 40 words
}

Category rules:
- Use "shark" for sharks and "stingray" for stingrays or other rays. Use "fish" only for other fish.
- Use "other_object" for a visible object that is none of the listed animals.
- Use "background" if the outlined region contains no distinct object.
- Use "unclear" if you cannot tell what the region contains.

Field rules:
- region_content describes the main object inside the rectangle.
- region_localization is "adequate" if the rectangle tightly encloses one whole object, "partial" if it covers only part of the object or mostly surroundings, "wrong_region" if it is not placed on any object.
- multiple_objects is "yes" if more than one separate object lies substantially inside the rectangle.
- evidence_status is "supported" if the image clearly shows your answer, "ambiguous" if several answers are plausible, "insufficient" if the image does not show enough."""

PROMPT = {
    "schema_version": PROMPT_VERSION,
    "system": SYSTEM_PROMPT,
    "user": USER_PROMPT,
    "image_order": ["full_frame_with_outline", "context_crop_with_outline"],
    "contains_query_class": False,
    "contains_detector_score": False,
    "contains_annotation_information": False,
    "case_specific_text": False,
}


def canonical_sha256(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


PROMPT_SHA256 = canonical_sha256(PROMPT)
ONTOLOGY_SHA256 = canonical_sha256(ONTOLOGY)

RESPONSE_STATUSES = (
    "valid",
    "empty_response",
    "malformed_json",
    "schema_violation",
    "execution_failure",
    "timeout",
)
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


def parse_response(text):
    """Classify a raw model response without repairing or coercing values.

    Returns ``(status, parsed_or_None, detail)``. Only a single JSON object with
    exactly the contract fields and allowed enum values is ``valid``. A single
    surrounding Markdown code fence is the only tolerated wrapper.
    """
    if not isinstance(text, str) or not text.strip():
        return "empty_response", None, "no text content"
    body = text.strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1)
    try:
        value = json.loads(body)
    except json.JSONDecodeError as error:
        return "malformed_json", None, f"json decode error at position {error.pos}"
    if not isinstance(value, dict):
        return "schema_violation", None, "top-level value is not an object"
    missing = [field for field in REQUIRED_FIELDS if field not in value]
    extra = sorted(set(value) - set(REQUIRED_FIELDS))
    if missing or extra:
        return "schema_violation", None, f"missing={missing} extra={extra}"
    for field, allowed in FIELD_VALUES.items():
        if value[field] not in allowed:
            return "schema_violation", None, f"{field} has disallowed value"
    description = value[DESCRIPTION_FIELD]
    if not isinstance(description, str) or len(description) > MAX_DESCRIPTION_CHARACTERS:
        return "schema_violation", None, "description missing, non-string or too long"
    return "valid", {field: value[field] for field in REQUIRED_FIELDS}, None


def consistency_flags(parsed):
    """Descriptive internal-consistency flags; they never change parsed values."""
    flags = []
    content = parsed["region_content"]
    if content == "background" and parsed["object_visible"] == "yes":
        flags.append("background_with_visible_object")
    if content in DATASET_CATEGORIES + ("other_object",) and parsed["object_visible"] == "no":
        flags.append("named_object_reported_not_visible")
    if content == "unclear" and parsed["evidence_status"] == "supported":
        flags.append("unclear_content_reported_supported")
    if content == "background" and parsed["region_localization"] == "adequate":
        flags.append("background_with_adequate_localization")
    return flags


def query_compatibility(query, parsed):
    """Map a validated observation to the frozen dataset ontology for one query."""
    if query not in DATASET_CATEGORIES:
        raise ValueError(f"Query is outside the frozen dataset vocabulary: {query}")
    if parsed is None:
        return "unavailable"
    content = parsed["region_content"]
    if content == query:
        return "match"
    if content in DATASET_CATEGORIES:
        overlap = (
            (content == "fish" and query in BIOLOGICAL_FISH_SUBSUMES)
            or (query == "fish" and content in BIOLOGICAL_FISH_SUBSUMES)
        )
        return "taxonomic_overlap" if overlap else "conflict_dataset_category"
    if content == "other_object":
        return "conflict_other_object"
    return content
