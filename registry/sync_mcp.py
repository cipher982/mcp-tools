#!/usr/bin/env python3
"""Sync MCP registry to Claude Code and project .mcp.json files.

Default behavior is dry-run. Use --write to apply changes.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

import tomllib


def _expand_path(path_str: str) -> Path:
    return Path(os.path.expanduser(path_str)).resolve()


def _merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merged[key] = {**base[key], **value}
        else:
            merged[key] = value
    return merged


def _apply_overrides(
    desired: Dict[str, Any],
    overrides: Dict[str, Any] | None,
) -> Dict[str, Any]:
    if not overrides:
        return desired
    out: Dict[str, Any] = {}
    for name, cfg in desired.items():
        override = overrides.get(name)
        if isinstance(override, dict):
            out[name] = _merge_dict(cfg, override)
        else:
            out[name] = cfg
    return out


def _load_registry(path: Path) -> Dict[str, Any]:
    data = tomllib.loads(path.read_text())
    if "servers" not in data or "targets" not in data:
        raise ValueError("Registry must include [servers] and [targets] sections")

    local_path = path.with_name("mcp-registry.local.toml")
    if local_path.exists():
        local_data = tomllib.loads(local_path.read_text())
        if "servers" in local_data:
            servers = data.get("servers", {})
            for name, cfg in local_data["servers"].items():
                if name in servers and isinstance(cfg, dict):
                    servers[name] = _merge_dict(servers[name], cfg)
                else:
                    servers[name] = cfg
            data["servers"] = servers
        if "targets" in local_data:
            targets = data.get("targets", {})
            for name, cfg in local_data["targets"].items():
                if name in targets and isinstance(cfg, dict):
                    targets[name] = _merge_dict(targets[name], cfg)
                else:
                    targets[name] = cfg
            data["targets"] = targets
    return data


def _validate_servers(servers: Dict[str, Any]) -> None:
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"Server '{name}' must be a table/dict")
        if "type" not in cfg:
            raise ValueError(f"Server '{name}' missing required 'type'")
        if "command" not in cfg:
            raise ValueError(f"Server '{name}' missing required 'command'")
        if "args" not in cfg or not isinstance(cfg["args"], list):
            raise ValueError(f"Server '{name}' missing required 'args' list")


def _merge_env(existing: Dict[str, Any], desired: Dict[str, Any]) -> Dict[str, Any]:
    # Prefer existing values when desired is a placeholder like ${VAR}.
    merged = dict(existing)
    for key, value in desired.items():
        if (
            isinstance(value, str)
            and "${" in value
            and key in existing
        ):
            continue
        merged[key] = value
    return merged


def _merge_server(
    existing: Dict[str, Any],
    desired: Dict[str, Any],
    keep_env: bool,
    keep_existing: bool,
    keep_extra: bool,
) -> Dict[str, Any]:
    if keep_existing:
        return copy.deepcopy(existing)
    merged = dict(existing) if keep_extra else {}
    for key, value in desired.items():
        merged[key] = value
    if keep_env and existing.get("env"):
        if "env" in merged:
            merged["env"] = _merge_env(existing.get("env", {}), merged["env"])  # type: ignore[arg-type]
        else:
            merged["env"] = copy.deepcopy(existing.get("env", {}))
    return merged


def _build_desired_servers(servers: Dict[str, Any], names: list[str]) -> Dict[str, Any]:
    missing = [n for n in names if n not in servers]
    if missing:
        raise ValueError(f"Unknown servers referenced: {', '.join(missing)}")
    return {name: servers[name] for name in names}


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    content = path.read_text()
    if not content.strip():
        return {}
    return json.loads(content)


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=False))
    tmp_path.replace(path)


def _prepare_json_target(target: Dict[str, Any], servers: Dict[str, Any]) -> Dict[str, Any]:
    path = _expand_path(target["path"])
    mode = target.get("mode", "merge")
    keep_env = bool(target.get("keep_env", True))
    keep_existing = bool(target.get("keep_existing", False))
    keep_extra = bool(target.get("keep_extra", True))
    desired = _build_desired_servers(servers, target["servers"])
    desired = _apply_overrides(desired, target.get("overrides"))
    strip_fields = target.get("strip_fields", [])
    if strip_fields:
        cleaned = {}
        for name, cfg in desired.items():
            cleaned[name] = {k: v for k, v in cfg.items() if k not in strip_fields}
        desired = cleaned
    desired = _apply_overrides(desired, target.get("overrides"))

    current = _load_json(path)
    current_mcp = current.get("mcpServers", {}) if isinstance(current, dict) else {}

    if mode == "replace":
        next_mcp = desired
    else:
        next_mcp = dict(current_mcp)
        for name, cfg in desired.items():
            if name in current_mcp:
                next_mcp[name] = _merge_server(
                    current_mcp[name],
                    cfg,
                    keep_env,
                    keep_existing,
                    keep_extra,
                )
            else:
                next_mcp[name] = cfg

    if current == {}:
        next_data = {"mcpServers": next_mcp}
    else:
        next_data = dict(current)
        next_data["mcpServers"] = next_mcp

    added = [n for n in desired.keys() if n not in current_mcp]
    updated = [n for n in desired.keys() if n in current_mcp]
    current_text = json.dumps(current, indent=2, sort_keys=False) + "\n" if current else ""
    next_text = json.dumps(next_data, indent=2, sort_keys=False) + "\n"
    return {
        "kind": "json",
        "path": path,
        "mode": mode,
        "added": added,
        "updated": updated,
        "current_data": current,
        "next_data": next_data,
        "current_text": current_text,
        "next_text": next_text,
    }


def _prepare_project(target: Dict[str, Any], servers: Dict[str, Any]) -> Dict[str, Any]:
    path = _expand_path(target["path"])
    mode = target.get("mode", "replace")
    keep_env = bool(target.get("keep_env", True))
    keep_existing = bool(target.get("keep_existing", False))
    keep_extra = bool(target.get("keep_extra", True))
    desired = _build_desired_servers(servers, target["servers"])
    strip_fields = target.get("strip_fields", [])
    if strip_fields:
        cleaned = {}
        for name, cfg in desired.items():
            cleaned[name] = {k: v for k, v in cfg.items() if k not in strip_fields}
        desired = cleaned
    desired = _apply_overrides(desired, target.get("overrides"))

    current = _load_json(path) if path.exists() else {}
    current_mcp = current.get("mcpServers", {}) if isinstance(current, dict) else {}

    if mode == "replace":
        next_mcp = desired
    else:
        next_mcp = dict(current_mcp)
        for name, cfg in desired.items():
            if name in current_mcp:
                next_mcp[name] = _merge_server(
                    current_mcp[name],
                    cfg,
                    keep_env,
                    keep_existing,
                    keep_extra,
                )
            else:
                next_mcp[name] = cfg

    out = {"mcpServers": next_mcp}

    added = [n for n in desired.keys() if n not in current_mcp]
    updated = [n for n in desired.keys() if n in current_mcp]
    current_text = json.dumps(current, indent=2, sort_keys=False) + "\n" if current else ""
    next_text = json.dumps(out, indent=2, sort_keys=False) + "\n"
    return {
        "kind": "project",
        "path": path,
        "mode": mode,
        "added": added,
        "updated": updated,
        "current_data": current,
        "next_data": out,
        "current_text": current_text,
        "next_text": next_text,
    }


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\"", "\\\"")


def _toml_array(values: list[str]) -> str:
    inner = ", ".join([f"\"{_toml_escape(v)}\"" for v in values])
    return f"[{inner}]"


def _toml_inline_table(values: Dict[str, Any]) -> str:
    parts = []
    for key, value in values.items():
        if isinstance(value, str):
            parts.append(f"{key} = \"{_toml_escape(value)}\"")
        else:
            parts.append(f"{key} = {value}")
    return "{ " + ", ".join(parts) + " }"


def _render_codex_server(name: str, cfg: Dict[str, Any]) -> str:
    lines = [f"[mcp_servers.{name}]"]
    lines.append(f"command = \"{_toml_escape(cfg['command'])}\"")
    lines.append(f"args = {_toml_array(cfg['args'])}")
    if "env" in cfg and isinstance(cfg["env"], dict) and cfg["env"]:
        lines.append(f"env = {_toml_inline_table(cfg['env'])}")
    if "tool_timeout_sec" in cfg:
        lines.append(f"tool_timeout_sec = {cfg['tool_timeout_sec']}")
    return "\n".join(lines) + "\n"


def _remove_codex_blocks(text: str, names: list[str]) -> str:
    if not names:
        return text.rstrip() + "\n"
    name_set = set(names)
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("[mcp_servers.") and line.endswith("]"):
            section_name = line[len("[mcp_servers.") : -1]
            if section_name in name_set:
                i += 1
                while i < len(lines) and not lines[i].startswith("["):
                    i += 1
                continue
        out.append(line)
        i += 1
    return "\n".join(out).rstrip() + "\n"


def _prepare_codex_user(target: Dict[str, Any], servers: Dict[str, Any]) -> Dict[str, Any]:
    path = _expand_path(target["path"])
    mode = target.get("mode", "merge")
    keep_env = bool(target.get("keep_env", True))
    keep_existing = bool(target.get("keep_existing", False))
    desired = _build_desired_servers(servers, target["servers"])

    text = path.read_text() if path.exists() else ""
    original_text = text
    existing_blocks = {}
    if text:
        for name in desired.keys():
            marker = f"[mcp_servers.{name}]"
            if marker in text:
                existing_blocks[name] = True

    # Decide which names to replace
    to_replace = []
    for name in desired.keys():
        if name in existing_blocks and keep_existing:
            continue
        to_replace.append(name)

    if mode == "replace":
        # Remove all existing mcp_servers blocks and write only desired.
        import re

        text = re.sub(r"^\\[mcp_servers\\.[^\\]]+\\]\\n(?:.*\\n)*?(?=^\\[|\\Z)", "", text, flags=re.MULTILINE)
        text = text.rstrip() + "\n"
        to_render = list(desired.keys())
    else:
        # Merge: only replace blocks we manage.
        text = _remove_codex_blocks(text, to_replace)
        to_render = to_replace

    rendered = "".join(_render_codex_server(name, desired[name]) for name in to_render)
    next_text = (text.rstrip() + "\n\n" + rendered).rstrip() + "\n" if rendered else text

    added = [n for n in desired.keys() if n not in existing_blocks]
    updated = [n for n in desired.keys() if n in existing_blocks]
    return {
        "kind": "codex_user",
        "path": path,
        "mode": mode,
        "added": added,
        "updated": updated,
        "current_text": original_text,
        "next_text": next_text,
    }


def _show_diff(path: Path, current_text: str, next_text: str) -> None:
    diff = difflib.unified_diff(
        current_text.splitlines(),
        next_text.splitlines(),
        fromfile=str(path),
        tofile=str(path),
        lineterm="",
    )
    for line in diff:
        print(line)


def _backup_file(path: Path) -> Path:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_suffix(path.suffix + f".bak-{timestamp}")
    if path.exists():
        backup_path.write_text(path.read_text())
    return backup_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="registry/mcp-registry.toml")
    parser.add_argument("--write", action="store_true", help="Apply changes to disk")
    parser.add_argument("--diff", action="store_true", help="Show unified diffs for changes")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if changes are needed")
    parser.add_argument("--target", action="append", help="Only sync specific target(s)")
    parser.add_argument("--no-backup", action="store_true", help="Skip backups on write")
    parser.add_argument("--list", action="store_true", help="List servers and targets and exit")
    args = parser.parse_args()

    registry_path = _expand_path(args.registry)
    data = _load_registry(registry_path)
    servers = data["servers"]
    targets = data["targets"]

    _validate_servers(servers)

    if args.list:
        print("Servers:")
        for name in sorted(servers.keys()):
            print("-", name)
        print("Targets:")
        for name, target in targets.items():
            if not isinstance(target, dict):
                continue
            path = target.get("path", "")
            ttype = target.get("type", "")
            print(f"- {name} ({ttype}) -> {path}")
        return

    results = []
    selected = set(args.target or [])
    for name, target in targets.items():
        if selected and name not in selected:
            continue
        if not isinstance(target, dict) or "type" not in target:
            raise ValueError(f"Target '{name}' must be a table with 'type'")
        if "servers" not in target or not isinstance(target["servers"], list):
            raise ValueError(f"Target '{name}' must include a servers list")
        if "path" not in target:
            raise ValueError(f"Target '{name}' must include a path")

        ttype = target["type"]
        if ttype == "claude_user":
            results.append({"name": name, **_prepare_json_target(target, servers)})
        elif ttype == "gemini_user":
            results.append({"name": name, **_prepare_json_target(target, servers)})
        elif ttype == "project":
            results.append({"name": name, **_prepare_project(target, servers)})
        elif ttype == "codex_user":
            results.append({"name": name, **_prepare_codex_user(target, servers)})
        else:
            raise ValueError(f"Unsupported target type: {ttype}")

    print("Registry:", registry_path)
    changed = False
    for result in results:
        path = result["path"]
        current_text = result["current_text"]
        next_text = result["next_text"]
        if result["kind"] in ("json", "project"):
            has_change = result["current_data"] != result["next_data"]
        else:
            has_change = current_text != next_text
        changed = changed or has_change
        added = len(result["added"])
        updated = len(result["updated"])
        print(
            f"- {result['name']} -> {path} (mode={result['mode']}) "
            f"added={added} updated={updated} changed={'yes' if has_change else 'no'}"
        )
        if args.diff and has_change:
            _show_diff(path, current_text, next_text)

    if args.write:
        for result in results:
            path = result["path"]
            current_text = result["current_text"]
            next_text = result["next_text"]
            if result["kind"] in ("json", "project"):
                if result["current_data"] == result["next_data"]:
                    continue
            else:
                if current_text == next_text:
                    continue
            if not args.no_backup:
                _backup_file(path)
            if result["kind"] in ("json", "project"):
                _write_json(path, result["next_data"])
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(next_text)
        print("(write) Applied changes")
    else:
        print("(dry-run) Use --write to apply changes")

    if args.check and changed:
        sys.exit(1)


if __name__ == "__main__":
    main()
