#!/usr/bin/env bash
#
# Export Anarlog meetings to markdown files in ~/mmeetings.
#
# Only exports meetings that aren't already there, so re-running is a cheap
# sync. Each file gets the meeting's memo, summary, and a speaker-attributed
# transcript.
#
# On the transcript: Anarlog has no per-person diarization (`speaker_hints` is
# empty on every meeting), but each transcribed word carries a `channel` --
# 0 is your mic, 1 is system audio, i.e. everyone else. The CLI's own markdown
# export flattens both channels into one time-ordered blob, so overlapping
# speech comes out interleaved word-by-word and reads as garbage. So we pull
# --format json instead and rebuild the transcript from the word list: split by
# channel, break each channel into utterances wherever it goes quiet for more
# than --gap milliseconds, then merge both sides back together by timestamp.
# The result is a two-voice dialogue. It cannot tell you which of six people on
# a call was talking -- only you vs. not-you.
#
# Meetings with no memo, no summary and no transcript (calendar entries that
# were never recorded) are skipped rather than written as empty stubs. Nothing
# is written for them, so every later run re-checks them and they get picked up
# automatically if content ever shows up.
#
# Filenames look like:
#   2026-07-31-confirmed-price-crawler-poc-e5354076.md
#
# The trailing 8 chars are the start of the meeting's UUID. The "already
# exported?" check matches on that, not the whole name, so renaming a meeting
# in Anarlog doesn't get you a second copy on the next sync.
#
# Usage:
#   anarlog-sync.sh [--dry-run] [--force] [--dest DIR] [--gap MS]
#
#   --dry-run   print what would happen, write nothing
#   --force     re-export meetings that already have a file
#   --dest DIR  where to write (default ~/mmeetings, or $ANARLOG_SYNC_DEST)
#   --gap MS    silence that separates two turns (default 2000)
#
# Speaker labels come from $ANARLOG_ME and $ANARLOG_THEM.

set -euo pipefail

# BSD sed chokes on accented characters in titles ("illegal byte sequence")
# unless we drop to byte semantics.
export LC_ALL=C

DEST="${ANARLOG_SYNC_DEST:-$HOME/mmeetings}"
ME="${ANARLOG_ME:-James}"
THEM="${ANARLOG_THEM:-Others}"
GAP=2000
PAGE_SIZE=200
force=0
dry_run=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=1; shift ;;
    --force)   force=1; shift ;;
    --dest)
      [ $# -ge 2 ] || { echo "anarlog-sync: --dest needs a directory" >&2; exit 2; }
      DEST="$2"; shift 2 ;;
    --gap)
      [ $# -ge 2 ] || { echo "anarlog-sync: --gap needs a value in ms" >&2; exit 2; }
      case "$2" in ''|*[!0-9]*) echo "anarlog-sync: --gap must be a number" >&2; exit 2 ;; esac
      GAP="$2"; shift 2 ;;
    -h|--help)
      sed -n '3,40p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "anarlog-sync: unknown option '$1' (try --help)" >&2; exit 2 ;;
  esac
done

for cmd in anarlog jq; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "anarlog-sync: '$cmd' not found on PATH" >&2
    exit 1
  }
done

# Bail early on a bad database rather than failing once per meeting.
if ! doctor=$(anarlog --json doctor 2>&1); then
  echo "anarlog-sync: anarlog doctor failed:" >&2
  echo "$doctor" >&2
  exit 1
fi
if [ "$(jq -r '.data.ready' <<<"$doctor")" != "true" ]; then
  echo "anarlog-sync: anarlog database is not ready" >&2
  jq -r '.data.database | "  path:  \(.path)\n  error: \(.error // "none")"' <<<"$doctor" >&2
  exit 1
fi

mkdir -p "$DEST"

# "Some Title / Thing!" -> "some-title-thing"
slugify() {
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -e 's/[^a-z0-9]\{1,\}/-/g' -e 's/^-*//' -e 's/-*$//' \
    | cut -c1-60 \
    | sed -e 's/-*$//'
}

