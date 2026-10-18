# 🅳🅾🆃 🅵🅸🅻🅴🆂

### Installation

`osx-bootstrap.sh` for software setup

`git-setup.sh` for git setup

### Stack
- oh-my-zsh
- pure prompt (https://github.com/sindresorhus/pure)
- [hyper-snazzy theme](https://github.com/sindresorhus/iterm2-snazzy)

### QMD knowledge base

`qmd/install.sh` restores the local QMD search index (Claude/Codex sessions,
meetings, recaps) and its daily launchd refresh. See `qmd/README.md`.

### Agent session restore

`agent-restore/install.sh` installs hooks that track which Claude Code and Codex
sessions are open in iTerm tabs, plus an `agent-restore` picker to reopen them after
a forced quit or reboot. `agent-restore snapshot` / `agent-restore last` save and
rebuild the whole iTerm window/tab layout. See `agent-restore/README.md`.
