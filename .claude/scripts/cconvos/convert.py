#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
cconvos: convert Claude Code session JSONLs into search-optimised markdown
for indexing with QMD.

Subcommands: convert | sync | status

Tunable policy is centralised in `classify()` and the constants block below.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ============================================================
# TUNABLE CONSTANTS 
# ============================================================
KEEP_THINKING = True                  # flip to False if reasoning blocks dominate embeddings
MIN_FIRST_MESSAGE_CHARS = 20          # skip 1-word user msgs as title hint
FIRST_MESSAGE_TRUNCATE = 100
ACTIVE_SESSION_GUARD_SECONDS = 60     # don't convert a JSONL still being written
META_PASTE_INSPECT_THRESHOLD = 500    # surface big isMeta drops in paste audit
SKIP_SESSIONS_STARTING_WITH = {"/review"}   # whole-session drop if it opens with one of these slash commands

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"
DEFAULT_OUT_DIR = Path.home() / "cconvos"

LOG_PATH = Path.home() / ".cconvos.log"
LOG_MAX_BYTES = 1_000_000
LOG_TRUNCATE_TO_LINES = 500

SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
COMMAND_WRAPPER_RE = re.compile(
    r"<(command-name|command-message|command-args|local-command-stdout|"
    r"local-command-stderr|local-command-caveat)>(.*?)</\1>",
    re.DOTALL,
)
SLASH_NAME_RE = re.compile(r"<command-name>([^<]+)</command-name>")


# ============================================================
# DATA
# ============================================================
@dataclass
class LineRecord:
    """Markdown body line. Mutable so tool-result pairing can append outcome
    onto an already-emitted tool-call summary line."""
    text: str
    tool_use_id: Optional[str] = None


@dataclass
class Stats:
    total_messages: int = 0
    kept_prose: int = 0
    collapsed_tool: int = 0
    dropped_by_reason: dict = field(default_factory=dict)

    def drop(self, reason: str) -> None:
        self.dropped_by_reason[reason] = self.dropped_by_reason.get(reason, 0) + 1

    @property
    def dropped_total(self) -> int:
        return sum(self.dropped_by_reason.values())

    def merge(self, other: "Stats") -> None:
        self.total_messages += other.total_messages
        self.kept_prose += other.kept_prose
        self.collapsed_tool += other.collapsed_tool
        for k, v in other.dropped_by_reason.items():
            self.dropped_by_reason[k] = self.dropped_by_reason.get(k, 0) + v


# ============================================================
# POLICY 
# ============================================================
class Action:
    KEEP_PROSE = "KEEP_PROSE"
    COLLAPSE_TOOL = "COLLAPSE_TOOL"
    EMIT_NOTE = "EMIT_NOTE"
    DROP = "DROP"


def classify(record: dict) -> tuple[str, str]:
    """Return (action, reason) for one transcript record."""
    t = record.get("type")

    if t == "user":
        text = _user_text_raw(record)
        # Slash-command markers can appear in either isMeta or non-meta records.
        # The non-meta peer carries `<command-name>`; the meta peer is usually
        # the (verbose, repetitive) prompt template body — drop the latter,
        # collapse the former to one line.
        if SLASH_NAME_RE.search(text or ""):
            return (Action.EMIT_NOTE, "slash-command")
        if record.get("isMeta"):
            return (Action.DROP, "isMeta-other")
        return (Action.KEEP_PROSE, "user")

    if t == "assistant":
        return (Action.KEEP_PROSE, "assistant")

    if t == "summary":
        return (Action.KEEP_PROSE, "summary")

    if t == "system":
        if record.get("subtype") == "compact_boundary":
            return (Action.EMIT_NOTE, "compact-boundary")
        return (Action.DROP, "system-other")

    if t == "attachment":
        att = record.get("attachment", {}) or {}
        if att.get("type") == "file":
            return (Action.EMIT_NOTE, "attachment-file")
        return (Action.DROP, f"attachment-{att.get('type')}")

    if t == "pr-link":
        return (Action.EMIT_NOTE, "pr-link")

    return (Action.DROP, t or "unknown")


