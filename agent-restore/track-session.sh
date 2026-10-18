#!/bin/bash
# Hook for Claude Code and Codex: keeps ~/.agent-restore/open/<iterm-pane-guid>.json
# pointing at the agent session running in that iTerm pane.
# Usage: track-session.sh start|prompt|end [claude|codex]   (agent defaults to claude)
# Entries are only removed on a deliberate Claude exit, so a forced close/reboot leaves them behind.
[ -z "$ITERM_SESSION_ID" ] && exit 0
agent="${2:-claude}"
dir="$HOME/.agent-restore/open"; mkdir -p "$dir"
pane="${ITERM_SESSION_ID#*:}"
f="$dir/$pane.json"
in=$(cat)
sid=$(jq -r '.session_id // empty' <<<"$in")
[ -z "$sid" ] && exit 0

case "$1" in
  end)
    # Claude: only forget on /exit, ctrl-D or logout; SIGHUP from a closing window must keep the entry.
    # Codex always reports reason "other", so its entries are never removed here.
    reason=$(jq -r '.reason // empty' <<<"$in")
    if [ "$agent" = claude ] && { [ "$reason" = "prompt_input_exit" ] || [ "$reason" = "logout" ]; }; then
      [ "$(jq -r .sessionId "$f" 2>/dev/null)" = "$sid" ] && rm -f "$f"
    fi
    exit 0 ;;
esac

if [ "$agent" = claude ]; then
  name=$(jq -r --arg s "$sid" 'select(.sessionId==$s) | .name // empty' "$HOME"/.claude/sessions/*.json 2>/dev/null | head -1)
else
  name=$(grep -F "\"$sid\"" "$HOME/.codex/session_index.jsonl" 2>/dev/null | tail -1 | jq -r '.thread_name // empty')
fi
jq -n --arg agent "$agent" --arg sid "$sid" --arg cwd "$(jq -r .cwd <<<"$in")" \
      --arg tp "$(jq -r '.transcript_path // empty' <<<"$in")" \
      --arg name "$name" --arg iterm "$ITERM_SESSION_ID" --argjson now "$(date +%s)" \
  '{agent:$agent,sessionId:$sid,cwd:$cwd,transcript:$tp,name:$name,itermSessionId:$iterm,lastSeen:$now}' > "$f.tmp" && mv "$f.tmp" "$f"
exit 0