# Turns one meeting's JSON export into the markdown we actually keep.
# Args: --arg me --arg them --arg gap
render_md() {
  jq -r --arg me "$ME" --arg them "$THEM" --arg gap "$GAP" '
    def pad2: tostring | if length < 2 then "0" + . else . end;
    def hhmmss:
      (. / 1000 | floor) as $s
      | "\(($s / 3600 | floor) | pad2):\((($s % 3600) / 60 | floor) | pad2):\(($s % 60) | pad2)";

    # Summaries and memos repeat the meeting title as their first line, and use
    # H1 for their own section headings. Drop the duplicate title and push the
    # headings below our "## Summary" so the outline nests properly.
    def clean_body($title):
      (. // "")
      | split("\n")
      | (if (length > 0) and (.[0] == ("# " + $title)) then .[1:] else . end)
      | map(if startswith("# ") then "### " + .[2:] else . end)
      | join("\n")
      | sub("^[[:space:]]+"; "")
      | sub("[[:space:]]+$"; "");

    . as $m
    | (($m.title // "") | if . == "" then "Untitled meeting" else . end) as $title
    | (if ($m.started_at // "") != "" then $m.started_at
       elif ($m.created_at // "") != "" then $m.created_at
       else "" end) as $date
    | ([$m.participants[]? | (.display_name // .email // empty)
        | select(. != "")] | unique) as $people
    | (($m.note.markdown // "") | clean_body($title)) as $note
    | ([$m.summaries[]? | (.markdown // "") | clean_body($title)
        | select(length > 0)]) as $sums
    | ([$m.transcripts[]?.words[]?]) as $words
    | ($gap | tonumber) as $G

    # Split by channel, glue each channel back into utterances across short
    # gaps, then interleave the two channels by start time.
    | ([0, 1]
       | map(. as $ch
           | [$words[] | select(.channel == $ch)]
           | reduce .[] as $x ([];
               if (length > 0) and ((($x.start_ms // 0) - (.[-1].end // 0)) < $G)
               then (.[:-1] + [{ch: $ch, start: .[-1].start, end: $x.end_ms,
                                text: (.[-1].text + ($x.text // ""))}])
               else . + [{ch: $ch, start: ($x.start_ms // 0), end: ($x.end_ms // 0),
                          text: ($x.text // "")}]
               end))
       | add // []
       | map(.text |= (gsub("[[:space:]]+"; " ") | sub("^ "; "") | sub(" $"; "")))
       | map(select(.text != ""))
       | sort_by(.start)) as $turns

    | (["# " + $title,
        "",
        "- ID: `" + ($m.id // "") + "`",
        "- Date: " + (if $date == "" then "(unknown)" else $date end)]
       + (if ($people | length) > 0
          then ["- Participants: " + ($people | join(", "))] else [] end)
       + (if $note != "" then ["", "## Notes", "", $note] else [] end)
       + (if ($sums | length) > 0
          then ["", "## Summary", "", ($sums | join("\n\n"))] else [] end)
       + (if ($turns | length) > 0
          then ["", "## Transcript", ""]
               + [$turns[]
                  | "[" + (.start | hhmmss) + "] **"
                    + (if .ch == 0 then $me else $them end) + ":** " + .text]
          else [] end)
       + [""])
    | join("\n")
  '
}

new=0
skipped=0
nocontent=0
failed=0
offset=0

while :; do
  if ! page=$(anarlog --json meetings list --limit "$PAGE_SIZE" --offset "$offset" 2>&1); then
    echo "anarlog-sync: failed to list meetings at offset $offset:" >&2
    echo "$page" >&2
    exit 1
  fi

  count=$(jq '.data | length' <<<"$page")
  [ "$count" -eq 0 ] && break

  # The dates are sometimes empty strings rather than null, and jq's `//` only
  # catches null/false, hence the explicit if/elif.
  while IFS=$'\t' read -r id date title; do
    [ -n "$id" ] || continue

    short="${id:0:8}"
    existing=$(find "$DEST" -maxdepth 1 -name "*-$short.md" -print -quit 2>/dev/null || true)

    if [ -n "$existing" ] && [ "$force" -eq 0 ]; then
      skipped=$((skipped + 1))
      continue
    fi

    slug=$(slugify "$title")
    [ -n "$slug" ] || slug="untitled-meeting"

    if [ -n "$date" ]; then
      base="$date-$slug-$short"
    else
      base="undated-$slug-$short"
    fi
    target="$DEST/$base.md"

    # Render into a temp file first. A Ctrl-C partway through then leaves
    # nothing behind, rather than a truncated file that future runs would
    # mistake for a finished export. The leading dot keeps it clear of the
    # find above.
    tmp=$(mktemp "$DEST/.$short.XXXXXX")
    if ! anarlog meetings export "$id" --format json 2>/dev/null | render_md > "$tmp" 2>/dev/null; then
      rm -f "$tmp"
      echo "FAILED      $id ($title)" >&2
      failed=$((failed + 1))
      continue
    fi

    # No memo, no summary, no transcript -> never recorded. Write nothing, so
    # the next run looks at it again.
    if ! grep -qE '^## (Notes|Summary|Transcript)$' "$tmp"; then
      rm -f "$tmp"
      nocontent=$((nocontent + 1))
      [ "$dry_run" -eq 1 ] && echo "no content       $base.md"
      # Drop a stub left behind by an older version of this script.
      if [ -n "$existing" ] && [ "$dry_run" -eq 0 ]; then
        rm -f "$existing"
        echo "removed     $(basename "$existing") (no content)"
      fi
      continue
    fi

    if [ "$dry_run" -eq 1 ]; then
      rm -f "$tmp"
      if [ -n "$existing" ]; then
        echo "would re-export  $base.md"
      else
        echo "would export     $base.md"
      fi
      new=$((new + 1))
      continue
    fi

    mv -f "$tmp" "$target"
    # Title changed since last sync? Drop the file under the old name.
    if [ -n "$existing" ] && [ "$existing" != "$target" ]; then
      rm -f "$existing"
      echo "re-exported $base.md (was $(basename "$existing"))"
    else
      echo "exported    $base.md"
    fi
    new=$((new + 1))
  done < <(jq -r '
    .data[] | [
      .id,
      (if (.started_at // "") != "" then .started_at
       elif (.created_at // "") != "" then .created_at
       else "" end)[0:10],
      (.title // "")
    ] | @tsv
  ' <<<"$page")

  offset=$((offset + count))
  [ "$count" -lt "$PAGE_SIZE" ] && break
done

echo "---"
if [ "$dry_run" -eq 1 ]; then
  echo "dry run: $new to export, $skipped already present, $nocontent with no content"
else
  echo "$new exported, $skipped skipped, $nocontent with no content, $failed failed -> $DEST"
fi

[ "$failed" -eq 0 ]
