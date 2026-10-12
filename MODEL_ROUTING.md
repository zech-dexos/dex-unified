# DexOS inference routing

DexOS keeps identity, continuity, goals, memories, governance, and capability implementations outside the replaceable inference model. The inference router selects a model for each request and reports the actual provider/model used.

## Quick model swap

Set the default chat model in the service environment:

```bash
DEX_MODEL=vertex:gemini-3.6-flash
```

Supported model prefixes:

| Prefix | Configuration | Example |
|---|---|---|
| `vertex:` | Existing Vertex/Gemini credentials | `vertex:gemini-3.6-flash` |
| `openrouter:` | `OPENROUTER_KEY` | `openrouter:google/gemma-4-26b-a4b-it:free` |
| `groq:` | `GROQ_KEY` | `groq:openai/gpt-oss-20b` |
| `ollama:` | `DEX_OLLAMA_BASE_URL`, optional `DEX_OLLAMA_API_KEY` | `ollama:qwen3:8b` |
| `openai-compatible:` | `DEX_OPENAI_COMPATIBLE_BASE_URL`, optional `DEX_OPENAI_COMPATIBLE_API_KEY` | `openai-compatible:your-model-id` |
| `local:` | Bundled GGUF model via `LOCAL_SLM_PATH` | `local:default` |

The OpenAI-compatible URL may be the server root, a `/v1` base URL, or a full `/v1/chat/completions` endpoint. For example, an Ollama server on the same machine typically uses `DEX_OLLAMA_BASE_URL=http://localhost:11434/v1`. A deployed Cloud Run service cannot reach Ollama on Root's PC through its own `localhost`; the URL must be reachable from the service.

## Separate chat and ambient models

```bash
DEX_MODEL=vertex:gemini-3.6-flash
DEX_AMBIENT_MODEL=local:default
DEX_MEMORY_MODEL=groq:openai/gpt-oss-20b
DEX_CLASSIFIER_MODEL=groq:openai/gpt-oss-20b
```

Ambient cognition defaults to the bundled local CPU model so scheduled pulses do not consume hosted API quota. Memory extraction and intent classification use the configured router and can fall back when a provider is unavailable. Choose auxiliary models deliberately: each hosted call can consume that provider's quota.

## Fallback and rate limits

`DEX_FALLBACK_MODELS` is an optional comma-separated ordered list. If unset, Dex tries the configured OpenRouter candidates and then the bundled local model. Local fallback can answer without hosted inference, but it does **not** execute Dex runtime capabilities; the chat response and UI report this limitation.

`strict_model: true` disables fallback for controlled comparisons. Use it when measuring whether two different models behave differently under the same Dex architecture.

Transient model rate limits trigger a short model cooldown. Daily/provider quota errors trigger a longer provider cooldown. Cooldowns are persisted in Firestore when available and cached in-process; if Firestore is unavailable, only the local cooldown remains.

The `/chat` response reports `provider`, `model`, `requested_model`, `fallback_used`, and `capability_execution_available`. Compare the actual provider/model and capability results, not just the prose response.

## Important verification boundary

This routing layer is not proof that every DexOS subsystem has been audited or that live providers are reachable. Run the repository verification workflow, then exercise chat, ambient pulse, memory recall, participant recognition, capability calls, and persistence in a controlled deployment before merging or changing production traffic.
