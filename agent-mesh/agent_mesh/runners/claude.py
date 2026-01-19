"""Claude Code CLI runner."""

import json
import os
from datetime import timezone

from agent_mesh.runners.base import run_subprocess
from agent_mesh.types import AgentResult, Artifacts, Usage


async def run_claude(
    prompt: str,
    cwd: str,
    timeout_s: int = 1800,
    auto_approve: bool = True,
    model: str | None = None,
    use_bedrock: bool | None = None,
    aws_profile: str | None = None,
    aws_region: str | None = None,
) -> AgentResult:
    """Run Claude Code CLI in print mode with JSON output.

    This runs a full agentic workflow (not a single LLM call), which includes
    tool use, retries, and I/O. The default 30min timeout accounts for this.

    Args:
        prompt: The prompt to send to Claude
        cwd: Working directory
        timeout_s: Timeout in seconds (default 1800=30min for full agentic workflow)
        auto_approve: If True, bypass permission checks (default True for headless)
        model: Model to use (defaults to env ANTHROPIC_MODEL)
        use_bedrock: Use Bedrock (defaults to env CLAUDE_CODE_USE_BEDROCK)
        aws_profile: AWS profile for Bedrock
        aws_region: AWS region for Bedrock

    Environment variables respected:
        CLAUDE_CODE_USE_BEDROCK: Set to "1" for Bedrock
        ANTHROPIC_MODEL: Model ID (e.g., us.anthropic.claude-sonnet-4-5-20250929-v1:0)
        ANTHROPIC_DEFAULT_HAIKU_MODEL: Haiku model for subtasks
        AWS_PROFILE: AWS profile for Bedrock auth
        AWS_REGION: AWS region for Bedrock
    """
    cmd = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "json",
    ]

    if auto_approve:
        cmd.append("--dangerously-skip-permissions")

    # Build environment - inherit from parent and add overrides
    env: dict[str, str] = {}

    # Bedrock configuration
    if use_bedrock or os.environ.get("CLAUDE_CODE_USE_BEDROCK") == "1":
        env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        env["AWS_PROFILE"] = aws_profile or os.environ.get("AWS_PROFILE", "")
        env["AWS_REGION"] = aws_region or os.environ.get("AWS_REGION", "us-east-1")

    # Model selection
    if model:
        env["ANTHROPIC_MODEL"] = model

    # Pass through other relevant env vars
    for key in ["ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL"]:
        if key in os.environ and key not in env:
            env[key] = os.environ[key]

    exit_code, stdout, stderr, started_at, ended_at = await run_subprocess(
        cmd, cwd, timeout_s, env=env if env else None
    )

    duration_ms = int((ended_at - started_at).total_seconds() * 1000)

    # Parse structured output if possible
    structured: dict = {}
    usage = Usage()
    is_error = False

    if stdout.strip():
        try:
            data = json.loads(stdout)
            # Only keep the essential fields, not full conversation/tool history
            if "result" in data:
                structured["result"] = data["result"]
            if "is_error" in data:
                structured["is_error"] = data["is_error"]
                is_error = data["is_error"]
            # Extract usage if present
            if "usage" in data:
                usage = Usage(
                    input_tokens=data["usage"].get("input_tokens"),
                    output_tokens=data["usage"].get("output_tokens"),
                    cached_input_tokens=data["usage"].get("cache_read_input_tokens"),
                )
                structured["usage"] = data["usage"]
        except json.JSONDecodeError:
            # Truncate raw output if it's huge
            max_raw = 2000
            raw = stdout[:max_raw]
            if len(stdout) > max_raw:
                raw += f"\n... [truncated {len(stdout) - max_raw} chars]"
            structured = {"raw_output": raw}

    # Truncate stdout to avoid context blowup
    max_stdout = 2000
    truncated_stdout = stdout[:max_stdout]
    if len(stdout) > max_stdout:
        truncated_stdout += f"\n... [truncated {len(stdout) - max_stdout} chars]"

    return AgentResult(
        agent="claude",
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
