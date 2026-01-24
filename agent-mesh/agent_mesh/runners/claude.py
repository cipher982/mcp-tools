"""Claude Code CLI runner - uses hatch."""

import json

from agent_mesh.runners.base import run_subprocess
from agent_mesh.types import AgentResult, Usage


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
    """Run Claude Code CLI in headless mode via hatch.

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
        AWS_PROFILE: AWS profile for Bedrock auth
        AWS_REGION: AWS region for Bedrock
        ZAI_API_KEY: API key for zai backend
    """
    # Use hatch CLI - unified headless agent runner
    # Default to bedrock backend (matches previous behavior)
    backend = "bedrock"
    cmd = ["hatch", "-b", backend, "-t", str(timeout_s), "--json", prompt]

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