# ============================================================
# CONTENT EXTRACTION
# ============================================================
def _strip_noise(text: str) -> str:
    if not text:
        return ""
    return SYSTEM_REMINDER_RE.sub("", text).strip()


def _user_text_raw(record: dict) -> str:
    """Concatenate text from a user record (string or content-blocks form)."""
    content = record.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "text":
                parts.append(blk.get("text", ""))
        return "\n".join(parts)
    return ""


def _user_blocks(record: dict) -> list[dict]:
    content = record.get("message", {}).get("content", [])
    return content if isinstance(content, list) else []


def _assistant_blocks(record: dict) -> list[dict]:
    content = record.get("message", {}).get("content", [])
    return content if isinstance(content, list) else []


# ============================================================
# TOOL SUMMARY
# ============================================================
def _short_path(p: str) -> str:
    if not p:
        return ""
    home = str(Path.home())
    if p.startswith(home):
        return "~" + p[len(home):]
    return p


def summarize_tool_use(block: dict, tool_index: int) -> str:
    name = block.get("name") or "Tool"
    inp = block.get("input") or {}

    if name in ("Read", "Edit", "Write"):
        path = _short_path(inp.get("file_path", ""))
        if name == "Edit":
            extras = []
            if inp.get("replace_all"):
                extras.append("replace_all")
            tail = f" ({', '.join(extras)})" if extras else ""
            return f"[Edit {path}{tail} → tool#{tool_index}]"
        return f"[{name} {path} → tool#{tool_index}]"

    if name == "MultiEdit":
        path = _short_path(inp.get("file_path", ""))
        n = len(inp.get("edits", []) or [])
        return f"[MultiEdit {path}: {n} hunks → tool#{tool_index}]"

    if name == "Bash":
        cmd = (inp.get("command") or "").strip()
        first = cmd.splitlines()[0] if cmd else ""
        if len(first) > 80:
            first = first[:77] + "..."
        return f"[Bash: {first} → tool#{tool_index}]"

    if name == "Grep":
        pat = inp.get("pattern", "")
        path = _short_path(inp.get("path", ""))
        loc = f" in {path}" if path else ""
        return f'[Grep "{pat}"{loc} → tool#{tool_index}]'

    if name == "Glob":
        return f"[Glob {inp.get('pattern','')} → tool#{tool_index}]"

    if name == "WebFetch":
        return f"[WebFetch {inp.get('url','')} → tool#{tool_index}]"

    if name == "WebSearch":
        return f'[WebSearch "{inp.get("query","")}" → tool#{tool_index}]'

    if name == "Task":
        sub = inp.get("subagent_type", "agent")
        desc = inp.get("description", "")
        return f"[Task ({sub}): {desc} → tool#{tool_index}]"

    if name == "TodoWrite":
        n = len(inp.get("todos", []) or [])
        return f"[TodoWrite: {n} items → tool#{tool_index}]"

    if name and name.startswith("mcp__"):
        # MCP tool — keep name verbose; many users will recall by the MCP fn name
        return f"[{name} → tool#{tool_index}]"

    return f"[{name} → tool#{tool_index}]"


def append_tool_outcome(line: LineRecord, user_record: dict, result_block: dict) -> None:
    """Append outcome ('(142L)' / '(interrupted)' / '⚠ error: ...') to the
    already-emitted tool-call summary line."""
    is_error = result_block.get("is_error") is True

    if is_error:
        content = result_block.get("content")
        err = ""
        if isinstance(content, str):
            err = content[:120].splitlines()[0] if content else ""
        elif isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    txt = blk.get("text", "")
                    if txt:
                        err = txt[:120].splitlines()[0]
                        break
        line.text = line.text + f" ⚠ error: {err}"
        return

    tur = user_record.get("toolUseResult") if isinstance(user_record, dict) else None
    if isinstance(tur, dict):
        if tur.get("interrupted"):
            line.text = line.text + " (interrupted)"
            return
        stdout = tur.get("stdout")
        if isinstance(stdout, str):
            n = len(stdout.splitlines()) if stdout else 0
            line.text = line.text + f" ({n}L)"
            return

    # No structured outcome data — leave the line as-is.


