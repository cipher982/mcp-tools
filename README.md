<p align="center">
  <img src="assets/header.svg" alt="MCP Tools" width="100%">
</p>

<p align="center">
  <a href="#installation"><img src="https://img.shields.io/badge/python-3.11+-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT License"></a>
  <a href="#tools"><img src="https://img.shields.io/badge/tools-4-orange?style=flat-square" alt="4 Tools"></a>
</p>

---

A personal collection of MCP servers I built for my Claude Code workflow. Some wrap heavier upstream servers to reduce token usage, others add capabilities that don't exist elsewhere.

## Tools

| Hub | Purpose | Backend | Notes |
|-----|---------|---------|-------|
| **[browser-hub](./browser-hub/)** | Browser automation | [agent-browser](https://github.com/vercel-labs/agent-browser) | 24x token reduction, batch form filling |
| **[search-hub](./search-hub/)** | Web research | OpenAI API | Synthesized answers with citations |
| **[image-hub](./image-hub/)** | Image generation | Vertex AI Gemini | Gemini 3 Pro native image gen |
| **[gdrive-hub](./gdrive-hub/)** | Google Drive access | Google Drive API | Service account auth, Shared Drives |

## Installation

Each tool is a standalone Python package managed with [uv](https://github.com/astral-sh/uv):

```bash
cd browser-hub && uv sync   # Browser automation
cd search-hub && uv sync    # Web research
cd image-hub && uv sync     # Image generation
cd gdrive-hub && uv sync    # Google Drive access
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
    },
    "gdrive-hub": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-tools/gdrive-hub", "gdrive-hub"],
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json",
        "GDRIVE_DRIVE_ID": "your-shared-drive-id"
      }
    }
  }
}
```

## Quick Start

### Browser Automation

```python
browser(action="navigate", url="https://example.com")
browser(action="look")  # Screenshot + filtered elements in ONE call

# Batch fill forms (10x faster than individual type calls)
browser(action="fill_form", fields={
    "#email": "user@example.com",
    "#name": "John Doe",
    "#country": "United States"
})

browser(action="click", ref="@e5")  # Refs from accessibility tree
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

### Google Drive

```python
# List files in root (or specific folder)
list_files()
list_files(folder_id="1ABC...")

# Search with Drive query syntax
list_files(query="name contains 'report'")
list_files(query="mimeType = 'application/pdf'")
list_files(query="modifiedTime > '2024-01-01'")

# Upload and download
upload_file(local_path="/tmp/doc.pdf", folder_id="1ABC...")
download_file(file_id="1XYZ...", export_format="pdf")  # Exports Google Docs
```

## Requirements

| Dependency | Purpose |
|------------|---------|
| Python 3.11+ | Runtime |
| [uv](https://github.com/astral-sh/uv) | Package management |
| [agent-browser](https://github.com/vercel-labs/agent-browser) | browser-hub (`npm i -g agent-browser && agent-browser install`) |
| OpenAI API key | search-hub |
| Google Cloud project | image-hub |
| Google service account | gdrive-hub (with Drive API access) |

## License

MIT
