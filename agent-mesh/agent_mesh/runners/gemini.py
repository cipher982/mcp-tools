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
    cmd = ["hatch", "-b", "gemini", "--json", prompt]

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
            if "output" in data:
                structured["result"] = data["output"]
        except json.JSONDecodeError:
            structured = {"raw_output": stdout[:2000]}

    # Truncate stdout to avoid context blowup
    max_stdout = 2000
    truncated_stdout = stdout[:max_stdout]
    if len(stdout) > max_stdout:
        truncated_stdout += f"\n... [truncated {len(stdout) - max_stdout} chars]"

    return AgentResult(
        agent="gemini",
        cwd=cwd,
        ok=exit_code == 0 and not is_error,
        exit_code=exit_code,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        stdout=truncated_stdout,
        stderr=stderr,
        structured=structured,
        usage=usage,
    )
