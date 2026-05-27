"""DuckDuckGo search engine adapter."""

from typing import Any, Dict, List, Optional

import httpx

from semsearch.search.engines import EngineAdapter, SearchResult


class DuckDuckGoAdapter(EngineAdapter):
    name = "duckduckgo"
    display_name = "DuckDuckGo"
    category = "general"
    base_url = "https://html.duckduckgo.com"

    async def search(
        self,
        query: str,
        limit: int = 10,
        language: Optional[str] = None,
        time_range: Optional[str] = None,
        **kwargs: Any,
    ) -> List[SearchResult]:
        url = "https://html.duckduckgo.com/html/"
        params: Dict[str, Any] = {"q": query}
        if language:
            params["kl"] = language
        if time_range:
            time_map = {"day": "d", "week": "w", "month": "m", "year": "y"}
            params["df"] = time_map.get(time_range, time_range)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.post(url, data=params, headers=headers)
            resp.raise_for_status()

        return self._parse_html(resp.text, limit)

    def _parse_html(self, html: str, limit: int) -> List[SearchResult]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        results = []
        for div in soup.select("div.results_links")[:limit]:
            title_el = div.select_one("a.result__a")
            snippet_el = div.select_one("a.result__snippet")
            if title_el:
                href = title_el.get("href", "")
                from urllib.parse import parse_qs, unquote, urlparse
                qs = parse_qs(urlparse(href).query)
                if "uddg" in qs:
                    href = unquote(qs["uddg"][0])
                results.append(
                    SearchResult(
                        title=title_el.get_text(strip=True),
                        url=href,
                        snippet=snippet_el.get_text(strip=True) if snippet_el else "",
                        engine=self.name,
                    )
                )
        return results
