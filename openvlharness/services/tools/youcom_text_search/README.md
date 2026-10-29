# Optional You.com search and page visits

Select these backends explicitly; Serper remains the default in every paper
preset. They use the same auxiliary model, retained-result formatting, URL
memory, page extraction prompts, truncation, and challenge detection as the
existing search tools. Reverse image search remains Serper Lens only.

| Capability | Backend | Credential |
| --- | --- | --- |
| General web search | `youcom_text_search` | Optional `YDC_API_KEY` or `YDC_API_KEY_FILE` |
| Page markdown and extraction | `youcom_webpage_visit` | Required `YDC_API_KEY` or `YDC_API_KEY_FILE` |

Without a key, search calls `GET https://api.you.com/v1/agents/search`. With a
key, it calls `POST https://ydc-index.io/v1/search` using `X-API-Key`. Both return
web result titles, URLs, and snippets. Keyless search was verified live on this
checkout; availability and IP quotas remain provider-controlled. An explicit
key is never silently discarded to bypass a key/account failure. An unreadable
key file is reported as an error.

Page visits call `POST https://ydc-index.io/v1/contents` with one URL and
`formats: [markdown, metadata]`, then use the existing extraction step. Missing
Contents credentials produce a startup warning and per-page failures; keyless
search itself produces no missing-key warning. See the official
[Search API](https://you.com/docs/api-reference/search/v1-search) and
[Contents API](https://you.com/docs/api-reference/contents) contracts.

To use both backends, copy an existing configuration and replace the capability
and matching service entries:

```yaml
capabilities:
  registries: [paper]
  tools:
    text_search: {backend: youcom_text_search}
    web_visit: {backend: youcom_webpage_visit}
services:
  tools:
    youcom_text_search: {model_service: auxiliary}
    youcom_webpage_visit: {model_service: auxiliary}
```

This is a fragment: retain the agent, memory, client/server, and main/auxiliary
model settings from the original configuration. Remove the replaced Serper
service entries. Search and page visits may also select different providers;
for example, use keyless You.com search with Serper page visits.
`configs/local_qwen_youcom.yaml` is a complete local configuration with SAM3,
OCR, depth, camera poses, zoom, coding, and both You.com backends. Select it in
`AGENT_CONFIG` in `.env` and restart the router, then use that same configuration
for inference/evaluation. Existing paper presets are unchanged.

You.com text search advertises and accepts only `search_type: search`; it does
not emulate Serper's images/news/scholar/maps/places/shopping/patents endpoints.
For a keyless smoke test, remove the `web_visit` capability and its service, or
retain a separately configured Serper page-visit backend.

All You.com API calls send
`User-Agent: youdotcom-integration/uclanlp-openvlharness`.
Transient HTTP/network failures have at most three attempts. A successful empty
search is retried once. HTTP 401/402/403 fail immediately and increment
`youcom_account`; exhausted HTTP 429 increments `youcom_rate_limit`. These
provider-specific buckets use the same `/backend-status` degradation reporting
as Serper, without incorrectly attributing You.com failures to Serper Lens.
Retry-After seconds and HTTP dates are honored. If the requested delay exceeds
60 seconds, the request fails without retrying early; retry after the provider's
deadline. Response bodies and credentials are excluded from error messages.

The shared summarization/extraction fallback paths retain the existing
`summarize`/`extract` counters. Check them before interpreting an evaluation as
a successful tool-assisted run. Provider choice changes retrieval evidence and
should be recorded when comparing results.
