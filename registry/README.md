# MCP Registry

Central source of truth for all MCP server config across Claude, Codex, and Gemini.

See [AGENTS.md](../AGENTS.md) for full documentation.

## Quick Reference

```bash
python3 registry/sync_mcp.py --diff    # preview
python3 registry/sync_mcp.py --write   # apply
```

- `mcp-registry.toml` — server definitions + targets (committed)
- `mcp-registry.local.toml` — secret overrides (git-ignored)
- `sync_mcp.py` — applies registry to agent config files
