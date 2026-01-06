"""
Browser Hub - A lightweight MCP facade for Playwright.

Reduces ~20 Playwright tools (~13k tokens) to 2 tools (~300 tokens).
Maintains persistent Playwright connection for stateful browser sessions.
"""

import asyncio
import atexit
from typing import Literal, Any

import mcp.types as mcp_types
from fastmcp import FastMCP, Client
from fastmcp.client.transports import StdioTransport

# Create the hub server
mcp = FastMCP(
    "browser-hub",
    instructions="""
    Browser automation hub. Use browser() for single actions, browser_batch() for multi-step flows.

    Typical workflow:
    1. browser(action="navigate", url="https://example.com")
    2. browser(action="snapshot") -> returns element refs like E1, E2, E42
    3. browser(action="click", ref="E5", element="Login button")
    4. browser(action="type", ref="E6", element="Email field", text="user@example.com")
    """
)

# Global state for persistent Playwright connection
_playwright_client: Client | None = None
_playwright_transport: StdioTransport | None = None  # Keep reference for cleanup
_playwright_connected: bool = False
_playwright_lock = asyncio.Lock()


async def get_playwright() -> Client:
    """Get or create persistent Playwright MCP connection."""
    global _playwright_client, _playwright_transport

    async with _playwright_lock:
        if _playwright_client is None:
            # Create transport with keep_alive=True (default) for session persistence
            _playwright_transport = StdioTransport(
                command="npx",
                args=["-y", "@playwright/mcp@0.0.54"],
            )
            _playwright_client = Client(_playwright_transport)

        return _playwright_client


async def _connect_playwright() -> Client:
    """Ensure Playwright client is connected. Connects once, stays connected."""
    global _playwright_connected

    client = await get_playwright()

    async with _playwright_lock:
        if not _playwright_connected:
            # Use __aenter__ to establish connection (initializes MCP session)
            await client.__aenter__()
            _playwright_connected = True

    return client


async def _disconnect_playwright():
    """Disconnect from Playwright and cleanup."""
    global _playwright_client, _playwright_transport, _playwright_connected

    async with _playwright_lock:
        if _playwright_client is not None and _playwright_connected:
            # close() force-disconnects and closes transport/subprocess
            await _playwright_client.close()
            _playwright_connected = False
            _playwright_client = None
            _playwright_transport = None


# Map our simplified actions to Playwright MCP tool names
TOOL_MAP = {
    "navigate": "browser_navigate",
    "snapshot": "browser_snapshot",
    "click": "browser_click",
    "type": "browser_type",
    "press_key": "browser_press_key",
    "screenshot": "browser_take_screenshot",
    "screenshot_file": "browser_take_screenshot",  # Same tool, different output handling
    "wait_for": "browser_wait_for",
    "evaluate": "browser_evaluate",
    "select": "browser_select_option",
    "close": "browser_close",
}


def build_params(
    action: str,
    url: str | None,
    ref: str | None,
    element: str | None,
    text: str | None,
    key: str | None,
    script: str | None,
    values: list[str] | None,
    timeout: float | None,
) -> dict[str, Any]:
    """Build params dict for Playwright tool based on action."""
    params: dict[str, Any] = {}

    if action == "navigate":
        if url:
            params["url"] = url

    elif action == "snapshot":
        pass  # No params needed

    elif action == "click":
        if ref:
            params["ref"] = ref
        if element:
            params["element"] = element

    elif action == "type":
        if ref:
            params["ref"] = ref
        if element:
            params["element"] = element
        if text:
            params["text"] = text

    elif action == "press_key":
        if key:
            params["key"] = key

    elif action in ("screenshot", "screenshot_file"):
        pass  # Uses defaults

    elif action == "wait_for":
        if text:
            params["text"] = text
        if timeout:
            params["time"] = timeout

    elif action == "evaluate":
        if script:
            params["function"] = script

    elif action == "select":
        if ref:
            params["ref"] = ref
        if element:
            params["element"] = element
        if values:
            params["values"] = values

    elif action == "close":
        pass  # No params needed

    return params


