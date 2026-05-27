"""Hacker News search adapter backed by the public Algolia HN API."""

from __future__ import annotations

from typing import Any, List, Optional

import httpx

from semsearch.search.engines import EngineAdapter, SearchResult


class HackerNewsAdapter(EngineAdapter):
    name = "hackernews"
    display_name = "Hacker News"
    category = "community"
    base_url = "https://hn.algolia.com"

    async def search(
        self,
        query: str,
        limit: int = 10,
        language: Optional[str] = None,
        time_range: Optional[str] = None,
        **kwargs: Any,
    ) -> List[SearchResult]:
        endpoint = f"{self.base_url}/api/v1/search"
        params: dict[str, Any] = {
            "query": query,
            "tags": "story",
            "hitsPerPage": min(limit, 50),
        }
        headers = {
            "User-Agent": "SemSearch/0.1.0 (https://github.com/semsearch/semsearch)",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.default_timeout, follow_redirects=True) as client:
            resp = await client.get(endpoint, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        results: List[SearchResult] = []
        for item in data.get("hits", [])[:limit]:
            title = item.get("title") or item.get("story_title") or ""
            object_id = item.get("objectID")
            url = item.get("url") or (f"https://news.ycombinator.com/item?id={object_id}" if object_id else "")
            if not title or not url:
                continue
            points = item.get("points") or 0
            comments = item.get("num_comments") or 0
            author = item.get("author") or "unknown"
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=f"{points} points, {comments} comments by {author}",
                    engine=self.name,
                    score=float(points or 0),
                    published_date=item.get("created_at"),
                    metadata={"points": points, "comments": comments, "author": author},
                )
            )
        return results
