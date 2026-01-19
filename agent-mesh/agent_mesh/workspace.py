"""Workspace utilities for git operations."""

import asyncio
from pathlib import Path


async def capture_git_diff(cwd: str, include_untracked: bool = True) -> str:
    """Capture git diff (staged + unstaged + untracked) in the working directory.

    Args:
        cwd: Working directory
        include_untracked: If True, include content of untracked files as pseudo-diffs
    """
    cwd_path = Path(cwd).resolve()

    # Check if it's a git repo (works in subdirectories too)
    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "--is-inside-work-tree",
        cwd=str(cwd_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0 or stdout.decode().strip() != "true":
        return ""

    parts: list[str] = []

    # Get combined diff (unstaged + staged)
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "HEAD",
        cwd=str(cwd_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    diff = stdout.decode("utf-8", errors="replace")
    if diff.strip():
        parts.append(diff)

    # Also include untracked files as pseudo-diffs
    if include_untracked:
        proc = await asyncio.create_subprocess_exec(
            "git", "ls-files", "--others", "--exclude-standard",
            cwd=str(cwd_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        untracked = stdout.decode("utf-8", errors="replace").strip().split("\n")

        for filename in untracked:
            if not filename:
                continue
            filepath = cwd_path / filename
            if filepath.exists() and filepath.is_file():
                try:
                    content = filepath.read_text(errors="replace")
                    # Format as a pseudo-diff for new file
                    lines = content.split("\n")
                    diff_lines = [f"+{line}" for line in lines]
                    parts.append(
                        f"diff --git a/{filename} b/{filename}\n"
                        f"new file mode 100644\n"
                        f"--- /dev/null\n"
                        f"+++ b/{filename}\n"
                        f"@@ -0,0 +1,{len(lines)} @@\n"
                        + "\n".join(diff_lines)
                    )
                except Exception:
                    pass

    return "\n".join(parts)


async def capture_git_status(cwd: str) -> str:
    """Capture git status in porcelain format."""
    cwd_path = Path(cwd).resolve()

    proc = await asyncio.create_subprocess_exec(
        "git", "status", "--porcelain",
        cwd=str(cwd_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode("utf-8", errors="replace")
