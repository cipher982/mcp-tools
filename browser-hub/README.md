# Browser Hub

Lightweight MCP facade for Playwright automation.

## Problem

The Playwright MCP plugin exposes 20+ tools, consuming ~13k tokens of context in every Claude Code session - even when you don't use browser automation.

## Solution

Browser Hub exposes **2 tools** (~300 tokens) that internally route to Playwright MCP:

- `browser(action, ...)` - Single browser action
- `browser_batch(steps)` - Multiple actions in sequence

## Token Savings

| Setup | MCP Tool Tokens |
|-------|-----------------|
| Playwright Plugin | ~13,000 |
| Browser Hub | ~300 |
| **Savings** | **~12,700 (97%)** |

## Installation

```bash
cd browser-hub
uv sync
```

## Configuration

1. **Disable Playwright plugin** in `~/.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "playwright@claude-plugins-official": false
  }
}
```

2. **Add browser-hub** to `~/.claude.json` mcpServers:

```json
{
  "mcpServers": {
    "browser-hub": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-tools/browser-hub", "browser-hub"]
    }
  }
}
```

## Usage

### Single Action

```python
# Navigate
browser(action="navigate", url="https://example.com")

# Get page structure (returns element refs like E1, E42)
browser(action="snapshot")

# Click element (ref + element required)
browser(action="click", ref="E5", element="Login button")

# Type into field (ref + element + text required)
browser(action="type", ref="E6", element="Email field", text="user@example.com")

# Press key
browser(action="press_key", key="Enter")

# Screenshot (inline image)
browser(action="screenshot")  # Returns ImageContent (renders in Claude Code)

# Screenshot (file path only, no base64 - good for batch workflows)
browser(action="screenshot_file")  # Returns file path like /tmp/.../page.png

# Wait for text
browser(action="wait_for", text="Welcome")

# Run JavaScript
browser(action="evaluate", script="() => document.title")

# Select dropdown
browser(action="select", ref="E10", element="Country", values=["US"])

# Close browser
browser(action="close")
```

### Batch Actions (Efficient)

For multi-step flows, use `browser_batch` to reduce round-trips:

```python
browser_batch(steps=[
    {"action": "navigate", "url": "https://example.com/login"},
    {"action": "snapshot"},
    {"action": "click", "ref": "E5", "element": "Login"},
    {"action": "type", "ref": "E6", "element": "Email", "text": "user@example.com"},
    {"action": "type", "ref": "E7", "element": "Password", "text": "password123"},
    {"action": "click", "ref": "E8", "element": "Submit"},
    {"action": "wait_for", "text": "Dashboard"},
    {"action": "snapshot"}
])
```

> **Note:** `browser_batch` omits image data from screenshot results to keep responses small. Use `browser(action="screenshot")` or `browser(action="screenshot_file")` separately if you need the actual image.

## Architecture

```
Claude Code
    │
    ▼
Browser Hub (FastMCP server, ~300 tokens)
    │ Persistent connection
    ▼
Playwright MCP (spawned on first use, kept warm)
    │
    ▼
Browser (Chromium)
```

Key design decisions:
- **Lazy initialization**: Playwright only spawns on first browser action
- **Persistent connection**: Same Playwright process for entire session
- **Facade pattern**: 2 tools wrap 20+ underlying tools
- **FastMCP Client**: Handles MCP protocol correctly (init, lifecycle, etc.)

## Requirements

- Node.js 18+ (for Playwright MCP)
- Python 3.11+
- `@playwright/mcp` (installed automatically via npx)
