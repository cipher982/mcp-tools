"""MCP server exposing agent-mesh tools for stdio transport."""

import asyncio
import os
import sys
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP


def _find_host_cwd() -> str:
    """Walk up the process tree to find the host agent's working directory.

    The MCP server is spawned by the agent CLI (e.g. `uv run agent-mesh`),
    which is in turn started by Claude Code / Codex / Gemini from their
    project directory. We walk ancestors until we find one whose cwd contains
    a .git directory — that's the project root the host agent is working in.
    Falls back to os.getcwd() (server's own directory) if nothing is found.
    """
    try:
        import psutil
        proc = psutil.Process()
        for ancestor in proc.parents():
            try:
                cwd = ancestor.cwd()
                if os.path.isdir(cwd) and os.path.exists(os.path.join(cwd, ".git")):
                    return cwd
            except (psutil.AccessDenied, psutil.NoSuchProcess, PermissionError):
                continue
    except Exception:
        pass
    return os.getcwd()


_HOST_CWD = _find_host_cwd()

# Create MCP server
mcp = FastMCP(
    name="agent-mesh",
    instructions="Agent mesh for headless CLI coordination. 4 agents: Claude (Bedrock), z.ai (GLM-5), Codex (GPT-5.2), Gemini.",
)


@mcp.tool()
async def claude_run(
    prompt: Annotated[str, "The task or prompt. Include project context (audience, principles like YAGNI, what NOT to do) to avoid enterprise-pattern defaults"],
    cwd: Annotated[str, "Working directory (defaults to host agent's cwd)"] = "",
    model: Annotated[str | None, "Model ID (e.g., us.anthropic.claude-sonnet-4-5-20250929-v1:0)"] = None,
) -> str:
    """Run Claude Code CLI with AWS Bedrock (Claude Sonnet). Full agentic workflow with tool use. Default 30min timeout."""
    from agent_mesh.runners.claude import run_claude

    result = await run_claude(prompt, cwd or _HOST_CWD, 1800, auto_approve=True, model=model)
    return result.model_dump_json()


@mcp.tool()
async def zai_run(
    prompt: Annotated[str, "The task or prompt. Include project context (audience, principles like YAGNI, what NOT to do) to avoid enterprise-pattern defaults"],
    cwd: Annotated[str, "Working directory (defaults to host agent's cwd)"] = "",
) -> str:
    """Run Claude Code CLI with z.ai backend (GLM-5). Full agentic workflow with tool use. Default 30min timeout."""
    from agent_mesh.runners.zai import run_zai

    result = await run_zai(prompt, cwd or _HOST_CWD, 1800)
    return result.model_dump_json()


@mcp.tool()
async def codex_run(
    prompt: Annotated[str, "The task or prompt. Include project context (audience, principles like YAGNI, what NOT to do) to avoid enterprise-pattern defaults"],
    cwd: Annotated[str, "Working directory (defaults to host agent's cwd)"] = "",
    reasoning_effort: Annotated[str, "Reasoning effort: low, medium, high"] = "low",
) -> str:
    """Run Codex CLI (gpt-5.2-codex) in headless mode. Full agentic workflow with tool use. Default 30min timeout. Use higher reasoning_effort for complex tasks."""
    from agent_mesh.runners.codex import run_codex

    result = await run_codex(
        prompt, cwd or _HOST_CWD, 1800,
        json_events=True,
        reasoning_effort=reasoning_effort,  # type: ignore
    )
    return result.model_dump_json()


@mcp.tool()
async def gemini_run(
    prompt: Annotated[str, "The task or prompt. Include project context (audience, principles like YAGNI, what NOT to do) to avoid enterprise-pattern defaults"],
    cwd: Annotated[str, "Working directory (defaults to host agent's cwd)"] = "",
) -> str:
    """Run Gemini CLI in headless mode. Full agentic workflow with tool use. Default 30min timeout."""
    from agent_mesh.runners.gemini import run_gemini

    result = await run_gemini(prompt, cwd or _HOST_CWD, 1800)
    return result.model_dump_json()


def main():
    """Run the MCP server on stdio."""
    # Redirect logs to stderr to keep stdout clean for MCP protocol
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    asyncio.run(mcp.run_stdio_async())


if __name__ == "__main__":
    main()
