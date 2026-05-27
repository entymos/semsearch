"""Search service that orchestrates multiple engine adapters."""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from semsearch.config import EngineConfig, SemSearchConfig
from semsearch.search.arxiv import ArxivAdapter
from semsearch.search.bing import BingAdapter
from semsearch.search.duckduckgo import DuckDuckGoAdapter
from semsearch.search.engines import EngineAdapter, SearchResult, registry
from semsearch.search.github import GitHubAdapter
from semsearch.search.google import GoogleAdapter
from semsearch.search.hackernews import HackerNewsAdapter
from semsearch.search.qwant import QwantAdapter
from semsearch.search.startpage import StartpageAdapter
from semsearch.search.wikipedia import WikipediaAdapter


def init_engines() -> None:
    """Register all available engine adapters."""
    registry.register(DuckDuckGoAdapter())
    registry.register(QwantAdapter())
    registry.register(StartpageAdapter())
    registry.register(WikipediaAdapter())
    registry.register(ArxivAdapter())
    registry.register(HackerNewsAdapter())
    registry.register(GitHubAdapter())
    registry.register(BingAdapter())
    registry.register(GoogleAdapter())


class SearchService:
    """Orchestrates search across multiple engine adapters."""

    def __init__(self, config: SemSearchConfig) -> None:
        self.config = config

    async def search(
        self,
        query: str,
        engines: Optional[List[str]] = None,
        limit: int = 10,
        language: Optional[str] = None,
        time_range: Optional[str] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Search across multiple engines with domain filtering."""
        requested_engines = [engine.strip() for engine in engines or [] if engine.strip()]
        adapters = registry.get_by_names(requested_engines) if requested_engines else registry.get_enabled(self.config.engines)
        unknown_engines = [engine for engine in requested_engines if registry.get(engine) is None]

        if not adapters:
            return {
                "results": [],
                "query": query,
                "engine_errors": [{"engine": "all", "error": "No enabled engines"}],
                "warnings": ["No engines available for this search"] + [
                    f"Unknown engine: {engine}" for engine in unknown_engines
                ],
            }

        tasks = []
        adapter_limit = min(limit * 3, 50) if include_domains or exclude_domains else limit
        for adapter in adapters:
            engine_config = self._get_engine_config(adapter.name)
            timeout = engine_config.timeout_sec if engine_config else adapter.default_timeout
            tasks.append(
                self._search_with_tracking(
                    adapter, query, adapter_limit, language, time_range, timeout
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: List[SearchResult] = []
        engine_errors: List[Dict[str, Any]] = []
        warnings: List[str] = [f"Unknown engine: {engine}" for engine in unknown_engines]

        for r in results:
            if isinstance(r, Exception):
                warnings.append(str(r))
            elif isinstance(r, dict):
                if r.get("error"):
                    engine_errors.append(r)
                else:
                    all_results.extend(r.get("results", []))

        all_results = self._deduplicate(all_results)
        all_results = self._filter_domains(all_results, include_domains, exclude_domains)
        all_results = self._rank(all_results, query)
        all_results = all_results[:limit]

        return {
            "results": [r.model_dump(mode="json") for r in all_results],
            "query": query,
            "total_results": len(all_results),
            "engine_errors": engine_errors,
            "warnings": warnings,
        }

    async def _search_with_tracking(
        self,
        adapter: EngineAdapter,
        query: str,
        limit: int,
        language: Optional[str],
        time_range: Optional[str],
        timeout: int,
    ) -> Dict[str, Any]:
        start = time.time()
        try:
            results = await asyncio.wait_for(
                adapter.search(query, limit, language, time_range),
                timeout=timeout,
            )
            latency = int((time.time() - start) * 1000)
            self._update_engine_status(
                adapter.name,
                "ok",
                latency,
                None,
                True,
                result_count=len(results),
            )
            return {"results": results}
        except asyncio.TimeoutError:
            latency = int((time.time() - start) * 1000)
            self._update_engine_status(adapter.name, "timeout", latency, "Request timed out", False)
            return {"error": f"{adapter.name}: timeout after {timeout}s"}
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            self._update_engine_status(adapter.name, "error", latency, str(e), False)
            return {"error": f"{adapter.name}: {str(e)}"}

    def _get_engine_config(self, name: str) -> Optional[EngineConfig]:
        for e in self.config.engines:
            if e.name == name:
                return e
        return None

    def _update_engine_status(
        self,
        name: str,
        status: str,
        latency: int,
        error: Optional[str],
        success: bool,
        result_count: Optional[int] = None,
        probe_query: Optional[str] = None,
        probe_sample: Optional[List[SearchResult]] = None,
    ) -> None:
        for e in self.config.engines:
            if e.name == name:
                e.last_probe_status = status
                e.last_probe_at = datetime.now(timezone.utc).isoformat()
                e.latency_ms = latency
                e.last_error = error
                e.last_result_count = result_count
                if probe_query is not None:
                    e.last_probe_query = probe_query
                if probe_sample is not None:
                    e.last_probe_sample = [
                        {"title": result.title, "url": result.url, "engine": result.engine}
                        for result in probe_sample[:3]
                    ]
                if success:
                    e.success_count += 1
                else:
                    e.failure_count += 1
                break

    async def probe_engine(self, name: str, query: str = "weather") -> Dict[str, Any]:
        adapter = registry.get(name)
        engine_config = self._get_engine_config(name)
        if adapter is None or engine_config is None:
            return {"status": "error", "engine": name, "error": f"Engine '{name}' not found"}

        timeout = engine_config.timeout_sec or adapter.default_timeout
        start = time.time()
        try:
            results = await asyncio.wait_for(adapter.search(query, 3), timeout=timeout)
            latency = int((time.time() - start) * 1000)
            status = "ok" if results else "degraded"
            error = None if results else "Probe search returned no results"
            self._update_engine_status(
                name,
                status,
                latency,
                error,
                bool(results),
                result_count=len(results),
                probe_query=query,
                probe_sample=results,
            )
            return {
                "status": status,
                "engine": name,
                "query": query,
                "latency_ms": latency,
                "result_count": len(results),
                "sample_results": [result.model_dump(mode="json") for result in results[:3]],
                "error": error,
            }
        except asyncio.TimeoutError:
            latency = int((time.time() - start) * 1000)
            error = f"Probe timed out after {timeout}s"
            self._update_engine_status(name, "timeout", latency, error, False, result_count=0, probe_query=query)
            return {"status": "timeout", "engine": name, "query": query, "latency_ms": latency, "error": error}
        except Exception as exc:
            latency = int((time.time() - start) * 1000)
            error = str(exc)
            self._update_engine_status(name, "error", latency, error, False, result_count=0, probe_query=query)
            return {"status": "error", "engine": name, "query": query, "latency_ms": latency, "error": error}

    def _deduplicate(self, results: List[SearchResult]) -> List[SearchResult]:
        seen_urls = set()
        unique = []
        for r in results:
            key = self._dedupe_url(r.url)
            if key not in seen_urls:
                seen_urls.add(key)
                unique.append(r)
        return unique

    def _dedupe_url(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed._replace(fragment="").geturl().rstrip("/") or url

    def _filter_domains(
        self,
        results: List[SearchResult],
        include_domains: Optional[List[str]],
        exclude_domains: Optional[List[str]],
    ) -> List[SearchResult]:
        """Filter results by include/exclude domain lists."""
        includes = self._normalize_domains(include_domains)
        excludes = self._normalize_domains(exclude_domains)
        if not includes and not excludes:
            return results

        filtered: List[SearchResult] = []
        for result in results:
            hostname = urlparse(result.url).hostname or ""
            hostname = hostname.lower().removeprefix("www.")
            if includes and not any(self._domain_matches(hostname, domain) for domain in includes):
                continue
            if excludes and any(self._domain_matches(hostname, domain) for domain in excludes):
                continue
            filtered.append(result)
        return filtered

    def _normalize_domains(self, domains: Optional[List[str]]) -> List[str]:
        if not domains:
            return []
        return [
            domain.strip().lower().removeprefix("www.")
            for domain in domains
            if isinstance(domain, str) and domain.strip()
        ]

    def _domain_matches(self, hostname: str, domain: str) -> bool:
        return hostname == domain or hostname.endswith(f".{domain}")

    def _rank(self, results: List[SearchResult], query: str) -> List[SearchResult]:
        """Rank search results based on query term matches."""
        query_terms = set(query.lower().split())
        for r in results:
            score = r.score
            title_lower = r.title.lower()
            snippet_lower = r.snippet.lower()
            title_matches = sum(1 for t in query_terms if t in title_lower)
            snippet_matches = sum(1 for t in query_terms if t in snippet_lower)
            score += title_matches * 2.0 + snippet_matches * 0.5
            r.score = round(score, 3)
        return sorted(results, key=lambda x: x.score, reverse=True)
