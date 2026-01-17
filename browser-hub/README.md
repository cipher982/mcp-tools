# Browser Hub

MCP server for browser automation with semantic element refs (@e1, @e2).

Uses [agent-browser](https://github.com/vercel-labs/agent-browser) CLI under the hood.

## Prerequisites

```bash
npm install -g agent-browser
agent-browser install
```

## Features

- **Smart snapshot filtering** - Returns only interactive elements (~500 tokens vs ~12k raw)
- **Batch form filling** - Fill multiple fields in ONE call via `fill_form` (works with React/Vue)
- **Combined look action** - Screenshot + filtered snapshot in one round trip
- Semantic element refs from accessibility tree
- Auto-isolated sessions per MCP instance
- Auth state save/load for sharing login across terminals

## Token Savings

| Before | After |
|--------|-------|
| ~12k tokens per snapshot | ~500-1k tokens (filtered) |
| 10+ round trips to fill 5 fields | 1 round trip (fill_form) |
| 2 calls to see page (screenshot + snapshot) | 1 call (look) |

## Usage

```bash
uv run browser-hub
```

## Actions

| Action | Required Params | Description |
|--------|-----------------|-------------|
| navigate | url | Go to URL |
| **look** | - | Screenshot + filtered snapshot in ONE call |
| snapshot | mode (optional) | Get elements (mode: "interactive" or "full") |
| click | ref | Click element (e.g., "@e1") |
| type | ref, text | Type into element |
| **fill_form** | fields | Fill multiple fields: `{"#email": "x@y.com", "#name": "John"}` |
| **get_value** | selector | Get current value of element (CSS selector like "#email") |
| press_key | key | Press keyboard key |
| screenshot | - | Take screenshot, returns path |
| wait | ref OR timeout_ms | Wait for element or time |
| evaluate | script | Run JavaScript |
| select | ref, values | Select dropdown option |
| state_save | path (optional) | Save auth state |
| state_load | path (optional) | Load auth state |
| close | - | Close browser |

## Example: Fast Form Filling

```python
# Old way: 10+ round trips
browser(action="type", ref="@e1", text="john@example.com")
browser(action="snapshot")
browser(action="type", ref="@e2", text="John")
browser(action="snapshot")
# ... repeat for each field

# New way: 1 round trip
browser(action="fill_form", fields={
    "#email": "john@example.com",
    "#firstName": "John",
    "#lastName": "Doe",
    "#country": "United States"
})
```
