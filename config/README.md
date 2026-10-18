# Agent configs

Backups / canonical copies of agent extensions and plugins I care about.

## Layout

```
config/
├── pi/
│   └── extensions/
│       └── litellm-provider.ts       # pi extension: auto-registers LiteLLM
│                                     # models as a pi provider on startup.
│                                     # Lives at ~/.pi/agent/extensions/
└── opencode/
    ├── plugins/
    │   └── litellm-model-sync.ts     # opencode plugin: adds the
    │                                 # `litellm_models_diff` tool.
    │                                 # Lives at ~/.config/opencode/plugins/
    └── commands/
        └── sync-models.md            # opencode `/sync-models` command,
                                      # walks through additions/removals
                                      # interactively and edits opencode.json.
                                      # Lives at ~/.config/opencode/commands/
```

## Install / restore

Symlink the tracked copies into place (destructive to whatever's already there):

```bash
DOT="$HOME/git/dotfiles/config"

mkdir -p "$HOME/.pi/agent/extensions" \
         "$HOME/.config/opencode/plugins" \
         "$HOME/.config/opencode/commands"

ln -sf "$DOT/pi/extensions/litellm-provider.ts"          "$HOME/.pi/agent/extensions/litellm-provider.ts"
ln -sf "$DOT/opencode/plugins/litellm-model-sync.ts"     "$HOME/.config/opencode/plugins/litellm-model-sync.ts"
ln -sf "$DOT/opencode/commands/sync-models.md"           "$HOME/.config/opencode/commands/sync-models.md"
```

Both tools need `LITELLM_API_KEY` set in the shell. Optional:
`LITELLM_BASE_URL` (defaults to `https://llm.ssense.com`).

## Upstream

The opencode plugin + command originate from
`ssense-skills/opencode/litellm-model-sync/` in the SSENSE workspace. This
directory is a snapshot — pull that repo for updates and re-copy if you want
them tracked here.

The pi extension is hand-rolled; the copy in this repo is the source of truth.
