"""GitHub repository search adapter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

import httpx

from semsearch.search.engines import EngineAdapter, SearchResult


class GitHubAdapter(EngineAdapter):
    name = "github"
    display_name = "GitHub Repositories"
    category = "code"
    base_url = "https://api.github.com"

    async def search(
        self,
        query: str,
        limit: int = 10,
        language: Optional[str] = None,
        time_range: Optional[str] = None,
        **kwargs: Any,
    ) -> List[SearchResult]:
        qualified_query = query
        if language:
            qualified_query = f"{qualified_query} language:{language}"
        if time_range:
            cutoff = self._cutoff_date(time_range)
            if cutoff:
                qualified_query = f"{qualified_query} pushed:>={cutoff}"

        params = {
            "q": qualified_query,
            "sort": "stars",
            "order": "desc",
            "per_page": min(limit, 50),
        }
        headers = {
            "User-Agent": "SemSearch/0.1.0 (https://github.com/semsearch/semsearch)",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        async with httpx.AsyncClient(timeout=self.default_timeout, follow_redirects=True) as client:
            resp = await client.get(f"{self.base_url}/search/repositories", params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        results: List[SearchResult] = []
        for item in data.get("items", [])[:limit]:
            title = item.get("full_name", "")
            url = item.get("html_url", "")
            if not title or not url:
                continue
            stars = item.get("stargazers_count") or 0
            language_name = item.get("language") or "unknown"
            description = item.get("description") or ""
            snippet = f"{description} ({stars} stars, {language_name})".strip()
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    engine=self.name,
                    score=float(stars),
                    published_date=item.get("pushed_at"),
                    metadata={
                        "stars": stars,
                        "forks": item.get("forks_count") or 0,
                        "language": language_name,
                        "open_issues": item.get("open_issues_count") or 0,
                    },
                )
            )
        return results

    def _cutoff_date(self, time_range: str) -> Optional[str]:
        days = {"day": 1, "week": 7, "month": 31, "year": 366}.get(time_range)
        if not days:
            return None
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return cutoff.date().isoformat()
