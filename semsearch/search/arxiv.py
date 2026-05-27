"""arXiv search engine adapter."""

from __future__ import annotations

from typing import Any, List, Optional
from xml.etree import ElementTree

import httpx

from semsearch.search.engines import EngineAdapter, SearchResult


class ArxivAdapter(EngineAdapter):
    name = "arxiv"
    display_name = "arXiv"
    category = "academic"
    base_url = "https://export.arxiv.org"
    default_timeout = 10

    async def search(
        self,
        query: str,
        limit: int = 10,
        language: Optional[str] = None,
        time_range: Optional[str] = None,
        **kwargs: Any,
    ) -> List[SearchResult]:
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": min(limit, 50),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        headers = {
            "User-Agent": "SemSearch/0.1.0 (https://github.com/semsearch/semsearch)",
            "Accept": "application/atom+xml, application/xml",
        }

        async with httpx.AsyncClient(timeout=self.default_timeout, follow_redirects=True) as client:
            resp = await client.get(f"{self.base_url}/api/query", params=params, headers=headers)
            resp.raise_for_status()

        return self._parse_atom(resp.text, limit)

    def _parse_atom(self, xml_text: str, limit: int) -> List[SearchResult]:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ElementTree.fromstring(xml_text)
        results: List[SearchResult] = []

        for entry in root.findall("atom:entry", ns)[:limit]:
            title = self._text(entry, "atom:title", ns)
            url = self._text(entry, "atom:id", ns)
            snippet = " ".join(self._text(entry, "atom:summary", ns).split())
            published = self._text(entry, "atom:published", ns) or None
            authors = [
                self._text(author, "atom:name", ns)
                for author in entry.findall("atom:author", ns)
                if self._text(author, "atom:name", ns)
            ]
            if not title or not url:
                continue
            results.append(
                SearchResult(
                    title=" ".join(title.split()),
                    url=url,
                    snippet=snippet,
                    engine=self.name,
                    published_date=published,
                    metadata={"authors": authors},
                )
            )
        return results

    def _text(self, element: ElementTree.Element, path: str, ns: dict[str, str]) -> str:
        found = element.find(path, ns)
        return found.text.strip() if found is not None and found.text else ""
