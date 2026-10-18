#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
cconvos: convert Claude Code and Codex CLI session logs into search-optimised
markdown for indexing with QMD.

Subcommands: convert | sync | status

Two sources are supported and tagged in each output file's `source:` frontmatter:
  - claude : ~/.claude/projects/*/*.jsonl  (Claude Code transcripts)
  - codex  : ~/.codex/sessions/**/*.jsonl  (Codex CLI rollout logs)

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
from typing import Any, Callable, Optional

# ============================================================
# TUNABLE CONSTANTS
# ============================================================
KEEP_THINKING = True                  # flip to False if reasoning blocks dominate embeddings
MIN_FIRST_MESSAGE_CHARS = 20          # skip 1-word user msgs as title hint
FIRST_MESSAGE_TRUNCATE = 100
ACTIVE_SESSION_GUARD_SECONDS = 60     # don't convert a log still being written
META_PASTE_INSPECT_THRESHOLD = 500    # surface big isMeta drops in paste audit
SKIP_SESSIONS_STARTING_WITH = {"/review"}   # whole-session drop if it opens with one of these slash commands

SOURCE_CLAUDE = "claude"
SOURCE_CODEX = "codex"

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"
DEFAULT_CODEX_DIR = Path.home() / ".codex" / "sessions"
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

# Codex injects a lot of synthetic "user" turns (instructions, environment
# context, approval scaffolding). These prefixes mark a turn the human never
# typed, so they get dropped from the prose body.
CODEX_SYNTHETIC_USER_PREFIXES = (
    "# AGENTS.md instructions",
    "<environment_context>",
    "<user_instructions>",
    "<turn_aborted>",
    "<user_action>",
    "# Context from my IDE setup:",
    "The following is the Codex agent",
    "The Codex agent has requested",
    ">>> APPROVAL REQUEST",
    "Planned action JSON:",
    "Assess the exact planned action",
    "Reviewed Codex session id:",
)
CODEX_EXIT_CODE_RE = re.compile(r"Exit code:\s*(-?\d+)")


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
# POLICY  (Claude transcripts)
# ============================================================
class Action:
    KEEP_PROSE = "KEEP_PROSE"
    COLLAPSE_TOOL = "COLLAPSE_TOOL"
    EMIT_NOTE = "EMIT_NOTE"
    DROP = "DROP"


