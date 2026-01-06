# browser-hub: Persistence & Content Handling Fix

## Executive Summary

Fix critical bugs in browser-hub where:
1. Playwright connection is **not actually persistent** - `async with client:` disconnects after each call
2. Non-text content (screenshots) is **silently dropped** - only `item.text` extracted
3. Clean up repo issues (tracked symlink, stale docs)

## Problem Analysis

### Bug 1: False Persistence

**Current code (server.py:171-183):**
```python
client = await get_playwright()
async with client:  # ← CONNECTS here
    result = await client.call_tool(tool_name, params)
    # ...
# ← DISCONNECTS here (Client.__aexit__)
```

The `get_playwright()` returns a cached `Client` instance, but every `browser()` call enters/exits the context manager, which:
- Calls `Client.__aenter__()` → starts MCP handshake, spawns Playwright
- Calls `Client.__aexit__()` → disconnects, Playwright dies

**Impact:** Workflow like `browser(); browser(); browser()` spawns 3 separate Playwright processes. Browser state lost between calls.

### Bug 2: Content Type Blindness

**Current code (server.py:176-180):**
```python
return "\n".join(
    item.text for item in result.content
    if hasattr(item, "text")
)
```

MCP content can be:
- `TextContent` → has `.text`
- `ImageContent` → has `.data` (base64) and `.mimeType`
- `EmbeddedResource` → has `.resource`

Screenshots return `ImageContent`, which is filtered out → "Action completed (no output)".

### Issue 3: Repo Hygiene

- `CLAUDE.md` symlink tracked in git (mode 120000) - breaks on Windows, against stated conventions
- `docs/specs/search-hub.md` is stale (wrong paths, wrong model, wrong field names)

## Decision Log

### Decision: Single long-lived connection with explicit lifecycle
**Context:** Need persistence across tool calls without leaking processes
**Choice:** Connect once at first use, disconnect on `close` action or server shutdown
**Rationale:** FastMCP Client supports staying connected; we just need to not use `async with`
**Revisit if:** Memory leaks observed in long-running sessions

### Decision: Return base64 images inline for screenshots
**Context:** Could return base64 inline, write to temp file, or skip
**Choice:** Return base64 data URI for image content
**Rationale:** Allows Claude to "see" screenshots; temp files add complexity
**Revisit if:** Base64 bloats responses too much (could add size limit)

### Decision: Pin Playwright MCP version
**Context:** Currently uses `@playwright/mcp@latest`
**Choice:** Pin to specific version for reproducibility
**Rationale:** `@latest` can break without warning
**Revisit if:** Need newer features

## Architecture

### Connection Lifecycle

```
Server Start
    │
    ▼
First browser() call
    │
    ├─→ Create Client + Transport
    ├─→ client.connect() (explicit)
    └─→ Store in global _playwright_client
    │
    ▼
Subsequent browser() calls
    │
    └─→ Reuse _playwright_client (already connected)
    │
    ▼
browser(action="close") OR Server Shutdown
    │
    └─→ client.disconnect() + clear global
```

### Content Handling

```
MCP Result
    │
    ├─→ TextContent → Extract .text
    ├─→ ImageContent → Convert to data URI (data:image/png;base64,...)
    └─→ Other → Log warning, skip
    │
    ▼
Combined output string
```

## Implementation Phases

### Phase 1: True Persistence
**Status:** ✅ Complete (commit: 63991a9)

Refactor connection management to connect once, stay connected.

**Changes:**
- ✅ Add `_connect_playwright()` that calls `client.connect()` once
- ✅ Remove `async with client:` from `browser()` and `browser_batch()`
- ✅ Add disconnection on `close` action
- ✅ Add `@mcp.on_shutdown` handler to cleanup

**Acceptance Criteria:**
- [x] `browser(); browser(); browser()` reuses same Playwright process
- [x] Browser state persists between calls (navigate → snapshot works)
- [x] `browser(action="close")` properly disconnects
- [x] No zombie Playwright processes after server shutdown

**Implementation Details:**
- Added `_playwright_connected` flag to track connection state
- `_connect_playwright()` checks flag and only connects once
- `_disconnect_playwright()` properly cleans up client and resets flags
- Both `browser()` and `browser_batch()` use `_connect_playwright()` instead of context manager
- Close action handled specially to trigger disconnection
- Shutdown handler ensures cleanup on server exit

**Test:**
```bash
# Manual test: Run these in sequence, should see same browser
browser(action="navigate", url="https://example.com")
browser(action="snapshot")  # Should show example.com content
browser(action="close")
```

### Phase 2: Content Type Handling
**Status:** ✅ Complete (commit: 553bb3b)

Handle ImageContent from screenshots.

**Changes:**
- ✅ Check content item type before extraction
- ✅ For ImageContent: return `data:{mimeType};base64,{data}`
- ✅ Add content type to output when mixed (text + image)

**Acceptance Criteria:**
- [x] `browser(action="screenshot")` returns base64 data URI
- [x] Text content still works as before
- [x] Mixed content (text + image) handled gracefully

**Implementation Details:**
- Added `extract_content()` helper function that checks `type` attribute of content items
- TextContent (type="text"): extracts `.text` attribute
- ImageContent (type="image"): formats as `data:{mimeType};base64,{data}`
- Mixed content: joins all parts with newlines
- Both `browser()` and `browser_batch()` use the helper
- Gracefully handles unknown content types (skips with no error)

**Test:**
```bash
browser(action="navigate", url="https://example.com")
browser(action="screenshot")  # Should return data:image/png;base64,...
```

### Phase 3: Integration Tests
**Status:** Not started

Add pytest tests that verify persistence and content handling.

**Deliverables:**
- `browser-hub/tests/test_persistence.py`
- `browser-hub/tests/test_content.py`
- CI-friendly test commands in README

**Acceptance Criteria:**
- [ ] Test verifies connection reuse (mock or real)
- [ ] Test verifies screenshot returns image data
- [ ] Tests can run in CI (with appropriate mocking)

### Phase 4: Cleanup
**Status:** Not started

Fix repo hygiene issues.

**Changes:**
- Remove CLAUDE.md from git tracking (keep local symlink)
- Update or remove stale `docs/specs/search-hub.md`
- Pin `@playwright/mcp` version

**Acceptance Criteria:**
- [ ] `git ls-files CLAUDE.md` returns nothing
- [ ] search-hub.md either updated or removed
- [ ] Playwright MCP version pinned in code

## Files to Modify

| File | Changes |
|------|---------|
| `browser-hub/browser_hub/server.py` | Connection lifecycle, content handling |
| `browser-hub/pyproject.toml` | Add pytest dev dependency |
| `browser-hub/tests/` | New test files |
| `docs/specs/search-hub.md` | Update or remove |
| `.gitignore` | Ensure CLAUDE.md ignored |

## Rollback Plan

If issues arise:
1. Each phase has separate commits
2. Can revert individual phases
3. Worst case: revert to pre-fix commit `da224e4`
