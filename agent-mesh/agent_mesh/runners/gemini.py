"""Gemini CLI runner - uses hatch."""

import json

from agent_mesh.runners.base import run_subprocess
from agent_mesh.types import AgentResult, Usage


async def run_gemini(prompt: str, cwd: str, timeout_s: int = 1800) -> AgentResult:
    """Run Gemini CLI in headless mode via hatch.

    This runs a full agentic workflow (not a single LLM call), which includes
    tool use, retries, and I/O. The default 30min timeout accounts for this.
    """
    # Use hatch CLI - unified headless agent runner
    cmd = ["hatch", "-b", "gemini", "-t", str(timeout_s), "--json", prompt]

    exit_code, stdout, stderr, started_at, ended_at = await run_subprocess(
        cmd, cwd, timeout_s
    )

    duration_ms = int((ended_at - started_at).total_seconds() * 1000)

    # Parse JSON output from hatch
    structured: dict = {}
    usage = Usage()
    is_error = False

    if stdout.strip():
        try:
            data = json.loads(stdout)
            structured = data
            is_error = not data.get("ok", False)
            # Drop stderr from structured — it contains the full session transcript
            # (tool calls, thinking, MCP logs) and is the main source of token bloat.
            # The final AI response in "output" is naturally bounded.
            structured.pop("stderr", None)
        except json.JSONDecodeError:
            structured = {"raw_output": stdout[:5000]}

    return AgentResult(
        agent="gemini",
        cwd=cwd,
        ok=exit_code == 0 and not is_error,
        exit_code=exit_code,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        stdout="",
        stderr="",
        structured=structured,
        usage=usage,
    )
