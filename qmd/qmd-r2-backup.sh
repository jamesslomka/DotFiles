#!/usr/bin/env bash
#
# Back up the QMD knowledge base (and the raw transcripts it is built from) to
# Cloudflare R2 with rclone, or restore it on a new machine.
#
#   qmd-r2-backup.sh sync              upload new/changed files (daily job calls this)
#   qmd-r2-backup.sh restore [NAME..]  pull everything (or named sets) back to ~
#   qmd-r2-backup.sh check [NAME..]    verify remote matches local, no changes
#   qmd-r2-backup.sh status            what is in the bucket, sizes
#   qmd-r2-backup.sh ls NAME           list one set's files on the remote
#
# Each set below maps a local dir to <bucket>/<name>/. `sync` mirrors local ->
# remote; anything it would overwrite or delete is moved to
# <bucket>/_history/<YYYY-MM-DD>/<name>/ first, so a bad local day never
# destroys the only copy. Restore uses `copy`, so it never deletes local files.
#
# Config: ~/.config/qmd/backup.env sets QMD_BACKUP_DEST (e.g. r2:qmd-backup-work).
# The rclone remote itself lives in ~/.config/rclone/rclone.conf; create both
# with qmd-r2-setup.sh.

set -uo pipefail

CONF="$HOME/.config/qmd/backup.env"
[ -f "$CONF" ] && . "$CONF"
DEST="${QMD_BACKUP_DEST:-}"

# name|local dir|space-separated globs to include (everything else is skipped)
SETS=(
  "cconvos|$HOME/cconvos|*.md"
  "mmeetings|$HOME/mmeetings|*.md"
  "recaps|$HOME/recaps|*.md"
  "qmd-config|$HOME/.config/qmd|index.yml"
  "claude-projects|$HOME/.claude/projects|*.jsonl *.md *.json"
  "codex-sessions|$HOME/.codex/sessions|*.jsonl"
)

usage() { sed -n '3,22p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

need_dest() {
  if [ -z "$DEST" ]; then
    echo "qmd-r2-backup: QMD_BACKUP_DEST not set. Run qmd-r2-setup.sh first." >&2
    exit 2
  fi
  command -v rclone >/dev/null || { echo "qmd-r2-backup: rclone not on PATH" >&2; exit 2; }
}

# "name|dir|globs" -> S_NAME S_DIR and FILTERS (an rclone --filter list).
# Hidden files/dirs are dropped first, then the globs are admitted, then
# everything else is rejected. Order matters to rclone.
load_set() {
  IFS='|' read -r S_NAME S_DIR globs <<<"$1"
  FILTERS=(--filter '- .*' --filter '- .*/**')
  # set -f: the globs must reach rclone literally, not expanded against cwd.
  set -f
  for g in $globs; do FILTERS+=(--filter "+ $g"); done
  set +f
  FILTERS+=(--filter '- *')
}

# Sets to operate on: all, or those named on the command line.
select_sets() {
  if [ $# -eq 0 ]; then printf '%s\n' "${SETS[@]}"; return; fi
  for want in "$@"; do
    found=0
    for s in "${SETS[@]}"; do
      case "$s" in "$want|"*) echo "$s"; found=1 ;; esac
    done
    [ "$found" -eq 1 ] || { echo "qmd-r2-backup: unknown set '$want'" >&2; exit 2; }
  done
}

COMMON=(--fast-list --transfers 8 --checkers 16 --stats 0)
INTERESTING='Copied|Deleted|Moved|Renamed|ERROR|Failed|differences|missing'

cmd_sync() {
  need_dest
  local today rc=0 out st
  today=$(date +%F)
  while read -r s; do
    load_set "$s"
    [ -d "$S_DIR" ] || { echo "skip $S_NAME: $S_DIR missing"; continue; }
    echo "sync $S_NAME  ($S_DIR -> $DEST/$S_NAME)"
    out=$(rclone sync "$S_DIR" "$DEST/$S_NAME" \
            --backup-dir "$DEST/_history/$today/$S_NAME" \
            "${FILTERS[@]}" "${COMMON[@]}" --log-level INFO 2>&1)
    st=$?
    grep -E "$INTERESTING" <<<"$out" | sed 's/^/  /'
    [ "$st" -eq 0 ] || { echo "  sync $S_NAME FAILED (exit $st)"; rc=1; }
  done < <(select_sets "$@")
  return $rc
}

cmd_restore() {
  need_dest
  local rc=0 out st
  while read -r s; do
    load_set "$s"
    echo "restore $S_NAME  ($DEST/$S_NAME -> $S_DIR)"
    mkdir -p "$S_DIR"
    out=$(rclone copy "$DEST/$S_NAME" "$S_DIR" "${COMMON[@]}" --log-level INFO 2>&1)
    st=$?
    printf '  %s files copied\n' "$(grep -c 'Copied' <<<"$out")"
    grep -E 'ERROR|Failed' <<<"$out" | sed 's/^/  /'
    [ "$st" -eq 0 ] || { echo "  restore $S_NAME FAILED (exit $st)"; rc=1; }
  done < <(select_sets "$@")
  return $rc
}

cmd_check() {
  need_dest
  local rc=0 out st
  while read -r s; do
    load_set "$s"
    [ -d "$S_DIR" ] || continue
    printf '%-16s ' "$S_NAME"
    out=$(rclone check "$S_DIR" "$DEST/$S_NAME" "${FILTERS[@]}" --one-way --fast-list 2>&1)
    st=$?
    grep -E 'matching files|differences|missing on' <<<"$out" | sed 's/^.*NOTICE: //' | tail -1
    [ "$st" -eq 0 ] || rc=1
  done < <(select_sets "$@")
  return $rc
}

_size() {
  rclone size "$1" --json 2>/dev/null \
    | jq -r '"\(.count | tostring | (" " * (6 - length)) + .) files  \(.bytes / 1e6 * 10 | round / 10) MB"' \
    || echo "(empty or unreachable)"
}

cmd_status() {
  need_dest
  echo "remote: $DEST"
  for s in "${SETS[@]}"; do
    load_set "$s"
    printf '%-16s %s\n' "$S_NAME" "$(_size "$DEST/$S_NAME")"
  done
  printf '%-16s %s\n' "_history" "$(_size "$DEST/_history")"
}

cmd_ls() {
  need_dest
  [ $# -eq 1 ] || usage 2
  rclone ls "$DEST/$1"
}

case "${1:-}" in
  sync)    shift; cmd_sync "$@" ;;
  restore) shift; cmd_restore "$@" ;;
  check)   shift; cmd_check "$@" ;;
  status)  cmd_status ;;
  ls)      shift; cmd_ls "$@" ;;
  -h|--help|help|"") usage 0 ;;
  *) echo "qmd-r2-backup: unknown command '$1'" >&2; usage 2 ;;
esac
