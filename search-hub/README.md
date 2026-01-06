# Search Hub

Lightweight MCP facade for OpenAI web search. Reduces bloated MCP servers from 5.2k tokens to <300 tokens.

## Why?

The original `openai-websearch-mcp` server has a massive timezone enum (TimeZoneName) that inflates the tool schema to 5.2k tokens. This wrapper eliminates unnecessary parameters and provides a minimal interface.

## Features

- **Single tool**: `web_research(task, reasoning_effort)` - pass a complete question, get a synthesized answer with citations
- **Minimal schema**: <300 tokens (vs 5.2k in original)
- **Direct OpenAI integration**: Uses OpenAI Responses API with `web_search_preview` tool
- **GPT-5.2 reasoning**: Adjustable reasoning effort (low/medium/high)
- **Structured output**: Returns JSON with `answer` and `sources` fields

## Installation

```bash
cd search-hub
uv sync
```

## Configuration

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
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

## Usage

```python
# Good: Complete question
web_research(task="What are the latest quantum computing breakthroughs in 2025?")

# With higher reasoning effort
web_research(task="Compare React vs Vue for large enterprise apps", reasoning_effort="high")

# Bad: Keywords (won't work well)
web_research(task="quantum computing news")
```

## Response Format

```json
{
  "answer": "The synthesized answer from the model...",
  "sources": [
    {"url": "https://example.com/article1"},
    {"url": "https://example.com/article2"}
  ]
}
```

## Environment Variables

- `OPENAI_API_KEY`: Required - your OpenAI API key

## Architecture

```
Claude Code
    │
    ▼
search-hub (FastMCP server, ~300 tokens)
    │ Direct API call
    ▼
OpenAI Responses API (gpt-5.2 + web_search_preview)
    │
    ▼
Web search results + synthesized answer
```

## Token Comparison

| Server | Tokens | Notes |
|--------|--------|-------|
| openai-websearch-mcp | 5,200 | Has UserLocation with TimeZoneName enum (500+ timezones) |
| search-hub | <300 | Minimal interface, no location parameters |

## Development

Test server startup:

```bash
cd search-hub
uv sync
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0.0"}}}' | timeout 3 uv run search-hub 2>/dev/null | head -5
```