# ============================================================
# SIDECAR
# ============================================================
class SidecarWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fh: Any = None

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = self.path.open("w")

    def write(self, entry: dict) -> None:
        self.fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def close(self) -> None:
        if self.fh:
            self.fh.close()


# ============================================================
# CONVERSION
# ============================================================
def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _starting_slash_command(records: list[dict]) -> Optional[str]:
    """Return the slash command (with leading '/') that opens the session,
    or None if the session opens with substantive user prose."""
    for rec in records:
        if rec.get("type") != "user":
            continue
        text = _user_text_raw(rec)
        m = SLASH_NAME_RE.search(text or "")
        if m:
            cmd = m.group(1).strip()
            return cmd if cmd.startswith("/") else "/" + cmd
        # If a non-meta user record has real prose before any slash marker,
        # the session was started by a normal prompt, not a slash command.
        if not rec.get("isMeta"):
            stripped = COMMAND_WRAPPER_RE.sub("", _strip_noise(text or "")).strip()
            if stripped:
                return None
    return None


def _select_first_user_message(records: list[dict]) -> str:
    for rec in records:
        if rec.get("type") != "user" or rec.get("isMeta"):
            continue
        text = _strip_noise(_user_text_raw(rec))
        text = COMMAND_WRAPPER_RE.sub("", text).strip()
        if SLASH_NAME_RE.search(text):
            continue
        if len(text) < MIN_FIRST_MESSAGE_CHARS:
            continue
        return text[:FIRST_MESSAGE_TRUNCATE].replace("\n", " ").strip()
    return "(no substantive user prompt)"


