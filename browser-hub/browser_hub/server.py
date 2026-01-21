"""
Browser Hub - MCP server for browser automation with semantic element refs.

Uses agent-browser CLI under the hood to provide semantic element refs (@e1, @e2)
from the accessibility tree, making browser automation more reliable for AI agents.
"""

import asyncio
import atexit
import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP

mcp = FastMCP(
    "browser-hub",
    instructions="""
    Browser automation hub with semantic element refs.

    Key actions:
    - look: Screenshot + filtered snapshot in ONE call (use this to see the page)
    - fill_form: Fill multiple fields at once with {selector: value} dict - 10x faster than type
    - get_value: Check element value by CSS selector
    - snapshot: Get interactive elements (filtered by default, use mode="full" for all)

    Typical workflow:
    1. browser(action="navigate", url="https://example.com")
    2. browser(action="look") -> screenshot + filtered elements
    3. browser(action="fill_form", fields={"#email": "user@example.com", "#name": "John"})
    4. browser(action="click", ref="@e1")

    Element refs (@e1, @e2) come from the accessibility tree. Snapshots are filtered to
    interactive elements only (~500 tokens vs ~12k raw).
    """
)

# Auto-generate unique session ID for this MCP instance
_default_session = f"mcp-{secrets.token_hex(4)}"
_session_locks: dict[str, asyncio.Lock] = {}
_locks_lock = asyncio.Lock()  # Lock for accessing _session_locks dict
_state_dir = Path.home() / ".browser-hub" / "states"
_snapshot_dir = Path.home() / ".browser-hub" / "snapshots"


async def _get_session_lock(session: str) -> asyncio.Lock:
    """Get or create a lock for a specific session (enables per-session parallelism)."""
    async with _locks_lock:
        if session not in _session_locks:
            _session_locks[session] = asyncio.Lock()
        return _session_locks[session]

# Interactive roles - these are always included in filtered snapshots
_INTERACTIVE_ROLES = frozenset({
    # Form controls
    "button", "textbox", "searchbox", "combobox", "listbox",
    "checkbox", "radio", "switch", "slider", "spinbutton",
    # Navigation
    "link", "tab", "menuitem", "menuitemcheckbox", "menuitemradio",
    # Tree/grid items
    "treeitem", "gridcell", "row", "columnheader", "rowheader",
    # Containers that are interactive
    "menu", "menubar", "tablist", "tree", "treegrid",
})

# Roles to always skip - structural/presentational only
_SKIP_ROLES = frozenset({
    "option",  # Bloats snapshots, just show the select/combobox
    "generic", "none", "presentation",  # Non-semantic
    "paragraph", "text", "definition",  # Pure text content
    "separator", "img", "figure",  # Decorative
})


def _extract_state(data: dict) -> dict:
    """Extract relevant state from element data."""
    return {
        k: v for k, v in {
            "disabled": data.get("disabled"),
            "required": data.get("required"),
            "checked": data.get("checked"),
            "expanded": data.get("expanded"),
            "selected": data.get("selected"),
        }.items() if v is not None
    }


def _filter_elements(raw_elements: dict) -> tuple[dict, int]:
    """
    Filter to interactive elements only.

    Returns (filtered_dict, total_count).
    """
    total = len(raw_elements)
    filtered = {}

    for ref, data in raw_elements.items():
        role = data.get("role", "")

        # Always skip certain roles
        if role in _SKIP_ROLES:
            continue

        # Include interactive roles unconditionally
        if role in _INTERACTIVE_ROLES:
            state = _extract_state(data)
            filtered[ref] = {
                "role": role,
                "name": data.get("name", ""),
                **({"value": data["value"]} if data.get("value") else {}),
                **({"state": state} if state else {}),
            }
            continue

        # Include named headings (useful for navigation/context)
        name = data.get("name", "")
        if role == "heading" and name:
            filtered[ref] = {"role": role, "name": name}

    return filtered, total


def _save_full_snapshot(data: dict, session: str) -> Path | None:
    """Save full snapshot to disk for debugging (only if BROWSER_HUB_DEBUG is set)."""
    if not os.environ.get("BROWSER_HUB_DEBUG"):
        return None
    _snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = _snapshot_dir / f"{session}-{secrets.token_hex(4)}.json"
    snapshot_path.write_text(json.dumps(data, indent=2))
    return snapshot_path


