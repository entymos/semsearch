"""Startpage search engine adapter (privacy-focused meta search)."""

from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from semsearch.search.engines import EngineAdapter, SearchResult


class StartpageAdapter(EngineAdapter):
    """Privacy-focused meta search engine - Startpage."""

    name = "startpage"
    display_name = "Startpage"
    category = "general"
    base_url = "https://www.startpage.com"

    async def search(
        self,
        query: str,
        limit: int = 10,
        language: Optional[str] = None,
        time_range: Optional[str] = None,
        **kwargs: Any,
    ) -> List[SearchResult]:
        """Search using Startpage search engine."""
        # Startpage is a meta search engine that searches multiple sources
        # Unfortunately, Startpage doesn't have a public API, so we use HTML scraping

        url = "https://www.startpage.com/sp/search"

        params: Dict[str, Any] = {
            "query": query,
            "cat": "web",
            "pl": "opensearch",
            "language": language or "en",
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with httpx.AsyncClient(timeout=self.default_timeout, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()

        return self._parse_html(resp.text, limit)

    def _parse_html(self, html: str, limit: int) -> List[SearchResult]:
        soup = BeautifulSoup(html, "html.parser")
        results = []

        # Startpage search results are in <li> tags with class "result"
        for li in soup.select("li.result")[:limit]:
            # Title and URL
            link = li.select_one("a.result-link")
            if not link:
                continue

            title = link.get_text(strip=True)
            url = link.get("href", "")

            # Description
            description_elem = li.select_one("p.result-snippet")
            snippet = description_elem.get_text(strip=True) if description_elem else ""

            if not title or not url:
                continue

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    engine=self.name,
                )
            )

        return results[:limit]