def _yaml_value(v: Any) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(_yaml_value(x) for x in v) + "]"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    s = "" if v is None else str(v)
    needs_quote = (s == "" or s.strip() != s
                   or any(c in s for c in ":\"'\n#[]{},&*!|>%@`"))
    if needs_quote:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def convert_session(jsonl_path: Path, out_dir: Path, force: bool,
                    paste_audit: Optional[list]) -> Optional[Stats]:
    """Convert a single .jsonl. Returns Stats or None if skipped."""
    if not jsonl_path.exists():
        return None

    # Active-session guard
    age = datetime.now().timestamp() - jsonl_path.stat().st_mtime
    if age < ACTIVE_SESSION_GUARD_SECONDS:
        print(f"  skip (active <{ACTIVE_SESSION_GUARD_SECONDS}s): {jsonl_path.name}",
              file=sys.stderr)
        return None

    # Read all records
    records: list[dict] = []
    with jsonl_path.open("r") as f:
        for lineno, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError as e:
                print(f"  warn: {jsonl_path.name}:{lineno} bad json ({e})",
                      file=sys.stderr)
    if not records:
        return None

    # Whole-session skip: starts with a blacklisted slash command (e.g. /review).
    starting_slash = _starting_slash_command(records)
    if starting_slash and starting_slash in SKIP_SESSIONS_STARTING_WITH:
        # Clean up any stale output from a previous policy run.
        sid_short_guess = jsonl_path.stem[:8]
        if out_dir.exists():
            for proj_dir in out_dir.iterdir():
                if not proj_dir.is_dir():
                    continue
                for stale in proj_dir.glob(f"*-{sid_short_guess}.*"):
                    stale.unlink()
        print(f"  skip (starts with {starting_slash}): {jsonl_path.name}",
              file=sys.stderr)
        return None

    # Metadata
    cwd = next((r.get("cwd") for r in records if r.get("cwd")), None)
    project_name = Path(cwd).name if cwd else jsonl_path.parent.name.split("-")[-1]

    session_id = next((r.get("sessionId") for r in records if r.get("sessionId")),
                      jsonl_path.stem)
    sid_short = session_id[:8]

    timestamps = [t for t in (_parse_iso(r.get("timestamp", "")) for r in records) if t]
    started = min(timestamps) if timestamps else None
    ended = max(timestamps) if timestamps else None
    duration_min = int((ended - started).total_seconds() / 60) if (started and ended) else 0
    date_str = started.strftime("%Y-%m-%d") if started else "unknown"

    md_path = out_dir / project_name / f"{date_str}-{sid_short}.md"
    sidecar_path = out_dir / project_name / f"{date_str}-{sid_short}.tools.jsonl"

    # Incremental skip
    if not force and md_path.exists() and md_path.stat().st_mtime >= jsonl_path.stat().st_mtime:
        return None

    first_user = _select_first_user_message(records)
    models_used = sorted({
        rec.get("message", {}).get("model")
        for rec in records
        if rec.get("type") == "assistant" and rec.get("message", {}).get("model")
    })
    git_branch = next((r.get("gitBranch") for r in records if r.get("gitBranch")), "")

    # Body assembly
    lines: list[LineRecord] = []
    pending: dict[str, LineRecord] = {}
    last_role: Optional[str] = None
    tool_index = 0
    stats = Stats()

    sidecar = SidecarWriter(sidecar_path)
    sidecar.open()

    def emit_heading(role: str) -> None:
        nonlocal last_role
        if last_role == role:
            return
        if lines and lines[-1].text != "":
            lines.append(LineRecord(""))
        lines.append(LineRecord(f"## {role}"))
        lines.append(LineRecord(""))
        last_role = role

    def emit_para(text: str) -> None:
        text = text.strip()
        if not text:
            return
        lines.append(LineRecord(text))
        lines.append(LineRecord(""))

    def emit_thinking(text: str) -> None:
        text = text.strip()
        if not text:
            return
        out = ["> *thinking:* " + text.splitlines()[0]]
        for ln in text.splitlines()[1:]:
            out.append("> " + ln)
        for ln in out:
            lines.append(LineRecord(ln))
        lines.append(LineRecord(""))

    for rec in records:
        stats.total_messages += 1
        action, reason = classify(rec)

        if action == Action.DROP:
            stats.drop(reason)
            if paste_audit is not None and reason == "isMeta-other":
                txt = _user_text_raw(rec)
                if len(txt) > META_PASTE_INSPECT_THRESHOLD:
                    paste_audit.append({
                        "session": jsonl_path.name,
                        "uuid": rec.get("uuid"),
                        "length": len(txt),
                        "preview": txt[:200].replace("\n", " "),
                    })
            continue

        if action == Action.EMIT_NOTE:
            if reason == "compact-boundary":
                lines.append(LineRecord(""))
                lines.append(LineRecord("---"))
                lines.append(LineRecord("*— conversation compacted —*"))
                lines.append(LineRecord("---"))
                lines.append(LineRecord(""))
                last_role = None
                continue
            if reason == "slash-command":
                m = SLASH_NAME_RE.search(_user_text_raw(rec) or "")
                cmd = (m.group(1) if m else "?").lstrip("/")
                emit_heading("User")
                emit_para(f"[Slash: /{cmd}]")
                stats.kept_prose += 1
                continue
            if reason == "attachment-file":
                att = rec.get("attachment", {}) or {}
                fp = att.get("displayPath") or att.get("filename") or "(unknown)"
                content_obj = att.get("content", {}) or {}
                file_meta = content_obj.get("file", {}) or {}
                num_lines = file_meta.get("numLines", "?")
                tool_index += 1
                emit_heading("User")
                emit_para(f"[Attached: {_short_path(fp)}, {num_lines} lines → tool#{tool_index}]")
                sidecar.write({
                    "index": tool_index,
                    "kind": "attachment",
                    "path": fp,
                    "num_lines": num_lines,
                    "content": file_meta.get("content"),
                    "timestamp": rec.get("timestamp"),
                })
                stats.collapsed_tool += 1
                continue
            if reason == "pr-link":
                pr_url = rec.get("prUrl", "")
                pr_repo = rec.get("prRepository", "")
                pr_num = rec.get("prNumber", "")
                emit_heading("Assistant")
                emit_para(f"[PR opened: [{pr_repo}#{pr_num}]({pr_url})]")
                stats.kept_prose += 1
                continue

        # KEEP_PROSE branches
        if rec.get("type") == "summary":
            txt = rec.get("summary") or rec.get("content") or ""
            if txt:
                lines.append(LineRecord(""))
                lines.append(LineRecord(f"*Session summary:* {txt}"))
                lines.append(LineRecord(""))
            stats.kept_prose += 1
            continue

        if rec.get("type") == "user":
            content = rec.get("message", {}).get("content")
            if isinstance(content, str):
                clean = COMMAND_WRAPPER_RE.sub("", _strip_noise(content)).strip()
                if clean:
                    emit_heading("User")
                    emit_para(clean)
                    stats.kept_prose += 1
                continue

            had_text = False
            for blk in _user_blocks(rec):
                if not isinstance(blk, dict):
                    continue
                bt = blk.get("type")
                if bt == "text":
                    txt = COMMAND_WRAPPER_RE.sub("", _strip_noise(blk.get("text", ""))).strip()
                    if txt:
                        if not had_text:
                            emit_heading("User")
                            had_text = True
                        emit_para(txt)
                elif bt == "tool_result":
                    tool_id = blk.get("tool_use_id")
                    line = pending.pop(tool_id, None)
                    if line is not None:
                        append_tool_outcome(line, rec, blk)
                    rc = blk.get("content")
                    sidecar.write({
                        "kind": "tool_result",
                        "tool_use_id": tool_id,
                        "is_error": blk.get("is_error", False),
                        "content": rc if isinstance(rc, (str, list, dict)) else str(rc),
                        "tool_use_result_meta": rec.get("toolUseResult"),
                        "timestamp": rec.get("timestamp"),
                    })
            if had_text:
                stats.kept_prose += 1
            continue

        if rec.get("type") == "assistant":
            had_prose = False
            for blk in _assistant_blocks(rec):
                if not isinstance(blk, dict):
                    continue
                bt = blk.get("type")
                if bt == "text":
                    txt = _strip_noise(blk.get("text", ""))
                    if txt:
                        if not had_prose:
                            emit_heading("Assistant")
                            had_prose = True
                        emit_para(txt)
                elif bt == "thinking":
                    if not KEEP_THINKING:
                        continue
                    txt = _strip_noise(blk.get("thinking", ""))
                    if txt:
                        if not had_prose:
                            emit_heading("Assistant")
                            had_prose = True
                        emit_thinking(txt)
                elif bt == "tool_use":
                    tool_index += 1
                    summary = summarize_tool_use(blk, tool_index)
                    if not had_prose:
                        emit_heading("Assistant")
                        had_prose = True
                    line = LineRecord(summary, tool_use_id=blk.get("id"))
                    lines.append(line)
                    lines.append(LineRecord(""))
                    pending[blk.get("id")] = line
                    sidecar.write({
                        "index": tool_index,
                        "kind": "tool_use",
                        "tool_use_id": blk.get("id"),
                        "name": blk.get("name"),
                        "input": blk.get("input"),
                        "timestamp": rec.get("timestamp"),
                    })
                    stats.collapsed_tool += 1
            if had_prose:
                stats.kept_prose += 1
            continue

    sidecar.close()

    # Skip empty outputs (e.g. tiny aborted sessions with no real content).
    if stats.kept_prose == 0 and stats.collapsed_tool == 0:
        if sidecar_path.exists():
            sidecar_path.unlink()
        return None

    frontmatter = {
        "date": date_str,
        "project_path": cwd or "",
        "project_name": project_name,
        "session_id": session_id,
        "session_id_short": sid_short,
        "message_count": stats.total_messages,
        "kept_prose_count": stats.kept_prose,
        "collapsed_tool_count": stats.collapsed_tool,
        "dropped_count": stats.dropped_total,
        "duration_minutes": duration_min,
        "started_at": started.isoformat() if started else "",
        "ended_at": ended.isoformat() if ended else "",
        "models_used": models_used,
        "git_branch": git_branch,
        "first_user_message": first_user,
    }

    md_path.parent.mkdir(parents=True, exist_ok=True)
    with md_path.open("w") as f:
        f.write("---\n")
        for k, v in frontmatter.items():
            f.write(f"{k}: {_yaml_value(v)}\n")
        f.write("---\n\n")
        prev_blank = False
        for ln in lines:
            if ln.text == "":
                if prev_blank:
                    continue
                prev_blank = True
            else:
                prev_blank = False
            f.write(ln.text + "\n")

    return stats


