"""Gemini CLI runner."""

import json

from agent_mesh.runners.base import run_subprocess
from agent_mesh.types import AgentResult, Usage


async def run_gemini(prompt: str, cwd: str, timeout_s: int = 1800) -> AgentResult:
    """Run Gemini CLI in headless mode.

    This runs a full agentic workflow (not a single LLM call), which includes
    tool use, retries, and I/O. The default 30min timeout accounts for this.
    """
    # Gemini CLI uses positional prompt and --output-format for JSON
    # --yolo auto-approves shell commands (required for headless execution)
    cmd = [
        "gemini",
        "--yolo",
        "--output-format",
        "json",
        prompt,
    ]

    exit_code, stdout, stderr, started_at, ended_at = await run_subprocess(
        cmd, cwd, timeout_s
    )

    duration_ms = int((ended_at - started_at).total_seconds() * 1000)

    # Gemini outputs JSON in headless mode
    structured: dict = {}
    usage = Usage()
    has_error = False

    if exit_code == 0 and stdout.strip():
        try:
            data = json.loads(stdout)
            # Only keep essential fields, not full conversation history
            if "response" in data:
                structured["response"] = data["response"]
            if "error" in data:
                structured["error"] = data["error"]
                has_error = True
            # Extract usage stats if present
            if "stats" in data:
                usage = Usage(
                    input_tokens=data["stats"].get("inputTokens"),
                    output_tokens=data["stats"].get("outputTokens"),
                )
                structured["stats"] = data["stats"]
        except json.JSONDecodeError:
            # Gemini might output plain text in some modes - truncate if huge
            max_raw = 2000
            raw = stdout.strip()[:max_raw]
            if len(stdout.strip()) > max_raw:
                raw += f"\n... [truncated {len(stdout.strip()) - max_raw} chars]"
            structured = {"response": raw}

    # Truncate stdout to avoid context blowup
    max_stdout = 2000
    truncated_stdout = stdout[:max_stdout]
    if len(stdout) > max_stdout:
        truncated_stdout += f"\n... [truncated {len(stdout) - max_stdout} chars]"

    return AgentResult(
        agent="gemini",
        cwd=cwd,
        ok=(exit_code == 0 and not has_error),
        exit_code=exit_code,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        stdout=truncated_stdout,
        stderr=stderr,
        structured=structured,
        usage=usage,
    )
