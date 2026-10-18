# agent-restore

Reopen the Claude Code and Codex conversations that were open in iTerm2 tabs
after a forced quit, crash or macOS update restart, or snapshot the whole iTerm
layout (windows, tabs, agent sessions and plain shells) before a restart and
rebuild it after.

## How it works

Hooks in both agents run `track-session.sh`, which keeps one file per iTerm
pane in `~/.agent-restore/open/<pane-guid>.json`:

```json
{"agent": "claude", "sessionId": "...", "cwd": "...", "transcript": "...",
 "name": "...", "itermSessionId": "w0t1p0:GUID", "lastSeen": 1790697236}
```

| Agent  | Config                    | Events                                    |
|--------|---------------------------|-------------------------------------------|
| Claude | `~/.claude/settings.json` | `SessionStart`, `UserPromptSubmit`, `SessionEnd` |
| Codex  | `~/.codex/hooks.json`     | `SessionStart`, `UserPromptSubmit`        |

Keying on the pane means `/clear` and resuming just overwrite the pane's entry.
For Claude the entry is deleted only on a deliberate exit (`/exit`, Ctrl-D,
logout); a force-kill, reboot or closing the window leaves it behind. Codex
reports the same `SessionEnd` reason for every kind of exit, so its entries are
never removed automatically. Use ctrl-x in the picker to forget old ones.

`agent-restore` lists those entries (skipping sessions that are still running)
in fzf and opens each pick as a new iTerm tab running
`cd <cwd> && claude --resume <id>` or `cd <cwd> && codex resume <id>`.

### Snapshots

`agent-restore snapshot` asks iTerm (AppleScript) for every window, tab and
pane, then works out what each pane is from its tty:

- a Claude process on the tty has a `~/.claude/sessions/<pid>.json`, which gives
  the session id, name and cwd;
- a `codex` process on the tty is matched to the hook's entry for that pane
  (Codex has no pid registry, so this needs the hook);
- otherwise it's a plain shell, and its cwd comes from `lsof`.

The result goes to `~/.agent-restore/snapshots/<timestamp>.json` with
`latest.json` symlinked to it. The last 20 are kept.

`agent-restore last` reads the latest snapshot and rebuilds the windows with
their tabs in the same order. Agent tabs resume their session, shell tabs just
`cd <cwd>`. Sessions already running somewhere are skipped.

Take one whenever you're about to quit iTerm or restart.

## Install

```sh
./install.sh
```

Needs `jq`, `fzf` and iTerm2 (`brew bundle` covers the first two if they are in
the Brewfile). The installer backs up each config to `*.bak-agent-restore` and
merges the hooks in without touching anything else. It also migrates an older
`claude-restore` install (`~/.claude/open-sessions`, `~/bin/claude-restore`).

Afterwards:

- restart open Claude/Codex tabs, since only sessions started after the install
  are tracked;
- in Codex, run `/hooks` once and trust `track-session.sh`. Codex skips new or
  changed hooks until they're trusted, so re-trust after editing the script.

## Use

```sh
agent-restore           # picker: TAB multi-select, ENTER restore, ctrl-x forget
agent-restore --all     # reopen everything without asking

agent-restore snapshot           # save the current iTerm windows/tabs
agent-restore last               # picker (all ticked): rebuild the latest snapshot
agent-restore last <file.json>   # rebuild an older one from ~/.agent-restore/snapshots/
```

The picker's preview pane shows the last few prompts from the highlighted
conversation. The first `snapshot` triggers a macOS prompt to let your terminal
control iTerm.

## Files

```
agent-restore/
├── install.sh          # copy scripts + merge hooks + migrate old install
├── track-session.sh    # -> ~/.agent-restore/   the hook (both agents)
└── agent-restore       # -> ~/bin/              the picker + snapshot/last
```

## Caveats

- iTerm2 only; entries without `$ITERM_SESSION_ID` are ignored.
- Snapshots don't recreate split panes. A split tab comes back as one tab per
  agent session in it, or as one shell tab if none was running an agent.
- "Already running" detection for Codex is best-effort: it looks for rollout
  files a `codex` process holds open and for `codex resume <id>` in process args.
- Assumes closing a window does not report `prompt_input_exit` as Claude's
  SessionEnd reason. If Claude entries vanish after a normal window close,
  check the `reason` handling in `track-session.sh`.