# ============================================================
# DISCOVERY / SUBCOMMANDS
# ============================================================
def find_sessions(projects_dir: Path) -> list[Path]:
    if not projects_dir.exists():
        return []
    return sorted(projects_dir.glob("*/*.jsonl"))


def cmd_convert(args) -> int:
    sessions = find_sessions(args.projects_dir)
    if args.session:
        sessions = [s for s in sessions if args.session in s.name or args.session in s.stem]
    if args.latest:
        sessions = sessions[-1:] if sessions else []
        if sessions:
            # 'latest' really means most-recently-modified, not last-by-name
            sessions = [max(find_sessions(args.projects_dir),
                            key=lambda p: p.stat().st_mtime)]
    if args.limit:
        sessions = sessions[:args.limit]

    if args.dry_run_listing:
        for s in sessions:
            print(s)
        return 0

    paste_audit: list[dict] = []
    aggregate = Stats()
    converted = skipped = 0
    for s in sessions:
        result = convert_session(s, args.out_dir, force=args.force, paste_audit=paste_audit)
        if result is None:
            skipped += 1
            continue
        converted += 1
        aggregate.merge(result)

    print()
    print(f"Processed: {converted} sessions ({skipped} skipped)")
    print(f"  Kept as prose:        {aggregate.kept_prose:,}")
    print(f"  Collapsed tool calls: {aggregate.collapsed_tool:,}")
    print(f"  Dropped:              {aggregate.dropped_total:,}")
    if aggregate.dropped_by_reason:
        items = sorted(aggregate.dropped_by_reason.items(), key=lambda kv: -kv[1])
        print("    by reason: " + "  ".join(f"{k}={v}" for k, v in items))
    print()
    print(f"Output: {args.out_dir}")
    if paste_audit:
        print()
        print(f"isMeta paste audit ({len(paste_audit)} messages > {META_PASTE_INSPECT_THRESHOLD} chars):")
        for entry in paste_audit:
            print(f"  {entry['session']} | {entry['length']} chars | {entry['preview'][:160]}")
    return 0


