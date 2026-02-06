# MCP Tools - Agent Instructions

Lightweight MCP server facades that reduce token usage. Each hub wraps a heavier upstream into a minimal tool interface.

## Servers

| Server | Purpose | Upstream |
|--------|---------|----------|
| agent-mesh | Headless AI CLI runners | Claude/Codex/Gemini/z.ai CLIs |
| browser-hub | Browser automation | agent-browser CLI |
| search-hub | Web research | OpenAI API |
| image-hub | Image generation | Vertex AI Gemini |
| gdrive-hub | Google Drive access | Google Drive API |
| gmail | Email access | Gmail API (external repo) |
| life-hub-agents | Tasks, insights, smart home | Life-Hub (external repo) |
| context7 | Library docs lookup | Upstash Context7 (npx) |
| claude-session-history | Session history | claude-session-mcp (external) |
| atlassian | Jira/Confluence | MCP remote bridge |

## Central Registry

**`registry/mcp-registry.toml`** is the single source of truth for all MCP config across all agents.

Servers are defined once, then assigned to targets. Targets map to agent config files. To see the current mapping:

```bash
python3 registry/sync_mcp.py --list
```

### Sync Commands

```bash
python3 registry/sync_mcp.py --diff          # preview changes
python3 registry/sync_mcp.py --write         # apply all targets
python3 registry/sync_mcp.py --target claude_user --write  # one target
python3 registry/sync_mcp.py --list          # list servers + targets
python3 registry/sync_mcp.py --check         # exit 1 if drift detected
```

### Secrets / Local Overrides

`registry/mcp-registry.local.toml` (git-ignored) overrides server fields without touching the main registry. Use for API keys and passwords. The sync tool merges local overrides on top before applying.

`keep_env = true` on a target preserves existing env values in the config file (avoids overwriting secrets already set).

## Development

Each hub is an independent Python package: **FastMCP** + **uv** + **hatchling**.

### Adding a New Hub

1. Create `new-hub/` directory with `new_hub/server.py`
2. Implement with FastMCP (goal: <500 tokens for tool schema)
3. Add `[servers.new-hub]` to `registry/mcp-registry.toml`
4. Add to relevant target `servers` lists
5. `python3 registry/sync_mcp.py --write`

### Adding a Server to an Agent

Edit `registry/mcp-registry.toml` — add the server name to the target's `servers` list, then sync.

### Testing a Server

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0.0"}}}' \
  | timeout 10 uv run --directory <hub-dir> <hub-name> 2>/dev/null | head -3
```

## Design Principles

1. **Minimal tokens** - expose only essential parameters
2. **Sensible defaults** - don't require optional params
3. **Clear tool names** - `web_research` not `search`
4. **Lazy initialization** - only spawn upstream when first used
5. **Central registry** - one file defines all MCP config for all agents
