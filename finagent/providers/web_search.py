from ..models import SourceDoc
from .base import SearchProvider


class DuckDuckGoSearch(SearchProvider):
    name = "duckduckgo"

    def search(self, query, max_results=5):
        try:
            from ddgs import DDGS
        except ImportError:  # older package name
            from duckduckgo_search import DDGS
        out = []
        for r in DDGS().text(query, max_results=max_results) or []:
            out.append(SourceDoc(r.get("title", ""), r.get("href", ""), r.get("body", "")))
        return out