def extract_content(result) -> list[mcp_types.ContentBlock]:
    """
    Extract content blocks from an MCP result, preserving rich content types.

    Important: Do NOT convert ImageContent to text (e.g., data URIs). Doing so can
    explode token usage (base64 screenshots) and break downstream model calls.
    """
    content = getattr(result, "content", None)
    if not content:
        return [mcp_types.TextContent(type="text", text="Action completed (no output)")]

    output_blocks: list[mcp_types.ContentBlock] = []
    for item in content:
        if isinstance(item, mcp_types.ContentBlock):
            output_blocks.append(item)
        else:
            output_blocks.append(
                mcp_types.TextContent(type="text", text=str(item))
            )

    return output_blocks or [
        mcp_types.TextContent(type="text", text="Action completed (no output)")
    ]


def extract_text_only(result) -> str:
    """
    Extract only text from an MCP result, omitting binary payloads.

    Use this for batch results to avoid massive responses when a step returns an image.
    """
    content = getattr(result, "content", None)
    if not content:
        return "Action completed (no output)"

    output_parts: list[str] = []
    for item in content:
        content_type = getattr(item, "type", None)
        if content_type == "text" and hasattr(item, "text") and item.text:
            output_parts.append(item.text)
        elif content_type == "image":
            mime_type = getattr(item, "mimeType", "image/*")
            data = getattr(item, "data", None)
            data_len = len(data) if isinstance(data, str) else 0
            output_parts.append(f"[image omitted: {mime_type} ({data_len} base64 chars)]")

    return "\n".join(output_parts) if output_parts else "Action completed (no output)"


@mcp.tool()
async def browser(
    action: Literal[
        "navigate", "snapshot", "click", "type", "press_key",
        "screenshot", "screenshot_file", "wait_for", "evaluate", "select", "close"
    ],
    url: str | None = None,
    ref: str | None = None,
    element: str | None = None,
    text: str | None = None,
    key: str | None = None,
    script: str | None = None,
    values: list[str] | None = None,
    timeout: float | None = None,
) -> list[mcp_types.ContentBlock]:
    """
    Browser automation with persistent session.

    Actions:
    - navigate: Go to URL (url required)
    - snapshot: Get page structure with element refs (E1, E2, etc.)
    - click: Click element (ref + element description required)
    - type: Type text into element (ref + element + text required)
    - press_key: Press keyboard key (key required, e.g. "Enter", "Tab")
    - screenshot: Take screenshot of current page (returns inline image)
    - screenshot_file: Take screenshot and return file path only (no base64)
    - wait_for: Wait for text to appear (text) or time in seconds (timeout)
    - evaluate: Run JavaScript (script required)
    - select: Select dropdown option (ref + values required)
    - close: Close browser

    Example workflow:
        browser(action="navigate", url="https://example.com")
        browser(action="snapshot")  # Returns refs like E1, E42
        browser(action="click", ref="E5", element="Login button")
        browser(action="type", ref="E6", element="Email field", text="user@example.com")
    """
    tool_name = TOOL_MAP.get(action)
    if not tool_name:
        return f"Unknown action: {action}. Valid actions: {list(TOOL_MAP.keys())}"

    # Handle close action specially - close browser then disconnect
    if action == "close":
        try:
            # First call browser_close to properly close the browser in Playwright
            if _playwright_connected and _playwright_client is not None:
                try:
                    await _playwright_client.call_tool("browser_close", {})
                except Exception:
                    pass  # Browser may already be closed, continue with disconnect
            # Then disconnect the MCP session
            await _disconnect_playwright()
            return [mcp_types.TextContent(type="text", text="Browser closed and disconnected")]
        except Exception as e:
            return [mcp_types.TextContent(type="text", text=f"Error closing browser: {e}")]

    params = build_params(action, url, ref, element, text, key, script, values, timeout)

    try:
        client = await _connect_playwright()
        result = await client.call_tool(tool_name, params)

        # screenshot_file: return only text (file path), omit image data
        if action == "screenshot_file":
            text_output = extract_text_only(result)
            return [mcp_types.TextContent(type="text", text=text_output)]

        # Preserve content blocks (text + image, etc.)
        return extract_content(result)
    except Exception as e:
        return [mcp_types.TextContent(type="text", text=f"Error: {e}")]


