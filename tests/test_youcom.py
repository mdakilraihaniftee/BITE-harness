"""Optional You.com provider contracts; all provider and model calls are offline."""
import copy
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import Mock

import pytest
import requests

from openvlharness.bootstrap import build_capabilities, load_agent_config
from openvlharness.services import degradation
from openvlharness.services.tools import youcom_common as yc
from openvlharness.services.tools.base import ToolArgumentError
from openvlharness.services.tools.youcom_text_search.tool import Text_Search_Tool
from openvlharness.services.tools.youcom_webpage_visit.tool import Webpage_Visit_Tool
from test_bootstrap import config_for


def response(payload, status=200, headers=None):
    value = requests.Response()
    value.status_code = status
    value._content = json.dumps(payload).encode()
    value.headers.update(headers or {})
    return value


WEB = {"results": {"web": [{"url": "https://example.test/page", "title": "Example",
                            "description": "fallback", "snippets": ["First fact.", "Second fact."]}]}}


@pytest.fixture(autouse=True)
def clear_provider_state():
    degradation.reset()
    yield
    degradation.reset()


def test_keyless_search_uses_get_and_normalizes_sources(monkeypatch):
    call = Mock(return_value=response(WEB))
    monkeypatch.setattr(yc.requests, "request", call)
    data = yc.YoucomClient().search("visual agents")
    assert data == {"organic": [{"title": "Example", "link": "https://example.test/page",
                                "snippet": "First fact. Second fact.", "position": 1}]}
    args, kwargs = call.call_args
    assert args == ("GET", yc.AGENT_SEARCH_URL)
    assert kwargs["params"] == {"query": "visual agents", "count": 10}
    assert kwargs["headers"] == {"User-Agent": yc.USER_AGENT, "Accept": "application/json"}
    assert kwargs["timeout"] == (5, 60)
    assert kwargs["allow_redirects"] is False


def test_keyed_search_never_falls_back_to_keyless_on_auth_failure(monkeypatch):
    monkeypatch.setenv("YDC_API_KEY", "private-test-key")
    call = Mock(return_value=response({"error": "private-test-key"}, 401))
    monkeypatch.setattr(yc.requests, "request", call)
    with pytest.raises(yc.YoucomRequestError, match="HTTP 401") as caught:
        yc.YoucomClient().search("query")
    assert call.call_count == 1
    assert call.call_args.args == ("POST", yc.SEARCH_URL)
    assert call.call_args.kwargs["json"] == {"query": "query", "count": 10}
    assert call.call_args.kwargs["headers"]["X-API-Key"] == "private-test-key"
    assert "private-test-key" not in str(caught.value)
    assert degradation.snapshot()["counts"]["youcom_account:http_401"] == 1
    assert "serper_account" not in degradation.snapshot()["counts"]


def test_key_environment_precedes_explicit_key_file(monkeypatch, tmp_path):
    path = tmp_path / "key.txt"
    path.write_text(" file-key \n")
    monkeypatch.setenv("YDC_API_KEY_FILE", str(path))
    assert yc.get_ydc_api_key() == "file-key"
    monkeypatch.setenv("YDC_API_KEY", " env-key ")
    assert yc.get_ydc_api_key() == "env-key"
    monkeypatch.delenv("YDC_API_KEY")
    path.unlink()
    with pytest.raises(FileNotFoundError):
        yc.get_ydc_api_key()


def test_credentialed_requests_do_not_follow_provider_redirects(monkeypatch):
    monkeypatch.setenv("YDC_API_KEY", "fixture-private-key")
    call = Mock(return_value=response({}, 302, {"Location": "https://other.test"}))
    monkeypatch.setattr(yc.requests, "request", call)
    with pytest.raises(yc.YoucomRequestError) as caught:
        yc.YoucomClient().search("query")
    assert caught.value.status_code == 302
    assert call.call_count == 1
    assert call.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("status", [401, 402, 403, 422])
