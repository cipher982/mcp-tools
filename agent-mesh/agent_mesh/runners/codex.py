"""Codex CLI runner - uses hatch."""

import json
from typing import Literal

from agent_mesh.runners.base import run_subprocess
from agent_mesh.types import AgentResult

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh"]


async def run_codex(
    task: str,
    cwd: str,
    timeout_s: int = 1800,
    json_events: bool = True,
    model: str = "gpt-5.2-codex",
    reasoning_effort: ReasoningEffort = "low",
    web_search: bool = True,
) -> AgentResult:
    """Run Codex CLI exec in headless mode via hatch.

    This runs a full agentic workflow (not a single LLM call), which includes
    tool use, retries, and I/O. The default 30min timeout accounts for this.

    Args:
        task: The task to execute
        cwd: Working directory
        timeout_s: Timeout in seconds (default 1800=30min for full agentic workflow)
        json_events: If True, output JSONL events
        model: Model to use (default: gpt-5.2-codex)
        reasoning_effort: Reasoning effort level (none/low/medium/high/xhigh)
        web_search: Enable web search capability

    Environment variables respected:
        OPENAI_API_KEY: Required for Codex API access
    """
    # Use hatch CLI - unified headless agent runner
    cmd = ["hatch", "-b", "codex", "-t", str(timeout_s), "--json", task]

    exit_code, stdout, stderr, started_at, ended_at = await run_subprocess(
        cmd, cwd, timeout_s
    )

    duration_ms = int((ended_at - started_at).total_seconds() * 1000)

    # Parse JSON output from hatch
    structured: dict = {}
    response_text: str | None = None

    if stdout.strip():
        try:
            data = json.loads(stdout)
            if data.get("ok"):
                response_text = data.get("output", "")
            structured = data
        except json.JSONDecodeError:
            structured = {"raw_output": stdout[:2000]}

    # Truncate stdout to avoid context blowup
    max_stdout = 2000
    truncated_stdout = stdout[:max_stdout]
    if len(stdout) > max_stdout:
        truncated_stdout += f"\n... [truncated {len(stdout) - max_stdout} chars]"

    return AgentResult(
        agent="codex",
        cwd=cwd,
        ok=exit_code == 0 and structured.get("ok", False),
        exit_code=exit_code,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        stdout=truncated_stdout,
        stderr=stderr,
        structured=structured,
    )
