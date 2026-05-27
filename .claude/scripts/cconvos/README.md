# cconvos

Convert Claude Code session transcripts (`~/.claude/projects/*/*.jsonl`) into
search-optimised markdown for indexing with [QMD](https://github.com/tobi/qmd).

The whole point is **embedding quality**. Raw transcripts are mostly noise
(hook output, environment dumps, large file reads echoed back, todo state
snapshots, system reminders); embedding them dilutes semantic signal. This
script keeps user prose and assistant prose verbatim, collapses tool calls to
one-line summaries, and preserves full tool payloads in a sidecar file.

## Install

Requires `uv` and Python 3.11+. The script uses PEP 723 inline metadata, so
there's no venv to set up:

```sh
# Add to ~/.zshrc:
cconvos() { uv run ~/cconvos-converter/convert.py "$@"; }
```

## Usage

```sh
cconvos convert --limit 5            # sample run (5 sessions)
cconvos convert                      # full bulk conversion
cconvos convert --force               # re-convert everything (after policy tune)
cconvos sync                         # convert + qmd embed
cconvos status                       # show stale / missing / orphan files
cconvos status --prune-orphans       # delete .md files whose source jsonl is gone
```

Output goes to `~/cconvos/<project-name>/<YYYY-MM-DD>-<sid8>.md` plus
`<...>.tools.jsonl` (sidecar with full tool inputs/outputs by index).

## Keep / drop / collapse policy

All policy lives in `classify()` in `convert.py`. Edit there, re-run with
`--force`. The four actions are `KEEP_PROSE`, `COLLAPSE_TOOL`, `EMIT_NOTE`,
`DROP`.

| Record type | Action | Notes |
|---|---|---|
| `user` (not meta) | KEEP_PROSE | Verbatim. `<system-reminder>` and command-XML wrappers stripped. |
| `user` (`isMeta`, slash command) | EMIT_NOTE | `[Slash: /init]` etc. — slash commands are signal. |
| `user` (`isMeta`, other) | DROP | But messages > 500 chars surface in the paste-audit log so you can spot lost user paste content. |
| `assistant` text/thinking | KEEP_PROSE | Thinking is rendered as `> *thinking:* ...` blockquotes. Toggle with `KEEP_THINKING`. |
| `assistant` tool_use | COLLAPSE_TOOL | One line: `[Bash: cmd → tool#7]`. Outcome appended later as `(142L)` or `⚠ error: ...`. |
| `summary` | KEEP_PROSE | Compaction summaries are already distilled. |
| `system` (`compact_boundary`) | EMIT_NOTE | `--- *— conversation compacted —* ---` hr. |
| `system` (other) | DROP | |
| `attachment` (`file`) | EMIT_NOTE | `[Attached: path, N lines → tool#X]`; full content in sidecar. |
| `attachment` (other) | DROP | MCP instruction deltas etc. |
| `pr-link` | EMIT_NOTE | Linked: `[PR opened: owner/repo#N](url)`. |
| `progress`, `permission-mode`, `last-prompt`, `file-history-snapshot`, `queue-operation` | DROP | Pure telemetry. |

## Tool-result pairing

When an assistant emits `tool_use`, the converter:

1. Writes a placeholder line `[Bash: cmd → tool#7]` and stores the
   `LineRecord` in a `pending` dict keyed by `tool_use_id`.
2. When a later `user` message contains a `tool_result` block with that id,
   the placeholder line is **mutated in place** to append the outcome:
   `(142L)`, `(interrupted)`, or `⚠ error: <first 80 chars>`.
3. Full input/output is written to the sidecar `.tools.jsonl` regardless, so
   nothing is lost.

## End-of-run summary stats

After `cconvos convert`, you'll see something like:

```
Processed: 47 sessions (3 skipped)
  Kept as prose:        14,203
  Collapsed tool calls:  3,981
  Dropped:               8,772
    by reason: progress=4,102  isMeta-other=2,113  permission-mode=987 ...

isMeta paste audit (4 messages > 500 chars):
  abc.jsonl | 3,420 chars | <local-command-stdout>...
```

The paste audit lists any `isMeta-other` user messages over the threshold —
review them to confirm we're not silently dropping pasted file content.

**Sanity ratio:** dropped/total in the 30–60% range is normal. >80% means the
policy is too aggressive (you're probably eating real signal); <15% means
noise is leaking into embeddings.

## Tunables (top of `convert.py`)

```python
KEEP_THINKING = True                  # flip if reasoning blocks dominate embeddings
MIN_FIRST_MESSAGE_CHARS = 20          # title-hint heuristic
FIRST_MESSAGE_TRUNCATE = 100
ACTIVE_SESSION_GUARD_SECONDS = 60     # don't touch JSONLs being actively written
META_PASTE_INSPECT_THRESHOLD = 500    # surface big isMeta drops in audit
SKIP_SESSIONS_STARTING_WITH = {"/review"}   # whole-session drop
```

`SKIP_SESSIONS_STARTING_WITH` skips sessions whose first user signal is one of
the listed slash commands. Default skips `/review` because PR-review sessions
are mostly identical template prompts that pollute embeddings. Add other
template-driven slashes here (e.g. `/security-review`, `/init`) if they end up
dominating search results. When a session is skipped, any previously-converted
`.md` and `.tools.jsonl` for that session_id are deleted, so re-running after
adding to this set cleans up automatically.

## Hook integration (steady-state freshness)

After the initial bulk run, register a SessionEnd hook in
`~/.claude/settings.json` so each finished session converts + re-embeds
automatically:

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run ~/cconvos-converter/convert.py sync --from-hook >>~/.cconvos.log 2>&1"
          }
        ]
      }
    ]
  }
}
```

Session id is resolved with a 3-tier fallback: stdin JSON payload → env var
(`CLAUDE_SESSION_ID`) → most-recently-modified `.jsonl`. Robust across hook
API revisions.

The log file at `~/.cconvos.log` self-rotates: when it exceeds 1 MB, the
script truncates to the last 500 lines on the next run. No external rotation
needed.

## QMD setup (one-time, after the first bulk run)

```sh
qmd collection add ~/cconvos --name claude-sessions
qmd context add qmd://claude-sessions "Past Claude Code sessions across all projects — user prompts, assistant prose, and collapsed tool-call traces. Use to recall prior work, debugging context, decisions, or how a problem was previously solved."
qmd embed
```

Re-run `qmd embed` after policy changes — `cconvos sync` does this for you.

## What's not in scope

- `claude -r` resume integration. Run it manually with the `session_id` from
  the .md frontmatter when you want to resume a session you found via QMD.
- TUI / file picker. QMD search is the discovery surface.
- Cross-session linking via `parentUuid`. Sessions are the unit of indexing.
- Auto-installing the zsh function or settings.json hook — they're documented
  above for you to paste in.
