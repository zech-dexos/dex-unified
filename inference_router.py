"""Central inference router for DexOS chat and model experiments.

Provider/model selection is explicit; identity and persisted state live elsewhere.
"""
import os
import time
import hashlib

OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("DEX_MODEL", "vertex:gemini-3.6-flash")
DEFAULT_AMBIENT_MODEL = os.environ.get("DEX_AMBIENT_MODEL", "local:default")
GROQ_MODEL = os.environ.get("DEX_GROQ_MODEL", "openai/gpt-oss-20b")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
RATE_LIMIT_COOLDOWN_SECONDS = max(1, int(os.environ.get("DEX_RATE_LIMIT_COOLDOWN_SECONDS", "120")))
QUOTA_COOLDOWN_SECONDS = max(1, int(os.environ.get("DEX_QUOTA_COOLDOWN_SECONDS", "43200")))
_MODEL_COOLDOWNS = {}
_SHARED_COOLDOWN_CACHE = {}
_SHARED_COOLDOWN_CACHE_SECONDS = 10.0


def _shared_cooldown_doc(db, key):
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return db.collection("dex_model_cooldowns").document(digest)


def _cooldown_remaining(key):
    now = time.monotonic()
    until = _MODEL_COOLDOWNS.get(key, 0.0)
    remaining = until - now
    if remaining > 0:
        return remaining
    _MODEL_COOLDOWNS.pop(key, None)

    cached = _SHARED_COOLDOWN_CACHE.get(key)
    if cached and now - cached[0] < _SHARED_COOLDOWN_CACHE_SECONDS:
        return max(0.0, cached[1] - (now - cached[0]))

    try:
        from dex_memory import _get_db
        db = _get_db()
        if db is None:
            _SHARED_COOLDOWN_CACHE[key] = (now, 0.0)
            return 0.0
        snapshot = _shared_cooldown_doc(db, key).get()
        data = snapshot.to_dict() or {}
        shared_until = float(data.get("cooldown_until_epoch", 0.0))
        remaining = max(0.0, shared_until - time.time())
        _SHARED_COOLDOWN_CACHE[key] = (now, remaining)
        if remaining > 0:
            _MODEL_COOLDOWNS[key] = now + remaining
        return remaining
    except Exception as exc:
        # Firestore is an optional shared guard; local backoff still works without it.
        print(f"[model-router] shared cooldown read unavailable: {exc}")
        _SHARED_COOLDOWN_CACHE[key] = (now, 0.0)
        return 0.0


def _persist_shared_cooldown(key, provider, model_id, duration, reason):
    try:
        from dex_memory import _get_db
        db = _get_db()
        if db is None:
            return
        _shared_cooldown_doc(db, key).set({
            "key": key,
            "provider": provider,
            "model": model_id,
            "cooldown_until_epoch": time.time() + duration,
            "duration_seconds": duration,
            "reason": str(reason)[:300],
            "updated_at_epoch": time.time(),
        }, merge=True)
        _SHARED_COOLDOWN_CACHE[key] = (time.monotonic(), duration)
    except Exception as exc:
        print(f"[model-router] shared cooldown write unavailable: {exc}")


def _record_provider_failure(provider, model_id, status_code, error_text, retry_after=None):
    text = str(error_text).lower()
    quota_failure = (
        status_code == 402
        or "quota" in text
        or "tokens per day" in text
        or "daily limit" in text
        or "tpd" in text
        or "resource_exhausted" in text
        or "resource exhausted" in text
    )
    if status_code != 429 and not quota_failure:
        return
    try:
        requested_wait = float(retry_after) if retry_after else 0.0
    except (TypeError, ValueError):
        requested_wait = 0.0
    duration = max(
        requested_wait,
        QUOTA_COOLDOWN_SECONDS if quota_failure else RATE_LIMIT_COOLDOWN_SECONDS,
    )
    key = f"provider:{provider}" if quota_failure else f"{provider}:{model_id}"
    _MODEL_COOLDOWNS[key] = time.monotonic() + duration
    _SHARED_COOLDOWN_CACHE[key] = (time.monotonic(), duration)
    _persist_shared_cooldown(key, provider, model_id, duration, text)
    print(f"[model-router] cooldown set for {key} ({int(duration)}s)")


def _model_is_cooling_down(provider, model_id):
    provider_wait = _cooldown_remaining(f"provider:{provider}")
    model_wait = _cooldown_remaining(f"{provider}:{model_id}")
    remaining = max(provider_wait, model_wait)
    if remaining > 0:
        print(f"[model-router] skipping {provider}:{model_id}; cooldown {int(remaining)}s remains")
        return True
    return False

# Identity, memory and governance remain independent of the replaceable spark.
# Explicit per-request model choices are strict for meaningful comparisons.
DEFAULT_FALLBACK_MODELS = [
    "openrouter:google/gemma-4-31b-it:free",
    "openrouter:google/gemma-4-26b-a4b-it:free",
    "openrouter:nvidia/nemotron-3-nano-30b-a3b:free",
    "openrouter:liquid/lfm-2.5-1.2b-instruct:free",
    "local:default",
]

