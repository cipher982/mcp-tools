# MCP Tools

Lightweight MCP (Model Context Protocol) facades for Claude Code. These tools wrap heavy MCP servers to reduce token usage while maintaining functionality.

## Tools

| Tool | Wraps | Token Savings |
|------|-------|---------------|
| [browser-hub](./browser-hub/) | Playwright MCP (~20 tools) | 13k → 300 (~97%) |
| [search-hub](./search-hub/) | OpenAI web search | 5.2k → 300 (~94%) |

## Philosophy

MCP servers often expose every possible parameter, inflating tool schemas to thousands of tokens. These facades:

- **Reduce** token usage by exposing only essential parameters
- **Simplify** APIs with sensible defaults
- **Maintain** full functionality through internal routing

## Installation

Each tool is a standalone Python package:

```bash
cd browser-hub && uv sync
cd search-hub && uv sync
```

## Configuration

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "browser-hub": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-tools/browser-hub", "browser-hub"]
    },
    "search-hub": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-tools/search-hub", "search-hub"],
      "env": {
        "OPENAI_API_KEY": "${OPENAI_API_KEY}"
      }
    }
  }
}
```

## Requirements

- Python 3.11+
- uv (Python package manager)
- Node.js 18+ (for browser-hub, spawns Playwright MCP)
- OpenAI API key (for search-hub)

## License

MIT
