"""Base runner utilities and dispatcher."""

import asyncio
import contextlib
import os
import signal
from datetime import datetime, timezone
from pathlib import Path

from agent_mesh.types import AgentResult


async def _terminate_then_kill(proc: asyncio.subprocess.Process, kill_grace_s: float = 3.0) -> None:
    """Gracefully stop a subprocess: SIGTERM first, escalate to SIGKILL if needed.

    Uses start_new_session=True (set at spawn time) so terminate/kill hit the
    entire process group, not just the immediate child — important when the child
    itself spawns agents (hatch → codex/claude/gemini).
    """
    if proc.returncode is not None:
        return  # already exited

    # 1) Polite: SIGTERM to the process group so children get it too
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGTERM)

    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(proc.wait(), timeout=kill_grace_s)

    if proc.returncode is not None:
        return

    # 2) Forceful: SIGKILL the process group
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)

    # Always reap to avoid zombies, even after SIGKILL
    await proc.wait()


async def run_subprocess(
    cmd: list[str],
    cwd: str,
    timeout_s: int,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str, datetime, datetime]:
    """Run a subprocess with timeout and capture output.

    Always returns a tuple, even on errors (FileNotFoundError, permission errors, etc).
    On timeout, returns partial output captured so far rather than losing everything.
    On cancellation (e.g. client pressed Escape), kills the subprocess before re-raising.
    """
    full_env = os.environ.copy()
    # Mark all agent-mesh sub-agents as sidechain so Longhouse hides them from the timeline.
    # The Stop hook inherits this env var and passes it to `longhouse-engine ship`.
    full_env["LONGHOUSE_IS_SIDECHAIN"] = "1"
    if env:
        full_env.update(env)

    started_at = datetime.now(timezone.utc)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,  # Close stdin to avoid MCP stdio conflicts
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=full_env,
            start_new_session=True,  # New process group so killpg reaches all children
        )
    except FileNotFoundError as e:
        ended_at = datetime.now(timezone.utc)
        return 127, "", f"Command not found: {cmd[0]} ({e})", started_at, ended_at
    except PermissionError as e:
        ended_at = datetime.now(timezone.utc)
        return 126, "", f"Permission denied: {e}", started_at, ended_at
    except NotADirectoryError as e:
        ended_at = datetime.now(timezone.utc)
        return 1, "", f"Invalid working directory: {cwd} ({e})", started_at, ended_at
    except Exception as e:
        ended_at = datetime.now(timezone.utc)
        return 1, "", f"Failed to start subprocess: {e}", started_at, ended_at

    # Stream output into buffers so we can return partial results on timeout
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []

    async def read_stream(stream: asyncio.StreamReader, chunks: list[bytes]) -> None:
        while True:
            chunk = await stream.read(8192)
            if not chunk:
                break
            chunks.append(chunk)

    try:
        await asyncio.wait_for(
            asyncio.gather(
                read_stream(proc.stdout, stdout_chunks),
                read_stream(proc.stderr, stderr_chunks),
                proc.wait(),
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        await asyncio.shield(_terminate_then_kill(proc))
        ended_at = datetime.now(timezone.utc)
        stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace")
        stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
        timeout_msg = f"\n\n[TIMEOUT after {timeout_s}s - partial output above]"
        return -1, stdout, stderr + timeout_msg, started_at, ended_at
    except asyncio.CancelledError:
        # Client disconnected (e.g. Escape in Claude Code) — kill subprocess before propagating
        await asyncio.shield(_terminate_then_kill(proc))
        raise

    ended_at = datetime.now(timezone.utc)
    return (
        proc.returncode or 0,
        b"".join(stdout_chunks).decode("utf-8", errors="replace"),
        b"".join(stderr_chunks).decode("utf-8", errors="replace"),
        started_at,
        ended_at,
    )


async def run_agent(agent: str, prompt: str, cwd: str = ".", timeout_s: int = 1800) -> AgentResult:
    """Dispatch to the appropriate agent runner.

    Note: These run full agentic workflows (not single LLM calls).
    Default 30min timeout accounts for tool use, retries, and I/O.
    """
    # Resolve cwd to absolute path
    cwd = str(Path(cwd).resolve())

    if agent == "claude":
        from agent_mesh.runners.claude import run_claude
        return await run_claude(prompt, cwd, timeout_s)
    elif agent == "codex":
        from agent_mesh.runners.codex import run_codex
        return await run_codex(prompt, cwd, timeout_s)
    elif agent == "gemini":
        from agent_mesh.runners.gemini import run_gemini
        return await run_gemini(prompt, cwd, timeout_s)
    else:
        # Return error result for unknown agent
        now = datetime.now(timezone.utc)
        return AgentResult(
            agent="unknown",
            cwd=cwd,
            ok=False,
            exit_code=1,
            started_at=now,
            ended_at=now,
            duration_ms=0,
            stdout="",
            stderr=f"Unknown agent: {agent}. Must be claude, codex, or gemini.",
        )
