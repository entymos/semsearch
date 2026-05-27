"""Command line interface for SemSearch."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

import httpx

from semsearch.config import ensure_config_exists, get_config_path
from semsearch.server import run_server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="semsearch", description="Local web search/fetch MCP service")
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Run the SemSearch HTTP and MCP server")
    serve.add_argument("--host", default="127.0.0.1", help="Host to bind, default: 127.0.0.1")
    serve.add_argument("--port", type=int, default=None, help="Port to bind, default: config server.port")
    serve.add_argument("--config", default=None, help="Config file path")

    init_config = subparsers.add_parser("init-config", help="Create the default user config")
    init_config.add_argument("--config", default=None, help="Config file path")
    init_config.add_argument("--force", action="store_true", help="Overwrite an existing config")

    doctor = subparsers.add_parser("doctor", help="Check a running SemSearch server")
    doctor.add_argument("--base-url", default="http://localhost:8088", help="Server base URL")

    return parser


def _init_config(config: str | None, force: bool) -> int:
    path = Path(config).expanduser() if config else get_config_path()
    ensure_config_exists(path, force=force)
    print(f"Config ready: {path}")
    return 0


def _doctor(base_url: str) -> int:
    base_url = base_url.rstrip("/")
    try:
        with httpx.Client(timeout=10) as client:
            health = client.get(f"{base_url}/api/health")
            health.raise_for_status()
            tools = client.post(
                f"{base_url}/mcp",
                headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
            tools.raise_for_status()
    except Exception as exc:
        print(f"SemSearch doctor failed: {exc}", file=sys.stderr)
        return 1

    tool_count = len(tools.json().get("result", {}).get("tools", []))
    print(json.dumps({"status": "ok", "base_url": base_url, "tools": tool_count}, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        if args.config:
            os.environ["SEMSEARCH_CONFIG"] = args.config
        run_server(host=args.host, port=args.port, config_path=args.config)
        return 0
    if args.command == "init-config":
        return _init_config(args.config, args.force)
    if args.command == "doctor":
        return _doctor(args.base_url)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
