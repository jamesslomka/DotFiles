#!/usr/bin/env bash
#
# Restore the QMD knowledge-base sync on a fresh Mac.
#
# Puts the scripts, QMD collection config and launchd agent in place, then
# runs one sync so the index exists. Idempotent; re-run after editing anything
# in this directory to push the change live.
#
# install.sh --restore   also pulls the whole corpus back from R2 first.
#
# Prereqs (see README.md): brew bundle from the repo Brewfile (jq, uv, nvm,
# hyprnote), a node on PATH, and `npm i -g @tobilu/qmd`.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.james.qmd-daily-sync"
NODE_BIN="$(dirname "$(command -v node)")"

for cmd in qmd uv jq anarlog rclone; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "install: '$cmd' not on PATH. See README.md prereqs." >&2
    exit 1
  }
done

echo "-> scripts"
mkdir -p "$HOME/bin" "$HOME/.claude/scripts/cconvos"
install -m 755 "$HERE/qmd-daily-sync.sh" "$HOME/bin/qmd-daily-sync.sh"
install -m 755 "$HERE/anarlog-sync.sh"   "$HOME/anarlog-sync.sh"
install -m 755 "$HERE/qmd-r2-backup.sh"  "$HOME/bin/qmd-r2-backup.sh"
install -m 755 "$HERE/qmd-r2-setup.sh"   "$HOME/bin/qmd-r2-setup.sh"
install -m 755 "$HERE/../.claude/scripts/cconvos/convert.py" "$HOME/.claude/scripts/cconvos/convert.py"
install -m 644 "$HERE/../.claude/scripts/cconvos/README.md"  "$HOME/.claude/scripts/cconvos/README.md"

# The wrapper's PATH names the nvm node dir from the original machine; point it
# at whatever node is current here so launchd can find qmd.
sed -i '' "s#\$HOME/.nvm/versions/node/v22.20.0/bin#$NODE_BIN#" "$HOME/bin/qmd-daily-sync.sh"

echo "-> qmd collections config"
mkdir -p "$HOME/.config/qmd" "$HOME/cconvos" "$HOME/mmeetings" "$HOME/recaps"
if [ -f "$HOME/.config/qmd/index.yml" ]; then
  cp "$HOME/.config/qmd/index.yml" "$HOME/.config/qmd/index.yml.bak"
fi
sed "s#/Users/james.slomka#$HOME#g" "$HERE/index.yml" > "$HOME/.config/qmd/index.yml"

echo "-> launchd agent"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
sed "s#/Users/james.slomka#$HOME#g" "$HERE/$LABEL.plist" > "$HOME/Library/LaunchAgents/$LABEL.plist"
plutil -lint "$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl print "gui/$(id -u)/$LABEL" | grep -E '^\s*(state|program) =' || true

echo "-> qmd models (skips anything already downloaded)"
qmd pull

# --restore: pull the previous machine's corpus down from R2 first, so the
# first index run is over the full history rather than an empty folder.
if [ "${1:-}" = "--restore" ]; then
  echo "-> restore from R2"
  [ -f "$HOME/.config/qmd/backup.env" ] || "$HOME/bin/qmd-r2-setup.sh"
  "$HOME/bin/qmd-r2-backup.sh" restore
fi

echo "-> first sync (this can take a while on a fresh index)"
"$HOME/bin/qmd-daily-sync.sh" || true
tail -n 8 "$HOME/Library/Logs/qmd-daily-sync.log"

echo
echo "Done. Daily run at 08:17; log at ~/Library/Logs/qmd-daily-sync.log"
echo "Kick it manually:  launchctl kickstart -k gui/\$(id -u)/$LABEL"
