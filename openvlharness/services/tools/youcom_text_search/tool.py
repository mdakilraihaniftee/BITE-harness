"""Reuse the harness search summarizer with You.com web results."""
import copy

from ..base import ToolArgumentError
from ..serper_text_search.tool import Text_Search_Tool as SerperTextSearch
from ..youcom_common import YoucomClient


class Text_Search_Tool(SerperTextSearch):
    """General web search with keyless access or an explicit You.com credential."""

    def __init__(self, llm_engine):
        super().__init__(llm_engine)
        self.tool_description = "Search the web using You.com and summarize source titles, snippets and links."
        self.input_schema = copy.deepcopy(self.input_schema)
        self.input_schema["properties"]["search_type"]["enum"] = ["search"]
        self.input_types["search_type"] = "str - search (general web search only)"
        self.user_metadata = {**self.user_metadata, "api_key_env": "YDC_API_KEY", "supported_search_types": ["search"]}
        self.demo_commands = [{"command": 'Text_Search_Tool(query="visual agent tool use")', "description": "Search web sources."}]

    def _get_client(self):
        if self._client is None:
            self._client = YoucomClient()
        return self._client

    def execute(self, query, search_type="search"):
        if search_type != "search":
            raise ToolArgumentError("youcom_text_search supports only search_type=search")
        return super().execute(query, search_type=search_type)

    @staticmethod
    def _format_no_raw_results(query, search_type):
        return (f"[Search Results — Type: search]\nNO RESULTS\nYou.com returned no web results "
                f"after two requests for {query!r}. Try a broader or reworded web query.")
