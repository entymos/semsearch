"""Bing search engine adapter."""

from typing import Any, Dict, List, Optional

import httpx

from semsearch.search.engines import EngineAdapter, SearchResult


class BingAdapter(EngineAdapter):
    name = "bing"
    display_name = "Bing"
    category = "general"
    base_url = "https://www.bing.com"

    async def search(
        self,
        query: str,
        limit: int = 10,
        language: Optional[str] = None,
        time_range: Optional[str] = None,
        **kwargs: Any,
    ) -> List[SearchResult]:
        url = "https://www.bing.com/search"
        params: Dict[str, Any] = {"q": query, "count": limit}
        if language:
            params["setlang"] = language
        if time_range:
            time_map = {"day": "1", "week": "2", "month": "3", "year": "4"}
            params["filters"] = f"ex1:ez{time_map.get(time_range, '1')}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()

        return self._parse_html(resp.text, limit)

    def _parse_html(self, html: str, limit: int) -> List[SearchResult]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        results = []
        for li in soup.select("li.b_algo")[:limit]:
            title_el = li.select_one("h2 a")
            snippet_el = li.select_one("p")
            if title_el:
                results.append(
                    SearchResult(
                        title=title_el.get_text(strip=True),
                        url=title_el.get("href", ""),
                        snippet=snippet_el.get_text(strip=True) if snippet_el else "",
                        engine=self.name,
                    )
                )
        return results