def _parse_model_spec(spec):
    """Return provider/model for hosted, local, and OpenAI-compatible inference."""
    spec = (spec or DEFAULT_MODEL).strip()
    if ":" in spec:
        prefix, model_id = spec.split(":", 1)
        if prefix.lower() in ("vertex", "gemini", "groq", "openrouter", "ollama", "openai-compatible", "local"):
            provider = "vertex" if prefix.lower() == "gemini" else prefix.lower()
            if not model_id.strip():
                raise ValueError("Model ID cannot be empty")
            return provider, model_id.strip()
    if spec.startswith("gemini-"):
        return "vertex", spec
    # Existing clients passing bare IDs keep OpenRouter semantics.
    return "openrouter", spec

def _chat_completions_url(base_url):
    """Accept a server root, /v1 base, or full chat-completions URL."""
    base = (base_url or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def _completion_text(data):
    if not isinstance(data, dict) or data.get("error"):
        return ""
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return message.get("content") or message.get("reasoning") or ""

async def _call_selected_model(client, messages, model_spec, max_tokens, enable_tools=True):
    provider, model_id = _parse_model_spec(model_spec)
    if provider == "local":
        try:
            import asyncio
            from local_llm import local_slm_generate, MODEL_PATH
            prompt = "\n\n".join(
                f"{str(item.get('role', 'user')).upper()}: {item.get('content', '')}"
                for item in messages
            )
            text = await asyncio.get_running_loop().run_in_executor(
                None, local_slm_generate, prompt, max_tokens
            )
            if not text:
                return None
            return {
                "reply": text, "model": os.path.basename(MODEL_PATH),
                "provider": "local", "requested_model": model_spec, "tool_calls": [],
                "capability_execution_available": False,
            }
        except Exception as exc:
            print(f"[model-router] local inference failed: {exc}")
            return None
    if provider != "local" and _model_is_cooling_down(provider, model_id):
        return None
    if provider == "vertex":
        from gemini_client import call_gemini
        result = await call_gemini(
            client, messages, max_tokens, model_name=model_id, enable_tools=enable_tools
        )
        if result:
            result.update({
                "model": model_id, "provider": provider,
                "requested_model": model_spec,
                "capability_execution_available": bool(enable_tools),
            })
        return result

    if provider == "groq":
        key, url = os.environ.get("GROQ_KEY", ""), GROQ_URL
    elif provider == "openrouter":
        key, url = OPENROUTER_KEY, OPENROUTER_URL
    elif provider == "ollama":
        key = os.environ.get("DEX_OLLAMA_API_KEY", "")
        url = _chat_completions_url(os.environ.get("DEX_OLLAMA_BASE_URL", "http://localhost:11434/v1"))
    elif provider == "openai-compatible":
        base_url = os.environ.get("DEX_OPENAI_COMPATIBLE_BASE_URL", "").strip()
        if not base_url:
            print("[model-router] DEX_OPENAI_COMPATIBLE_BASE_URL is not configured")
            return None
        key = os.environ.get("DEX_OPENAI_COMPATIBLE_API_KEY", "")
        url = _chat_completions_url(base_url)
    else:
        raise ValueError(f"Unsupported inference provider: {provider}")
    if provider in ("groq", "openrouter") and not key:
        print(f"[model-router] {provider} selected but its API key is not configured")
        return None

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
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
                    **({"tools": tool_specs, "tool_choice": "auto"} if enable_tools else {}),
                },
            )
            try:
                data = response.json()
            except Exception:
                data = {}
            if not response.is_success or data.get("error"):
                error_text = str(data.get("error", data))[:400]
                print(f"[model-router] {provider}:{model_id} failed HTTP {response.status_code}: {error_text}")
                _record_provider_failure(
                    provider, model_id, response.status_code, error_text,
                    response.headers.get("Retry-After"),
                )
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
                    "capability_execution_available": bool(enable_tools),
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

async def _safe_call_selected_model(client, messages, model_spec, max_tokens, enable_tools):
    try:
        return await _call_selected_model(
            client, messages, model_spec, max_tokens, enable_tools=enable_tools
        )
    except Exception as exc:
        print(f"[model-router] invalid/unavailable model spec {model_spec!r}: {exc}")
        return None


async def call_llm(client, messages, max_tokens=1000, requested_model=None,
                   allow_fallback=None, enable_tools=True):
    """Route inference; implicit callers may fall back, explicit comparisons can be strict."""
    selected = requested_model or DEFAULT_MODEL
    if allow_fallback is None:
        allow_fallback = requested_model is None
    result = await _safe_call_selected_model(client, messages, selected, max_tokens, enable_tools)
    if result:
        result["fallback_used"] = False
        result["fallback_attempted"] = False
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
        result = await _safe_call_selected_model(client, messages, fallback, max_tokens, enable_tools)
        if result:
            result["requested_model"] = selected
            result["fallback_used"] = True
            result["fallback_attempted"] = True
            return result
    return {
        "reply": "[all configured models failed]", "model": "none",
        "provider": "none", "requested_model": selected,
        "fallback_used": False, "fallback_attempted": True,
    }
