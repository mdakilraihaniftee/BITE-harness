#!/usr/bin/env python3
"""Phase 4C-1E Stages C, E, F, G: freeze the semantic action contract, the GT-blind
pilot manifest, the paired comparison design, and validate everything end to end
with scripted mock responses. No model is called."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

from evaluation_kit.bite_calibration.semantic_comparison_design import design_record
from evaluation_kit.bite_calibration.semantic_feature_extractor import (
    finalize_feature_table,
)
from evaluation_kit.bite_calibration.semantic_observation_schema import (
    ACTION_NAME,
    ONTOLOGY,
    ONTOLOGY_SHA256,
    PROMPT,
    PROMPT_SHA256,
    canonical_sha256,
)
from evaluation_kit.bite_calibration.semantic_pilot_protocol import (
    PILOT_DISPATCH_CAP,
    build_manifest,
    collect_observations,
    mock_requester,
    run_pilot,
)
from evaluation_kit.bite_calibration.semantic_region_action import (
    CONTEXT_MARGIN_FRACTION,
    INFERENCE_OPTIONS,
    INFERENCE_SEED,
    LOGICAL_ACTION_COST,
    MAXIMUM_IMAGE_EDGE,
    MINIMUM_CONTEXT_MARGIN_PIXELS,
    MODEL_ALIAS,
    OUTLINE_RGB,
    RENDER_VERSION,
    build_adapter,
    redacted_payload,
)
from evaluation_kit.bite_calibration.zoom_conditional_protocol import file_sha256
from evaluation_kit.bite_collection.persistence import atomic_json

ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = "outputs/bite/phase04b2b3/expansion/aquarium_task_v_expansion_seed418_g30"


def _valid(content, visible="yes", localization="adequate", multiple="no", status="supported"):
    return json.dumps({
        "region_content": content, "object_visible": visible, "region_localization": localization,
        "multiple_objects": multiple, "evidence_status": status,
        "short_visual_description": "scripted mock response",
    })


SCENARIOS = (
    ("valid_dataset_category", lambda: _valid("fish")),
    ("valid_other_dataset_category", lambda: _valid("shark")),
    ("valid_background", lambda: _valid("background", "no", "wrong_region", "no", "supported")),
    ("valid_unclear", lambda: _valid("unclear", "uncertain", "uncertain", "uncertain", "insufficient")),
    ("valid_other_object_multiple", lambda: _valid("other_object", "yes", "partial", "yes", "ambiguous")),
    ("malformed_prose_wrapper", lambda: "Sure! " + _valid("fish")),
    ("schema_violation_probability_field", lambda: _valid("fish")[:-1] + ', "confidence": 0.9}'),
    ("empty_response", lambda: ""),
    ("fenced_valid_json", lambda: "```json\n" + _valid("penguin") + "\n```"),
    ("timeout", None),
    ("execution_failure", None),
)


def _respond(index, payload):
    name, make = SCENARIOS[index % len(SCENARIOS)]
    if name == "timeout":
        raise TimeoutError("scripted mock timeout")
    if name == "execution_failure":
        raise RuntimeError("scripted mock HTTP 500")
    return make()


def _invariant_text(payload):
    redacted = redacted_payload(payload)
    for message in redacted["messages"]:
        if isinstance(message["content"], list):
            message["content"] = [part for part in message["content"] if part.get("type") != "image_url"]
    return canonical_sha256(redacted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/bite/phase04c1e")
    args = parser.parse_args()
    output = args.output
    selection_path = ROOT / RUN_DIR / "sample_selection_manifest.json"
    selection = json.loads(selection_path.read_text())

    contract = {
        "schema_version": "bite.semantic_action_contract.v1",
        "action_name": ACTION_NAME,
        "status": "FROZEN_NOT_EXECUTED",
        "prompt": PROMPT,
        "prompt_sha256": PROMPT_SHA256,
        "ontology": ONTOLOGY,
        "ontology_sha256": ONTOLOGY_SHA256,
        "render": {
            "version": RENDER_VERSION,
            "images": ["full frame with outline", "context crop with outline"],
            "outline_rgb": list(OUTLINE_RGB),
            "outline_placement": "outside candidate box",
            "context_margin": f"max({MINIMUM_CONTEXT_MARGIN_PIXELS}px, {CONTEXT_MARGIN_FRACTION} x larger box side)",
            "maximum_image_edge": MAXIMUM_IMAGE_EDGE,
            "upsampling": False,
            "encoding": "PNG, inline base64 data URL; media.encode_image_to_base64 not used because its env-dependent resizing would change input bytes",
        },
        "backend": {
            "interface": "openvlharness.services.models.ModelAdapter (existing), injected; production agent and tool registry unchanged",
            "model_alias": MODEL_ALIAS,
            "inference_options": INFERENCE_OPTIONS,
            "seed": INFERENCE_SEED,
            "transport_retries": 0,
            "structured_output_enforcement": "none available in repository; strict post-hoc JSON contract parsing",
            "checkpoint_attestation": "not available from an OpenAI-compatible endpoint; served model name recorded only",
        },
        "logical_cost": LOGICAL_ACTION_COST,
        "dependence": {
            "parents": ["source image", "initial SAM 3 grounding", "original proposal box"],
            "independent_of_sam3_assumed": False,
            "naive_likelihood_multiplication": "prohibited",
        },
    }
    atomic_json(output / "semantic_action/contract.json", contract)

    manifest = build_manifest(RUN_DIR, root=ROOT, expansion_protocol=selection,
                              cohort_groups=selection["selected_source_groups"])
    manifest["source_selection_manifest_sha256"] = file_sha256(selection_path)
    manifest["manifest_sha256"] = canonical_sha256({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    atomic_json(output / "semantic_pilot_manifest/manifest.json", manifest)
    design = design_record()
    atomic_json(output / "semantic_pilot_manifest/paired_comparison_design.json", design)

    mock_dir = output / "semantic_observation_contract/mock_run"
    if mock_dir.exists():
        shutil.rmtree(mock_dir)
    requester = mock_requester(_respond)
    adapter = build_adapter("http://mock.invalid/v1", requester=requester)
    first = run_pilot(manifest, adapter, mock_dir, root=ROOT, mode="mock_dry_run")
    resumed = run_pilot(manifest, adapter, mock_dir, root=ROOT, mode="mock_dry_run", resume=True)
    observations = collect_observations(mock_dir)
    table = finalize_feature_table(observations, allow_mock=True)
    invariant = {_invariant_text(payload) for payload in requester.calls}
    serialized = [json.dumps(redacted_payload(payload)) for payload in requester.calls]
    report = {
        "schema_version": "bite.semantic_mock_contract_report.v1",
        "status": "MOCK_ONLY_NO_MODEL_CALLED",
        "manifest_sha256": manifest["manifest_sha256"],
        "cases": manifest["case_count"],
        "first_run": first,
        "resume_run": resumed,
        "resume_idempotent": resumed["dispatched"] == 0 and resumed["complete_before_run"] == manifest["case_count"],
        "mock_requests_issued": len(requester.calls),
        "scenario_cycle": [name for name, _ in SCENARIOS],
        "response_status_counts": dict(Counter(row["response_status"] for row in observations)),
        "compatibility_counts": dict(Counter(row["semantic_compatibility"] for row in table["rows"])),
        "payload_text_identical_across_cases": len(invariant) == 1,
        "redacted_payload_mentions_score": any("score" in text.lower() for text in serialized),
        "query_text_is_case_independent": len(invariant) == 1,
        "feature_rows": table["row_count"],
        "feature_rows_marked_mock": all(row["mock"] for row in table["rows"]),
        "feature_table_sha256": table["rows_sha256"],
        "offline_labels_accessed": False,
        "network_requests": 0,
    }
    atomic_json(output / "semantic_observation_contract/mock_contract_report.json", report)

    plan = {
        "schema_version": "bite.semantic_pilot_execution_plan.v1",
        "status": "PREPARED_LIVE_INFERENCE_NOT_AUTHORIZED",
        "manifest": "outputs/bite/phase04c1e/semantic_pilot_manifest/manifest.json",
        "manifest_sha256": manifest["manifest_sha256"],
        "model_alias": MODEL_ALIAS,
        "dispatch_cap": PILOT_DISPATCH_CAP,
        "case_count": manifest["case_count"],
        "dry_run_command": (
            ".venv/bin/python scripts/bite/run_semantic_verification_pilot.py "
            "--mode mock_dry_run --output <scratch dir>"
        ),
        "live_command": (
            "MODEL_BASE_URL=<vLLM base> .venv/bin/python scripts/bite/run_semantic_verification_pilot.py "
            "--mode live --authorization <authorization.json> "
            "--output outputs/bite/phase04c1f/semantic_pilot_run"
        ),
        "resume_command_suffix": "--resume (same output, manifest and configuration; corrupt or partial cases stop the run)",
        "output_location": "outputs/bite/phase04c1f/semantic_pilot_run (new phase root; never phase04c1e)",
        "authorization_template": {
            "live_semantic_inference_authorized": True,
            "authorized_by": "<researcher name>",
            "manifest_sha256": manifest["manifest_sha256"],
            "prompt_sha256": PROMPT_SHA256,
            "model_alias": MODEL_ALIAS,
            "dispatch_cap": manifest["case_count"],
        },
        "error_handling": [
            "one physical request per case; no automatic retry",
            "timeouts and execution failures are recorded as observations of failure, never imputed",
            "malformed or schema-violating responses are preserved verbatim and classified",
            "partial or corrupt case directories halt the run for inspection",
        ],
        "checklist": [
            "researcher authorizes live semantic inference in writing",
            "vLLM endpoint serves Qwen/Qwen3-VL-8B-Instruct; served model name recorded per response",
            "manifest, prompt and ontology digests verified by the runner",
            "output root is a new phase directory",
            "no validation or internal-test case present (manifest asserts 0)",
            "labels joined only after all raw observations are finalized, via finalize_feature_table digest",
        ],
        "resource_estimate": manifest["resource_estimate"],
    }
    atomic_json(output / "execution_readiness/semantic_pilot_execution_plan.json", plan)
    print(json.dumps({"contract": PROMPT_SHA256, "manifest": manifest["manifest_sha256"],
                      "cases": manifest["case_count"], "design": design["design_sha256"],
                      "mock_report": report}, indent=2))


if __name__ == "__main__":
    main()
