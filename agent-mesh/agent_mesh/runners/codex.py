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
    cmd = [
        "hatch", "-b", "codex",
        "-t", str(timeout_s),
        "--model", model,
        "--reasoning-effort", reasoning_effort,
        "--json", task,
    ]

    exit_code, stdout, stderr, started_at, ended_at = await run_subprocess(
        cmd, cwd, timeout_s
    )

    duration_ms = int((ended_at - started_at).total_seconds() * 1000)

    # Parse JSON output from hatch
    structured: dict = {}

    if stdout.strip():
        try:
            data = json.loads(stdout)
            structured = data
            # Drop stderr from structured — it contains the full session transcript
            # (tool calls, thinking, MCP logs) and is the main source of token bloat.
            # The final AI response in "output" is naturally bounded.
            structured.pop("stderr", None)
        except json.JSONDecodeError:
            structured = {"raw_output": stdout[:5000]}

    return AgentResult(
        agent="codex",
        cwd=cwd,
        ok=exit_code == 0 and structured.get("ok", False),
        exit_code=exit_code,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        stdout="",
        stderr="",
        structured=structured,
    )
