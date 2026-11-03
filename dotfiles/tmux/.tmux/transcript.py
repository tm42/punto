"""Render an agent's session log as searchable plain text.

Claude Code and codex both keep the full session on disk as JSONL, and both draw
their TUI on the alternate screen, so tmux copy-mode can only ever see one
screenful. Reading back further means reading the file.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HOME = Path.home()
CLAUDE_PROJECTS = HOME / ".claude" / "projects"
CODEX_SESSIONS = HOME / ".codex" / "sessions"
CLIP = 2000  # per block, so one pasted file cannot bury the rest


def newest(paths):
    paths = [p for p in paths if p.is_file()]
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def claude_log(cwd: str):
    # Claude Code's own slug: every / _ and . in the path becomes a dash.
    slug = "".join("-" if c in "/_." else c for c in cwd)
    d = CLAUDE_PROJECTS / slug
    return newest(d.glob("*.jsonl")) if d.is_dir() else None


def codex_log(_cwd: str):
    # codex files are not keyed by directory, so the newest rollout is the guess.
    return newest(CODEX_SESSIONS.glob("*/*/*/rollout-*.jsonl"))


def clip(s: str) -> str:
    s = s.rstrip()
    return s if len(s) <= CLIP else s[:CLIP] + f"\n[... {len(s) - CLIP} more chars]"


def emit(out, who: str, body: str) -> None:
    body = clip(body)
    if body.strip():
        out.append(f"\n=== {who} " + "=" * max(0, 68 - len(who)))
        out.append(body)


def render_claude(path: Path, out: list) -> None:
    for line in path.open(errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") not in ("user", "assistant"):
            continue
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", d["type"])
        content = msg.get("content")
        if isinstance(content, str):
            emit(out, role, content)
            continue
        for b in content or []:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text":
                emit(out, role, b.get("text", ""))
            elif t == "thinking":
                emit(out, f"{role} (thinking)", b.get("thinking", ""))
            elif t == "tool_use":
                emit(out, f"tool {b.get('name')}", json.dumps(b.get("input"), indent=2))
            elif t == "tool_result":
                c = b.get("content")
                if isinstance(c, list):
                    c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
                emit(out, "tool result", c if isinstance(c, str) else json.dumps(c))


def render_codex(path: Path, out: list) -> None:
    for line in path.open(errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        p = d.get("payload")
        if d.get("type") != "response_item" or not isinstance(p, dict):
            continue
        t = p.get("type")
        if t == "message":
            role = p.get("role", "?")
            text = "\n".join(
                c.get("text", "")
                for c in p.get("content") or []
                if isinstance(c, dict) and "text" in c
            )
            emit(out, role, text)
        elif t == "reasoning":
            text = "\n".join(
                s.get("text", "")
                for s in p.get("summary") or []
                if isinstance(s, dict)
            )
            emit(out, "reasoning", text)
        elif t in ("function_call", "custom_tool_call"):
            emit(out, f"tool {p.get('name')}", str(p.get("arguments") or p.get("input")))
        elif t in ("function_call_output", "custom_tool_call_output"):
            emit(out, "tool result", str(p.get("output")))


def main() -> int:
    tool = sys.argv[1] if len(sys.argv) > 1 else "claude"
    cwd = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
    finder, render = {
        "claude": (claude_log, render_claude),
        "codex": (codex_log, render_codex),
    }.get(tool, (claude_log, render_claude))

    path = finder(cwd)
    if path is None:
        print(f"no {tool} session log found for {cwd}", file=sys.stderr)
        return 1

    out = [f"# {path}", f"# {tool} session, rendered for search"]
    render(path, out)
    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
