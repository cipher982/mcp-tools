"""Doctor/smoke checks for agent-mesh."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

from agent_mesh.runners import run_agent
from agent_mesh.types import AgentResult


@dataclass(frozen=True)
class BinaryCheck:
    name: str
    ok: bool
    path: str | None = None
    version: str | None = None
    warning: str | None = None


@dataclass(frozen=True)
class McpCheck:
    ok: bool
    tools: list[str] = field(default_factory=list)
    error: str | None = None


def _run_version(cmd: str) -> str | None:
    try:
        proc = subprocess.run(
            [cmd, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    out = (proc.stdout or proc.stderr).strip()
    return out.splitlines()[0].strip() if out else None


def check_binaries() -> dict[str, BinaryCheck]:
    checks: dict[str, BinaryCheck] = {}

    for name in ["claude", "codex", "gemini"]:
        path = shutil.which(name)
        if not path:
            checks[name] = BinaryCheck(name=name, ok=False, warning="not found on PATH")
            continue

        checks[name] = BinaryCheck(
            name=name,
            ok=True,
            path=path,
            version=_run_version(name),
        )

    # Add lightweight env warnings (not hard failures)
    if checks["codex"].ok and not os.environ.get("OPENAI_API_KEY"):
        checks["codex"] = replace(checks["codex"], warning="OPENAI_API_KEY is not set (Codex calls may fail)")

    # Bedrock hint (only if user is trying to use Bedrock)
    if os.environ.get("CLAUDE_CODE_USE_BEDROCK") == "1" and checks["claude"].ok:
        aws_profile = os.environ.get("AWS_PROFILE")
        aws_region = os.environ.get("AWS_REGION")
        if not aws_profile or not aws_region:
            checks["claude"] = replace(
                checks["claude"],
                warning="CLAUDE_CODE_USE_BEDROCK=1 but AWS_PROFILE/AWS_REGION not fully set (Claude calls may fail)",
            )

    return checks


async def check_mcp_server_tools(timeout_s: int = 5) -> McpCheck:
    """Start the MCP server and validate it responds to initialize + tools/list."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "agent_mesh.mcp_server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(Path.cwd()),
    )

    async def _send(msg: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write((json.dumps(msg) + "\n").encode())
        await proc.stdin.drain()

    async def _recv() -> dict:
        assert proc.stdout is not None
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout_s)
        return json.loads(line)

    try:
        await _send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "agent-mesh-doctor", "version": "0"},
                },
            }
        )
        init_resp = await _recv()
        if "result" not in init_resp:
            return McpCheck(ok=False, tools=[], error=f"initialize failed: {init_resp}")

        await _send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools_resp = await _recv()
        if "result" not in tools_resp:
            return McpCheck(ok=False, tools=[], error=f"tools/list failed: {tools_resp}")

        tools = [t["name"] for t in tools_resp["result"]["tools"]]
        required = {"claude_run", "codex_exec", "gemini_run"}
        missing = sorted(required - set(tools))
        if missing:
            return McpCheck(ok=False, tools=tools, error=f"missing tools: {missing}")

        return McpCheck(ok=True, tools=sorted(tools))
    except asyncio.TimeoutError:
        return McpCheck(ok=False, tools=[], error="timeout waiting for MCP response")
    except Exception as e:
        return McpCheck(ok=False, tools=[], error=str(e))
    finally:
        if proc.stdin:
            proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except Exception:
            proc.kill()


def _extract_response_text(result: AgentResult) -> str | None:
    s = result.structured or {}

    if result.agent == "codex":
        resp = s.get("response")
        return resp.strip() if isinstance(resp, str) else None

    if result.agent == "claude":
        for key in ["result", "output", "response", "text"]:
            v = s.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    if result.agent == "gemini":
        for key in ["response", "text"]:
            v = s.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # Best-effort for common nested shapes
        try:
            candidates = s.get("candidates")
            if isinstance(candidates, list) and candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if isinstance(parts, list) and parts:
                    text = parts[0].get("text")
                    if isinstance(text, str) and text.strip():
                        return text.strip()
        except Exception:
            pass
        return None

    return None


async def run_smoke(
    agents: list[str],
    cwd: str = ".",
    timeout_s: int = 60,
) -> dict[str, dict]:
    """Run a minimal real call against each requested agent."""
    prompt = "What is 2+2? Reply with just: 4"
    results: dict[str, dict] = {}

    for agent in agents:
        r = await run_agent(agent=agent, prompt=prompt, cwd=cwd, timeout_s=timeout_s)
        results[agent] = {
            "ok": r.ok,
            "exit_code": r.exit_code,
            "duration_ms": r.duration_ms,
            "response": _extract_response_text(r),
            "stderr": (r.stderr or "").strip()[:200] if not r.ok else "",
        }

    return results
