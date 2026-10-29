"""Reuse page extraction, truncation and challenge detection with You.com Contents."""
from ..serper_webpage_visit.tool import Webpage_Visit_Tool as SerperWebpageVisit
from ..youcom_common import YoucomClient


class Webpage_Visit_Tool(SerperWebpageVisit):
    """Fetch page markdown with an authenticated You.com Contents client."""

    def __init__(self, llm_engine):
        super().__init__(llm_engine)
        self.tool_description = self.tool_description.replace("Serper's web scraping API", "You.com's Contents API")
        self.user_metadata = {**self.user_metadata, "api_key_env": "YDC_API_KEY",
                              "scrape_endpoint": "https://ydc-index.io/v1/contents",
                              "notes": "You.com Contents requires a key; transient failures respect Retry-After."}

    def _get_client(self):
        if self._client is None:
            self._client = YoucomClient()
        return self._client

    def _fetch_page(self, url):
        page = self._get_client().contents(url)
        anti_bot = self._looks_like_anti_bot(page["content"], page["metadata"])
        if anti_bot:
            raise RuntimeError(anti_bot)
        return page
