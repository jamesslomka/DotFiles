#!/usr/bin/env bash
#
# Daily QMD refresh. Run by launchd (com.james.qmd-daily-sync) once a day.
#
#   1. ~/anarlog-sync.sh            -> ~/mmeetings   (meetings collection)
#   2. cconvos convert.py           -> ~/cconvos     (claude-sessions collection, Claude + Codex)
#   3. qmd update                   -> re-scan every collection for new/changed files
#   4. qmd embed                    -> refresh vector embeddings
#   5. qmd-r2-backup.sh sync        -> mirror everything to Cloudflare R2 (if configured)
#
# Each step logs to ~/Library/Logs/qmd-daily-sync.log. A failure in one step
# does not stop the others; the exit code is non-zero if anything failed.
#
# Run by hand:  ~/bin/qmd-daily-sync.sh
# Kick launchd: launchctl kickstart -k gui/$(id -u)/com.james.qmd-daily-sync

set -uo pipefail

# launchd does not source your shell profile, so build PATH explicitly.
export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v22.20.0/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export HOME="${HOME:-/Users/james.slomka}"

LOG="$HOME/Library/Logs/qmd-daily-sync.log"
# convert.py lives at james-custom/ on the original machine and at scripts/
# when restored from the dotfiles repo; accept either.
CCONVOS=""
for c in "$HOME/.claude/james-custom/cconvos/convert.py" "$HOME/.claude/scripts/cconvos/convert.py"; do
  [ -f "$c" ] && { CCONVOS="$c"; break; }
done
LOCK="$HOME/.qmd-daily-sync.lock"

# Keep the log from growing forever (~5 MB cap, keep the tail).
if [ -f "$LOG" ] && [ "$(stat -f %z "$LOG")" -gt 5000000 ]; then
  tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

exec >>"$LOG" 2>&1

# Don't overlap with a still-running previous run (qmd's sqlite hates that).
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "[$(date '+%F %T')] another run holds $LOCK, skipping"
  exit 0
fi
trap 'rmdir "$LOCK"' EXIT

failed=0
step() {
  local name="$1"; shift
  echo
  echo "===== [$(date '+%F %T')] $name"
  if "$@"; then
    echo "----- $name: ok"
  else
    echo "----- $name: FAILED (exit $?)"
    failed=1
  fi
}

echo
echo "################ qmd-daily-sync start $(date '+%F %T') ################"

step "anarlog-sync"    "$HOME/anarlog-sync.sh"
if [ -n "$CCONVOS" ]; then
  step "cconvos convert" uv run --python 3.11 "$CCONVOS" convert
else
  echo "cconvos convert: convert.py not found, skipping"; failed=1
fi
step "qmd update"      qmd update
step "qmd embed"       qmd embed

# 5) off-site copy to Cloudflare R2. Silently skipped until qmd-r2-setup.sh has
#    been run, so the job keeps working on a machine with no bucket configured.
if [ -f "$HOME/.config/qmd/backup.env" ]; then
  step "r2 backup"       "$HOME/bin/qmd-r2-backup.sh" sync
else
  echo; echo "===== r2 backup: not configured (run qmd-r2-setup.sh), skipping"
fi

echo
echo "################ qmd-daily-sync end   $(date '+%F %T') (failed=$failed) ################"
exit "$failed"
