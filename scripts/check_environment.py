"""Check configured services; optionally execute real tools (including paid search)."""
import argparse
import base64
import io
import json
import os
from pathlib import Path

import numpy as np
import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw

from openvlharness.bootstrap import PAPER_CAPABILITIES, build_capabilities, load_agent_config
from openvlharness.services.client import ToolClient
from openvlharness.services.models import ModelAdapter
from openvlharness.services.tools.python_executor_local.executor import (
    execute_python_code,
    prepare_execution_context,
)


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    load_dotenv(root / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=os.getenv("AGENT_CONFIG", "configs/local_qwen.yaml"))
    parser.add_argument("--probe-tools", action="store_true", help="Execute configured tools; search uses provider credits")
    parser.add_argument("--image", type=Path, help="Optional real scene for perception probes")
    parser.add_argument("--output", type=Path, default=Path("outputs/setup/environment.json"))
    args = parser.parse_args()
    config = load_agent_config(args.config)
    records = []

    def record(name, status, detail):
        records.append({"component": name, "status": status, "detail": detail})
        print(f"{status.upper():8} {name}: {detail}", flush=True)

    def check(name, callback):
        try:
            detail = callback()
            record(name, "pass", detail)
            return detail
        except Exception as exc:
            # Connection exceptions can contain private URLs; do not write them.
            detail = str(exc) if isinstance(exc, AssertionError) else type(exc).__name__
            record(name, "fail", detail)
            return None

    def get(url, headers=None):
        response = requests.get(url, headers=headers, timeout=(3, 10))
        response.raise_for_status()
        if not response.content:
            return {"status": "ok", "http_status": response.status_code}
        return response.json()

    def model_check(settings):
        adapter = ModelAdapter(settings)
        base = adapter.endpoint.rsplit("/", 1)[0]
        if adapter.protocol == "chat_completions":
            base = base.removesuffix("/chat")
        response = get(base + "/models", {"Authorization": f"Bearer {adapter.key}"})
        names = [item["id"] for item in response["data"]]
        assert adapter.model in names, f"Required served model is absent: {adapter.model}"
        return adapter.model

    model_health = {}
    for name, settings in config["services"]["models"].items():
        model_health[name] = check("model:" + name, lambda settings=settings: model_check(settings))
    router = config["services"]["client"]["base_url"].rstrip("/")
    health = check("router", lambda: get(router + "/health"))
    if health is not None:
        expected = set(build_capabilities(config))

        def tool_check():
            actual = set(get(router + "/tools"))
            assert actual == expected, "Router tool set differs from the selected agent config; restart the router with the same config"
            return sorted(actual)

        def schema_check():
            actual = {item["function"]["name"] for item in get(router + "/llm-schema")}
            assert actual == expected, "Router schemas differ from the selected agent config"
            return sorted(actual)

        check("router:tools", tool_check)
        check("router:schemas", schema_check)
        check("router:capacity", lambda: get(router + "/backend-status"))
    worker_health = {}
    for name, settings in config["services"]["tools"].items():
        if "server_url" in settings:
            url = settings["server_url"].rstrip("/")
            if url not in worker_health:
                worker_health[url] = check("worker:" + name, lambda url=url: get(url + "/health"))
    for name in PAPER_CAPABILITIES:
        if name not in config["capabilities"]["tools"]:
            record("capability:" + name, "disabled", "Not selected in this configuration")
    search = set(config["capabilities"]["tools"]) & {"text_search", "image_search", "web_visit"}
    credential_available = {}
    if search:
        for name in sorted(search):
            backend = config["capabilities"]["tools"][name]["backend"]
            if backend.startswith("youcom_"):
                from openvlharness.services.tools.youcom_common import get_ydc_api_key
                try:
                    key = get_ydc_api_key(required=name == "web_visit")
                    credential_available[name] = True
                    record("search:credentials:" + name, "pass", "You.com key configured (not authenticated)" if key else "You.com keyless web search")
                except (OSError, ValueError):
                    credential_available[name] = False
                    record("search:credentials:" + name, "fail", "Set readable YDC_API_KEY or YDC_API_KEY_FILE for You.com Contents")
            else:
                from openvlharness.services.tools.serper_common import get_serper_api_key
                try:
                    get_serper_api_key()
                    credential_available[name] = True
                    record("search:credentials:" + name, "pass", "Serper key configured (not authenticated)")
                except (OSError, ValueError):
                    credential_available[name] = False
                    record("search:credentials:" + name, "fail", "Set SERPER_API_KEY or SERPER_API_KEY_FILE")
        if "image_search" in search:
            provider = os.getenv("IMAGE_UPLOAD_PROVIDER", "s3")
            required = {"local": ("IMAGE_UPLOAD_PUBLIC_BASE_URL",), "s3": ("AWS_S3_BUCKET_NAME", "AWS_S3_REGION"), "gcs": ("GCS_BUCKET_NAME", "GOOGLE_APPLICATION_CREDENTIALS")}.get(provider)
            missing = [key for key in required if not os.getenv(key)] if required else ["valid IMAGE_UPLOAD_PROVIDER"]
            record("search:image-host", "fail" if missing else "pass", "Missing: " + ", ".join(missing) if missing else f"{provider} configured (upload not checked)")

    if args.probe_tools and health is not None:
        if args.image:
            image = Image.open(args.image).convert("RGB")
            image.thumbnail((640, 640))
        else:
            image = Image.new("RGB", (560, 320), "white")
            draw = ImageDraw.Draw(image)
            draw.text((40, 30), "OpenVLHarness 123", fill="black", font_size=32)
            for x in (70, 230, 390):
                draw.rectangle((x, 120, x + 70, 280), fill="#3266a8")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode()
        client = ToolClient(router, timeout_seconds=180, retry=0)
        probes = {
            "grounding": ("Visual_Grounding_Tool", {"image_base64": encoded, "prompt": "object"}),
            "ocr": ("OCR_Tool", {"image_base64": encoded}),
            "depth": ("Depth_Estimation_Tool", {"image_base64": encoded}),
            "camera_pose": ("Camera_Trajectory_Tool", {"image_base64s": [encoded, encoded]}),
            "zoom": ("Zoom_In_Tool", {"image_base64": encoded, "coords": [100, 100, 600, 800], "padding": 50}),
            "coding": ("Python_Coding_Agent_Tool", {"objective": "Compute 17 * 23 and print only the integer result."}),
            "text_search": ("Text_Search_Tool", {"query": "OpenVLHarness visual agent"}),
            "image_search": ("Image_Search_Tool", {"image_base64": encoded}),
            "web_visit": ("Webpage_Visit_Tool", {"urls": ["https://example.com"], "goal": "Identify the title of this webpage."}),
        }

        def probe(name, tool, arguments):
            payload = client.execute(tool, arguments, tool_call_id="setup_" + name)
            assert payload["ok"], f"Tool returned error code: {(payload.get('error') or {}).get('code', 'unknown')}"
            result = payload["result"]
            if name == "web_visit":
                pages = payload.get("meta", {}).get("pages", [])
                assert pages and not any(page.get("error") for page in pages), "Webpage fetch returned a per-page error"
            if name in search and isinstance(result, str):
                assert result.strip(), "Search or webpage extraction returned empty text"
                return {"result_type": "text", "characters": len(result)}
            assert isinstance(result, dict), "Tool returned an unexpected result type"
            assert not result.get("error"), "Tool returned an embedded error; inspect its service log"
            if name == "coding":
                assert result.get("generated_code"), "No code was generated"
                execution = execute_python_code(result["generated_code"], prepare_execution_context({}), timeout_seconds=30)
                assert not execution.get("execution_error"), "Generated code execution failed"
                assert execution["printed_output"].strip() == "391", "Unexpected computation result"
                return "Generated Python executed successfully: 391"
            if name == "ocr":
                assert result.get("text", "").strip(), "OCR returned no text"
                return result["text"][:120]
            if name == "depth":
                array = np.frombuffer(base64.b64decode(result["depth_meters_b64"]), dtype=np.float32)
                assert array.size == int(np.prod(result["depth_shape"])) and np.isfinite(array).all(), "Invalid depth array"
                return {"shape": result["depth_shape"], "finite": True}
            if name == "camera_pose":
                assert result["num_images"] == 2 and len(result["extrinsics"]) == 2, "Invalid ordered camera output"
                return "Two ordered camera matrices returned (identical-frame contract probe)"
            if name == "zoom":
                crop = Image.open(io.BytesIO(base64.b64decode(result["cropped_image_base64"])))
                return {"crop_size": list(crop.size)}
            return "Tool returned: " + ", ".join(sorted(result))

        for name in config["capabilities"]["tools"]:
            if name in search and not credential_available[name]:
                record("probe:" + name, "blocked", "Missing provider credentials")
                continue
            backend = config["services"]["tools"][config["capabilities"]["tools"][name].get("backend", "python_coding_agent")]
            if backend.get("model_service") and model_health[backend["model_service"]] is None:
                record("probe:" + name, "blocked", "Required model service is unavailable")
                continue
            if backend.get("server_url", "").rstrip("/") in worker_health and worker_health[backend["server_url"].rstrip("/")] is None:
                record("probe:" + name, "blocked", "Worker is unavailable")
                continue
            tool, arguments = probes[name]
            check("probe:" + name, lambda name=name, tool=tool, arguments=arguments: probe(name, tool, arguments))
        def degradation_check():
            status = get(router + "/backend-status")["degradations"]
            assert not any(status["counts"].values()), "Router recorded a provider or auxiliary-model degradation; inspect /backend-status"
            return status
        check("router:degradations-after-probes", degradation_check)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"config": args.config, "checks": records}, indent=2) + "\n")
    print(f"Saved: {args.output}")
    raise SystemExit(1 if any(item["status"] in {"fail", "blocked"} for item in records) else 0)


if __name__ == "__main__":
    main()
