#!/usr/bin/env bash
#
# Install the agent session tracker + `agent-restore` (Claude Code and Codex).
# Idempotent: re-run after editing anything in this directory.
#
# Copies the scripts into place and merges the tracking hooks into
# ~/.claude/settings.json and ~/.codex/hooks.json (a .bak copy of each is written first).
# Existing settings and other hooks are left alone. Also migrates the older
# claude-restore install (~/.claude/open-sessions, ~/bin/claude-restore) if present.
# Only sessions started after this runs get tracked.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="$HOME/.agent-restore"
TRACK="~/.agent-restore/track-session.sh"

for cmd in jq fzf osascript; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "install: '$cmd' not on PATH (brew install jq fzf)." >&2
    exit 1
  }
done

echo "-> scripts"
mkdir -p "$HOME/bin" "$BASE/open" "$BASE/snapshots"
install -m 755 "$HERE/track-session.sh" "$BASE/track-session.sh"
install -m 755 "$HERE/agent-restore"    "$HOME/bin/agent-restore"

# merge_hooks <file> <event:arg>...  replaces any earlier track-session.sh hook for each event
merge_hooks() {
  local file="$1" agent="$2"; shift 2
  mkdir -p "$(dirname "$file")"
  [ -f "$file" ] || echo '{}' > "$file"
  cp "$file" "$file.bak-agent-restore"
  local filter='.hooks = (.hooks // {})' pair
  for pair in "$@"; do
    filter+=" | add(\"${pair%%:*}\"; \"${pair#*:}\")"
  done
  local tmp; tmp="$(mktemp "$file.XXXXXX")"
  jq --arg track "$TRACK" --arg agent "$agent" '
    def add(ev; arg):
      .hooks[ev] = ((.hooks[ev] // [])
        | map(select(any(.hooks[]?; .command // "" | contains("track-session.sh")) | not))
        + [{hooks: [{type: "command", command: ($track + " " + arg + " " + $agent)}]}]);
  '"$filter" "$file" > "$tmp" && mv "$tmp" "$file"
}

echo "-> Claude hooks in ~/.claude/settings.json"
merge_hooks "$HOME/.claude/settings.json" claude SessionStart:start UserPromptSubmit:prompt SessionEnd:end

if command -v codex >/dev/null 2>&1 || [ -d "$HOME/.codex" ]; then
  echo "-> Codex hooks in ~/.codex/hooks.json"
  # no SessionEnd: Codex can't tell /exit from a closing window, so entries are kept
  merge_hooks "$HOME/.codex/hooks.json" codex SessionStart:start UserPromptSubmit:prompt
fi

# migrate from the old claude-restore layout
if [ -d "$HOME/.claude/open-sessions" ]; then
  echo "-> migrating ~/.claude/open-sessions"
  for f in "$HOME"/.claude/open-sessions/*.json; do
    [ -e "$f" ] || continue
    dest="$BASE/open/$(basename "$f")"
    [ -e "$dest" ] || jq '. + {agent: (.agent // "claude")}' "$f" > "$dest"
  done
  rm -rf "$HOME/.claude/open-sessions"
fi
if [ -d "$HOME/.claude/iterm-snapshots" ]; then
  echo "-> migrating ~/.claude/iterm-snapshots"
  for f in "$HOME"/.claude/iterm-snapshots/2*.json; do
    [ -e "$f" ] || continue
    jq '.panes |= map(. + {agent: (if .sessionId != "" then "claude" else "" end)})' "$f" > "$BASE/snapshots/$(basename "$f")"
  done
  latest=$(ls -t "$BASE"/snapshots/2*.json 2>/dev/null | head -1 || true)
  [ -n "$latest" ] && ln -sf "$latest" "$BASE/snapshots/latest.json"
  rm -rf "$HOME/.claude/iterm-snapshots"
fi
rm -f "$HOME/bin/claude-restore" "$HOME/bin/claude-snapshot" "$HOME/.claude/james-custom/track-session.sh"

case ":$PATH:" in *":$HOME/bin:"*) ;; *) echo "note: ~/bin is not on PATH; add it to run 'agent-restore' directly." ;; esac

echo
echo "Done. Restart running Claude/Codex tabs so their hooks load."
echo "Codex skips new hooks until trusted: run /hooks inside codex once and approve track-session.sh."
echo "Then use:  agent-restore   |   agent-restore snapshot   |   agent-restore last"
