# SemSearch MCP Client Configs

Start SemSearch before using these examples:

```sh
semsearch serve --host 127.0.0.1 --port 8088
```

MCP endpoint:

```text
http://localhost:8088/mcp
```

## Included Examples

| Client | Example file | Notes |
| --- | --- | --- |
| Codex | `.codex/config.toml` | HTTP MCP URL format |
| VSCode | `.vscode/mcp.json` | Workspace MCP config |
| Claude Code | `.claude-code/.mcp.json` | Project-scoped HTTP MCP config |
| Cursor | `.cursor/mcp.json` | Cursor MCP JSON config |
| Cline | `.cline/mcp.json` | Remote Streamable HTTP config |
| Continue | `.continue/mcpServers/semsearch.yaml` | YAML MCP block |
| Windsurf | `.windsurf/mcp_config.json` | Cascade remote HTTP config |
| Zed | `.zed/settings.json` | Uses `context_servers` |
| Generic | `generic/mcp-http.json` | Portable HTTP MCP JSON shape |

Some clients require adding this content to a user-level settings file instead of copying the whole directory. Keep the server running locally while the client connects.
