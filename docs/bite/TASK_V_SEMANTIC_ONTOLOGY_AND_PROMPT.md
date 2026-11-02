# Task V semantic ontology and prompt (frozen before any semantic inference)

Status: **FROZEN — NO SEMANTIC INFERENCE HAS BEEN RUN**.

| Item | Version | SHA-256 (canonical JSON) |
| --- | --- | --- |
| Prompt | `bite.semantic_region_prompt.v1` | `fc0f1b15bf0dd0074ac9586aa4f9c05b2758c3d18a709dea1d0bdd3cb0c035ea` |
| Ontology | `bite.aquarium_semantic_ontology.v1` | `d03ffffc3a3df202c0d823d7afbe67a817319b79dba196ebe8530cd093a52d84` |

Source of truth: `evaluation_kit/bite_calibration/semantic_observation_schema.py`.
Changing a single character of the prompt or ontology changes its digest. The
pilot runner, the manifest verifier and the feature extractor all reject
mismatched digests, so any change must be released as a new version.

## Prompt design

- **The prompt is the same for every case.** It never contains the queried
  class, the SAM 3 score, an annotation or an expected answer. The only
  case-specific content in a request is the two rendered images. A mock run over
  all 101 pilot cases confirmed that the payload text, with images removed, has
  a single digest.
- It asks for neutral identification: *"Inspect the outlined region and
  identify the visible content. Do not assume it contains any particular animal
  or object. If the identity or the placement of the rectangle is unclear,
  report uncertainty instead of guessing."*
- It never asks for a correctness probability or a confidence number. A response
  that adds such a field fails the strict schema.
- The model sees two images: (1) the full photograph and (2) an enlarged context
  view. In both, a thin magenta rectangle is drawn just *outside* the candidate
  box, so no box pixels are covered. The prompt tells the model that the outline
  was added by software.
- The 7-class vocabulary is always listed in the same fixed order. That list
  identifies the schema; it does not hint at the answer.

## Output contract (`bite.semantic_region_observation.v1`)

| Field | Values |
| --- | --- |
| `region_content` | fish, jellyfish, penguin, puffin, shark, starfish, stingray, other_object, background, unclear |
| `object_visible` | yes, no, uncertain |
| `region_localization` | adequate, partial, wrong_region, uncertain |
| `multiple_objects` | yes, no, uncertain |
| `evidence_status` | supported, ambiguous, insufficient |
| `short_visual_description` | string, ≤ 300 characters |

Parsing is strict and never repairs a response. The only wrapper tolerated is a
single surrounding Markdown code fence. Each response gets one status:

- `valid`
- `empty_response`
- `malformed_json` (for example, prose before the JSON)
- `schema_violation` (missing or extra keys, an enum value outside the list, a
  description that is too long, or a top-level value that is not an object)
- `timeout`
- `execution_failure`

The raw text is always kept. Internal-consistency flags, such as `background`
together with `object_visible=yes`, are recorded for description only and never
change a value.

## Ontology: dataset categories are not biological taxa

The seven categories are **mutually exclusive dataset labels**. Biologically,
sharks and stingrays are fish, but the benchmark annotates them separately. The
prompt therefore says: use `shark` for sharks, `stingray` for rays, and `fish`
only for other fish. After the response is finalized, it is compared with the
query as follows:

| Compatibility | Rule |
| --- | --- |
| `match` | content equals the query category |
| `taxonomic_overlap` | fish ↔ shark or fish ↔ stingray: different dataset categories that overlap biologically. **Never counted as a match.** |
| `conflict_dataset_category` | a different dataset category, such as penguin vs puffin |
| `conflict_other_object` | `other_object` |
| `background` | `background` |
| `unclear` | `unclear` |
| `unavailable` | no valid observation (parse, timeout or execution failure) |

`match` alone does not establish a benchmark-correct detection. Localization is
a separate field, because a correctly classified region can still miss IoU 0.75.
Background, unclear and unavailable remain separate categories. None of them is
merged into a positive or negative answer.

## Known limitations

- There is no structured-output enforcement. The repository's `ModelAdapter`
  does not support `response_format` or guided decoding, and its option
  allowlist would reject it. Contract validity is therefore an empirical rate
  that the pilot must measure.
- The magenta outline is itself a visual cue, and the model could treat it as
  part of the scene. The prompt says otherwise, but that is not a guarantee.
- Showing the full frame also shows other objects. That could pull the answer
  toward classes visible elsewhere in the image, which is a dependence on image
  context that the pilot should describe.
