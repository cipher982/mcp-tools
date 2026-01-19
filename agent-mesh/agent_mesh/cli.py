"""CLI for agent-mesh."""

from typing import Annotated

import typer

from agent_mesh import __version__

app = typer.Typer(
    name="agent-mesh",
    help="Headless agent mesh for Claude, Codex, and Gemini CLI cooperation.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Show version information."""
    typer.echo(f"agent-mesh {__version__}")


@app.command()
def doctor(
    cwd: Annotated[str, typer.Option("--cwd", "-C", help="Working directory")] = ".",
    agent: Annotated[list[str], typer.Option("--agent", "-a", help="Agents to check (repeatable)")] = [],
    mcp: Annotated[bool, typer.Option("--mcp/--no-mcp", help="Validate MCP server responds to tools/list")] = True,
    smoke: Annotated[bool, typer.Option("--smoke/--no-smoke", help="Make real LLM calls (costs money)")] = False,
    timeout: Annotated[int, typer.Option("--timeout", "-t", help="Timeout in seconds")] = 60,
    json_out: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON")] = False,
) -> None:
    """Sanity-check installation/auth and (optionally) run smoke calls."""
    import asyncio
    import json
    from pathlib import Path

    from agent_mesh.doctor import check_binaries, check_mcp_server_tools, run_smoke

    agents = agent or ["claude", "codex", "gemini"]
    cwd = str(Path(cwd).resolve())

    bins = check_binaries()
    selected_bins = {a: bins.get(a) for a in agents if a in bins}

    mcp_result = None
    if mcp:
        mcp_result = asyncio.run(check_mcp_server_tools(timeout_s=5))

    smoke_result = None
    if smoke:
        smoke_result = asyncio.run(run_smoke(agents=agents, cwd=cwd, timeout_s=timeout))

    payload = {
        "cwd": cwd,
        "binaries": {k: (v.__dict__ if v else None) for k, v in selected_bins.items()},
        "mcp": (mcp_result.__dict__ if mcp_result else None),
        "smoke": smoke_result,
    }

    if json_out:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(f"cwd: {cwd}")
        if mcp_result:
            typer.echo(f"mcp: {'ok' if mcp_result.ok else 'FAIL'}")
            if mcp_result.ok:
                typer.echo(f"  tools: {', '.join(mcp_result.tools)}")
            elif mcp_result.error:
                typer.echo(f"  error: {mcp_result.error}")

        for a in agents:
            b = selected_bins.get(a)
            if not b:
                continue
            status = "ok" if b.ok else "FAIL"
            details = []
            if b.version:
                details.append(b.version)
            if b.path:
                details.append(b.path)
            typer.echo(f"{a}: {status}" + (f" ({' | '.join(details)})" if details else ""))
            if b.warning:
                typer.echo(f"  warning: {b.warning}")

        if smoke_result:
            typer.echo("smoke:")
            for a in agents:
                r = smoke_result.get(a)
                if not r:
                    continue
                status = "ok" if r["ok"] else "FAIL"
                extra = f"{r['duration_ms']}ms"
                resp = r.get("response")
                if resp:
                    extra += f", response={resp[:60]!r}"
                typer.echo(f"  {a}: {status} ({extra})")
                if r.get("stderr"):
                    typer.echo(f"    stderr: {r['stderr']}")
        else:
            typer.echo("hint: run `agent-mesh smoke` to make a real call")

    ok = True
    for a in agents:
        b = selected_bins.get(a)
        if b and not b.ok:
            ok = False
    if mcp_result and not mcp_result.ok:
        ok = False
    if smoke_result and any(not r.get("ok") for r in smoke_result.values()):
        ok = False
    if not ok:
        raise typer.Exit(1)


@app.command()
def smoke(
    cwd: Annotated[str, typer.Option("--cwd", "-C", help="Working directory")] = ".",
    agent: Annotated[list[str], typer.Option("--agent", "-a", help="Agents to smoke-test (repeatable)")] = [],
    timeout: Annotated[int, typer.Option("--timeout", "-t", help="Timeout in seconds")] = 60,
    json_out: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON")] = False,
) -> None:
    """Run a minimal real call against each agent (costs money)."""
    agents = agent or ["claude", "codex", "gemini"]
    doctor(cwd=cwd, agent=agents, mcp=False, smoke=True, timeout=timeout, json_out=json_out)


@app.command()
def run(
    agent: Annotated[str, typer.Option("--agent", "-a", help="Agent to run: claude, codex, or gemini")],
    prompt: Annotated[str, typer.Option("--prompt", "-p", help="Prompt to send to the agent")],
    cwd: Annotated[str, typer.Option("--cwd", "-C", help="Working directory")] = ".",
    timeout: Annotated[int, typer.Option("--timeout", "-t", help="Timeout in seconds")] = 120,
) -> None:
    """Run a single agent in headless mode."""
    import asyncio
    import json

    from agent_mesh.runners import run_agent

    result = asyncio.run(run_agent(agent, prompt, cwd, timeout))
    typer.echo(result.model_dump_json(indent=2))


@app.command()
def pipeline(
    name: Annotated[str, typer.Argument(help="Pipeline name: review")],
    prompt: Annotated[str, typer.Option("--prompt", "-p", help="Prompt for the pipeline")] = "",
    cwd: Annotated[str, typer.Option("--cwd", "-C", help="Working directory")] = ".",
) -> None:
    """Run a pipeline (e.g., review: Claude implements → Codex reviews)."""
    if name == "review":
        import asyncio

        from agent_mesh.pipelines.review import run_review_pipeline

        result = asyncio.run(run_review_pipeline(prompt, cwd))
        typer.echo(result)
    else:
        typer.echo(f"Unknown pipeline: {name}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
