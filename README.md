<p align="center">
  <img src="assets/header.svg" alt="MCP Tools" width="100%">
</p>

<p align="center">
  <a href="#installation"><img src="https://img.shields.io/badge/python-3.11+-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT License"></a>
  <a href="#tools"><img src="https://img.shields.io/badge/tools-3-orange?style=flat-square" alt="3 Tools"></a>
</p>

---

A personal collection of MCP servers I built for my Claude Code workflow. Some wrap heavier upstream servers to reduce token usage, others add capabilities that don't exist elsewhere.

## Tools

| Hub | Purpose | Backend | Notes |
|-----|---------|---------|-------|
| **[browser-hub](./browser-hub/)** | Browser automation | Playwright MCP | Reduces 13k tokens to ~300 |
| **[search-hub](./search-hub/)** | Web research | OpenAI API | Reduces 5k tokens to ~300 |
| **[image-hub](./image-hub/)** | Image generation | Vertex AI Gemini | New capability |

## Installation

Each tool is a standalone Python package managed with [uv](https://github.com/astral-sh/uv):

```bash
cd browser-hub && uv sync   # Browser automation
cd search-hub && uv sync    # Web research
cd image-hub && uv sync     # Image generation
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
    },
    "image-hub": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-tools/image-hub", "image-hub"],
      "env": {
        "GOOGLE_CLOUD_PROJECT": "${GOOGLE_CLOUD_PROJECT}"
      }
    }
  }
}
```

## Quick Start

### Browser Automation

```python
browser(action="navigate", url="https://example.com")
browser(action="snapshot")  # Returns element refs: E1, E2, E42...
browser(action="click", ref="E5", element="Login button")
browser(action="type", ref="E6", element="Email", text="user@example.com")

# Batch operations
browser_batch(steps=[
    {"action": "navigate", "url": "https://example.com"},
    {"action": "snapshot"},
    {"action": "click", "ref": "E5", "element": "Submit"}
])
```

### Web Research

```python
# Ask complete questions, not keywords
web_research(task="What are the latest developments in quantum computing?")
web_research(task="Compare React vs Vue", reasoning_effort="high")
```

### Image Generation

```python
# Generate images with Gemini
generate_image(prompt="A sunset over mountains", output_path="/tmp/sunset.png")
```

## Requirements

| Dependency | Purpose |
|------------|---------|
| Python 3.11+ | Runtime |
| [uv](https://github.com/astral-sh/uv) | Package management |
| Node.js 18+ | Playwright MCP (browser-hub) |
| OpenAI API key | search-hub |
| Google Cloud project | image-hub |

## License

MIT
