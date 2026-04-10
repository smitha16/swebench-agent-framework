"""
Tools available to the coding agent.
Each tool returns a string result and is logged by the trajectory logger.
"""

import os
import subprocess
import fnmatch
from pathlib import Path
from typing import Optional


class ToolError(Exception):
    pass


def file_read(path: str, workspace: str) -> str:
    """Read a file from the workspace."""
    full = _resolve(path, workspace)
    if not os.path.isfile(full):
        raise ToolError(f"File not found: {path}")
    with open(full, "r", errors="replace") as f:
        content = f.read()
    # Truncate very large files
    if len(content) > 50_000:
        content = content[:50_000] + "\n... [truncated]"
    return content


def file_write(path: str, content: str, workspace: str) -> str:
    """Write content to a file in the workspace."""
    full = _resolve(path, workspace)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)
    return f"Written {len(content)} chars to {path}"


def file_edit(path: str, old_str: str, new_str: str, workspace: str) -> str:
    """Replace old_str with new_str in a file (must match exactly once)."""
    full = _resolve(path, workspace)
    if not os.path.isfile(full):
        raise ToolError(f"File not found: {path}")
    with open(full, "r") as f:
        text = f.read()
    count = text.count(old_str)
    if count == 0:
        raise ToolError(f"String not found in {path}")
    if count > 1:
        raise ToolError(f"String appears {count} times in {path}; must be unique")
    text = text.replace(old_str, new_str, 1)
    with open(full, "w") as f:
        f.write(text)
    return f"Edited {path}: replaced 1 occurrence"


def bash(command: str, workspace: str, timeout: int = 60) -> str:
    """Run a bash command in the workspace directory."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            output += "\nSTDERR:\n" + result.stderr
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        # Truncate
        if len(output) > 20_000:
            output = output[:20_000] + "\n... [truncated]"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"[command timed out after {timeout}s]"


def search_files(pattern: str, workspace: str, max_results: int = 50) -> str:
    """Search for files matching a glob pattern."""
    matches = []
    for root, dirs, files in os.walk(workspace):
        # Skip hidden dirs and common noise
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), workspace)
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(f, pattern):
                matches.append(rel)
                if len(matches) >= max_results:
                    break
        if len(matches) >= max_results:
            break
    if not matches:
        return "No files matching pattern."
    return "\n".join(matches)


def directory_tree(path: str, workspace: str, max_depth: int = 3) -> str:
    """Show directory structure."""
    full = _resolve(path, workspace)
    if not os.path.isdir(full):
        raise ToolError(f"Not a directory: {path}")
    lines = []
    _tree(full, workspace, "", 0, max_depth, lines)
    return "\n".join(lines[:200]) if lines else "(empty)"


def _tree(dirpath, workspace, prefix, depth, max_depth, lines):
    if depth >= max_depth:
        return
    try:
        entries = sorted(os.listdir(dirpath))
    except PermissionError:
        return
    entries = [e for e in entries if not e.startswith(".") and e != "__pycache__"]
    for e in entries[:50]:
        full = os.path.join(dirpath, e)
        rel = os.path.relpath(full, workspace)
        if os.path.isdir(full):
            lines.append(f"{prefix}{e}/")
            _tree(full, workspace, prefix + "  ", depth + 1, max_depth, lines)
        else:
            lines.append(f"{prefix}{e}")


def _resolve(path: str, workspace: str) -> str:
    """Resolve a path relative to workspace, preventing escape."""
    if os.path.isabs(path):
        full = os.path.normpath(path)
    else:
        full = os.path.normpath(os.path.join(workspace, path))
    if not full.startswith(os.path.normpath(workspace)):
        raise ToolError("Path escapes workspace")
    return full


# Tool registry for the agent
TOOLS = {
    "file_read": {
        "description": "Read a file. Args: {\"path\": \"relative/path\"}",
        "params": ["path"],
    },
    "file_write": {
        "description": "Write content to a file. Args: {\"path\": \"...\", \"content\": \"...\"}",
        "params": ["path", "content"],
    },
    "file_edit": {
        "description": "Edit a file by replacing a unique string. Args: {\"path\": \"...\", \"old_str\": \"...\", \"new_str\": \"...\"}",
        "params": ["path", "old_str", "new_str"],
    },
    "bash": {
        "description": "Run a bash command. Args: {\"command\": \"...\"}",
        "params": ["command"],
    },
    "search_files": {
        "description": "Find files matching a glob pattern. Args: {\"pattern\": \"*.py\"}",
        "params": ["pattern"],
    },
    "directory_tree": {
        "description": "Show directory structure. Args: {\"path\": \".\"}",
        "params": ["path"],
    },
    "submit": {
        "description": "Submit your solution. Call when done. Args: {}",
        "params": [],
    },
}


def get_openai_tools_schema() -> list:
    """Return OpenAI-compatible tool/function definitions."""
    schema = []
    for name, info in TOOLS.items():
        props = {}
        for p in info["params"]:
            props[p] = {"type": "string", "description": p}
        schema.append({
            "type": "function",
            "function": {
                "name": name,
                "description": info["description"],
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": info["params"],
                },
            },
        })
    return schema
