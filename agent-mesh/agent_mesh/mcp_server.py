"""MCP server exposing agent-mesh tools for stdio transport."""

import asyncio
import sys
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP

# Create MCP server
mcp = FastMCP(
    name="agent-mesh",
    instructions="Agent mesh for headless CLI coordination. 4 agents: Claude (Bedrock), z.ai (GLM-4.7), Codex (GPT-5.2), Gemini.",
)


@mcp.tool()
async def claude_run(
    prompt: Annotated[str, "The task or prompt. Include project context (audience, principles like YAGNI, what NOT to do) to avoid enterprise-pattern defaults"],
    cwd: Annotated[str, "Working directory"] = ".",
    model: Annotated[str | None, "Model ID (e.g., us.anthropic.claude-sonnet-4-5-20250929-v1:0)"] = None,
) -> str:
    """Run Claude Code CLI with AWS Bedrock (Claude Sonnet). Full agentic workflow with tool use. Default 30min timeout."""
    from agent_mesh.runners.claude import run_claude

    result = await run_claude(prompt, cwd, 1800, auto_approve=True, model=model)
    return result.model_dump_json()


@mcp.tool()
async def zai_run(
    prompt: Annotated[str, "The task or prompt. Include project context (audience, principles like YAGNI, what NOT to do) to avoid enterprise-pattern defaults"],
    cwd: Annotated[str, "Working directory"] = ".",
) -> str:
    """Run Claude Code CLI with z.ai backend (GLM-4.7). Full agentic workflow with tool use. Default 30min timeout. Requires ZAI_API_KEY."""
    from agent_mesh.runners.zai import run_zai

    result = await run_zai(prompt, cwd, 1800)
    return result.model_dump_json()


@mcp.tool()
async def codex_run(
    prompt: Annotated[str, "The task or prompt. Include project context (audience, principles like YAGNI, what NOT to do) to avoid enterprise-pattern defaults"],
    cwd: Annotated[str, "Working directory"] = ".",
    reasoning_effort: Annotated[str, "Reasoning effort: low, medium, high"] = "low",
) -> str:
    """Run Codex CLI (gpt-5.2-codex) in headless mode. Full agentic workflow with tool use. Default 30min timeout. Use higher reasoning_effort for complex tasks."""
    from agent_mesh.runners.codex import run_codex

    result = await run_codex(
        prompt, cwd, 1800,
        json_events=True,
        reasoning_effort=reasoning_effort,  # type: ignore
    )
    return result.model_dump_json()


@mcp.tool()
async def gemini_run(
    prompt: Annotated[str, "The task or prompt. Include project context (audience, principles like YAGNI, what NOT to do) to avoid enterprise-pattern defaults"],
    cwd: Annotated[str, "Working directory"] = ".",
) -> str:
    """Run Gemini CLI in headless mode. Full agentic workflow with tool use. Default 30min timeout. Requires GEMINI_API_KEY."""
    from agent_mesh.runners.gemini import run_gemini

    result = await run_gemini(prompt, cwd, 1800)
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
