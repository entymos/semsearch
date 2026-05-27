"""Qwant search engine adapter (privacy-focused)."""

from typing import Any, Dict, List, Optional

import httpx

from semsearch.search.engines import EngineAdapter, SearchResult


class QwantAdapter(EngineAdapter):
    """Privacy-focused search engine - Qwant."""

    name = "qwant"
    display_name = "Qwant"
    category = "general"
    base_url = "https://www.qwant.com"

    async def search(
        self,
        query: str,
        limit: int = 10,
        language: Optional[str] = None,
        time_range: Optional[str] = None,
        **kwargs: Any,
    ) -> List[SearchResult]:
        """Search using Qwant search engine."""
        # Qwant API: https://api.qwant.com/v3/search/web
        url = "https://api.qwant.com/v3/search/web"

        params: Dict[str, Any] = {
            "q": query,
            "count": min(limit, 50),  # Qwant limit
            "offset": 0,
        }

        if language:
            # Language format: en, fr, de, etc.
            lang_code = language.split("-")[0] if "-" in language else language
            params["locale"] = lang_code

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.default_timeout, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        results = []
        results_data = data.get("data", {}).get("result", {}).get("items", [])

        for item in results_data[:limit]:
            title = item.get("title", "")
            url = item.get("url", "")
            description = item.get("description", "")

            if not title or not url:
                continue

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=description,
                    engine=self.name,
                )
            )

        return results