def test_permanent_errors_fail_fast_without_exposing_response_bodies(monkeypatch, status):
    call = Mock(return_value=response({"error": "private-provider-details"}, status))
    monkeypatch.setattr(yc.requests, "request", call)
    with pytest.raises(yc.YoucomRequestError) as caught:
        yc.YoucomClient().search("query")
    assert caught.value.status_code == status
    assert not caught.value.transient
    assert call.call_count == 1
    assert "private-provider-details" not in str(caught.value)
    counts = degradation.snapshot()["counts"]
    assert counts.get("youcom_account", 0) == (0 if status == 422 else 1)


def test_rate_limit_honors_retry_after_then_recovers(monkeypatch):
    call = Mock(side_effect=[response({}, 429, {"Retry-After": "7"}), response(WEB)])
    sleep = Mock()
    monkeypatch.setattr(yc.requests, "request", call)
    monkeypatch.setattr(yc.time, "sleep", sleep)
    assert yc.YoucomClient().search("query")["organic"]
    sleep.assert_called_once_with(7.0)
    assert call.call_count == 2
    assert not degradation.snapshot()["counts"]


def test_exhausted_rate_limit_is_counted_and_bounded(monkeypatch):
    call = Mock(return_value=response({}, 429, {"Retry-After": "0"}))
    monkeypatch.setattr(yc.requests, "request", call)
    monkeypatch.setattr(yc.time, "sleep", Mock())
    with pytest.raises(yc.YoucomRequestError) as caught:
        yc.YoucomClient().search("query")
    assert caught.value.attempts == 3
    assert degradation.snapshot()["counts"]["youcom_rate_limit"] == 1
    assert call.call_count == 3


def test_long_retry_after_does_not_send_an_early_retry(monkeypatch):
    call = Mock(return_value=response({}, 429, {"Retry-After": "120"}))
    sleep = Mock()
    monkeypatch.setattr(yc.requests, "request", call)
    monkeypatch.setattr(yc.time, "sleep", sleep)
    with pytest.raises(yc.YoucomRequestError) as caught:
        yc.YoucomClient().search("query")
    assert caught.value.retry_after == 120
    assert "120 seconds" in str(caught.value)
    assert call.call_count == 1
    sleep.assert_not_called()


def test_http_date_retry_after_and_malformed_values():
    later = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=20), usegmt=True)
    assert 18 <= yc._retry_after(later) <= 20
    for value in ("invalid", "NaN", "Infinity"):
        assert yc._retry_after(value) is None


def test_network_retries_and_response_parse_errors(monkeypatch):
    call = Mock(side_effect=requests.Timeout("private-endpoint-detail"))
    monkeypatch.setattr(yc.requests, "request", call)
    monkeypatch.setattr(yc.time, "sleep", Mock())
    with pytest.raises(yc.YoucomRequestError) as caught:
        yc.YoucomClient().search("query")
    assert caught.value.attempts == 3 and caught.value.transient
    assert "private-endpoint-detail" not in str(caught.value)
    broken = response({})
    broken._content = b"not JSON"
    call.reset_mock(side_effect=True)
    call.return_value = broken
    with pytest.raises(yc.YoucomRequestError) as caught:
        yc.YoucomClient().search("query")
    assert caught.value.status_code is None
    assert call.call_count == 1


def test_empty_results_are_retried_once_then_return_no_results(monkeypatch):
    call = Mock(return_value=response({"results": {"web": []}}))
    sleep = Mock()
    monkeypatch.setattr(yc.requests, "request", call)
    monkeypatch.setattr(yc.time, "sleep", sleep)
    tool = Text_Search_Tool(Mock())
    assert "NO RESULTS" in tool.execute("rare query")
    assert call.call_count == 2
    sleep.assert_called_once_with(1)
    tool.llm_engine.generate.assert_not_called()


@pytest.mark.parametrize("payload", [{}, {"results": []}, {"results": {"web": "not-a-list"}}])
def test_malformed_search_is_an_error_not_an_empty_result(monkeypatch, payload):
    call = Mock(return_value=response(payload))
    monkeypatch.setattr(yc.requests, "request", call)
    with pytest.raises(yc.YoucomRequestError):
        yc.YoucomClient().search("query")
    assert call.call_count == 1