def _get_screenshot_dir() -> Path:
    """Get screenshot directory: ./screenshots/ in cwd, fallback to ~/Pictures/browser-hub/."""
    cwd_dir = Path.cwd() / "screenshots"
    try:
        cwd_dir.mkdir(parents=True, exist_ok=True)
        # Test if writable
        test_file = cwd_dir / ".test"
        test_file.touch()
        test_file.unlink()
        return cwd_dir
    except (OSError, PermissionError):
        fallback = Path.home() / "Pictures" / "browser-hub"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _check_installation() -> str | None:
    """Check if agent-browser is installed. Returns error message or None."""
    if not shutil.which("agent-browser"):
        return (
            "agent-browser not found. Install with:\n"
            "  npm install -g agent-browser && agent-browser install"
        )
    return None


def _cleanup_session():
    """Kill daemon on exit to prevent zombie browsers."""
    try:
        subprocess.run(
            ["agent-browser", "--session", _default_session, "close"],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


atexit.register(_cleanup_session)


async def _run_cli(
    args: list[str], session: str | None = None, timeout: int = 30
) -> dict:
    """Run agent-browser CLI with JSON output."""
    sess = session or _default_session
    full_args = ["agent-browser", "--session", sess] + args + ["--json"]

    # Use per-session lock to allow parallelism across different sessions
    session_lock = await _get_session_lock(sess)
    async with session_lock:
        proc = await asyncio.create_subprocess_exec(
            *full_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            return {"success": False, "error": f"Timeout after {timeout}s", "retriable": True}

        if proc.returncode != 0:
            error_msg = (
                stderr.decode().strip()
                or stdout.decode().strip()
                or f"Exit code {proc.returncode}"
            )
            return {"success": False, "error": error_msg, "retriable": False}

        output = stdout.decode().strip()
        if not output:
            return {"success": True}

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"success": True, "output": output}


def _sanitize_name(name: str) -> str:
    """Sanitize a name for use in file paths."""
    return name.replace("/", "_").replace("..", "_").replace("\\", "_")


@mcp.tool()
async def browser(
    action: Literal[
        "navigate",
        "snapshot",
        "look",
        "click",
        "type",
        "fill_form",
        "press_key",
        "screenshot",
        "wait",
        "evaluate",
        "select",
        "get_value",
        "state_save",
        "state_load",
        "close",
    ],
    url: str | None = None,
    ref: str | None = None,
    text: str | None = None,
    key: str | None = None,
    script: str | None = None,
    values: list[str] | None = None,
    path: str | None = None,
    timeout_ms: int | None = None,
    session: str | None = None,
    mode: Literal["interactive", "full"] | None = None,
    fields: dict[str, str] | None = None,
    selector: str | None = None,
) -> str:
    """
    Browser automation with semantic element refs (@e1, @e2, etc).

    Actions:
    - navigate: Go to URL (url required)
    - snapshot: Get interactive elements with refs (mode: "interactive"|"full")
    - look: Screenshot + filtered snapshot in one call - use this to see the page
    - click: Click element (ref required, e.g. "@e1")
    - type: Type into element (ref, text required)
    - fill_form: Fill multiple fields at once (fields: {selector: value, ...}) - FAST batch fill
    - press_key: Press key (key required, e.g. "Enter", "Tab")
    - screenshot: Take screenshot, returns file path
    - wait: Wait for element (ref) or milliseconds (timeout_ms)
    - evaluate: Run JavaScript (script required)
    - select: Select dropdown (ref, values required)
    - get_value: Get current value of element (selector required, e.g. "#email")
    - state_save: Save auth state (path = name like "myapp")
    - state_load: Load auth state (path = name)
    - close: Close browser

    Element refs (@e1, @e2) come from the accessibility tree and are stable within a session.
    """
    if err := _check_installation():
        return json.dumps({"success": False, "error": err})

    if action == "navigate":
        if not url:
            return json.dumps({"success": False, "error": "url required for navigate"})
        result = await _run_cli(["open", url], session)

    elif action == "snapshot":
        sess = session or _default_session
        raw_result = await _run_cli(["snapshot", "-i"], session)

        if not raw_result.get("success", True) or raw_result.get("error"):
            result = raw_result
        else:
            # agent-browser returns {success, data: {refs, snapshot}, error}
            data = raw_result.get("data", {})
            raw_elements = data.get("refs", {})

            # Save full snapshot for debugging (only if BROWSER_HUB_DEBUG set)
            snapshot_path = _save_full_snapshot(raw_result, sess)

            # Filter unless mode=full
            if mode == "full":
                filtered = raw_elements
                total = len(raw_elements)
            else:
                filtered, total = _filter_elements(raw_elements)

            result = {
                "success": True,
                "elements": filtered,
                "element_count": len(filtered),
                "element_count_total": total,
                **({"snapshot_path": str(snapshot_path)} if snapshot_path else {}),
            }

    elif action == "look":
        # Combined screenshot + filtered snapshot in one call
        screenshot_dir = _get_screenshot_dir()
        out_path = screenshot_dir / f"screenshot-{secrets.token_hex(4)}.png"

        # Take screenshot
        screenshot_result = await _run_cli(["screenshot", str(out_path)], session)
        if not screenshot_result.get("success", True) or screenshot_result.get("error"):
            result = screenshot_result
        else:
            # Get snapshot
            raw_result = await _run_cli(["snapshot", "-i"], session)
            if not raw_result.get("success", True) or raw_result.get("error"):
                result = raw_result
            else:
                # agent-browser returns {success, data: {refs, snapshot}, error}
                data = raw_result.get("data", {})
                raw_elements = data.get("refs", {})

                # Always filter for look action (use snapshot with mode=full if you need everything)
                filtered, total = _filter_elements(raw_elements)

                result = {
                    "success": True,
                    "screenshot_path": str(out_path),
                    "elements": filtered,
                    "element_count": len(filtered),
                    "element_count_total": total,
                }

    elif action == "click":
        if not ref:
            return json.dumps({"success": False, "error": "ref required for click"})
        result = await _run_cli(["click", ref], session)

    elif action == "type":
        if not ref:
            return json.dumps({"success": False, "error": "ref required for type"})
        if text is None:
            return json.dumps({"success": False, "error": "text required for type"})
        result = await _run_cli(["fill", ref, text], session)

    elif action == "fill_form":
        # Batch fill multiple fields in ONE call via JS - huge speed boost
        if not fields:
            return json.dumps({
                "success": False,
                "error": "fields dict required: {selector: value, ...}"
            })

        # Safe JSON payload - escape for embedding in JS string literal
        fields_json = json.dumps(fields).replace("\\", "\\\\").replace("'", "\\'")
        fill_js = f"""
            (function(fieldsJson) {{
                const fields = JSON.parse(fieldsJson);
                const results = [];
                for (const [selector, value] of Object.entries(fields)) {{
                    const el = document.querySelector(selector);
                    if (!el) {{
                        results.push({{ selector, filled: false, error: 'not found' }});
                        continue;
                    }}
                    try {{
                        if (el.tagName === 'SELECT') {{
                            el.value = value;
                            el.dispatchEvent(new Event('change', {{bubbles: true}}));
                        }} else if (el.type === 'checkbox' || el.type === 'radio') {{
                            el.checked = value === true || value === 'true';
                            el.dispatchEvent(new Event('change', {{bubbles: true}}));
                        }} else if (el.isContentEditable) {{
                            el.textContent = value;
                            el.dispatchEvent(new InputEvent('input', {{bubbles: true, data: value}}));
                        }} else {{
                            // Use correct native setter based on element type
                            const proto = el.tagName === 'TEXTAREA'
                                ? window.HTMLTextAreaElement.prototype
                                : window.HTMLInputElement.prototype;
                            const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                            if (nativeSetter) {{
                                nativeSetter.call(el, value);
                            }} else {{
                                el.value = value;
                            }}
                            el.dispatchEvent(new Event('input', {{bubbles: true}}));
                            el.dispatchEvent(new Event('change', {{bubbles: true}}));
                        }}
                        results.push({{ selector, filled: true }});
                    }} catch (e) {{
                        results.push({{ selector, filled: false, error: e.message }});
                    }}
                }}
                return results;
            }})('{fields_json}')
        """
        js_result = await _run_cli(["eval", fill_js], session)

        if not js_result.get("success", True) or "error" in js_result:
            result = js_result
        else:
            result = {
                "success": True,
                "fields_filled": len(fields),
                "details": js_result.get("result", js_result),
            }

    elif action == "press_key":
        if not key:
            return json.dumps({"success": False, "error": "key required for press_key"})
        result = await _run_cli(["press", key], session)

    elif action == "screenshot":
        screenshot_dir = _get_screenshot_dir()
        out_path = screenshot_dir / f"screenshot-{secrets.token_hex(4)}.png"
        result = await _run_cli(["screenshot", str(out_path)], session)
        if result.get("success", True) and "error" not in result:
            result["path"] = str(out_path)

    elif action == "wait":
        if timeout_ms:
            result = await _run_cli(["wait", str(timeout_ms)], session)
        elif ref:
            result = await _run_cli(["wait", ref], session)
        else:
            return json.dumps(
                {"success": False, "error": "ref or timeout_ms required for wait"}
            )

    elif action == "evaluate":
        if not script:
            return json.dumps(
                {"success": False, "error": "script required for evaluate"}
            )
        result = await _run_cli(["eval", script], session)

    elif action == "select":
        if not ref:
            return json.dumps({"success": False, "error": "ref required for select"})
        if not values:
            return json.dumps(
                {"success": False, "error": "values required for select"}
            )
        result = await _run_cli(["select", ref, *values], session)

    elif action == "get_value":
        # Quick value check for a single element using CSS selector
        if not selector:
            return json.dumps({
                "success": False,
                "error": "selector required for get_value (CSS selector like '#email')"
            })

        # Safe JSON injection for selector - escape for JS string literal
        selector_json = json.dumps(selector).replace("\\", "\\\\").replace("'", "\\'")
        js_get_value = f"""
            (function(selectorJson) {{
                const selector = JSON.parse(selectorJson);
                const el = document.querySelector(selector);
                if (!el) return {{ error: 'Element not found', selector }};
                return {{
                    selector,
                    value: el.value ?? el.textContent?.trim() ?? null,
                    checked: el.checked ?? null,
                    selectedIndex: el.selectedIndex ?? null,
                    selectedText: el.selectedOptions?.[0]?.text ?? null,
                    tagName: el.tagName,
                    type: el.type ?? null
                }};
            }})('{selector_json}')
        """
        result = await _run_cli(["eval", js_get_value], session)

    elif action == "state_save":
        _state_dir.mkdir(parents=True, exist_ok=True)
        name = _sanitize_name(path or "default")
        state_path = _state_dir / f"{name}.json"
        result = await _run_cli(["state", "save", str(state_path)], session)
        if result.get("success", True) and "error" not in result:
            result["state_path"] = str(state_path)

    elif action == "state_load":
        name = _sanitize_name(path or "default")
        state_path = _state_dir / f"{name}.json"
        if not state_path.exists():
            return json.dumps(
                {"success": False, "error": f"State '{name}' not found at {state_path}"}
            )
        result = await _run_cli(["state", "load", str(state_path)], session)

    elif action == "close":
        result = await _run_cli(["close"], session)

    else:
        return json.dumps({"success": False, "error": f"Unknown action: {action}"})

    return json.dumps(result, indent=2)


@mcp.tool()
async def browser_batch(steps: list[dict]) -> str:
    """
    Execute multiple browser actions in sequence. Stops on first error.

    Each step is a dict with 'action' and relevant params.

    Example:
        browser_batch(steps=[
            {"action": "navigate", "url": "https://example.com"},
            {"action": "snapshot"},
            {"action": "click", "ref": "@e1"},
            {"action": "type", "ref": "@e2", "text": "user@example.com"},
            {"action": "press_key", "key": "Enter"},
            {"action": "wait", "timeout_ms": 1000},
            {"action": "snapshot"}
        ])

    Returns list of results, one per step.
    """
    results = []

    for i, step in enumerate(steps):
        action = step.get("action")
        if not action:
            results.append({"step": i, "success": False, "error": "Missing 'action'"})
            break

        result_str = await browser(
            action=action,
            url=step.get("url"),
            ref=step.get("ref"),
            text=step.get("text"),
            key=step.get("key"),
            script=step.get("script"),
            values=step.get("values"),
            path=step.get("path"),
            timeout_ms=step.get("timeout_ms"),
            session=step.get("session"),
            mode=step.get("mode"),
            fields=step.get("fields"),
            selector=step.get("selector"),
        )

        result = json.loads(result_str)
        results.append({"step": i, **result})

        if not result.get("success", True) or "error" in result:
            break

    return json.dumps(results, indent=2)


# Add batch support for parallel execution
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.batch import add_batch_support

add_batch_support(mcp, {
    "browser": browser,
    "browser_batch": browser_batch,
})


def main():
    """Entry point for browser-hub server."""
    mcp.run()


if __name__ == "__main__":
    main()
