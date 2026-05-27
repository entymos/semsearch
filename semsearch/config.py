"""Configuration management for SemSearch."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from importlib import resources
from pathlib import Path
from typing import Any, List, Optional

import yaml
from pydantic import BaseModel, Field

try:
    from platformdirs import user_config_path
except ImportError:  # pragma: no cover - platformdirs is a package dependency.
    def user_config_path(appname: str, appauthor: str | None = None) -> Path:
        return Path.home() / ".config" / appname


class EngineConfig(BaseModel):
    name: str
    display_name: str
    enabled: bool = True
    category: str = "general"
    timeout_sec: int = 8
    base_url: str = ""
    last_probe_status: Optional[str] = None
    last_probe_at: Optional[str] = None
    latency_ms: Optional[int] = None
    last_error: Optional[str] = None
    last_probe_query: Optional[str] = None
    last_result_count: Optional[int] = None
    last_probe_sample: List[dict[str, Any]] = Field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0


class ServerConfig(BaseModel):
    port: int = 8088
    public_base_url: str = "http://localhost:8088"


class SecurityConfig(BaseModel):
    admin_token_env: str = "SEMSEARCH_ADMIN_TOKEN"


class FetchConfig(BaseModel):
    guard: str = "unrestricted_lab"


class SemSearchConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    fetch: FetchConfig = Field(default_factory=FetchConfig)
    engines: List[EngineConfig] = Field(default_factory=list)


DEFAULT_CONFIG = SemSearchConfig(
    engines=[
        EngineConfig(
            name="duckduckgo",
            display_name="DuckDuckGo",
            enabled=True,
            category="general",
            base_url="https://html.duckduckgo.com",
        ),
        EngineConfig(
            name="qwant",
            display_name="Qwant",
            enabled=True,
            category="general",
            base_url="https://www.qwant.com",
        ),
        EngineConfig(
            name="startpage",
            display_name="Startpage",
            enabled=True,
            category="general",
            base_url="https://www.startpage.com",
        ),
        EngineConfig(
            name="wikipedia",
            display_name="Wikipedia",
            enabled=True,
            category="reference",
            base_url="https://en.wikipedia.org",
        ),
        EngineConfig(
            name="arxiv",
            display_name="arXiv",
            enabled=True,
            category="academic",
            base_url="https://export.arxiv.org",
        ),
        EngineConfig(
            name="hackernews",
            display_name="Hacker News",
            enabled=True,
            category="community",
            base_url="https://hn.algolia.com",
        ),
        EngineConfig(
            name="github",
            display_name="GitHub Repositories",
            enabled=True,
            category="code",
            base_url="https://api.github.com",
        ),
        EngineConfig(
            name="bing",
            display_name="Bing",
            enabled=False,
            category="general",
            base_url="https://www.bing.com",
        ),
        EngineConfig(
            name="google",
            display_name="Google",
            enabled=False,
            category="general",
            timeout_sec=10,
            base_url="https://www.google.com",
        ),
    ]
)


def merge_default_engines(config: SemSearchConfig) -> SemSearchConfig:
    """Keep user config compatible when new built-in engines are added."""
    existing = {engine.name: engine for engine in config.engines}
    merged = list(config.engines)
    for default_engine in DEFAULT_CONFIG.engines:
        if default_engine.name not in existing:
            merged.append(default_engine.model_copy(deep=True))
            continue
        engine = existing[default_engine.name]
        if not engine.display_name:
            engine.display_name = default_engine.display_name
        if not engine.category:
            engine.category = default_engine.category
        if not engine.base_url:
            engine.base_url = default_engine.base_url
    config.engines = merged
    return config


def get_config_path() -> Path:
    env_path = os.environ.get("SEMSEARCH_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    return user_config_path("semsearch", "semsearch") / "semsearch.yaml"


def load_default_config() -> SemSearchConfig:
    try:
        config_text = resources.files("semsearch").joinpath("default_config.yaml").read_text(encoding="utf-8")
        raw: dict[str, Any] = yaml.safe_load(config_text) or {}
        return merge_default_engines(SemSearchConfig(**raw))
    except Exception:
        return DEFAULT_CONFIG.model_copy(deep=True)


def ensure_config_exists(path: Optional[Path] = None, force: bool = False) -> Path:
    if path is None:
        path = get_config_path()
    if path.exists() and not force:
        return path
    if not save_config(load_default_config(), path):
        raise RuntimeError(f"Failed to create config at {path}")
    return path


def load_config(path: Optional[Path] = None) -> SemSearchConfig:
    if path is None:
        path = get_config_path()
    if not path.exists():
        return load_default_config()
    with open(path, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}
    return merge_default_engines(SemSearchConfig(**raw))


def save_config(config: SemSearchConfig, path: Optional[Path] = None) -> bool:
    if path is None:
        path = get_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = config.model_dump(mode="json")
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".yaml.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_f:
                yaml.dump(data, tmp_f, default_flow_style=False, allow_unicode=True)
            os.replace(tmp_path, str(path))
            return True
        except Exception:
            with suppress(OSError):
                os.unlink(tmp_path)
            raise
    except Exception:
        return False


def validate_config(data: dict[str, Any]) -> bool:
    try:
        SemSearchConfig(**data)
        return True
    except Exception:
        return False
