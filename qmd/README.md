# QMD knowledge base sync

Everything that feeds my local [QMD](https://github.com/tobi/qmd) search index,
and the launchd job that refreshes it every morning.

## What gets indexed

| Collection        | Folder        | Fed by                                              |
|-------------------|---------------|-----------------------------------------------------|
| `claude-sessions` | `~/cconvos`   | `convert.py` (Claude Code **and** Codex transcripts) |
| `meetings`        | `~/mmeetings` | `anarlog-sync.sh` (Hyprnote/Anarlog meetings)        |
| `projects`        | `~/.claude/projects` | Claude Code auto-memory, nothing to run       |
| `recaps`          | `~/recaps`    | the `/recap` Claude skill, on demand                 |

## Files

```
qmd/
├── install.sh                      # restore everything on a new machine (--restore: from R2)
├── qmd-r2-backup.sh                # -> ~/bin/                 sync|restore|check|status to R2
├── qmd-r2-setup.sh                 # -> ~/bin/                 one-time R2 remote config
├── qmd-daily-sync.sh               # -> ~/bin/                 the daily job
├── anarlog-sync.sh                 # -> ~/                     meeting export
├── com.james.qmd-daily-sync.plist  # -> ~/Library/LaunchAgents daily 08:17
└── index.yml                       # -> ~/.config/qmd/         collections + models

../.claude/scripts/cconvos/
├── convert.py                      # -> ~/.claude/scripts/cconvos/  session converter
└── README.md
```

The daily job runs, in order: `anarlog-sync.sh`, `convert.py convert`,
`qmd update`, `qmd embed`, then `qmd-r2-backup.sh sync`. The `qmd update` step matters: `qmd embed` on its
own only embeds documents already in the index and never notices new files.
That was the bug with the old SessionEnd hook, which is why this is a cron-style
job now instead of a Claude hook.

## Restore on a new Mac

1. `brew bundle` from the repo root (gives `jq`, `uv`, `nvm`, `hyprnote`).
2. Have a node on PATH, then `npm i -g @tobilu/qmd`.
3. Install the `anarlog` CLI (ships with Hyprnote) so it is on PATH.
4. Sign in to Hyprnote so `~/Library/Application Support/hyprnote/app.db` exists.
5. `./install.sh`

`install.sh` copies files into place (no symlinks, matching the rest of this
repo), rewrites the hardcoded `/Users/james.slomka` in the plist and
`index.yml` to `$HOME`, loads the launchd agent, pulls the QMD models and runs
one full sync. The first embed of ~2,000 documents takes a while.

## Day to day

```bash
tail -f ~/Library/Logs/qmd-daily-sync.log            # watch a run
launchctl kickstart -k gui/$(id -u)/com.james.qmd-daily-sync   # run now
launchctl print gui/$(id -u)/com.james.qmd-daily-sync | grep 'last exit'
qmd collection list                                  # per-collection freshness
```

If the Mac is asleep at 08:17, launchd runs the job at the next wake, which is
the reason this is a LaunchAgent rather than a crontab entry.

## Editing

The copies under `~` are the live ones. After changing something here, re-run
`./install.sh` (or copy the one file by hand) to push it live, and vice versa.
`~/bin/qmd-daily-sync.sh` hardcodes the nvm node path of the original machine
in its `PATH` line; `install.sh` patches it to the current node on restore.

## Off-site backup (Cloudflare R2)

Step 5 of the daily job mirrors the corpus to an R2 bucket with rclone:

| Set               | Local                | What                                  |
|-------------------|----------------------|---------------------------------------|
| `cconvos`         | `~/cconvos`          | converted sessions, `*.md` only        |
| `mmeetings`       | `~/mmeetings`        | meeting exports                        |
| `recaps`          | `~/recaps`           | `/recap` output                        |
| `qmd-config`      | `~/.config/qmd`      | `index.yml`                            |
| `claude-projects` | `~/.claude/projects` | raw Claude transcripts, memory notes   |
| `codex-sessions`  | `~/.codex/sessions`  | raw Codex rollouts                     |

The raw transcripts are included because the markdown is a lossy derivative;
with them you can re-convert later. `.tools.jsonl` sidecars and the QMD index
database are not backed up, both are regenerable.

Anything a sync would overwrite or delete is moved to
`_history/<date>/<set>/` in the bucket first (R2 has no object versioning), so
a bad local day never destroys the only copy. Prune `_history` by hand when it
gets big.

Setup, once per machine:

1. Cloudflare dashboard > R2: create a bucket (default name `qmd-backup-work`).
2. R2 > Manage R2 API Tokens: create a token, permission **Object Read & Write**,
   scoped to that bucket only. Note the Access Key ID, Secret Access Key, and
   your account ID.
3. `~/bin/qmd-r2-setup.sh` and answer the prompts. Writes
   `~/.config/rclone/rclone.conf` (600) and `~/.config/qmd/backup.env`.
   Neither is tracked here; the token is the only secret.
4. `~/bin/qmd-r2-backup.sh sync` for the first upload, then `status`.

Restore on a new machine: `./install.sh --restore` (prompts for the token if
needed, pulls everything, then indexes). Or by hand:
`qmd-r2-backup.sh restore` for everything, `restore cconvos mmeetings` for a
subset. `check` verifies the bucket matches local without changing anything.
