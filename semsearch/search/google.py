"""Google search engine adapter (use with caution - may be rate limited)."""

from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from semsearch.search.engines import EngineAdapter, SearchResult


class GoogleAdapter(EngineAdapter):
    """Google Search adapter (HTML scraping).

    WARNING: This adapter uses HTML scraping and may violate Google's Terms of Service.
    Google has strong rate limiting and IP blocking mechanisms. Use with caution.
    For production use, consider using Google Custom Search Engine or official APIs.
    """

    name = "google"
    display_name = "Google"
    category = "general"
    base_url = "https://www.google.com"
    default_timeout = 10

    async def search(
        self,
        query: str,
        limit: int = 10,
        language: Optional[str] = None,
        time_range: Optional[str] = None,
        **kwargs: Any,
    ) -> List[SearchResult]:
        """Search using Google (HTML scraping).

        Note: This may result in IP bans or CAPTCHAs. Use sparingly.
        """
        # Google parameters
        params: Dict[str, Any] = {
            "q": query,
            "num": min(limit, 100),
        }

        if language:
            # Language code
            lang_code = language.split("-")[0] if "-" in language else language
            params["hl"] = lang_code

        # Time range: d (day), w (week), m (month), y (year)
        if time_range:
            time_map = {"day": "qdr:d", "week": "qdr:w", "month": "qdr:m", "year": "qdr:y"}
            if time_range in time_map:
                params["tbs"] = time_map[time_range]

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/",
        }

        async with httpx.AsyncClient(timeout=self.default_timeout, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.google.com/search",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()

        return self._parse_html(resp.text, limit)

    def _parse_html(self, html: str, limit: int) -> List[SearchResult]:
        soup = BeautifulSoup(html, "html.parser")
        results = []

        # Google search results are in div.g elements
        for div in soup.select("div.g")[:limit]:
            # Find title and URL
            title_elem = div.select_one("h3")
            link_elem = div.select_one("a")

            if not title_elem or not link_elem:
                continue

            title = title_elem.get_text(strip=True)
            url = link_elem.get("href", "")

            # Remove Google redirect if present
            if url.startswith("/url?q="):
                try:
                    url = url.split("/url?q=")[1].split("&")[0]
                except (IndexError, ValueError):
                    continue

            # Get snippet/description
            snippet_elem = div.select_one("span.aCOpf")
            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

            if not title or not url or not url.startswith(("http://", "https://")):
                continue

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    engine=self.name,
                )
            )

        return results
