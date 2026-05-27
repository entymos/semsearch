"""Search engine adapter base class and registry."""

import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

from semsearch.config import EngineConfig


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    engine: str
    score: float = 0.0
    published_date: Optional[str] = None
    thumbnail: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EngineAdapter(ABC):
    """Base class for search engine adapters."""

    name: str = ""
    display_name: str = ""
    category: str = "general"
    base_url: str = ""
    default_timeout: int = 8

    @abstractmethod
    async def search(
        self,
        query: str,
        limit: int = 10,
        language: Optional[str] = None,
        time_range: Optional[str] = None,
        **kwargs: Any,
    ) -> List[SearchResult]:
        pass

    async def probe(self, timeout: int = 5) -> Dict[str, Any]:
        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(self.base_url or "https://example.com")
                latency = int((time.time() - start) * 1000)
                return {"status": "ok" if resp.status_code < 400 else "error", "latency_ms": latency}
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return {"status": "error", "latency_ms": latency, "error": str(e)}


class EngineRegistry:
    """Registry for search engine adapters."""

    def __init__(self) -> None:
        self._adapters: Dict[str, EngineAdapter] = {}

    def register(self, adapter: EngineAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> Optional[EngineAdapter]:
        return self._adapters.get(name)

    def get_enabled(self, config_engines: List[EngineConfig]) -> List["EngineAdapter"]:
        """Get list of enabled search adapters."""
        return [
            self._adapters[e.name]
            for e in config_engines
            if e.enabled and e.name in self._adapters
        ]

    def get_by_names(self, names: Optional[List[str]]) -> List["EngineAdapter"]:
        """Get list of adapters by name."""
        if not names:
            return []
        return [self._adapters[n] for n in names if n in self._adapters]

    def list_all(self) -> List[str]:
        return list(self._adapters.keys())


registry = EngineRegistry()
