"""You.com transport and result normalization; no model or storage dependencies."""
import logging
import math
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from openvlharness.services import degradation
from .base import ToolArgumentError

logger = logging.getLogger(__name__)
USER_AGENT = "youdotcom-integration/uclanlp-openvlharness"
SEARCH_URL = "https://ydc-index.io/v1/search"
AGENT_SEARCH_URL = "https://api.you.com/v1/agents/search"
CONTENTS_URL = "https://ydc-index.io/v1/contents"
_TRANSIENT = {408, 429, 500, 502, 503, 504}


def get_ydc_api_key(*, required=False):
    """Read YDC_API_KEY, then an explicitly configured YDC_API_KEY_FILE.

    An unreadable explicit file is an error, not an implicit switch to keyless
    mode. An absent or empty credential permits keyless search only.
    """
    key = os.getenv("YDC_API_KEY", "").strip()
    path = os.getenv("YDC_API_KEY_FILE", "").strip()
    if not key and path:
        key = Path(path).read_text().strip()
    if required and not key:
        raise FileNotFoundError("You.com Contents requires YDC_API_KEY or YDC_API_KEY_FILE.")
    return key


class YoucomRequestError(RuntimeError):
    """Safe provider failure metadata; response bodies and credentials stay out of messages."""

    def __init__(self, endpoint, *, status_code=None, transient=False, attempts=1, retry_after=None):
        status = f"HTTP {status_code}" if status_code is not None else "transport or response-format error"
        advice = ("Check the You.com credential, account permissions, or credits."
                  if status_code in {401, 402, 403} else
                  "Retry later after the provider rate limit resets." if status_code == 429 else
                  "Retry later." if transient else "Check the request or provider response format.")
        if retry_after is not None:
            advice += f" Retry after at least {math.ceil(retry_after)} seconds."
        super().__init__(f"You.com {endpoint} failed: {status} after {attempts} attempt(s). {advice}")
        self.status_code = status_code
        self.transient = transient
        self.attempts = attempts
        self.endpoint = endpoint
        self.retry_after = retry_after


def _retry_after(value):
    """Interpret both Retry-After seconds and HTTP dates; ignore malformed values."""
    if not value:
        return None
    try:
        delay = float(value)
    except (TypeError, ValueError):
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            delay = (when - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0.0, delay) if math.isfinite(delay) else None


class YoucomClient:
    """Keyless/keyed search and authenticated Contents with bounded retries."""

    def __init__(self):
        self.api_key = get_ydc_api_key()

    def _request(self, method, url, *, endpoint, **kwargs):
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        code, transient, delay = None, False, None
        for attempt in range(1, 4):
            code, transient, delay = None, False, None
            try:
                response = requests.request(method, url, headers=headers, timeout=(5, 60),
                                            allow_redirects=False, **kwargs)
                code = response.status_code
                if 200 <= code < 300:
                    return response.json()
                transient = code in _TRANSIENT
                if code == 429:
                    delay = _retry_after(response.headers.get("Retry-After"))
            except (requests.Timeout, requests.ConnectionError):
                transient = True
            except ValueError:
                code = None
                break
            except requests.RequestException:
                break
            if not transient or attempt == 3:
                break
            # A long Retry-After is respected by failing now instead of issuing
            # an early retry or blocking the router thread for many minutes.
            if delay is not None and delay > 60:
                break
            time.sleep(delay if delay is not None else min(2 ** (attempt - 1), 4))
        if code in {401, 402, 403}:
            degradation.record("youcom_account", tool=endpoint, reason=f"http_{code}")
        elif code == 429:
            degradation.record("youcom_rate_limit", tool=endpoint, reason="http_429")
        logger.warning("You.com %s failed: status=%s attempts=%s transient=%s", endpoint, code, attempt, transient)
        raise YoucomRequestError(endpoint, status_code=code, transient=transient, attempts=attempt, retry_after=delay)

    def search(self, query, search_type="search", num=10, gl=None, hl=None):
        """Map You.com web snippets onto the existing organic-result contract."""
        if search_type != "search":
            raise ToolArgumentError("youcom_text_search supports only search_type=search")
        if not isinstance(query, str) or not query.strip():
            raise ToolArgumentError("query must be a non-empty string")
        params = {"query": query, "count": num}
        for empty_attempt in range(2):
            data = (self._request("POST", SEARCH_URL, endpoint="search", json=params)
                    if self.api_key else
                    self._request("GET", AGENT_SEARCH_URL, endpoint="search", params=params))
            sections = data.get("results") if isinstance(data, dict) else None
            items = sections.get("web") if isinstance(sections, dict) else None
            if not isinstance(items, list):
                raise YoucomRequestError("search")
            organic = []
            for item in items:
                if not isinstance(item, dict) or not str(item.get("url") or "").startswith(("http://", "https://")):
                    continue
                snippets = item.get("snippets")
                if not isinstance(snippets, list):
                    snippets = []
                snippet = " ".join(text for text in snippets if isinstance(text, str)) or str(item.get("description") or "")
                organic.append({"title": str(item.get("title") or ""), "link": item["url"],
                                "snippet": snippet, "position": len(organic) + 1})
            if organic or empty_attempt == 1:
                return {"organic": organic[:num]}
            time.sleep(1)

    def contents(self, url):
        """Retrieve one matching URL's markdown and metadata without positional assumptions."""
        if not self.api_key:
            raise FileNotFoundError("You.com Contents requires YDC_API_KEY or YDC_API_KEY_FILE.")
        data = self._request("POST", CONTENTS_URL, endpoint="contents",
                             json={"urls": [url], "formats": ["markdown", "metadata"]})
        if not isinstance(data, list):
            raise YoucomRequestError("contents")
        page = next((item for item in data if isinstance(item, dict) and item.get("url") == url), None)
        if page is None or not isinstance(page.get("markdown"), str) or not page["markdown"].strip():
            raise RuntimeError("You.com Contents returned no markdown for the requested URL.")
        metadata = page.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, dict) else {}
        metadata.setdefault("title", page.get("title") or "")
        return {"content": page["markdown"], "metadata": metadata,
                "description": str(metadata.get("description") or metadata.get("og:description") or "")}
