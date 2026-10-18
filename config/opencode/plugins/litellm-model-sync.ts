import type { Plugin } from "@opencode-ai/plugin"
import { tool } from "@opencode-ai/plugin"

/**
 * litellm-model-sync (opencode plugin)
 *
 * Adds a `litellm_models_diff` tool that compares the models currently
 * configured in opencode.json (provider.litellm.models) against what
 * llm.ssense.com actually reports via its OpenAI-compatible /v1/models
 * route.
 *
 * This tool is read-only: it reports differences but never mutates
 * config. Use the `/sync-models` command (see
 * ~/.config/opencode/commands/sync-models.md) to review the diff
 * interactively and apply changes.
 *
 * NOTE: Not to be confused with the pi extension `litellm-provider.ts` at
 *   ~/.pi/agent/extensions/litellm-provider.ts
 * That one auto-registers LiteLLM models as a pi provider on startup and
 * does not touch any config file.
 */

const LITELLM_BASE_URL = "https://llm.ssense.com"
const TOKEN_ENV_NAMES = [
  "LITELLM_API_KEY",
  "OPENAI_API_KEY",
  "SSENSE_LLM_API_KEY",
  "OPENCODE_LITELLM_API_KEY",
]

type RemoteModel = {
  id: string
}

async function fetchRemoteModelIds(): Promise<string[]> {
  const apiKey = TOKEN_ENV_NAMES.map((name) => process.env[name]).find(Boolean)
  if (!apiKey) {
    throw new Error(
      `No LiteLLM API key found. Set one of: ${TOKEN_ENV_NAMES.join(", ")}.`,
    )
  }

  const res = await fetch(`${LITELLM_BASE_URL}/v1/models`, {
    headers: { Authorization: `Bearer ${apiKey}` },
  })

  if (!res.ok) {
    throw new Error(
      `LiteLLM /v1/models request failed: ${res.status} ${res.statusText}`,
    )
  }

  const body = (await res.json()) as { data: RemoteModel[] }
  return body.data.map((m) => m.id).sort()
}

export const LitellmModelSyncPlugin: Plugin = async ({ directory, worktree, $ }) => {
  return {
    tool: {
      litellm_models_diff: tool({
        description:
          "Fetch the current model list from llm.ssense.com (LiteLLM proxy) and " +
          "diff it against the models configured in opencode.json under " +
          "provider.litellm.models. Returns remote model ids not yet in local " +
          "config, and local model ids (by short suffix match) no longer seen " +
          "remotely. Read-only — does not modify any files.",
        args: {
          configPath: tool.schema
            .string()
            .optional()
            .describe(
              "Absolute path to the opencode.json to diff against. " +
                "Defaults to ~/.config/opencode/opencode.jsonc.",
            ),
        },
        async execute(args) {
          const path =
            args.configPath ?? `${process.env.HOME}/.config/opencode/opencode.jsonc`

          const file = await Bun.file(path).text()
          const config = JSON.parse(stripJsonComments(file))

          const localModelKeys: string[] = Object.keys(
            config?.provider?.litellm?.models ?? {},
          )

          // Local keys look like "global.anthropic.claude-sonnet-5" or
          // "bedrock/moonshotai.kimi-k2.5". Remote ids are short, e.g.
          // "claude-sonnet-5" or "moonshotai.kimi-k2.5". Match remote id
          // as a suffix of the local key (after the last '.' segment logic
          // is too lossy, so just check "endsWith" / "includes").
          const remoteIds = await fetchRemoteModelIds()

          const remoteNotLocal = remoteIds.filter(
            (rid) => !localModelKeys.some((lk) => lk.endsWith(rid) || lk.includes(rid)),
          )

          const localNotRemote = localModelKeys.filter(
            (lk) => !remoteIds.some((rid) => lk.endsWith(rid) || lk.includes(rid)),
          )

          const result = {
            remoteTotal: remoteIds.length,
            localTotal: localModelKeys.length,
            remoteOnly: remoteNotLocal,
            localOnly: localNotRemote,
          }

          return JSON.stringify(result, null, 2)
        },
      }),
    },
  }
}

function stripJsonComments(input: string): string {
  let result = ""
  let inString = false
  let inLineComment = false
  let inBlockComment = false
  let escaped = false

  for (let i = 0; i < input.length; i++) {
    const char = input[i]
    const next = input[i + 1]

    if (inLineComment) {
      if (char === "\n") {
        inLineComment = false
        result += char
      }
      continue
    }

    if (inBlockComment) {
      if (char === "*" && next === "/") {
        inBlockComment = false
        i++
      }
      continue
    }

    if (!inString && char === "/" && next === "/") {
      inLineComment = true
      i++
      continue
    }

    if (!inString && char === "/" && next === "*") {
      inBlockComment = true
      i++
      continue
    }

    result += char

    if (char === '"' && !escaped) inString = !inString
    escaped = inString && char === "\\" && !escaped
  }

  return result
}

export default LitellmModelSyncPlugin
