"""SemSearch FastAPI application."""

import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import psutil
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from semsearch import __version__
from semsearch.config import (
    SemSearchConfig,
    ensure_config_exists,
    get_config_path,
    load_config,
    save_config,
    validate_config,
)
from semsearch.fetch.service import FetchService
from semsearch.mcp import (
    TOOL_DEFINITIONS,
    initialize_result,
    jsonrpc_error,
    jsonrpc_result,
    tool_error,
    tool_result,
)
from semsearch.search.engines import registry
from semsearch.search.service import SearchService, init_engines

START_TIME = time.time()

_config: Optional[SemSearchConfig] = None
_search_service: Optional[SearchService] = None
_fetch_service: Optional[FetchService] = None


class LogCaptureHandler(logging.Handler):
    def __init__(self, maxlen: int = 2000):
        super().__init__()
        self.logs: deque = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        self.logs.append({
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3],
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        })

_log_handler = LogCaptureHandler()
logging.getLogger().addHandler(_log_handler)
logging.getLogger().setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config, _search_service, _fetch_service
    ensure_config_exists()
    _config = load_config()
    init_engines()
    _search_service = SearchService(_config)
    _fetch_service = FetchService(_config.fetch)
    yield
    if _fetch_service:
        await _fetch_service.close()


app = FastAPI(title="SemSearch", version=__version__, lifespan=lifespan)


def get_config() -> SemSearchConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> SemSearchConfig:
    global _config
    _config = load_config()
    return _config


def get_admin_token() -> Optional[str]:
    config = get_config()
    return os.environ.get(config.security.admin_token_env)


def require_admin(authorization: Optional[str] = None) -> None:
    token = get_admin_token()
    if not token:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Admin token required")
    if authorization[7:] != token:
        raise HTTPException(status_code=403, detail="Invalid admin token")


def validate_mcp_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    parsed = urlparse(origin)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(status_code=403, detail="Origin not allowed")


