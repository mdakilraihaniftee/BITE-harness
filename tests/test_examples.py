"""Example configurations load offline, expose configured tools, and are discoverable."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from openvlharness.bootstrap import build_agent, load_agent_config
from openvlharness.services.server import create_app

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "examples").glob("*.yaml"))
ENV = {"MODEL_BASE_URL": "http://fixture.invalid/v1", "MODEL_API_KEY": "fixture-key",
       "TOOL_SERVER_URL": "http://fixture.invalid:8101",
       "SAM3_SERVER_URL": "http://fixture.invalid:8086",
       "OCR_SERVER_URL": "http://fixture.invalid:8085",
       "DEPTH_ESTIMATION_SERVER_URL": "http://fixture.invalid:8087"}


class ExampleConfigTests(unittest.TestCase):
    def test_examples_build_an_agent_and_a_router(self):
        self.assertTrue(EXAMPLES)
        with patch.dict(os.environ, ENV):
            for path in EXAMPLES:
                with self.subTest(example=path.name):
                    build_agent(str(path))
                    configured = load_agent_config(path)["capabilities"]["tools"]
                    with TestClient(create_app(str(path))) as client:
                        self.assertEqual(client.get("/health").json(), {"status": "ok", "tools": len(configured)})

    def test_readme_links_each_example(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for path in EXAMPLES:
            with self.subTest(example=path.name):
                self.assertIn(f"(examples/{path.name})", readme)