@mcp.tool()
async def browser_batch(
    steps: list[dict],
) -> list[str]:
    """
    Execute multiple browser actions in sequence. Efficient for multi-step flows.

    Each step is a dict with 'action' and relevant params.
    Stops on first error and returns results up to that point.

    Example:
        browser_batch(steps=[
            {"action": "navigate", "url": "https://example.com"},
            {"action": "snapshot"},
            {"action": "click", "ref": "E5", "element": "Login"},
            {"action": "type", "ref": "E6", "text": "user@example.com"},
            {"action": "type", "ref": "E7", "text": "password123"},
            {"action": "click", "ref": "E8", "element": "Submit"},
            {"action": "wait_for", "text": "Welcome"},
            {"action": "snapshot"}
        ])

    Returns list of results, one per step.
    """
    results: list[str] = []

    try:
        client = await _connect_playwright()

        for i, step in enumerate(steps):
            action = step.get("action")
            if not action:
                results.append(f"Step {i}: Missing 'action' key")
                break

            # Handle close action specially - close browser then disconnect
            if action == "close":
                try:
                    # First call browser_close to properly close the browser in Playwright
                    if _playwright_connected and _playwright_client is not None:
                        try:
                            await client.call_tool("browser_close", {})
                        except Exception:
                            pass  # Browser may already be closed, continue with disconnect
                    # Then disconnect the MCP session
                    await _disconnect_playwright()
                    results.append("Browser closed and disconnected")
                except Exception as e:
                    results.append(f"Step {i} error closing: {e}")
                break  # Close ends the batch

            tool_name = TOOL_MAP.get(action)
            if not tool_name:
                results.append(f"Step {i}: Unknown action '{action}'")
                break

            params = build_params(
                action=action,
                url=step.get("url"),
                ref=step.get("ref"),
                element=step.get("element"),
                text=step.get("text"),
                key=step.get("key"),
                script=step.get("script"),
                values=step.get("values"),
                timeout=step.get("timeout"),
            )

            try:
                result = await client.call_tool(tool_name, params)
                # Extract text only to avoid large binary payloads in batch mode.
                results.append(extract_text_only(result))
            except Exception as e:
                results.append(f"Step {i} error: {e}")
                break  # Stop on error

    except Exception as e:
        results.append(f"Connection error: {e}")

    return results


def _cleanup_sync():
    """
    Best-effort sync cleanup handler for atexit.

    Note: This may not work perfectly because FastMCP Client uses asyncio tasks
    tied to the original event loop. The primary cleanup mechanism is:
    1. User calls browser(action="close") explicitly
    2. OS cleans up orphaned subprocesses on parent exit

    This handler attempts cleanup but failures are acceptable.
    """
    global _playwright_client, _playwright_transport, _playwright_connected

    if not _playwright_connected:
        return

    # Try to access and terminate any subprocess via transport internals
    # This is fragile but better than nothing
    if _playwright_transport is not None:
        try:
            # StdioTransport may have a _connect_task that holds the subprocess
            # Try to cancel it (best effort)
            if hasattr(_playwright_transport, '_connect_task') and _playwright_transport._connect_task:
                _playwright_transport._connect_task.cancel()
        except Exception:
            pass

    # Mark as disconnected regardless of success
    _playwright_connected = False
    _playwright_client = None
    _playwright_transport = None


# Register cleanup handler
atexit.register(_cleanup_sync)


def main():
    """Entry point for the browser-hub server."""
    mcp.run()


if __name__ == "__main__":
    main()
