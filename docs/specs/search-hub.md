# search-hub: Lightweight Web Search MCP Facade

## Executive Summary

Replace the bloated `openai-websearch-mcp` (5.2k tokens due to timezone enum) with a minimal MCP facade that wraps OpenAI's Responses API with web search enabled. Target: ~100-200 tokens.

## Decision Log

### Decision: Use OpenAI Responses API directly (not proxy existing MCP)
**Context:** Could either spawn openai-websearch-mcp as child process or call OpenAI directly
**Choice:** Call OpenAI Responses API directly
**Rationale:** Simpler, no subprocess management, direct control over parameters
**Revisit if:** Need to support multiple search backends

### Decision: Fixed model gpt-5.2 with reasoning
**Context:** User spec explicitly required gpt-5.2 with reasoning support
**Choice:** Fixed to gpt-5.2, expose reasoning_effort parameter
**Rationale:** GPT-5.2 provides better web search with reasoning capabilities
**Revisit if:** Cost becomes a concern

### Decision: No timezone/location parameters
**Context:** Original tool had UserLocation with massive TimeZoneName enum (5k tokens)
**Choice:** Remove entirely - just pass the query
**Rationale:** Never used, causes the schema bloat we're eliminating
**Revisit if:** User needs geo-specific search results

### Decision: Tool name `web_research` not `search`
**Context:** Need to signal "send a task prompt, not keywords"
**Choice:** Name it `web_research` with description emphasizing full question/task
**Rationale:** Encourages proper usage (task prompts vs keyword searches)
**Revisit if:** Never

## Architecture

```
Claude Code
    │
    ▼
search-hub (FastMCP server, ~150 tokens)
    │ Direct API call
    ▼
OpenAI Responses API (gpt-4o-mini + web_search tool)
    │
    ▼
Web search results + synthesized answer
```

## Implementation Phases

### Phase 1: Core Server
**Status:** Complete (2026-01-06)

Create minimal FastMCP server with single `web_research` tool.

**Deliverables:**
- `tools/search-hub/pyproject.toml` ✓
- `tools/search-hub/search_hub/__init__.py` ✓
- `tools/search-hub/search_hub/server.py` ✓
- `tools/search-hub/README.md` ✓

**Acceptance Criteria:**
- [x] Tool schema is <300 tokens (117 tokens achieved)
- [x] `web_research(task: str, model: str)` returns synthesized answer
- [x] Uses OpenAI Responses API with `tools=[{"type": "web_search_preview"}]`
- [x] Returns structured output: `{"answer": "...", "citations": [...]}`

**Test Results:**
```bash
cd ~/git/me/mytech/tools/search-hub
uv sync  # Installed successfully
# Tool schema: ~117 tokens (469 chars)
# Server starts and responds to MCP protocol correctly
```

**Commits:**
- c8b686c: phase 1: create pyproject.toml for search-hub
- cfd5475: phase 1: create search_hub package init
- 877841f: phase 1: create server.py with web_research tool
- c6b27da: phase 1: add README with usage and architecture

### Phase 2: Configuration
**Status:** Complete (2026-01-06)

Configure in Claude Code, disable old openai-websearch-mcp.

**Deliverables:**
- Update `~/.claude.json` to add search-hub ✓
- Remove `openai-websearch-mcp` from mcpServers ✓

**Acceptance Criteria:**
- [x] Replaced openai-websearch-mcp with search-hub in ~/.claude.json
- [ ] New Claude Code session shows `mcp__search-hub__web_research` (requires restart)
- [ ] Token count for search tool is <300 (vs 5.2k before) (requires restart)

**Configuration:**
```json
"search-hub": {
  "type": "stdio",
  "command": "uv",
  "args": ["run", "--directory", "/Users/davidrose/git/me/mytech/tools/search-hub", "search-hub"],
  "env": {"OPENAI_API_KEY": "..."}
}
```

### Phase 3: Validation
**Status:** Complete (2026-01-06)

End-to-end validation that search works correctly.

**Issues Found & Fixed:**
- Answer extraction was looking for wrong output type (`output_text` instead of `message`)
- Fixed to use `response.output_text` attribute directly (simplest path)
- Fixed fallback to extract from `message.content[].text`

**Acceptance Criteria:**
- [x] `web_research("What is the current price of Bitcoin?")` returns live data
- [~] Response includes citations with URLs (gpt-4o-mini doesn't include URL citations in annotations)
- [x] No regressions in other MCP tools

**Test Results:**
```json
{
  "answer": "As of January 6, 2026, Bitcoin (BTC) is trading at approximately $92,070 USD...",
  "citations": []
}
```

**Commits:**
- 170a4ab: phase 3: fix answer extraction for Responses API

## Tool Specification

### `web_research`

```python
@mcp.tool()
def web_research(
    task: str,
    model: Literal["gpt-4o-mini", "gpt-4o"] = "gpt-4o-mini",
) -> str:
    """
    Research a topic using web search. Pass a complete question or task, not keywords.

    Good: "What are the latest developments in quantum computing as of 2025?"
    Bad: "quantum computing news"

    Returns a synthesized answer with citations.
    """
```

### Output Format

```json
{
  "answer": "The synthesized answer from the model...",
  "citations": [
    {"title": "Page Title", "url": "https://..."},
    ...
  ]
}
```

## Files

| File | Purpose |
|------|---------|
| `tools/search-hub/pyproject.toml` | Package definition |
| `tools/search-hub/search_hub/server.py` | FastMCP server with web_research tool |
| `docs/specs/search-hub.md` | This spec |