def test_contents_requires_key_before_network_and_uses_markdown(monkeypatch):
    call = Mock(return_value=response([
        {"url": "https://other.test", "markdown": "Wrong page"},
        {"url": "https://example.test/page", "title": "Page", "markdown": "# Content", "metadata": {"description": "Description"}},
    ]))
    monkeypatch.setattr(yc.requests, "request", call)
    with pytest.raises(FileNotFoundError, match="YDC_API_KEY"):
        yc.YoucomClient().contents("https://example.test/page")
    call.assert_not_called()
    monkeypatch.setenv("YDC_API_KEY", "fixture-key")
    result = yc.YoucomClient().contents("https://example.test/page")
    assert result["content"] == "# Content"
    assert result["metadata"]["title"] == "Page"
    assert call.call_args.args == ("POST", yc.CONTENTS_URL)
    assert call.call_args.kwargs["json"] == {"urls": ["https://example.test/page"], "formats": ["markdown", "metadata"]}


@pytest.mark.parametrize("page", [[], [{"url": "https://other.test", "markdown": "Unrelated"}],
                                  [{"url": "https://example.test", "markdown": ""}]])
def test_contents_does_not_substitute_an_unrelated_or_empty_page(monkeypatch, page):
    monkeypatch.setenv("YDC_API_KEY", "fixture-key")
    monkeypatch.setattr(yc.requests, "request", Mock(return_value=response(page)))
    with pytest.raises(RuntimeError, match="no markdown"):
        yc.YoucomClient().contents("https://example.test")


def test_webpage_challenge_detection_and_truncation_are_preserved():
    tool = Webpage_Visit_Tool(Mock())
    tool._client = Mock()
    tool._client.contents.return_value = {"content": "Verify you are human", "metadata": {"title": "Just a moment"}}
    with pytest.raises(RuntimeError, match="anti-bot"):
        tool._fetch_page("https://example.test")
    long_text = "text " * 200000
    assert len(tool._truncate_content(long_text)) < len(long_text)


def you_config():
    config = copy.deepcopy(config_for("text_search", "web_visit"))
    for name, backend in (("text_search", "youcom_text_search"), ("web_visit", "youcom_webpage_visit")):
        old = config["capabilities"]["tools"][name]["backend"]
        config["capabilities"]["tools"][name]["backend"] = backend
        config["services"]["tools"][backend] = config["services"]["tools"].pop(old)
    return config


def test_optional_backends_validate_and_do_not_change_serper_schemas():
    config = load_agent_config(you_config())
    caps = build_capabilities(config)
    assert caps["Text_Search_Tool"].public_schema()["function"]["parameters"]["properties"]["search_type"]["enum"] == ["search"]
    assert "You.com" in caps["Webpage_Visit_Tool"].public_schema()["function"]["description"]
    serper = build_capabilities(load_agent_config(config_for("text_search")))["Text_Search_Tool"]
    assert "images" in serper.public_schema()["function"]["parameters"]["properties"]["search_type"]["enum"]
    assert "Serper" not in caps["Text_Search_Tool"].public_schema()["function"]["description"]


def test_unsupported_search_modes_are_rejected_before_network():
    tool = Text_Search_Tool(Mock())
    with pytest.raises(ToolArgumentError, match="only search_type=search"):
        tool.execute("query", search_type="images")


def test_router_injects_auxiliary_model_and_warns_only_for_contents(monkeypatch, caplog):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from openvlharness.services import server
    engine = Mock()
    monkeypatch.setattr(server, "AuxiliaryModel", Mock(return_value=engine))
    app = server.create_app(you_config())
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok", "tools": 2}
        tools = client.get("/tools").json()
        assert tools["Text_Search_Tool"]["backend"] == "youcom_text_search"
        assert tools["Webpage_Visit_Tool"]["backend"] == "youcom_webpage_visit"
        result = client.post("/execute", json={"tool_name": "Webpage_Visit_Tool", "tool_call_id": "missing-key",
                                               "args": {"urls": ["https://example.test"], "goal": "Read title"}}).json()
        assert result["meta"]["pages"][0]["error"]
        assert "YDC_API_KEY" in result["meta"]["pages"][0]["error"]
    assert all(tool.llm_engine is engine for tool, _, _ in app.state.registry.values())
    assert "Contents requires" in caplog.text
    assert "no Serper API key" not in caplog.text
