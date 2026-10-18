---
description: Interactively sync opencode.json's LiteLLM model list against llm.ssense.com
agent: build
---

Sync the `provider.litellm.models` block in `~/.config/opencode/opencode.jsonc`
against what llm.ssense.com (LiteLLM proxy) actually serves.

Instructions:

1. Call the `litellm_models_diff` tool (no args needed unless the user specifies
   a different config path). It returns JSON with `remoteOnly` (models on
   LiteLLM not yet in local config) and `localOnly` (local model keys that no
   longer appear to have a remote match).

2. If both `remoteOnly` and `localOnly` are empty, tell the user config is
   already in sync and stop.

3. For each model id in `remoteOnly`:
   - Use the `question` tool to ask the user, one batch at a time (group
     related models, e.g. all `claude-opus-4-*` together), whether to add it.
   - Offer a sensible default `name` label (e.g. `claude-opus-4-8` ->
     "Claude Opus 4.8"), and ask if they want it wired to any agent as the
     model (default: no, just add to the catalog).
   - For approved additions, determine the correct local key format. This
     LiteLLM instance accepts both the short id (e.g. `claude-opus-4-8`) and
     the `global.anthropic.<id>` long form used elsewhere in the existing
     config — match the existing convention for that model family (Bedrock
     Anthropic models use `global.anthropic.*`, Kimi uses `bedrock/moonshotai.*`,
     etc. — read the existing `provider.litellm.models` keys to infer the
     right prefix per family before guessing).

4. For each model id in `localOnly`:
   - Ask the user (via `question`) whether to remove it, keep it (e.g. it may
     be an alias LiteLLM exposes under a different id), or investigate further.
   - Never delete a model that is currently referenced by name in the
     `agent.*.model`, `model`, or `small_model` top-level fields without
     explicitly flagging that removing it will break that reference.

5. Apply only the changes the user approved, using the Edit tool on
   `opencode.jsonc`. Preserve existing formatting, key order, and the
   `$schema` field.

6. Validate the file is still valid JSONC after editing. If the file contains
   no comments, `python3 -m json.tool < ~/.config/opencode/opencode.jsonc` is
   sufficient; otherwise parse it with a JSONC-aware tool.

7. Remind the user: config changes require an opencode restart to take effect.