def parse_csv(value: Optional[str]) -> Optional[list[str]]:
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def normalize_list_arg(value: Any) -> Optional[list[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        return parse_csv(value)
    if isinstance(value, list):
        items = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return items or None
    return None


@app.get("/api/health")
async def health():
    config = get_config()
    uptime = time.time() - START_TIME
    enabled_engines = [e for e in config.engines if e.enabled]
    process = psutil.Process(os.getpid())
    return {
        "status": "ok",
        "version": __version__,
        "uptime_sec": round(uptime, 1),
        "config_loaded": True,
        "config_path": str(get_config_path()),
        "enabled_engine_count": len(enabled_engines),
        "total_engine_count": len(config.engines),
        "memory_mb": round(process.memory_info().rss / 1024 / 1024, 1),
        "cpu_percent": process.cpu_percent(),
    }


@app.get("/api/logs")
async def get_logs(
    level: Optional[str] = Query(None, description="Filter by log level (DEBUG, INFO, WARNING, ERROR)"),
    tail: int = Query(200, ge=1, le=2000, description="Number of recent log lines"),
):
    logs = list(_log_handler.logs)
    if level:
        level_upper = level.upper()
        logs = [entry for entry in logs if entry["level"] == level_upper]
    return {"logs": logs[-tail:]}


@app.get("/api/search")
async def api_search(
    q: str = Query(..., description="Search query"),
    engines: Optional[str] = Query(None, description="Comma-separated engine names"),
    limit: int = Query(10, ge=1, le=50),
    language: Optional[str] = Query(None),
    time_range: Optional[str] = Query(None),
    include_domains: Optional[str] = Query(None, description="Comma-separated domains to include"),
    exclude_domains: Optional[str] = Query(None, description="Comma-separated domains to exclude"),
):
    global _search_service
    if not _search_service:
        return JSONResponse({"status": "error", "detail": "Search service not initialized"}, status_code=503)
    engine_list = [e.strip() for e in engines.split(",")] if engines else None
    logging.info("Search: q=%s engines=%s limit=%d", q, engines or "all", limit)
    result = await _search_service.search(
        query=q,
        engines=engine_list,
        limit=limit,
        language=language,
        time_range=time_range,
        include_domains=parse_csv(include_domains),
        exclude_domains=parse_csv(exclude_domains),
    )
    return JSONResponse(result)


@app.get("/api/fetch")
async def api_fetch(
    url: str = Query(..., description="Target URL"),
    format: str = Query("markdown", pattern="^(markdown|html|text|json|xml)$"),
    max_chars: Optional[int] = Query(None, ge=1),
):
    global _fetch_service
    if not _fetch_service:
        return JSONResponse({"status": "error", "detail": "Fetch service not initialized"}, status_code=503)
    logging.info("Fetch: url=%s format=%s", url, format)
    result = await _fetch_service.fetch(url, format=format, max_chars=max_chars)
    return JSONResponse(result)


@app.post("/api/batch_fetch")
async def api_batch_fetch(payload: dict[str, Any]):
    global _fetch_service
    if not _fetch_service:
        return JSONResponse({"status": "error", "detail": "Fetch service not initialized"}, status_code=503)
    urls = payload.get("urls")
    if not isinstance(urls, list) or not urls:
        raise HTTPException(status_code=400, detail="urls must be a non-empty list")
    logging.info("BatchFetch: %d urls concurrency=%s", len(urls), payload.get("concurrency", 5))
    result = await _fetch_service.batch_fetch(
        urls=urls,
        format=payload.get("format", "markdown"),
        max_chars=payload.get("max_chars"),
        concurrency=payload.get("concurrency", 5),
    )
    return JSONResponse(result)


@app.get("/api/crawl")
async def api_crawl(
    url: str = Query(..., description="Seed URL"),
    depth: int = Query(1, ge=1, le=5),
    max_pages: int = Query(10, ge=1, le=100),
    format: str = Query("markdown", pattern="^(markdown|html|text|json|xml)$"),
):
    global _fetch_service
    if not _fetch_service:
        return JSONResponse({"status": "error", "detail": "Fetch service not initialized"}, status_code=503)
    logging.info("Crawl: url=%s depth=%d max_pages=%d", url, depth, max_pages)
    result = await _fetch_service.crawl(url, depth=depth, max_pages=max_pages, format=format)
    return JSONResponse(result)


@app.get("/api/engines")
async def get_engines():
    config = get_config()
    engines = []
    for engine in config.engines:
        adapter = registry.get(engine.name)
        data = engine.model_dump(mode="json")
        data["registered"] = adapter is not None
        if adapter is not None:
            data["display_name"] = data.get("display_name") or adapter.display_name
            data["category"] = data.get("category") or adapter.category
            data["base_url"] = data.get("base_url") or adapter.base_url
        engines.append(data)
    return {"engines": engines}


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    validate_mcp_origin(request)
    try:
        msg = await request.json()
    except Exception:
        return JSONResponse(jsonrpc_error(None, -32700, "Parse error"), status_code=400)

    if not isinstance(msg, dict):
        return JSONResponse(jsonrpc_error(None, -32600, "Invalid request"), status_code=400)

    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if method is None or msg_id is None:
        return Response(status_code=202)

    if method == "initialize":
        return JSONResponse(jsonrpc_result(msg_id, initialize_result(params.get("protocolVersion"))))

    if method == "tools/list":
        return JSONResponse(jsonrpc_result(msg_id, {"tools": TOOL_DEFINITIONS}))

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments") or {}
        result = await handle_mcp_tool_call(tool_name, tool_args)
        return JSONResponse(jsonrpc_result(msg_id, result))

    if method == "ping":
        return JSONResponse(jsonrpc_result(msg_id, {}))

    if method in {"resources/list", "prompts/list"}:
        key = "resources" if method == "resources/list" else "prompts"
        return JSONResponse(jsonrpc_result(msg_id, {key: []}))

    return JSONResponse(jsonrpc_error(msg_id, -32601, f"Method not found: {method}"), status_code=404)


@app.get("/mcp")
async def mcp_sse_not_supported(request: Request):
    validate_mcp_origin(request)
    raise HTTPException(status_code=405, detail="SSE stream is not supported; use POST /mcp")


async def handle_mcp_tool_call(tool_name: str, arguments: dict) -> dict:
    try:
        global _search_service, _fetch_service
        if _search_service is None:
            _search_service = SearchService(get_config())
        if _fetch_service is None:
            _fetch_service = FetchService(get_config().fetch)

        if tool_name == "web_search":
            result = await _search_service.search(
                query=arguments["q"],
                engines=[e.strip() for e in arguments["engines"].split(",")] if arguments.get("engines") else None,
                limit=arguments.get("limit", 10),
                language=arguments.get("language"),
                time_range=arguments.get("time_range"),
                include_domains=normalize_list_arg(arguments.get("include_domains")),
                exclude_domains=normalize_list_arg(arguments.get("exclude_domains")),
            )
        elif tool_name == "web_fetch":
            result = await _fetch_service.fetch(
                arguments["url"],
                format=arguments.get("format", "markdown"),
                max_chars=arguments.get("max_chars"),
            )
        elif tool_name == "batch_fetch":
            result = await _fetch_service.batch_fetch(
                urls=arguments["urls"],
                format=arguments.get("format", "markdown"),
                max_chars=arguments.get("max_chars"),
                concurrency=arguments.get("concurrency", 5),
            )
        elif tool_name == "crawl":
            result = await _fetch_service.crawl(
                arguments["url"],
                depth=arguments.get("depth", 1),
                max_pages=arguments.get("max_pages", 10),
                format=arguments.get("format", "markdown"),
            )
        elif tool_name == "md":
            result = await _fetch_service.fetch(
                arguments["url"],
                format="markdown",
                max_chars=arguments.get("max_chars"),
            )
        elif tool_name == "sem_search":
            result = await _search_service.search(
                query=arguments["q"],
                engines=[e.strip() for e in arguments["engines"].split(",")] if arguments.get("engines") else None,
                limit=arguments.get("limit", 10),
                include_domains=normalize_list_arg(arguments.get("include_domains")),
                exclude_domains=normalize_list_arg(arguments.get("exclude_domains")),
            )
            fetch_top = arguments.get("fetch_top", 0)
            if fetch_top and result.get("results"):
                for item in result["results"][:fetch_top]:
                    fetch_result = await _fetch_service.fetch(item["url"], format="markdown", max_chars=3000)
                    item["fetched_content"] = fetch_result.get("content", "")
        else:
            return tool_error(f"Unknown tool: {tool_name}")

        return tool_result(result)
    except Exception as e:
        return tool_error(str(e))


@app.post("/api/engines/{name}/enable")
async def enable_engine(name: str, authorization: Optional[str] = Header(None)):
    require_admin(authorization)
    config = get_config()
    for engine in config.engines:
        if engine.name == name:
            engine.enabled = True
            if save_config(config):
                return {"status": "ok", "engine": name, "enabled": True}
            raise HTTPException(status_code=500, detail="Failed to save config")
    raise HTTPException(status_code=404, detail=f"Engine '{name}' not found")


@app.post("/api/engines/{name}/disable")
async def disable_engine(name: str, authorization: Optional[str] = Header(None)):
    require_admin(authorization)
    config = get_config()
    for engine in config.engines:
        if engine.name == name:
            engine.enabled = False
            if save_config(config):
                return {"status": "ok", "engine": name, "enabled": False}
            raise HTTPException(status_code=500, detail="Failed to save config")
    raise HTTPException(status_code=404, detail=f"Engine '{name}' not found")


@app.post("/api/engines/{name}/probe")
async def probe_engine(
    name: str,
    query: str = Query("weather", min_length=1, max_length=120),
    authorization: Optional[str] = Header(None),
):
    require_admin(authorization)
    global _search_service
    config = get_config()
    if _search_service is None or _search_service.config is not config:
        _search_service = SearchService(config)
    result = await _search_service.probe_engine(name, query=query)
    if result["status"] == "error" and result.get("error") == f"Engine '{name}' not found":
        raise HTTPException(status_code=404, detail=f"Engine '{name}' not found")
    if save_config(config):
        return result
    raise HTTPException(status_code=500, detail="Failed to save config")


@app.post("/api/config/reload")
async def reload_config_endpoint(authorization: Optional[str] = Header(None)):
    require_admin(authorization)
    new_config = reload_config()
    return {"status": "ok", "config_path": str(get_config_path()), "engines": len(new_config.engines)}


@app.post("/api/config/save")
async def save_config_endpoint(
    config_data: dict,
    authorization: Optional[str] = Header(None),
):
    require_admin(authorization)
    if not validate_config(config_data):
        raise HTTPException(status_code=400, detail="Invalid config schema")
    new_config = SemSearchConfig(**config_data)
    if save_config(new_config):
        reload_config()
        return {"status": "ok"}
    raise HTTPException(status_code=500, detail="Failed to save config")


@app.get("/dashboard")
async def dashboard():
    return HTMLResponse(
        content=_get_dashboard_html(),
        status_code=200,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/wiki")
async def wiki():
    """Serve SemSearch Technical Wiki as markdown rendered HTML."""
    import pathlib
    import markdown
    
    wiki_path = pathlib.Path(__file__).parent.parent / "SEMSEARCH-wiki.md"
    if not wiki_path.exists():
        return JSONResponse(
            {"error": "Wiki not found"},
            status_code=404
        )
    
    try:
        with open(wiki_path, "r", encoding="utf-8") as f:
            wiki_content = f.read()
        
        # Convert markdown to HTML
        html_content = markdown.markdown(
            wiki_content,
            extensions=[
                'markdown.extensions.tables',
                'markdown.extensions.fenced_code',
                'markdown.extensions.toc',
            ]
        )
        
        return HTMLResponse(
            content=f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SemSearch Technical Wiki</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f5; color: #333; }}
h1, h2, h3, h4, h5, h6 {{ margin-top: 1.5em; margin-bottom: 0.5em; }}
code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-family: 'Courier New', monospace; }}
pre {{ background: #1e1e1e; color: #d4d4d4; padding: 1em; border-radius: 5px; overflow-x: auto; }}
pre code {{ background: none; padding: 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #f0f0f0; }}
a {{ color: #0066cc; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.toc {{ background: #f9f9f9; padding: 1em; border-left: 4px solid #0066cc; margin: 1em 0; }}
</style>
</head>
<body>
<div style="margin-bottom: 1em;">
<a href="/dashboard">← Back to Dashboard</a>
</div>
{html_content}
</body>
</html>""",
            status_code=200,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            }
        )
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to render wiki: {str(e)}"},
            status_code=500
        )


def _get_dashboard_html() -> str:
    return """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SemSearch (WebSearchAPI)</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; }
.header { background: #1e293b; padding: 1rem 2rem; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }
.header h1 { font-size: 1.5rem; color: #38bdf8; }
.header .tagline { color: #94a3b8; font-size: 0.82rem; margin-top: 0.2rem; }
.header .version { color: #64748b; font-size: 0.875rem; }
.container { max-width: 1400px; margin: 0 auto; padding: 2rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; margin-bottom: 2rem; }
.card { background: #1e293b; border-radius: 0.75rem; padding: 1.5rem; border: 1px solid #334155; }
.card h2 { font-size: 1.125rem; margin-bottom: 1rem; color: #94a3b8; }
.stat { font-size: 2rem; font-weight: 700; color: #38bdf8; }
.stat-label { font-size: 0.875rem; color: #64748b; margin-top: 0.25rem; }
.status-ok { color: #4ade80; }
.status-warn { color: #fbbf24; }
.status-error { color: #f87171; }
.status-degraded, .status-timeout { color: #fbbf24; }
.btn { background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 0.375rem; cursor: pointer; font-size: 0.875rem; }
.btn:hover { background: #2563eb; }
.btn:disabled { opacity: 0.55; cursor: progress; }
.btn-sm { padding: 0.25rem 0.75rem; font-size: 0.75rem; }
.btn-danger { background: #ef4444; }
.btn-danger:hover { background: #dc2626; }
.btn-success { background: #22c55e; }
.btn-success:hover { background: #16a34a; }
input, select { background: #0f172a; border: 1px solid #334155; color: #e2e8f0; padding: 0.5rem; border-radius: 0.375rem; width: 100%; }
textarea { background: #0f172a; border: 1px solid #334155; color: #e2e8f0; padding: 0.5rem; border-radius: 0.375rem; width: 100%; font-family: monospace; min-height: 200px; }
.form-group { margin-bottom: 1rem; }
.form-group label { display: block; margin-bottom: 0.5rem; color: #94a3b8; font-size: 0.875rem; }
.form-row { display: flex; gap: 1rem; }
.form-row .form-group { flex: 1; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #334155; }
th { color: #64748b; font-weight: 500; font-size: 0.875rem; }
.toggle { position: relative; width: 44px; height: 24px; }
.toggle input { opacity: 0; width: 0; height: 0; }
.toggle-slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background: #475569; border-radius: 24px; transition: 0.3s; }
.toggle-slider:before { content: ""; position: absolute; height: 18px; width: 18px; left: 3px; bottom: 3px; background: white; border-radius: 50%; transition: 0.3s; }
.toggle input:checked + .toggle-slider { background: #3b82f6; }
.toggle input:checked + .toggle-slider:before { transform: translateX(20px); }
#token-modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 100; justify-content: center; align-items: center; }
#token-modal.active { display: flex; }
.modal-content { background: #1e293b; padding: 2rem; border-radius: 0.75rem; max-width: 400px; width: 90%; }
.tabs { display: flex; gap: 0.5rem; margin-bottom: 1.5rem; border-bottom: 1px solid #334155; padding-bottom: 0.5rem; }
.tab { padding: 0.5rem 1rem; cursor: pointer; border-radius: 0.375rem; color: #64748b; }
.tab.active { background: #3b82f6; color: white; }
.tab:hover { color: #e2e8f0; }
.tab-content { display: none; }
.tab-content.active { display: block; }
pre { background: #0f172a; padding: 1rem; border-radius: 0.375rem; overflow-x: auto; font-size: 0.875rem; }
.browser-bar { display:flex; align-items:center; gap:0.5rem; background:#0f172a; border:1px solid #334155; border-radius:2rem; padding:0.5rem 1rem; margin-bottom:1.5rem; }
.browser-url { display:flex; align-items:center; flex:1; }
.browser-lock { color:#4ade80; margin-right:0.5rem; font-size:0.875rem; }
.browser-url input { background:transparent; border:none; color:#e2e8f0; font-size:0.9375rem; outline:none; width:100%; }
.browser-url input::placeholder { color:#475569; }
.browser-result { padding:1rem 0; border-bottom:1px solid #1e293b; }
.browser-result:last-child { border-bottom:none; }
.browser-result .browser-title { font-size:1.1rem; }
.browser-result .browser-title a { color:#38bdf8; text-decoration:none; }
.browser-result .browser-title a:hover { text-decoration:underline; }
.browser-result .browser-url-display { font-size:0.8rem; color:#4ade80; word-break:break-all; margin:0.125rem 0 0.25rem; }
.browser-result .browser-snippet { font-size:0.875rem; color:#94a3b8; line-height:1.5; }
.browser-result .browser-engine { font-size:0.75rem; color:#64748b; margin-top:0.25rem; }
.browser-result .browser-engine span { background:#1e293b; padding:0.125rem 0.375rem; border-radius:0.25rem; }
.browser-result .browser-actions { margin-top:0.25rem; display:flex; gap:0.375rem; }
.browser-result .browser-actions button { background:#1e293b; border:1px solid #334155; color:#94a3b8; padding:0.2rem 0.5rem; border-radius:0.25rem; cursor:pointer; font-size:0.75rem; }
.browser-result .browser-actions button:hover { background:#334155; color:#e2e8f0; }
.browser-result .browser-actions button.fetching { color:#fbbf24; cursor:default; }
.browser-fetch-result { background:#0f172a; border:1px solid #334155; border-radius:0.375rem; padding:0.75rem; margin-top:0.5rem; max-height:400px; overflow:auto; font-size:0.8rem; line-height:1.5; display:none; }
.browser-fetch-result pre { margin:0; white-space:pre-wrap; word-break:break-all; font-size:0.75rem; }
.browser-fetch-result .fetch-status { padding:0.25rem 0; }
.browser-fetch-result .fetch-error { color:#f87171; }
.browser-fetch-result .fetch-close { float:right; background:none; border:none; color:#64748b; cursor:pointer; font-size:1rem; }
.browser-loading { display:flex; align-items:center; justify-content:center; gap:0.75rem; padding:3rem; color:#94a3b8; }
.spinner { width:24px; height:24px; border:3px solid #334155; border-top-color:#38bdf8; border-radius:50%; animation:spin 0.8s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
.browser-no-results { text-align:center; padding:3rem; color:#64748b; }
.logs-header { display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:1rem; margin-bottom:1rem; }
.logs-header h2 { margin-bottom:0; }
.logs-controls { display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap; }
.logs-toggle-group { display:flex; align-items:center; gap:0.5rem; }
.logs-toggle-label { font-size:0.85rem; color:#94a3b8; white-space:nowrap; }
.logs-filter { width:auto; padding:0.25rem 0.5rem; font-size:0.8rem; }
.logs-container { background:#0f172a; border:1px solid #334155; border-radius:0.5rem; padding:0.75rem; height:500px; overflow-y:auto; font-family:'Cascadia Code','Fira Code','Consolas',monospace; font-size:0.8rem; line-height:1.6; }
.logs-container .log-line { padding:0.125rem 0.5rem; white-space:pre-wrap; word-break:break-all; border-radius:0.25rem; }
.logs-container .log-line:hover { background:#1e293b; }
.logs-container .log-DEBUG { color:#64748b; }
.logs-container .log-INFO { color:#e2e8f0; }
.logs-container .log-WARNING { color:#fbbf24; }
.logs-container .log-ERROR { color:#f87171; }
.logs-container .log-CRITICAL { color:#f87171; font-weight:bold; background:#7f1d1d; }
.logs-placeholder { color:#475569; text-align:center; padding:2rem; }
.muted { color:#64748b; font-size:0.8rem; }
.engine-actions { display:flex; gap:0.375rem; align-items:center; flex-wrap:wrap; }
.engine-probe-query { max-width:260px; margin-bottom:1rem; }
.engine-probe-result { margin-top:1rem; max-height:260px; white-space:pre-wrap; }
.engine-sample { margin-top:0.25rem; color:#64748b; font-size:0.75rem; max-width:280px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.browser-nav { display:flex; align-items:center; gap:0.25rem; }
.browser-nav button { background:transparent; border:1px solid #334155; color:#94a3b8; padding:0.375rem 0.5rem; border-radius:0.375rem; cursor:pointer; font-size:0.875rem; line-height:1; }
.browser-nav button:hover { background:#334155; color:#e2e8f0; }
.browser-nav button:disabled { opacity:0.35; cursor:default; }
.browser-nav button:disabled:hover { background:transparent; color:#94a3b8; }
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>SemSearch (WebSearchAPI)</h1>
    <div class="tagline">Simple open-source web search and fetch API</div>
  </div>
  <div>
    <span class="version" id="version">v0.1.0</span>
    <a href="/wiki" target="_blank" style="margin-left:1rem; color:#38bdf8; text-decoration:none;">
      <button class="btn btn-sm" style="cursor:pointer;">📖 Wiki</button>
    </a>
    <button class="btn btn-sm" onclick="showTokenModal()" style="margin-left:0.5rem;">Set Token</button>
  </div>
</div>
<div class="container">
    <div class="tabs">
      <div class="tab active" onclick="switchTab('overview', this)">Overview</div>
      <div class="tab" onclick="switchTab('browser', this)">Browser</div>
      <div class="tab" onclick="switchTab('search', this)">Search</div>
      <div class="tab" onclick="switchTab('fetch', this)">Fetch/Crawl</div>
      <div class="tab" onclick="switchTab('engines', this)">Engines</div>
      <div class="tab" onclick="switchTab('logs', this)">Logs</div>
      <div class="tab" onclick="switchTab('system', this)">System</div>
      <div class="tab" onclick="switchTab('docs', this)">Docs</div>
    </div>

  <div id="tab-overview" class="tab-content active">
    <div class="grid">
      <div class="card">
        <h2>Service Status</h2>
        <div class="stat status-ok" id="status">Checking...</div>
        <div class="stat-label">Server status</div>
      </div>
      <div class="card">
        <h2>Uptime</h2>
        <div class="stat" id="uptime">-</div>
        <div class="stat-label">Server uptime</div>
      </div>
      <div class="card">
        <h2>Engines</h2>
        <div class="stat" id="engine-count">-</div>
        <div class="stat-label">Enabled / Total</div>
      </div>
      <div class="card">
        <h2>Memory</h2>
        <div class="stat" id="memory">-</div>
        <div class="stat-label">MB used</div>
      </div>
    </div>
  </div>

  <div id="tab-browser" class="tab-content">
    <div class="card">
      <div class="browser-bar">
        <div class="browser-nav">
          <button onclick="browserGoBack()" id="browser-back" disabled title="Back">&lt;</button>
          <button onclick="browserGoForward()" id="browser-forward" disabled title="Forward">&gt;</button>
          <button onclick="refreshBrowserSearch()" title="Refresh">R</button>
        </div>
        <div class="browser-url" style="flex:1;">
          <span class="browser-lock">local</span>
          <input type="text" id="browser-query" placeholder="https://semsearch/search?q=..." value="https://semsearch/search?q=" onkeydown="if(event.key==='Enter') runBrowserSearch()">
        </div>
        <label style="font-size:0.8rem;color:#64748b;white-space:nowrap;">Limit</label>
        <input type="number" id="browser-limit" value="10" min="1" max="50" style="width:55px;background:#0f172a;border:1px solid #334155;color:#e2e8f0;padding:0.25rem 0.5rem;border-radius:0.375rem;font-size:0.8rem;">
        <button class="btn btn-sm" onclick="runBrowserSearch()" style="margin-left:0.5rem;">Go</button>
      </div>
      <div id="browser-results"></div>
      <div id="browser-loading" class="browser-loading" style="display:none;">
        <div class="spinner"></div>
        <span>Searching across engines...</span>
      </div>
    </div>
  </div>

  <div id="tab-search" class="tab-content">
    <div class="card">
      <h2>Search Playground</h2>
      <div class="form-group">
        <label>Query</label>
        <input type="text" id="search-q" placeholder="Enter search query...">
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Limit</label>
          <input type="number" id="search-limit" value="10" min="1" max="50">
        </div>
        <div class="form-group">
          <label>Language</label>
          <input type="text" id="search-lang" placeholder="e.g. ko, en">
        </div>
        <div class="form-group">
          <label>Time Range</label>
          <select id="search-time">
            <option value="">All</option>
            <option value="day">Today</option>
            <option value="week">This week</option>
            <option value="month">This month</option>
            <option value="year">This year</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Include Domains</label>
          <input type="text" id="search-include" placeholder="example.com,docs.example.com">
        </div>
        <div class="form-group">
          <label>Exclude Domains</label>
          <input type="text" id="search-exclude" placeholder="example.com">
        </div>
      </div>
      <div class="form-group">
        <label>Engines</label>
        <input type="text" id="search-engines" placeholder="Optional: duckduckgo,wikipedia,github">
      </div>
      <button class="btn" onclick="runSearch()">Search</button>
      <h3 style="margin-top:1rem;margin-bottom:0.5rem;">Result</h3>
      <pre id="search-result">{}</pre>
    </div>
  </div>

  <div id="tab-fetch" class="tab-content">
    <div class="card">
      <h2>Fetch Playground</h2>
      <div class="form-group">
        <label>URL</label>
        <input type="text" id="fetch-url" placeholder="https://example.com">
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Format</label>
          <select id="fetch-format">
            <option value="markdown">Markdown</option>
            <option value="html">HTML</option>
            <option value="text">Text</option>
            <option value="json">JSON</option>
            <option value="xml">XML</option>
          </select>
        </div>
        <div class="form-group">
          <label>Max Chars</label>
          <input type="number" id="fetch-chars" placeholder="Optional">
        </div>
      </div>
      <button class="btn" onclick="runFetch()">Fetch</button>
      <h3 style="margin-top:1rem;margin-bottom:0.5rem;">Result</h3>
      <pre id="fetch-result">{}</pre>
    </div>
    <div class="card" style="margin-top:1.5rem;">
      <h2>Crawl Playground</h2>
      <div class="form-group">
        <label>Seed URL</label>
        <input type="text" id="crawl-url" placeholder="https://example.com">
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Depth</label>
          <input type="number" id="crawl-depth" value="1" min="1" max="5">
        </div>
        <div class="form-group">
          <label>Max Pages</label>
          <input type="number" id="crawl-pages" value="10" min="1" max="100">
        </div>
        <div class="form-group">
          <label>Format</label>
          <select id="crawl-format">
            <option value="markdown">Markdown</option>
            <option value="html">HTML</option>
            <option value="text">Text</option>
            <option value="json">JSON</option>
            <option value="xml">XML</option>
          </select>
        </div>
      </div>
      <button class="btn" onclick="runCrawl()">Crawl</button>
      <h3 style="margin-top:1rem;margin-bottom:0.5rem;">Result</h3>
      <pre id="crawl-result">{}</pre>
    </div>
  </div>

  <div id="tab-engines" class="tab-content">
    <div class="card">
      <h2>Engine Management</h2>
      <div class="form-group engine-probe-query">
        <label>Probe Query</label>
        <input type="text" id="engine-probe-query" value="weather">
      </div>
      <table>
        <thead><tr><th>Engine</th><th>Category</th><th>Status</th><th>Latency</th><th>Results</th><th>Last Error</th><th>Success/Fail</th><th>Enabled</th><th>Actions</th></tr></thead>
        <tbody id="engine-table"></tbody>
      </table>
      <pre id="engine-probe-result" class="engine-probe-result">{}</pre>
    </div>
  </div>

  <div id="tab-logs" class="tab-content">
    <div class="card">
      <div class="logs-header">
        <h2>Server Logs</h2>
        <div class="logs-controls">
          <select id="logs-level" class="logs-filter">
            <option value="">All levels</option>
            <option value="DEBUG">DEBUG</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
            <option value="CRITICAL">CRITICAL</option>
          </select>
          <button class="btn btn-sm" onclick="loadLogs()">Refresh</button>
          <button class="btn btn-sm btn-danger" onclick="clearLogs()">Clear</button>
        </div>
      </div>
      <div class="logs-container" id="logs-container">
        <div class="logs-placeholder">Waiting for logs...</div>
      </div>
    </div>
  </div>

  <div id="tab-system" class="tab-content">
    <div class="grid">
      <div class="card">
        <h2>CPU</h2>
        <div class="stat" id="cpu">-</div>
        <div class="stat-label">CPU usage %</div>
      </div>
      <div class="card">
        <h2>Memory</h2>
        <div class="stat" id="mem-system">-</div>
        <div class="stat-label">MB used</div>
      </div>
      <div class="card">
        <h2>Uptime</h2>
        <div class="stat" id="uptime-system">-</div>
        <div class="stat-label">Server uptime</div>
      </div>
    </div>
  </div>

  <div id="tab-docs" class="tab-content">
    <div class="card">
      <h2>REST API Reference</h2>
      <pre>
GET  /api/health                    - Server health check
GET  /api/search?q=&limit=          - Web search, with include_domains/exclude_domains filters
GET  /api/fetch?url=&format=        - Fetch single URL or PDF (markdown|html|text|json|xml)
POST /api/batch_fetch               - Fetch multiple URLs in parallel
GET  /api/crawl?url=&depth=         - Crawl from seed URL (markdown|html|text|json|xml)
GET  /api/engines                   - List all engines
POST /api/engines/{name}/enable     - Enable engine (admin token)
POST /api/engines/{name}/disable    - Disable engine (admin token)
POST /api/engines/{name}/probe      - Run a live probe search (admin token, query optional)
      </pre>
    </div>
    <div class="card" style="margin-top:1.5rem;">
      <h2>MCP Tools</h2>
      <pre>
web_search(q, engines?, limit?, language?, time_range?, include_domains?, exclude_domains?)
web_fetch(url, format?, max_chars?)
batch_fetch(urls, format?, max_chars?, concurrency?)
crawl(url, depth?, max_pages?, format?)
md(url, max_chars?)
sem_search(q, engines?, limit?, fetch_top?, include_domains?, exclude_domains?)
      </pre>
    </div>
    <div class="card" style="margin-top:1.5rem;">
      <h2>Attribution</h2>
      <p>SemSearch is inspired by and builds upon:</p>
      <ul style="margin-left:1.5rem;margin-top:0.5rem;">
        <li><a href="https://github.com/searxng/searxng" style="color:#38bdf8;">SearXNG</a> (AGPL-3.0) - Meta search engine architecture</li>
        <li><a href="https://github.com/unclecode/crawl4ai" style="color:#38bdf8;">Crawl4AI</a> (Apache-2.0) - Web fetch/crawl functionality</li>
      </ul>
    </div>
  </div>
</div>

<div id="token-modal">
  <div class="modal-content">
    <h2 style="margin-bottom:1rem;">Admin Token</h2>
    <div class="form-group">
      <label>Enter admin token</label>
      <input type="password" id="admin-token" placeholder="SEMSEARCH_ADMIN_TOKEN">
    </div>
    <button class="btn" onclick="saveToken()">Save</button>
    <button class="btn btn-danger" onclick="hideTokenModal()" style="margin-left:0.5rem;">Cancel</button>
  </div>
</div>

<script>
document.title = 'SemSearch (WebSearchAPI)';
let adminToken = '';
const API = window.location.origin;

function showTokenModal() { document.getElementById('token-modal').classList.add('active'); }
function hideTokenModal() { document.getElementById('token-modal').classList.remove('active'); }
function saveToken() {
  adminToken = document.getElementById('admin-token').value;
  hideTokenModal();
  loadHealth();
}

function authHeader() { return adminToken ? { 'Authorization': 'Bearer ' + adminToken } : {}; }

async function loadHealth() {
  try {
    const res = await fetch(API + '/api/health');
    const data = await res.json();
    document.getElementById('status').textContent = data.status.toUpperCase();
    document.getElementById('status').className = 'stat ' + (data.status === 'ok' ? 'status-ok' : 'status-error');
    document.getElementById('uptime').textContent = data.uptime_sec + 's';
    document.getElementById('engine-count').textContent = data.enabled_engine_count + ' / ' + data.total_engine_count;
    document.getElementById('memory').textContent = data.memory_mb;
    document.getElementById('version').textContent = 'v' + data.version;
    document.getElementById('cpu').textContent = data.cpu_percent;
    document.getElementById('mem-system').textContent = data.memory_mb;
    document.getElementById('uptime-system').textContent = data.uptime_sec + 's';
  } catch(e) { document.getElementById('status').textContent = 'ERROR'; document.getElementById('status').className = 'stat status-error'; }
}

async function runSearch() {
  const q = document.getElementById('search-q').value;
  const limit = document.getElementById('search-limit').value;
  const lang = document.getElementById('search-lang').value;
  const time = document.getElementById('search-time').value;
  const include = document.getElementById('search-include').value;
  const exclude = document.getElementById('search-exclude').value;
  const engines = document.getElementById('search-engines').value;
  let url = API + '/api/search?q=' + encodeURIComponent(q) + '&limit=' + limit;
  if (lang) url += '&language=' + lang;
  if (time) url += '&time_range=' + time;
  if (include) url += '&include_domains=' + encodeURIComponent(include);
  if (exclude) url += '&exclude_domains=' + encodeURIComponent(exclude);
  if (engines) url += '&engines=' + encodeURIComponent(engines);
  try { const res = await fetch(url); const data = await res.json(); document.getElementById('search-result').textContent = JSON.stringify(data, null, 2); } catch(e) { document.getElementById('search-result').textContent = 'Error: ' + e.message; }
}

async function runFetch() {
  const url = document.getElementById('fetch-url').value;
  const fmt = document.getElementById('fetch-format').value;
  const chars = document.getElementById('fetch-chars').value;
  let req = API + '/api/fetch?url=' + encodeURIComponent(url) + '&format=' + fmt;
  if (chars) req += '&max_chars=' + chars;
  try { const res = await fetch(req); const data = await res.json(); document.getElementById('fetch-result').textContent = JSON.stringify(data, null, 2); } catch(e) { document.getElementById('fetch-result').textContent = 'Error: ' + e.message; }
}

async function runCrawl() {
  const url = document.getElementById('crawl-url').value;
  const depth = document.getElementById('crawl-depth').value;
  const pages = document.getElementById('crawl-pages').value;
  const fmt = document.getElementById('crawl-format').value;
  let req = API + '/api/crawl?url=' + encodeURIComponent(url) + '&depth=' + depth + '&max_pages=' + pages + '&format=' + fmt;
  try { const res = await fetch(req); const data = await res.json(); document.getElementById('crawl-result').textContent = JSON.stringify(data, null, 2); } catch(e) { document.getElementById('crawl-result').textContent = 'Error: ' + e.message; }
}

async function loadEngines() {
  try {
    const res = await fetch(API + '/api/engines');
    const data = await res.json();
    const tbody = document.getElementById('engine-table');
    tbody.innerHTML = '';
    for (const e of data.engines) {
      const status = e.last_probe_status || '-';
      const statusClass = status === 'ok' ? 'status-ok' : (status === 'error' ? 'status-error' : (status === 'timeout' || status === 'degraded' ? 'status-timeout' : ''));
      const sample = (e.last_probe_sample || []).map(r => r.title).filter(Boolean).slice(0, 2).join(' | ');
      const tr = document.createElement('tr');
      tr.innerHTML = `<td><strong>${escapeHtml(e.display_name || e.name)}</strong><div class="muted">${escapeHtml(e.name)}${e.registered ? '' : ' (not registered)'}</div></td>
        <td>${escapeHtml(e.category || '-')}</td>
        <td class="${statusClass}">${escapeHtml(status)}</td>
        <td>${e.latency_ms ? e.latency_ms + 'ms' : '-'}</td>
        <td>${Number.isInteger(e.last_result_count) ? e.last_result_count : '-'}${sample ? '<div class="engine-sample">' + escapeHtml(sample) + '</div>' : ''}</td>
        <td>${escapeHtml(e.last_error || '-')}</td>
        <td>${e.success_count || 0} / ${e.failure_count || 0}</td>
        <td><label class="toggle"><input type="checkbox" ${e.enabled ? 'checked' : ''} onchange="toggleEngine('${e.name}', this.checked)"><span class="toggle-slider"></span></label></td>
        <td><div class="engine-actions"><button class="btn btn-sm" onclick="probeEngine('${e.name}', this)">Probe</button></div></td>`;
      tbody.appendChild(tr);
    }
  } catch(e) { document.getElementById('engine-table').innerHTML = '<tr><td colspan="9">Error loading engines</td></tr>'; }
}

async function toggleEngine(name, enabled) {
  const endpoint = enabled ? 'enable' : 'disable';
  try {
    const res = await fetch(API + '/api/engines/' + name + '/' + endpoint, { method: 'POST', headers: authHeader() });
    const data = await res.json();
    if (res.ok) loadEngines();
    else alert(data.detail || 'Failed');
  } catch(e) { alert('Error: ' + e.message); }
}

async function probeEngine(name, btn) {
  const query = document.getElementById('engine-probe-query').value || 'weather';
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Probing...';
  }
  try {
    const res = await fetch(API + '/api/engines/' + name + '/probe?query=' + encodeURIComponent(query), { method: 'POST', headers: authHeader() });
    const data = await res.json();
    document.getElementById('engine-probe-result').textContent = JSON.stringify(data, null, 2);
    if (!res.ok) alert(data.detail || 'Probe failed');
    loadEngines();
  } catch(e) { alert('Error: ' + e.message); }
  finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Probe';
    }
  }
}

let browserHistory = [];
let browserHistoryIndex = -1;

function switchTab(name, el) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
  if (name === 'engines') loadEngines();
  if (name === 'logs') loadLogs();
}

async function runBrowserSearch() {
  const raw = document.getElementById('browser-query').value.trim();
  if (!raw) return;
  const prefix = 'https://semsearch/search?q=';
  let q;
  if (raw.startsWith(prefix)) {
    q = raw.slice(prefix.length).trim();
    if (!q) return;
  } else {
    q = raw;
  }
  if (browserHistoryIndex < browserHistory.length - 1) {
    browserHistory = browserHistory.slice(0, browserHistoryIndex + 1);
  }
  browserHistory.push({ raw: raw, query: q });
  browserHistoryIndex = browserHistory.length - 1;
  updateBrowserNavButtons();
  await executeBrowserSearch(q);
}

async function refreshBrowserSearch() {
  if (browserHistoryIndex >= 0 && browserHistoryIndex < browserHistory.length) {
    await executeBrowserSearch(browserHistory[browserHistoryIndex].query);
  }
}

function browserGoBack() {
  if (browserHistoryIndex > 0) {
    browserHistoryIndex--;
    const entry = browserHistory[browserHistoryIndex];
    document.getElementById('browser-query').value = entry.raw;
    updateBrowserNavButtons();
    executeBrowserSearch(entry.query);
  }
}

function browserGoForward() {
  if (browserHistoryIndex < browserHistory.length - 1) {
    browserHistoryIndex++;
    const entry = browserHistory[browserHistoryIndex];
    document.getElementById('browser-query').value = entry.raw;
    updateBrowserNavButtons();
    executeBrowserSearch(entry.query);
  }
}

function updateBrowserNavButtons() {
  document.getElementById('browser-back').disabled = browserHistoryIndex <= 0;
  document.getElementById('browser-forward').disabled = browserHistoryIndex >= browserHistory.length - 1;
}

async function executeBrowserSearch(q) {
  const loading = document.getElementById('browser-loading');
  const results = document.getElementById('browser-results');
  loading.style.display = 'flex';
  results.innerHTML = '';
  const limit = document.getElementById('browser-limit').value;
  let url = API + '/api/search?q=' + encodeURIComponent(q) + '&limit=' + limit;
  try {
    const res = await fetch(url);
    const data = await res.json();
    renderBrowserResults(data, q);
  } catch(e) {
    results.innerHTML = '<div class="browser-no-results">Error: ' + e.message + '</div>';
  } finally {
    loading.style.display = 'none';
  }
}

function renderBrowserResults(data, query) {
  const container = document.getElementById('browser-results');
  if (!data.results || data.results.length === 0) {
    container.innerHTML = '<div class="browser-no-results">No results found for <strong>' + escapeHtml(query) + '</strong></div>';
    return;
  }
  let html = '<div style="margin-bottom:0.75rem;color:#64748b;font-size:0.875rem;">About ' + data.total_results + ' results</div>';
  for (const r of data.results) {
    var displayUrl = '';
    try { displayUrl = r.url ? new URL(r.url).hostname : ''; } catch(e) { displayUrl = r.url || ''; }
    var urlEncoded = encodeURIComponent(r.url);
    var safeUrl = escapeHtml(r.url);
    html += '<div class="browser-result" data-url="' + urlEncoded + '">' +
      '<div class="browser-title"><a href="' + safeUrl + '" target="_blank" rel="noopener">' + escapeHtml(r.title) + '</a></div>' +
      '<div class="browser-url-display">' + escapeHtml(displayUrl) + '</div>' +
      '<div class="browser-snippet">' + escapeHtml(r.snippet) + '</div>' +
      (r.engine ? '<div class="browser-engine"><span>' + escapeHtml(r.engine) + '</span></div>' : '') +
      '<div class="browser-actions">' +
        '<button onclick="browserFetchResult(this)" data-url="' + safeUrl + '">Fetch</button>' +
      '</div>' +
      '<div class="browser-fetch-result"></div>' +
      '</div>';
  }
  container.innerHTML = html;
}

async function browserFetchResult(btn) {
  if (btn.classList.contains('fetching')) return;
  var url = btn.getAttribute('data-url');
  var resultDiv = btn.parentElement.nextElementSibling;
  if (resultDiv.style.display === 'block' && resultDiv.dataset.fetched) {
    resultDiv.style.display = 'none';
    btn.textContent = 'Fetch';
    return;
  }
  btn.classList.add('fetching');
  btn.textContent = 'Fetching...';
  resultDiv.style.display = 'block';
  resultDiv.innerHTML = '<div class="fetch-status">Fetching...</div>';
  try {
    var res = await fetch(API + '/api/fetch?url=' + encodeURIComponent(url) + '&format=markdown&max_chars=3000');
    var data = await res.json();
    if (data.status === 'success' || data.content) {
      resultDiv.innerHTML = '<button class="fetch-close" onclick="this.parentElement.style.display=\\'none\\'">x</button>' +
        '<div class="fetch-status" style="color:#4ade80;">Fetched (' + (data.latency_ms || 0) + 'ms)</div>' +
        '<pre>' + escapeHtml(data.content) + '</pre>';
    } else {
      resultDiv.innerHTML = '<button class="fetch-close" onclick="this.parentElement.style.display=\\'none\\'">x</button>' +
        '<div class="fetch-status fetch-error">Failed: ' + escapeHtml(data.error || 'Unknown error') + '</div>';
    }
    resultDiv.dataset.fetched = '1';
  } catch(e) {
    resultDiv.innerHTML = '<button class="fetch-close" onclick="this.parentElement.style.display=\\'none\\'">x</button>' +
      '<div class="fetch-status fetch-error">Error: ' + escapeHtml(e.message) + '</div>';
  } finally {
    btn.classList.remove('fetching');
    btn.textContent = 'Close';
  }
}

function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}


async function loadLogs() {
  const level = document.getElementById('logs-level').value;
  let url = API + '/api/logs?tail=500';
  if (level) url += '&level=' + level;
  try {
    const res = await fetch(url);
    const data = await res.json();
    const container = document.getElementById('logs-container');
    if (!data.logs || data.logs.length === 0) {
      container.innerHTML = '<div class="logs-placeholder">No logs available</div>';
      return;
    }
    const logsHtml = data.logs.map(l =>
      '<div class="log-line log-' + l.level + '">' +
      '<span style="color:#64748b;">' + escapeHtml(l.time) + '</span> ' +
      '<span style="color:#94a3b8;">[' + l.level + ']</span> ' +
      escapeHtml(l.message) +
      '</div>'
    ).join('');
    container.innerHTML = logsHtml;
  } catch(e) { /* ignore */ }
}

function clearLogs() {
  document.getElementById('logs-container').innerHTML = '<div class="logs-placeholder">Logs cleared</div>';
}

loadHealth();
setInterval(loadHealth, 30000);
</script>
</body>
</html>"""


def run_server(host: str = "127.0.0.1", port: Optional[int] = None, config_path: Optional[str] = None) -> None:
    if config_path:
        os.environ["SEMSEARCH_CONFIG"] = config_path
    config = load_config()
    logging.info("SemSearch starting on %s:%d", host, port or config.server.port)
    uvicorn.run(app, host=host, port=port or config.server.port)


def main() -> None:
    run_server(host="0.0.0.0")


if __name__ == "__main__":
    main()
