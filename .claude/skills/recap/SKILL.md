---
name: recap
description: Dumps the current conversation into a structured recap markdown file, organised by repo and date-time, stored in ~/recaps/.
---

# Recap

Produce a structured markdown recap of the current conversation and write it to disk.

## Steps

### 1. Gather context

Run the following shell commands to collect metadata. Handle failures gracefully — if any command fails (e.g. not in a git repo), use a sensible fallback.

```bash
# Repo name — basename of the git root, fallback to "no-repo"
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); basename "${GIT_ROOT:-}" 2>/dev/null || echo "no-repo"

# Current branch, fallback to "no-branch"
git branch --show-current 2>/dev/null || echo "no-branch"

# Absolute path to git root (to know where to write the file)
git rev-parse --show-toplevel 2>/dev/null || echo "$HOME"

# Session ID — read from the most recently modified entry in ~/.claude/session-env/
ls -t ~/.claude/session-env/ 2>/dev/null | head -1 || echo "unknown-session"

# Date-time stamp for the filename
date +"%Y-%m-%d_%H-%M-%S"

# Transcript path — Claude Code stores the raw session JSONL under
# ~/.claude/projects/<encoded-cwd>/<session-id>.jsonl
# where <encoded-cwd> is $PWD with every "/" replaced by "-".
SESSION_ID=$(ls -t ~/.claude/session-env/ 2>/dev/null | head -1)
ENCODED_CWD=$(pwd | sed 's|/|-|g')
TRANSCRIPT="$HOME/.claude/projects/${ENCODED_CWD}/${SESSION_ID}.jsonl"
[ -f "$TRANSCRIPT" ] && echo "$TRANSCRIPT" || echo "no-transcript"
```

### 2. Determine output path

```
~/recaps/{repo-name}/{date-time}/
```

Ensure the base `~/recaps/` directory exists (creating it if missing), then create the full path including any missing parent directories:

```bash
mkdir -p ~/recaps/{repo-name}/{date-time}
```

The output file will be:
- `~/recaps/{repo-name}/{date-time}/recap.md` — structured findings

### 3. Write the recap file

Write `recap.md` inside the folder. The file must follow this template exactly:

```markdown
# Recap — {date-time}

**Repo:** {repo-name}
**Branch:** {branch-name}
**Session ID:** {session-id}
**Date:** {ISO date-time}
**Transcript:** [{session-id}.jsonl]({transcript-path})

---

## Summary

{2–4 sentence plain-English summary of what was worked on this session.}

---

## Key Decisions

{Bulleted list of decisions made. Each bullet should be a single sentence stating what was decided and why (if known). Omit this section if no decisions were made.}

---

## Changes Made

{Bulleted list of files created, edited, or deleted. Include a one-line description of what changed. Omit if nothing was changed.}

---

## Open Questions

{Numbered list of unresolved questions or ambiguities that came up. Omit if none.}

---

## Follow-ups / Next Steps

{Numbered list of concrete next actions the user or Claude should take. Omit if none.}

---

## Notes

{Anything else worth preserving — context, links, constraints, gotchas. Omit if empty.}
```

### 4. Index with QMD

After writing the files, check whether `qmd` is available:

```bash
command -v qmd 2>/dev/null
```

If available, run:

```bash
qmd embed
```

Output the recap folder path and confirm indexing ran (or that qmd was not found).

## Notes

- Write every section you have content for. Omit sections that would be empty — don't leave placeholder text.
- Be concise but specific. A good recap is one someone could read in 2 minutes and know exactly what happened.
- If the conversation touched multiple unrelated topics, group the Key Decisions and Follow-ups under sub-headings per topic.
- If the transcript lookup in step 1 returned `no-transcript` (file not found), omit the `**Transcript:**` line entirely from the header.
