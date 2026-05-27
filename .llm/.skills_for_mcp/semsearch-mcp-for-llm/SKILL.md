---
name: semsearch-mcp-for-llm
description: Use SemSearch MCP reliably for LLMs, including small or local models (e.g., Ollama) that may have weak tool-selection ability. Trigger this skill when answering current, recent, web-backed, market, finance, news, event, URL-summary, crawling, or source-citation requests through SemSearch tools (`web_search`, `sem_search`, `web_fetch`, `md`, `crawl`).
---

# SemSearch MCP for LLM

## Core Rule

Use the actual SemSearch MCP tool call. Do not print JSON as a pretend tool call. Do not invent tool names. If SemSearch is unavailable, say that the SemSearch MCP server is not available and ask the user to enable it.

## Tool Choice

Choose exactly one first tool:

- Use `web_search` for current facts, recent news, prices, indexes, weather, events, and simple web lookup.
- Use `sem_search` for research-style questions where fetching top pages helps. Set `fetch_top` to `1` or `2`.
- Use `web_fetch` for a specific URL when the desired output format matters. Prefer `format: "markdown"` or `format: "text"`.
- Use `md` for a specific URL when a readable markdown summary is enough.
- Use `crawl` only when the user asks for a site crawl or information spread across multiple pages on the same site. Keep `depth` and `max_pages` small.

## First Call Recipes

For current or recent information:

```json
{ "q": "<entity> <metric/event> <timeframe> <current month year>", "limit": 5, "time_range": "week" }
```

For broad source-backed research:

```json
{ "q": "<specific topic plus date/context>", "limit": 5, "fetch_top": 2 }
```

For a URL summary:

```json
{ "url": "<url>", "max_chars": 12000 }
```

For crawling a small site area:

```json
{ "url": "<site or section url>", "depth": 1, "max_pages": 5, "format": "markdown" }
```

## Query Rules

- Include the entity, requested metric, timeframe, and current date context.
- For Korean questions, keep Korean proper nouns when useful and add English search terms if the topic is international.
- For market/index questions, search for close, price, chart, or official quote wording.
- Use `time_range: "day"`, `"week"`, `"month"`, or `"year"` only when the request is explicitly recent or time-bounded.
- Keep `limit` between `3` and `8`.

## Retry Rules

Retry at most twice:

1. If results are weak, make the query more specific with date, source type, location, or official name.
2. If results disagree, fetch or search for an official or primary source.
3. If results remain weak, answer with that limitation instead of guessing.

## Answer Rules

- Base the answer only on returned SemSearch sources.
- Cite source titles or URLs from the tool result.
- Use absolute dates for recent information.
- State uncertainty when sources are incomplete or inconsistent.
- Keep the final answer concise unless the user asks for detail.

## Examples

User: "KOSPI index for the past week"

Call `web_search`:

```json
{ "q": "KOSPI index past week close May 2026", "limit": 5, "time_range": "week" }
```

User: "Summarize https://example.com/report"

Call `md`:

```json
{ "url": "https://example.com/report", "max_chars": 12000 }
```

User: "Recent AI regulation news in Korea"

Call `sem_search`:

```json
{ "q": "South Korea AI regulation news May 2026", "limit": 5, "fetch_top": 2 }
```
