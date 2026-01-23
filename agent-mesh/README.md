# agent-mesh

MCP server exposing headless CLI runners for Claude, Codex, and Gemini.

## Tools

| Tool | Description |
|------|-------------|
| `claude_run` | Run Claude Code headlessly |
| `codex_run` | Run OpenAI Codex headlessly |
| `gemini_run` | Run Google Gemini CLI headlessly |

## Usage

```bash
cd agent-mesh && uv sync
uv run agent-mesh
```

## Raw Commands (for scripts)

If you don't need MCP, use these directly:

```bash
# Claude
claude-code -p "prompt" --dangerously-skip-permissions

# Codex
codex-agent low "prompt"

# Gemini
gemini-agent "prompt"
```

## Claude Code Backends

Claude Code can use different backends via environment variables:

```bash
# Default (Bedrock)
CLAUDE_CODE_USE_BEDROCK=1 claude-code -p "prompt"

# Direct Anthropic API
ANTHROPIC_API_KEY=... claude-code -p "prompt"

# z.ai (GLM models)
ANTHROPIC_BASE_URL="https://api.z.ai/api/anthropic" \
ANTHROPIC_API_KEY="<zai-key>" \
ANTHROPIC_MODEL="glm-4.7" \
claude-code -p "prompt"
```
