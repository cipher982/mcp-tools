"""Core types for agent-mesh."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Usage(BaseModel):
    """Token usage statistics from agent run."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None


class Artifacts(BaseModel):
    """Artifacts produced by agent run."""

    files_written: list[str] = Field(default_factory=list)
    git_diff: str | None = None


class AgentResult(BaseModel):
    """Normalized result from any agent run."""

    agent: Literal["claude", "codex", "gemini", "unknown"]
    mode: Literal["headless"] = "headless"
    cwd: str
    ok: bool
    exit_code: int
    started_at: datetime
    ended_at: datetime
    duration_ms: int
    stdout: str
    stderr: str
    structured: dict[str, Any] = Field(default_factory=dict)
    artifacts: Artifacts = Field(default_factory=Artifacts)
    usage: Usage = Field(default_factory=Usage)

    def model_dump_json_pretty(self) -> str:
        """Return pretty-printed JSON."""
        return self.model_dump_json(indent=2)


class RunConfig(BaseModel):
    """Configuration for running an agent."""

    prompt: str
    cwd: str = Field(default=".")
    timeout_s: int = Field(
        default=1800,
        ge=1,
        le=7200,
        description="Timeout in seconds (default 1800=30min). Accounts for full agentic workflows including tool use, retries, and I/O.",
    )
    output_format: Literal["json", "text"] = "json"
    env: dict[str, str] = Field(default_factory=dict)
