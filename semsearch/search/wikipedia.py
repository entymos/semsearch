"""Wikipedia search engine adapter."""

from typing import Any, List, Optional

import httpx

from semsearch.search.engines import EngineAdapter, SearchResult


class WikipediaAdapter(EngineAdapter):
    name = "wikipedia"
    display_name = "Wikipedia"
    category = "reference"
    base_url = "https://en.wikipedia.org"

    async def search(
        self,
        query: str,
        limit: int = 10,
        language: Optional[str] = None,
        time_range: Optional[str] = None,
        **kwargs: Any,
    ) -> List[SearchResult]:
        lang = language.split("-")[0] if language and isinstance(language, str) else "en"
        url = f"https://{lang}.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "format": "json",
            "srprop": "snippet|timestamp|wordcount",
        }

        headers = {
            "User-Agent": "SemSearch/0.1.0 (https://github.com/semsearch/semsearch)",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=10, headers=headers) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("query", {}).get("search", [])[:limit]:
            from bs4 import BeautifulSoup

            title = item.get("title", "")
            snippet = BeautifulSoup(item.get("snippet", ""), "html.parser").get_text(" ", strip=True)
            timestamp = item.get("timestamp", "")
            results.append(
                SearchResult(
                    title=title,
                    url=f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}",
                    snippet=snippet,
                    engine=self.name,
                    published_date=timestamp,
                )
            )
        return results