def cmd_sync(args) -> int:
    rc = cmd_convert(args)
    if rc != 0:
        return rc
    print()
    print("Running qmd embed ...")
    proc = subprocess.run(["qmd", "embed"], check=False)
    return proc.returncode


def cmd_status(args) -> int:
    sessions = find_sessions(args.projects_dir)
    md_files = list(args.out_dir.rglob("*.md")) if args.out_dir.exists() else []

    sid_to_jsonl = {s.stem[:8]: s for s in sessions}

    stale: list[tuple[Path, Path]] = []
    missing: list[Path] = []
    orphan: list[Path] = []

    for s in sessions:
        sid_short = s.stem[:8]
        match = next((m for m in md_files if m.stem.endswith(f"-{sid_short}")), None)
        if not match:
            missing.append(s)
            continue
        if s.stat().st_mtime > match.stat().st_mtime:
            stale.append((s, match))

    valid_shorts = set(sid_to_jsonl.keys())
    for m in md_files:
        parts = m.stem.rsplit("-", 1)
        if len(parts) == 2 and parts[1] not in valid_shorts:
            orphan.append(m)

    print(f"Sessions in {args.projects_dir}: {len(sessions)}")
    print(f".md files in {args.out_dir}:    {len(md_files)}")
    print()
    print(f"Stale  (jsonl newer than md):  {len(stale)}")
    for s, _ in stale[:10]:
        print(f"  - {s.name}")
    if len(stale) > 10:
        print(f"  ... and {len(stale) - 10} more")
    print(f"Missing (no md output):        {len(missing)}")
    for s in missing[:10]:
        print(f"  - {s.name}")
    if len(missing) > 10:
        print(f"  ... and {len(missing) - 10} more")
    print(f"Orphan (md without source):    {len(orphan)}")
    for m in orphan[:10]:
        try:
            print(f"  - {m.relative_to(args.out_dir)}")
        except ValueError:
            print(f"  - {m}")
    if len(orphan) > 10:
        print(f"  ... and {len(orphan) - 10} more")

    if args.prune_orphans and orphan:
        for m in orphan:
            m.unlink()
            sc = m.with_name(m.stem + ".tools.jsonl")
            if sc.exists():
                sc.unlink()
        print(f"\nPruned {len(orphan)} orphan files.")

    return 0