def classify(record: dict) -> tuple[str, str]:
    """Return (action, reason) for one Claude transcript record."""
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
# CONTENT EXTRACTION  (Claude)
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
# TOOL SUMMARY  (Claude)
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
    already-emitted Claude tool-call summary line."""
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
# CONTENT EXTRACTION / TOOL SUMMARY  (Codex)
# ============================================================
def _safe_json(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return None
    return None


def _codex_message_text(payload: dict) -> str:
    """Join the text blocks of a Codex `message` response item."""
    parts = []
    for blk in payload.get("content", []) or []:
        if isinstance(blk, dict) and blk.get("type") in ("input_text", "output_text", "text"):
            parts.append(blk.get("text", ""))
    return "\n".join(parts)


def _codex_reasoning_text(payload: dict) -> str:
    """Codex reasoning carries a `summary` list of summary_text blocks; the
    full `content` is usually encrypted/null, so we lean on the summary."""
    parts = []
    for blk in payload.get("summary", []) or []:
        if isinstance(blk, dict) and blk.get("text"):
            parts.append(blk["text"])
    if not parts:
        content = payload.get("content")
        if isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("text"):
                    parts.append(blk["text"])
        elif isinstance(content, str):
            parts.append(content)
    return "\n\n".join(parts).strip()


def _is_synthetic_codex_user(text: str) -> bool:
    stripped = text.lstrip()
    return any(stripped.startswith(p) for p in CODEX_SYNTHETIC_USER_PREFIXES)


def _count_patch_files(patch: str) -> int:
    return len(re.findall(r"^\*\*\* (?:Add|Update|Delete) File:", patch, re.MULTILINE))


def summarize_codex_tool(payload: dict, tool_index: int) -> str:
    """One-line summary for a Codex function_call / custom_tool_call."""
    pt = payload.get("type")
    name = payload.get("name") or pt or "tool"

    if pt == "custom_tool_call":
        raw = payload.get("input") or ""
        if name == "apply_patch" or raw.lstrip().startswith("*** Begin Patch"):
            n = _count_patch_files(raw)
            return f"[apply_patch: {n} file(s) → tool#{tool_index}]"
        first = raw.strip().splitlines()[0] if raw.strip() else ""
        if len(first) > 80:
            first = first[:77] + "..."
        return f"[{name}: {first} → tool#{tool_index}]"

    # function_call — arguments is a JSON string
    args = _safe_json(payload.get("arguments")) or {}

    if isinstance(args, dict) and "command" in args:
        cmd = args["command"]
        if isinstance(cmd, list):
            cmd = " ".join(str(c) for c in cmd)
        first = str(cmd).strip().splitlines()[0] if cmd else ""
        if len(first) > 80:
            first = first[:77] + "..."
        return f"[shell: {first} → tool#{tool_index}]"

    if name == "update_plan":
        steps = args.get("plan") if isinstance(args, dict) else None
        n = len(steps) if isinstance(steps, list) else 0
        return f"[update_plan: {n} steps → tool#{tool_index}]"

    if name == "write_stdin":
        return f"[write_stdin → tool#{tool_index}]"

    if isinstance(args, dict) and args:
        # surface the first scalar arg as a hint (url, path, query, ...)
        for key in ("url", "path", "file_path", "query", "pattern"):
            if args.get(key):
                return f"[{name} {args[key]} → tool#{tool_index}]"

    return f"[{name} → tool#{tool_index}]"


def codex_outcome_suffix(output: Any) -> str:
    """Return the ' (NL)' / ' ⚠ exit N' / ' ⚠ error' suffix for a Codex tool
    result. Handles both the newer plain-text shape ("Exit code: N ... Output:
    ...") and the older JSON-wrapped shape ({"output": "...", "metadata":
    {"exit_code": N}}) where the real newlines are escaped."""
    if output is None:
        return ""
    text = output if isinstance(output, str) else json.dumps(output, default=str)

    exit_code: Optional[int] = None
    body = text

    if text.lstrip().startswith("{"):
        obj = _safe_json(text)
        if isinstance(obj, dict):
            meta = obj.get("metadata")
            if isinstance(meta, dict) and meta.get("exit_code") is not None:
                try:
                    exit_code = int(meta["exit_code"])
                except (TypeError, ValueError):
                    pass
            if isinstance(obj.get("output"), str):
                body = obj["output"]

    if exit_code is None:
        m = CODEX_EXIT_CODE_RE.search(text)
        if m:
            exit_code = int(m.group(1))

    if exit_code not in (None, 0):
        return f" ⚠ exit {exit_code}"
    if exit_code is None and body.lstrip().lower().startswith("execution error"):
        return " ⚠ error"

    if "Output:" in body:
        body = body.split("Output:", 1)[1]
    n = len([ln for ln in body.splitlines() if ln.strip()])
    return f" ({n}L)"


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
# BODY BUILDER  (shared markdown-emission state)
# ============================================================
class BodyBuilder:
    """Accumulates markdown LineRecords plus tool-call bookkeeping. Both the
    Claude and Codex parsers drive the same emission surface so the output
    format stays identical across sources."""

    def __init__(self, sidecar: SidecarWriter) -> None:
        self.lines: list[LineRecord] = []
        self.pending: dict[str, LineRecord] = {}
        self.last_role: Optional[str] = None
        self.tool_index = 0
        self.stats = Stats()
        self.sidecar = sidecar

    def emit_heading(self, role: str) -> None:
        if self.last_role == role:
            return
        if self.lines and self.lines[-1].text != "":
            self.lines.append(LineRecord(""))
        self.lines.append(LineRecord(f"## {role}"))
        self.lines.append(LineRecord(""))
        self.last_role = role

    def emit_para(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.lines.append(LineRecord(text))
        self.lines.append(LineRecord(""))

    def emit_thinking(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        out = ["> *thinking:* " + text.splitlines()[0]]
        for ln in text.splitlines()[1:]:
            out.append("> " + ln)
        for ln in out:
            self.lines.append(LineRecord(ln))
        self.lines.append(LineRecord(""))

    def emit_raw(self, *texts: str) -> None:
        for t in texts:
            self.lines.append(LineRecord(t))

    def emit_compaction(self) -> None:
        self.lines.append(LineRecord(""))
        self.lines.append(LineRecord("---"))
        self.lines.append(LineRecord("*— conversation compacted —*"))
        self.lines.append(LineRecord("---"))
        self.lines.append(LineRecord(""))
        self.last_role = None

    def add_tool_use(self, make_summary: Callable[[int], str],
                     call_id: Optional[str], sidecar_entry: dict) -> None:
        self.tool_index += 1
        line = LineRecord(make_summary(self.tool_index), tool_use_id=call_id)
        self.lines.append(line)
        self.lines.append(LineRecord(""))
        if call_id:
            self.pending[call_id] = line
        entry = dict(sidecar_entry)
        entry["index"] = self.tool_index
        self.sidecar.write(entry)
        self.stats.collapsed_tool += 1


# ============================================================
# CONVERSION  (shared helpers)
# ============================================================
def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


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


def _read_records(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r") as f:
        for lineno, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError as e:
                print(f"  warn: {path.name}:{lineno} bad json ({e})", file=sys.stderr)
    return records


def _write_markdown(md_path: Path, frontmatter: dict, lines: list[LineRecord]) -> None:
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


def _incremental_skip(md_path: Path, source_path: Path, force: bool) -> bool:
    return (not force and md_path.exists()
            and md_path.stat().st_mtime >= source_path.stat().st_mtime)


# ------------------------------------------------------------
# CLAUDE-SPECIFIC HELPERS
# ------------------------------------------------------------
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


def _convert_claude(jsonl_path: Path, records: list[dict], out_dir: Path,
                    force: bool, paste_audit: Optional[list]) -> Optional[Stats]:
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

    if _incremental_skip(md_path, jsonl_path, force):
        return None

    first_user = _select_first_user_message(records)
    models_used = sorted({
        rec.get("message", {}).get("model")
        for rec in records
        if rec.get("type") == "assistant" and rec.get("message", {}).get("model")
    })
    git_branch = next((r.get("gitBranch") for r in records if r.get("gitBranch")), "")

    sidecar = SidecarWriter(sidecar_path)
    sidecar.open()
    b = BodyBuilder(sidecar)

    for rec in records:
        b.stats.total_messages += 1
        action, reason = classify(rec)

        if action == Action.DROP:
            b.stats.drop(reason)
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
                b.emit_compaction()
                continue
            if reason == "slash-command":
                m = SLASH_NAME_RE.search(_user_text_raw(rec) or "")
                cmd = (m.group(1) if m else "?").lstrip("/")
                b.emit_heading("User")
                b.emit_para(f"[Slash: /{cmd}]")
                b.stats.kept_prose += 1
                continue
            if reason == "attachment-file":
                att = rec.get("attachment", {}) or {}
                fp = att.get("displayPath") or att.get("filename") or "(unknown)"
                content_obj = att.get("content", {}) or {}
                file_meta = content_obj.get("file", {}) or {}
                num_lines = file_meta.get("numLines", "?")
                b.tool_index += 1
                b.emit_heading("User")
                b.emit_para(f"[Attached: {_short_path(fp)}, {num_lines} lines → tool#{b.tool_index}]")
                sidecar.write({
                    "index": b.tool_index,
                    "kind": "attachment",
                    "path": fp,
                    "num_lines": num_lines,
                    "content": file_meta.get("content"),
                    "timestamp": rec.get("timestamp"),
                })
                b.stats.collapsed_tool += 1
                continue
            if reason == "pr-link":
                pr_url = rec.get("prUrl", "")
                pr_repo = rec.get("prRepository", "")
                pr_num = rec.get("prNumber", "")
                b.emit_heading("Assistant")
                b.emit_para(f"[PR opened: [{pr_repo}#{pr_num}]({pr_url})]")
                b.stats.kept_prose += 1
                continue

        # KEEP_PROSE branches
        if rec.get("type") == "summary":
            txt = rec.get("summary") or rec.get("content") or ""
            if txt:
                b.emit_raw("", f"*Session summary:* {txt}", "")
            b.stats.kept_prose += 1
            continue

        if rec.get("type") == "user":
            content = rec.get("message", {}).get("content")
            if isinstance(content, str):
                clean = COMMAND_WRAPPER_RE.sub("", _strip_noise(content)).strip()
                if clean:
                    b.emit_heading("User")
                    b.emit_para(clean)
                    b.stats.kept_prose += 1
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
                            b.emit_heading("User")
                            had_text = True
                        b.emit_para(txt)
                elif bt == "tool_result":
                    tool_id = blk.get("tool_use_id")
                    line = b.pending.pop(tool_id, None)
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
                b.stats.kept_prose += 1
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
                            b.emit_heading("Assistant")
                            had_prose = True
                        b.emit_para(txt)
                elif bt == "thinking":
                    if not KEEP_THINKING:
                        continue
                    txt = _strip_noise(blk.get("thinking", ""))
                    if txt:
                        if not had_prose:
                            b.emit_heading("Assistant")
                            had_prose = True
                        b.emit_thinking(txt)
                elif bt == "tool_use":
                    if not had_prose:
                        b.emit_heading("Assistant")
                        had_prose = True
                    b.add_tool_use(
                        lambda i, blk=blk: summarize_tool_use(blk, i),
                        blk.get("id"),
                        {
                            "kind": "tool_use",
                            "tool_use_id": blk.get("id"),
                            "name": blk.get("name"),
                            "input": blk.get("input"),
                            "timestamp": rec.get("timestamp"),
                        },
                    )
            if had_prose:
                b.stats.kept_prose += 1
            continue

    sidecar.close()

    # Skip empty outputs (e.g. tiny aborted sessions with no real content).
    if b.stats.kept_prose == 0 and b.stats.collapsed_tool == 0:
        if sidecar_path.exists():
            sidecar_path.unlink()
        return None

    frontmatter = {
        "source": SOURCE_CLAUDE,
        "date": date_str,
        "project_path": cwd or "",
        "project_name": project_name,
        "session_id": session_id,
        "session_id_short": sid_short,
        "message_count": b.stats.total_messages,
        "kept_prose_count": b.stats.kept_prose,
        "collapsed_tool_count": b.stats.collapsed_tool,
        "dropped_count": b.stats.dropped_total,
        "duration_minutes": duration_min,
        "started_at": started.isoformat() if started else "",
        "ended_at": ended.isoformat() if ended else "",
        "models_used": models_used,
        "git_branch": git_branch,
        "first_user_message": first_user,
    }

    _write_markdown(md_path, frontmatter, b.lines)
    return b.stats


# ------------------------------------------------------------
# CODEX-SPECIFIC HELPERS
# ------------------------------------------------------------
def _codex_sid_short(session_id: str) -> str:
    """Codex session ids are UUIDv7, whose first 8 hex chars are a coarse
    timestamp shared by every session started within ~65s. Use 12 hex (the full
    48-bit millisecond timestamp) so same-day sessions never collide on the
    output filename."""
    return session_id.replace("-", "")[:12] or session_id[:12]


def _codex_session_meta(records: list[dict]) -> dict:
    for rec in records:
        if rec.get("type") == "session_meta":
            return rec.get("payload", {}) or {}
    return {}


def _codex_first_user_message(records: list[dict]) -> str:
    for rec in records:
        if rec.get("type") != "response_item":
            continue
        p = rec.get("payload", {}) or {}
        if p.get("type") != "message" or p.get("role") != "user":
            continue
        text = _strip_noise(_codex_message_text(p)).strip()
        if not text or _is_synthetic_codex_user(text):
            continue
        if len(text) < MIN_FIRST_MESSAGE_CHARS:
            continue
        return text[:FIRST_MESSAGE_TRUNCATE].replace("\n", " ").strip()
    return "(no substantive user prompt)"


def _convert_codex(jsonl_path: Path, records: list[dict], out_dir: Path,
                   force: bool) -> Optional[Stats]:
    meta = _codex_session_meta(records)

    cwd = meta.get("cwd") or next(
        (r.get("payload", {}).get("cwd")
         for r in records
         if r.get("type") == "turn_context" and isinstance(r.get("payload"), dict)
         and r["payload"].get("cwd")),
        None,
    )
    project_name = Path(cwd).name if cwd else "codex"

    session_id = meta.get("id") or jsonl_path.stem
    sid_short = _codex_sid_short(session_id)

    timestamps = [t for t in (_parse_iso(r.get("timestamp", "")) for r in records) if t]
    started = _parse_iso(meta.get("timestamp", "")) or (min(timestamps) if timestamps else None)
    ended = max(timestamps) if timestamps else started
    duration_min = int((ended - started).total_seconds() / 60) if (started and ended) else 0
    date_str = started.strftime("%Y-%m-%d") if started else "unknown"

    # Prefix codex outputs so they never collide with a Claude session that
    # happens to share a date + 8-char id, and so they're greppable on disk.
    md_path = out_dir / project_name / f"{date_str}-codex-{sid_short}.md"
    sidecar_path = out_dir / project_name / f"{date_str}-codex-{sid_short}.tools.jsonl"

    if _incremental_skip(md_path, jsonl_path, force):
        return None

    models_used = sorted({
        r.get("payload", {}).get("model")
        for r in records
        if r.get("type") == "turn_context" and isinstance(r.get("payload"), dict)
        and r["payload"].get("model")
    })
    git = meta.get("git") or {}
    git_branch = git.get("branch", "") if isinstance(git, dict) else ""
    first_user = _codex_first_user_message(records)

    sidecar = SidecarWriter(sidecar_path)
    sidecar.open()
    b = BodyBuilder(sidecar)

    for rec in records:
        b.stats.total_messages += 1
        t = rec.get("type")

        if t == "compacted":
            b.emit_compaction()
            continue

        # Everything that drives the prose body lives in response_item records.
        # event_msg / turn_context / token_count / session_meta are either
        # duplicates of response_item content or pure telemetry — drop them.
        if t != "response_item":
            b.stats.drop(t or "unknown")
            continue

        p = rec.get("payload", {}) or {}
        pt = p.get("type")
        ts = rec.get("timestamp")

        if pt == "message":
            role = p.get("role")
            text = _strip_noise(_codex_message_text(p)).strip()
            if role == "user":
                if not text:
                    b.stats.drop("empty")
                elif _is_synthetic_codex_user(text):
                    b.stats.drop("codex-synthetic-user")
                else:
                    b.emit_heading("User")
                    b.emit_para(text)
                    b.stats.kept_prose += 1
            elif role == "assistant":
                if text:
                    b.emit_heading("Assistant")
                    b.emit_para(text)
                    b.stats.kept_prose += 1
                else:
                    b.stats.drop("empty")
            else:
                # developer / system instruction injections
                b.stats.drop(f"codex-{role}")
            continue

        if pt == "reasoning":
            if not KEEP_THINKING:
                b.stats.drop("reasoning-skipped")
                continue
            txt = _strip_noise(_codex_reasoning_text(p))
            if txt:
                b.emit_heading("Assistant")
                b.emit_thinking(txt)
                b.stats.kept_prose += 1
            else:
                b.stats.drop("reasoning-empty")
            continue

        if pt in ("function_call", "custom_tool_call"):
            b.emit_heading("Assistant")
            b.add_tool_use(
                lambda i, p=p: summarize_codex_tool(p, i),
                p.get("call_id"),
                {
                    "kind": "tool_use",
                    "tool_use_id": p.get("call_id"),
                    "name": p.get("name"),
                    "input": p.get("arguments") if pt == "function_call" else p.get("input"),
                    "timestamp": ts,
                },
            )
            continue

        if pt in ("function_call_output", "custom_tool_call_output"):
            call_id = p.get("call_id")
            output = p.get("output")
            line = b.pending.pop(call_id, None)
            if line is not None:
                line.text = line.text + codex_outcome_suffix(output)
            sidecar.write({
                "kind": "tool_result",
                "tool_use_id": call_id,
                "content": output if isinstance(output, (str, list, dict)) else str(output),
                "timestamp": ts,
            })
            continue

        if pt == "web_search_call":
            action = p.get("action") or {}
            target = action.get("url") or action.get("query") or ""
            b.emit_heading("Assistant")
            b.add_tool_use(
                lambda i, target=target: f"[WebSearch {target} → tool#{i}]",
                None,
                {"kind": "tool_use", "name": "web_search_call",
                 "input": action, "timestamp": ts},
            )
            continue

        if pt in ("tool_search_call", "tool_search_output"):
            # low-signal tool-discovery chatter; count as dropped
            b.stats.drop(f"codex-{pt}")
            continue

        # ghost_snapshot, encrypted reasoning duplicates, etc.
        b.stats.drop(f"codex-{pt or 'unknown'}")

    sidecar.close()

    if b.stats.kept_prose == 0 and b.stats.collapsed_tool == 0:
        if sidecar_path.exists():
            sidecar_path.unlink()
        return None

    frontmatter = {
        "source": SOURCE_CODEX,
        "date": date_str,
        "project_path": cwd or "",
        "project_name": project_name,
        "session_id": session_id,
        "session_id_short": sid_short,
        "message_count": b.stats.total_messages,
        "kept_prose_count": b.stats.kept_prose,
        "collapsed_tool_count": b.stats.collapsed_tool,
        "dropped_count": b.stats.dropped_total,
        "duration_minutes": duration_min,
        "started_at": started.isoformat() if started else "",
        "ended_at": ended.isoformat() if ended else "",
        "models_used": models_used,
        "git_branch": git_branch,
        "codex_cli_version": meta.get("cli_version", ""),
        "first_user_message": first_user,
    }

    _write_markdown(md_path, frontmatter, b.lines)
    return b.stats


# ------------------------------------------------------------
# DISPATCH
# ------------------------------------------------------------
def convert_session(path: Path, out_dir: Path, force: bool,
                    paste_audit: Optional[list], source: str) -> Optional[Stats]:
    """Convert a single session log. Returns Stats or None if skipped."""
    if not path.exists():
        return None

    # Active-session guard: don't convert a log still being written.
    age = datetime.now().timestamp() - path.stat().st_mtime
    if age < ACTIVE_SESSION_GUARD_SECONDS:
        print(f"  skip (active <{ACTIVE_SESSION_GUARD_SECONDS}s): {path.name}",
              file=sys.stderr)
        return None

    records = _read_records(path)
    if not records:
        return None

    if source == SOURCE_CODEX:
        return _convert_codex(path, records, out_dir, force)
    return _convert_claude(path, records, out_dir, force, paste_audit)


# ============================================================
# DISCOVERY / SUBCOMMANDS
# ============================================================
def find_claude_sessions(projects_dir: Path) -> list[Path]:
    if not projects_dir.exists():
        return []
    return sorted(projects_dir.glob("*/*.jsonl"))


def find_codex_sessions(codex_dir: Path) -> list[Path]:
    if not codex_dir.exists():
        return []
    # Codex nests logs under YYYY/MM/DD/. Legacy flat *.json files at the root
    # use an older schema and are intentionally skipped.
    return sorted(codex_dir.rglob("*.jsonl"))


def gather_sessions(args) -> list[tuple[Path, str]]:
    """Return (path, source) pairs honouring --source."""
    pairs: list[tuple[Path, str]] = []
    if args.source in (SOURCE_CLAUDE, "both"):
        pairs += [(p, SOURCE_CLAUDE) for p in find_claude_sessions(args.projects_dir)]
    if args.source in (SOURCE_CODEX, "both"):
        pairs += [(p, SOURCE_CODEX) for p in find_codex_sessions(args.codex_dir)]
    return pairs


def cmd_convert(args) -> int:
    pairs = gather_sessions(args)
    if args.session:
        pairs = [(p, s) for (p, s) in pairs
                 if args.session in p.name or args.session in p.stem]
    if args.latest:
        pairs = [max(pairs, key=lambda ps: ps[0].stat().st_mtime)] if pairs else []
    if args.limit:
        pairs = pairs[:args.limit]

    if args.dry_run_listing:
        for p, s in pairs:
            print(f"{s}\t{p}")
        return 0

    paste_audit: list[dict] = []
    aggregate = Stats()
    converted = skipped = 0
    by_source: dict[str, int] = {}
    for p, s in pairs:
        result = convert_session(p, args.out_dir, force=args.force,
                                 paste_audit=paste_audit, source=s)
        if result is None:
            skipped += 1
            continue
        converted += 1
        by_source[s] = by_source.get(s, 0) + 1
        aggregate.merge(result)

    print()
    src_breakdown = "  ".join(f"{k}={v}" for k, v in sorted(by_source.items()))
    print(f"Processed: {converted} sessions ({skipped} skipped)"
          + (f"  [{src_breakdown}]" if src_breakdown else ""))
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


_UUID_RE = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


def _md_short_id(md: Path) -> str:
    """Recover the source session short-id from an output filename. Codex files
    are named '<date>-codex-<sid8>', Claude '<date>-<sid8>'; in both the short
    id is the final dash-delimited segment."""
    stem = md.stem
    parts = stem.rsplit("-", 1)
    return parts[1] if len(parts) == 2 else stem


def _source_short_id(path: Path, source: str) -> str:
    """8-char session id from a source log filename. Claude logs are named by
    the bare UUID; Codex logs are 'rollout-<iso>-<uuid>', so pull the UUID out."""
    if source == SOURCE_CODEX:
        m = _UUID_RE.search(path.stem)
        if m:
            return _codex_sid_short(m.group(1))
    return path.stem[:8]


def cmd_status(args) -> int:
    pairs = gather_sessions(args)
    sessions = [p for p, _ in pairs]
    md_files = list(args.out_dir.rglob("*.md")) if args.out_dir.exists() else []

    stale: list[tuple[Path, Path]] = []
    missing: list[Path] = []
    orphan: list[Path] = []

    for p, src in pairs:
        sid_short = _source_short_id(p, src)
        match = next((m for m in md_files if _md_short_id(m) == sid_short), None)
        if not match:
            missing.append(p)
            continue
        if p.stat().st_mtime > match.stat().st_mtime:
            stale.append((p, match))

    valid_shorts = {_source_short_id(p, src) for p, src in pairs}
    for m in md_files:
        if _md_short_id(m) not in valid_shorts:
            orphan.append(m)

    print(f"Sessions discovered (source={args.source}): {len(sessions)}")
    print(f".md files in {args.out_dir}:    {len(md_files)}")
    print()
    print(f"Stale  (source newer than md): {len(stale)}")
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
    sessions = find_claude_sessions(DEFAULT_PROJECTS_DIR)
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
    p.add_argument("--codex-dir", type=Path, default=DEFAULT_CODEX_DIR)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--source", choices=[SOURCE_CLAUDE, SOURCE_CODEX, "both"],
                   default="both", help="which session source(s) to process")


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
                   help="resolve session from Claude Code hook stdin/env (implies --source claude)")
    p.add_argument("--dry-run-listing", action="store_true",
                   help="print the logs that would be processed and exit")


def main() -> int:
    rotate_log()
    parser = argparse.ArgumentParser(
        prog="cconvos",
        description="Convert Claude Code & Codex CLI sessions to QMD-indexable markdown.",
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
            args.source = SOURCE_CLAUDE
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
