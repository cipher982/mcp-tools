# MCP Tools - Agent Instructions

Lightweight MCP facades for Claude Code that dramatically reduce token usage.

## Overview

This repo contains MCP servers that wrap heavier upstream servers:

| Tool | Purpose | Upstream |
|------|---------|----------|
| browser-hub | Browser automation | Playwright MCP |
| search-hub | Web research | OpenAI API directly |

## Development

Each tool is an independent Python package using:
- **FastMCP** for MCP server implementation
- **uv** for dependency management
- **hatchling** for building

### Structure

```
mcp-tools/
├── browser-hub/
│   ├── pyproject.toml
│   └── browser_hub/
│       ├── __init__.py
│       └── server.py
├── search-hub/
│   ├── pyproject.toml
│   └── search_hub/
│       ├── __init__.py
│       └── server.py
└── AGENTS.md
```

### Testing a Server

```bash
# Browser hub
cd browser-hub && uv sync
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0.0"}}}' | timeout 3 uv run browser-hub 2>/dev/null | head -5

# Search hub (needs OPENAI_API_KEY)
cd search-hub && uv sync
OPENAI_API_KEY=... echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0.0"}}}' | timeout 3 uv run search-hub 2>/dev/null | head -5
```

### Adding a New Hub

1. Create `new-hub/` directory with same structure
2. Implement server.py with FastMCP
3. Define minimal tool interface (goal: <500 tokens)
4. Add to main README table

## Design Principles

1. **Minimal tokens**: Expose only essential parameters
2. **Sensible defaults**: Don't require optional params
3. **Clear tool names**: `web_research` not `search` (signals "send a task")
4. **Structured output**: Return JSON when multiple fields needed
5. **Lazy initialization**: Only spawn upstream when first used
