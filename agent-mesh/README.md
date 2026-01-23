# agent-mesh

MCP server for headless AI agent coordination. Spawns Claude, Codex, and Gemini agents.

## Tools

| Tool | Backend | Model |
|------|---------|-------|
| `claude_run` | AWS Bedrock | Claude Sonnet |
| `zai_run` | z.ai | GLM-4.7 |
| `codex_run` | OpenAI | GPT-5.2 Codex |
| `gemini_run` | Google | Gemini |

## Usage

```bash
cd agent-mesh && uv sync
uv run agent-mesh
```

## Direct CLI (without MCP)

Uses `hatch` CLI (`uv tool install -e ~/git/hatch`):

```bash
hatch "prompt"                    # z.ai (default)
hatch -b bedrock "prompt"         # AWS Bedrock
hatch -b codex "prompt"           # OpenAI Codex
hatch -b gemini "prompt"          # Google Gemini
hatch --json -b zai "prompt"      # JSON output
```

## Environment Variables

| Backend | Required |
|---------|----------|
| bedrock | `AWS_PROFILE`, `AWS_REGION` |
| zai | `ZAI_API_KEY` |
| codex | `OPENAI_API_KEY` |
| gemini | Gemini CLI OAuth (no key needed) |
