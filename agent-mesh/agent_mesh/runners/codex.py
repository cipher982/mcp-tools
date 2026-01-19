"""Codex CLI runner."""

import json
import os
from typing import Literal

from agent_mesh.runners.base import run_subprocess
from agent_mesh.types import AgentResult, Usage

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
    """Run Codex CLI exec in headless mode.

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
    # Use codex-agent wrapper - handles config + auto-detects headless mode
    cmd = ["codex-agent", reasoning_effort, task]

    exit_code, stdout, stderr, started_at, ended_at = await run_subprocess(
        cmd, cwd, timeout_s
    )

    duration_ms = int((ended_at - started_at).total_seconds() * 1000)

    # Parse JSONL events if json mode
    structured: dict = {}
    response_text: str | None = None
    event_count = 0

    if json_events and stdout.strip():
        for line in stdout.strip().split("\n"):
            if line.strip():
                try:
                    event = json.loads(line)
                    event_count += 1
                    # Extract final agent message
                    # Codex emits: {"type":"item.completed","item":{"type":"agent_message","text":"..."}}
                    if event.get("type") == "item.completed":
                        item = event.get("item", {})
                        if item.get("type") == "agent_message" and "text" in item:
                            response_text = item["text"]
                except json.JSONDecodeError:
                    pass

        # Only keep the response, not the full event log (can be 60k+ tokens)
        if response_text:
            structured["response"] = response_text
        structured["event_count"] = event_count

    # Truncate stdout to avoid context blowup (test output can be huge)
    max_stdout = 2000
    truncated_stdout = stdout[:max_stdout]
    if len(stdout) > max_stdout:
        truncated_stdout += f"\n... [truncated {len(stdout) - max_stdout} chars]"

    return AgentResult(
        agent="codex",
        cwd=cwd,
        ok=exit_code == 0,
        exit_code=exit_code,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        stdout=truncated_stdout,
        stderr=stderr,
        structured=structured,
    )
