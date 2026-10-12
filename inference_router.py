"""Central inference router for DexOS chat and model experiments.

Provider/model selection is explicit; identity and persisted state live elsewhere.
"""
import os

OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("DEX_MODEL", "vertex:gemini-3.6-flash")
GROQ_MODEL = os.environ.get("DEX_GROQ_MODEL", "openai/gpt-oss-20b")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")

# Identity, memory and governance remain independent of the replaceable spark.
# Explicit per-request model choices are strict for meaningful comparisons.
DEFAULT_FALLBACK_MODELS = [
    "openrouter:google/gemma-4-31b-it:free",
    "openrouter:google/gemma-4-26b-a4b-it:free",
    "openrouter:nvidia/nemotron-3-nano-30b-a3b:free",
    "openrouter:liquid/lfm-2.5-1.2b-instruct:free",
]

def _parse_model_spec(spec):
    """Return provider/model. Prefixes: vertex:, groq:, openrouter:."""
    spec = (spec or DEFAULT_MODEL).strip()
    if ":" in spec:
        prefix, model_id = spec.split(":", 1)
        if prefix.lower() in ("vertex", "gemini", "groq", "openrouter"):
            provider = "vertex" if prefix.lower() == "gemini" else prefix.lower()
            if not model_id.strip():
                raise ValueError("Model ID cannot be empty")
            return provider, model_id.strip()
    if spec.startswith("gemini-"):
        return "vertex", spec
    # Existing clients passing bare IDs keep OpenRouter semantics.
    return "openrouter", spec

def _completion_text(data):
    if not isinstance(data, dict) or data.get("error"):
        return ""
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return message.get("content") or message.get("reasoning") or ""

async def _call_selected_model(client, messages, model_spec, max_tokens):
    provider, model_id = _parse_model_spec(model_spec)
    if provider == "vertex":
        from gemini_client import call_gemini
        result = await call_gemini(
            client, messages, max_tokens, model_name=model_id, enable_tools=True
        )
        if result:
            result.update({
                "model": model_id, "provider": provider,
                "requested_model": model_spec,
            })
        return result

    if provider == "groq":
        key, url = os.environ.get("GROQ_KEY", ""), GROQ_URL
    elif provider == "openrouter":
        key, url = OPENROUTER_KEY, OPENROUTER_URL
    else:
        raise ValueError(f"Unsupported inference provider: {provider}")
    if not key:
        print(f"[model-router] {provider} selected but its API key is not configured")
        return None

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://dex-backend-production-2bbe.up.railway.app"
        headers["X-Title"] = "DexOS"

    # Keep Dex's capability surface portable across OpenAI-compatible providers.
    # Models/providers that do not support function calling fail explicitly;
    # we do not silently pretend the capability was available.
    tool_specs = [
        {"type": "function", "function": {"name": "inspect_state", "description": "Inspect Dex's durable self-state, goals, workspace and latest pulse.", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "inspect_workspace", "description": "Inspect Dex's active mental workspace.", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "inspect_goals", "description": "Inspect Dex's persisted goals.", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "inspect_open_loops", "description": "Inspect Dex's persisted unresolved/open loops.", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "inspect_thoughts", "description": "Inspect Dex's recent persistent thoughts.", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "inspect_experiences", "description": "Inspect durable experiences and continuity lineage.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}}},
        {"type": "function", "function": {"name": "inspect_participant", "description": "Inspect Dex's current participant snapshot and interlocutor.", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "inspect_conversation", "description": "Inspect ongoing conversation state.", "parameters": {"type": "object", "properties": {"user_id": {"type": "string"}}}}},
        {"type": "function", "function": {"name": "recall_experience", "description": "Retrieve relevant durable experiences into active cognition.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}}},
        {"type": "function", "function": {"name": "listen", "description": "Listen to latest durable signals available to Dex.", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "evoke", "description": "Retrieve a DexOS resource into active cognition. Resources: state, workspace, goals, open_loops, thoughts, experiences, participant, conversation, signals.", "parameters": {"type": "object", "properties": {"resource": {"type": "string"}}, "required": ["resource"]}}},
        {"type": "function", "function": {"name": "search_architecture", "description": "Search DexOS source and persisted text read-only; never executes source.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    ]
    working_messages = list(messages)
    tool_calls_seen = []
    try:
        for _ in range(5):
            response = await client.post(
                url, headers=headers,
                json={
                    "model": model_id,
                    "messages": working_messages,
                    "max_tokens": max_tokens,
                    "tools": tool_specs,
                    "tool_choice": "auto",
                },
            )
            try:
                data = response.json()
            except Exception:
                data = {}
            if not response.is_success or data.get("error"):
                print(f"[model-router] {provider}:{model_id} failed HTTP {response.status_code}: "
                      f"{str(data.get('error', data))[:400]}")
                return None
            choices = data.get("choices") or []
            if not choices:
                print(f"[model-router] {provider}:{model_id} returned no choices")
                return None
            message = choices[0].get("message") or {}
            pending_calls = message.get("tool_calls") or []
            if not pending_calls:
                content = message.get("content") or message.get("reasoning") or ""
                if not content:
                    return None
                return {
                    "reply": content, "model": model_id, "provider": provider,
                    "requested_model": model_spec, "tool_calls": tool_calls_seen,
                }

            # Preserve the assistant's tool-call turn and feed actual capability
            # observations back to the same model, without changing Dex's identity.
            working_messages.append({
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": pending_calls,
            })
            import json as _json
            from dex_capabilities import execute_capability
            for tool_call in pending_calls:
                function = tool_call.get("function") or {}
                name = function.get("name", "")
                args = {}
                try:
                    args = _json.loads(function.get("arguments") or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("tool arguments must be a JSON object")
                    observation = execute_capability(name, args)
                except Exception as exc:
                    observation = {"error": str(exc), "capability": name}
                tool_calls_seen.append({
                    "name": name, "args": args,
                    "observation": observation,
                })
                working_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", ""),
                    "content": _json.dumps({"observation": observation}, default=str),
                })
        print(f"[model-router] {provider}:{model_id} reached tool-call limit")
    except Exception as exc:
        print(f"[model-router] {provider}:{model_id} exception: {exc}")
    return None

async def call_llm(client, messages, max_tokens=1000, requested_model=None,
                   allow_fallback=None):
    """Route inference; implicit callers may fall back, explicit comparisons can be strict."""
    selected = requested_model or DEFAULT_MODEL
    if allow_fallback is None:
        allow_fallback = requested_model is None
    result = await _call_selected_model(client, messages, selected, max_tokens)
    if result:
        result["fallback_used"] = False
        return result
    if not allow_fallback:
        return {
            "reply": "[selected model failed; fallback disabled]",
            "model": "none", "provider": "none",
            "requested_model": selected, "fallback_used": False,
        }

    configured = os.environ.get("DEX_FALLBACK_MODELS", "")
    fallbacks = [x.strip() for x in configured.split(",") if x.strip()]
    if not fallbacks:
        fallbacks = DEFAULT_FALLBACK_MODELS
    attempted = {selected}
    for fallback in fallbacks:
        if fallback in attempted:
            continue
        attempted.add(fallback)
        result = await _call_selected_model(client, messages, fallback, max_tokens)
        if result:
            result["requested_model"] = selected
            result["fallback_used"] = True
            return result
    return {
        "reply": "[all configured models failed]", "model": "none",
        "provider": "none", "requested_model": selected, "fallback_used": True,
    }
