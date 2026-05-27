"""Shared MCP protocol helpers for SemSearch."""

from __future__ import annotations

import json
from typing import Any

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL_VERSION = PROTOCOL_VERSIONS[0]

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "web_search",
        "title": "Web Search",
        "description": "Search the web for information using multiple engines",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query"},
                "engines": {"type": "string", "description": "Comma-separated engine names (optional)"},
                "limit": {"type": "integer", "description": "Number of results (default 10, max 50)"},
                "language": {"type": "string", "description": "Language code (e.g. ko, en)"},
                "time_range": {"type": "string", "description": "Time range (day, week, month, year)"},
                "include_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only return results from these domains",
                },
                "exclude_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exclude results from these domains",
                },
            },
            "required": ["q"],
        },
    },
    {
        "name": "web_fetch",
        "title": "Web Fetch",
        "description": "Fetch a single URL and return content in specified format",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL"},
                "format": {
                    "type": "string",
                    "description": "Output format: markdown, html, text, json, xml",
                    "default": "markdown",
                },
                "max_chars": {"type": "integer", "description": "Maximum characters to return"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "batch_fetch",
        "title": "Batch Fetch",
        "description": "Fetch multiple URLs in parallel and return extracted content",
        "inputSchema": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target URLs (max 20)",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: markdown, html, text, json, xml",
                    "default": "markdown",
                },
                "max_chars": {"type": "integer", "description": "Maximum characters per URL"},
                "concurrency": {"type": "integer", "description": "Parallel fetches (1-10, default 5)"},
            },
            "required": ["urls"],
        },
    },
    {
        "name": "crawl",
        "title": "Crawl",
        "description": "Crawl a website starting from a seed URL with limited depth and pages",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Seed URL"},
                "depth": {"type": "integer", "description": "Crawl depth (1-5, default 1)"},
                "max_pages": {"type": "integer", "description": "Maximum pages to crawl (1-100, default 10)"},
                "format": {
                    "type": "string",
                    "description": "Output format: markdown, html, text, json, xml",
                    "default": "markdown",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "md",
        "title": "Markdown Fetch",
        "description": "Fetch a URL and return markdown content (shortcut for web_fetch with format=markdown)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL"},
                "max_chars": {"type": "integer", "description": "Maximum characters to return"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "sem_search",
        "title": "Search With Fetch",
        "description": "Web search with optional fetching of top results for richer context",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query"},
                "engines": {"type": "string", "description": "Comma-separated engine names (optional)"},
                "limit": {"type": "integer", "description": "Number of results (default 10)"},
                "fetch_top": {"type": "integer", "description": "Fetch and include content from top N results"},
                "include_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only return results from these domains",
                },
                "exclude_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exclude results from these domains",
                },
            },
            "required": ["q"],
        },
    },
]


def negotiate_protocol_version(requested: str | None) -> str:
    if requested in PROTOCOL_VERSIONS:
        return requested
    return DEFAULT_PROTOCOL_VERSION


def initialize_result(requested_version: str | None = None) -> dict[str, Any]:
    return {
        "protocolVersion": negotiate_protocol_version(requested_version),
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "semsearch", "version": "0.1.0"},
    }


def tool_result(payload: Any) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ]
    }


def tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": f"Error: {message}"}], "isError": True}


def jsonrpc_result(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def jsonrpc_error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}