# ============================================================
# HOOK SUPPORT + LOG ROTATION
# ============================================================
def resolve_session_from_hook() -> Optional[str]:
    """3-tier: stdin JSON → env var → most-recent-mtime fallback."""
    try:
        if not sys.stdin.isatty():
            payload = sys.stdin.read()
            if payload.strip():
                data = json.loads(payload)
                sid = data.get("session_id") or data.get("sessionId")
                if sid:
                    return sid
    except Exception:
        pass
    for v in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "SESSION_ID"):
        sid = os.environ.get(v)
        if sid:
            return sid
    sessions = find_sessions(DEFAULT_PROJECTS_DIR)
    if sessions:
        return max(sessions, key=lambda p: p.stat().st_mtime).stem
    return None


def rotate_log() -> None:
    if not LOG_PATH.exists() or LOG_PATH.stat().st_size <= LOG_MAX_BYTES:
        return
    try:
        with LOG_PATH.open("r") as f:
            tail = f.readlines()[-LOG_TRUNCATE_TO_LINES:]
        with LOG_PATH.open("w") as f:
            f.writelines(tail)
    except Exception:
        pass


# ============================================================
# CLI
# ============================================================
def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--projects-dir", type=Path, default=DEFAULT_PROJECTS_DIR)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)


def _add_convert_args(p: argparse.ArgumentParser) -> None:
    _add_common(p)
    p.add_argument("--force", action="store_true",
                   help="re-convert even if .md is up to date")
    p.add_argument("--limit", type=int, default=0,
                   help="convert at most N sessions (sample mode)")
    p.add_argument("--session", default=None,
                   help="filter to sessions whose filename matches this substring")
    p.add_argument("--latest", action="store_true",
                   help="convert only the most recently modified session")
    p.add_argument("--from-hook", action="store_true",
                   help="resolve session from Claude Code hook stdin/env")
    p.add_argument("--dry-run-listing", action="store_true",
                   help="print the JSONLs that would be processed and exit")


def main() -> int:
    rotate_log()
    parser = argparse.ArgumentParser(
        prog="cconvos",
        description="Convert Claude Code sessions to QMD-indexable markdown.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_convert = sub.add_parser("convert", help="Convert sessions to markdown")
    _add_convert_args(p_convert)

    p_sync = sub.add_parser("sync", help="Convert + qmd embed")
    _add_convert_args(p_sync)

    p_status = sub.add_parser("status", help="Show conversion status & drift")
    _add_common(p_status)
    p_status.add_argument("--prune-orphans", action="store_true")

    args = parser.parse_args()

    if args.cmd in ("convert", "sync") and getattr(args, "from_hook", False):
        sid = resolve_session_from_hook()
        if sid:
            args.session = sid
        else:
            print("warn: --from-hook resolved no session; nothing to do",
                  file=sys.stderr)
            return 0

    if args.cmd == "convert":
        return cmd_convert(args)
    if args.cmd == "sync":
        return cmd_sync(args)
    if args.cmd == "status":
        return cmd_status(args)
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
