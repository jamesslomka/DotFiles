import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/**
 * pi extension: dynamically registers all active LiteLLM models as a pi
 * provider on startup. Read-only — does not edit any config files.
 *
 * NOTE: Do not confuse with the opencode plugin `litellm-model-sync.ts` at
 *   ~/.config/opencode/plugins/litellm-model-sync.ts
 * That one is an interactive `/sync-models` command for opencode that edits
 * `opencode.json`. Same vibe, different agent, different behavior.
 *
 * Env vars:
 *   LITELLM_BASE_URL  (default: https://llm.ssense.com)
 *   LITELLM_API_KEY   (used for Authorization: Bearer <key>)
 */
export default async function (pi: ExtensionAPI) {
    const baseUrl = (process.env.LITELLM_BASE_URL ?? "https://llm.ssense.com").replace(/\/$/, "");
    const apiKey = process.env.LITELLM_API_KEY ?? "";

    let modelIds: string[] = [];
    try {
        const res = await fetch(`${baseUrl}/v1/models`, {
            headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
        });
        if (!res.ok) {
            console.error(`[litellm ext] /v1/models returned ${res.status}`);
            return;
        }
        const payload = (await res.json()) as { data?: Array<{ id: string }> };
        modelIds = (payload.data ?? []).map((m) => m.id).filter(Boolean);
    } catch (err) {
        console.error(`[litellm ext] failed to fetch models from ${baseUrl}:`, err);
        return;
    }

    if (modelIds.length === 0) {
        console.error("[litellm ext] no models returned from LiteLLM");
        return;
    }

    // Heuristics: assume reasoning + image support for known families.
    const isReasoning = (id: string) =>
        /(^|[/-])(o[13-9]|gpt-5|claude-(opus|sonnet)-[4-9]|deepseek-r1|gemini-.*(pro|thinking))/i.test(id);
    const supportsImage = (id: string) =>
        /(gpt-4|gpt-5|claude-|gemini-|llava|vision|-vl-)/i.test(id);

    pi.registerProvider("litellm", {
        baseUrl: `${baseUrl}/v1`,
        apiKey: "$LITELLM_API_KEY",
        api: "openai-completions",
        authHeader: true,
        models: modelIds.map((id) => ({
            id,
            name: id,
            reasoning: isReasoning(id),
            input: supportsImage(id) ? ["text", "image"] : ["text"],
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
            contextWindow: 128000,
            maxTokens: 8192,
        })),
    });
}
