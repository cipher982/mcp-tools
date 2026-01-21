"""
Shared batch support for MCP hubs.

Adds a `batch` tool to any FastMCP server that runs multiple tool calls in parallel.
"""

import asyncio
from typing import Any


def add_batch_support(mcp_server, tools: dict[str, callable], max_concurrent: int = 10):
    """
    Add a batch tool to an MCP server for parallel execution.

    Args:
        mcp_server: FastMCP server instance
        tools: Dict mapping tool names to async functions
        max_concurrent: Max parallel operations (default 10)

    Usage:
        from shared.batch import add_batch_support

        add_batch_support(mcp, {
            "web_research": web_research,
            "other_tool": other_tool,
        })
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _execute_one(tool_name: str, args: dict) -> dict:
        """Execute a single tool call with error handling."""
        if tool_name not in tools:
            return {
                "ok": False,
                "error": {"type": "unknown_tool", "message": f"Unknown tool: {tool_name}"}
            }

        async with semaphore:
            try:
                result = await tools[tool_name](**args)
                return {"ok": True, "value": result}
            except Exception as e:
                return {
                    "ok": False,
                    "error": {"type": type(e).__name__, "message": str(e)}
                }

    @mcp_server.tool()
    async def batch(calls: list[dict]) -> dict:
        """
        Execute multiple tool calls in parallel.

        Args:
            calls: List of {tool: str, args: dict} objects
                   Example: [{"tool": "web_research", "args": {"task": "..."}}, ...]

        Returns:
            {
                "results": [{"ok": true, "value": ...}, {"ok": false, "error": {...}}, ...],
                "succeeded": 2,
                "failed": 1
            }
        """
        if not calls:
            return {"results": [], "succeeded": 0, "failed": 0}

        # Validate structure
        for i, call in enumerate(calls):
            if not isinstance(call, dict):
                return {
                    "results": [],
                    "succeeded": 0,
                    "failed": len(calls),
                    "error": f"Call {i} is not a dict"
                }
            if "tool" not in call:
                return {
                    "results": [],
                    "succeeded": 0,
                    "failed": len(calls),
                    "error": f"Call {i} missing 'tool' field"
                }

        # Execute all in parallel
        tasks = [
            _execute_one(call["tool"], call.get("args", {}))
            for call in calls
        ]
        results = await asyncio.gather(*tasks)

        succeeded = sum(1 for r in results if r["ok"])
        failed = len(results) - succeeded

        return {
            "results": list(results),
            "succeeded": succeeded,
            "failed": failed
        }

    return batch  # Return in case caller wants reference
