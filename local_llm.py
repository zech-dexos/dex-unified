"""
local_llm.py — local GGUF inference for ambient and interactive chat.
Models are loaded lazily and kept resident for the life of the container.
"""
import os

_llm = None
_chat_llm = None
MODEL_PATH = os.environ.get(
    "LOCAL_SLM_PATH",
    "/app/models/qwen2.5-0.5b-instruct-q4_k_m.gguf",
)
# Honor the Cloud Run configuration first; retain the older variable as a
# compatibility fallback for deployments that still use it.
CHAT_MODEL_PATH = os.environ.get(
    "LOCAL_CHAT_MODEL_PATH",
    os.environ.get(
        "DEX_CHAT_MODEL_PATH",
        "/app/models/heretic/model_q4_k_m.gguf",
    ),
)
CHAT_CONTEXT_SIZE = max(512, int(os.environ.get("LOCAL_CHAT_N_CTX", "4096")))
CHAT_THREADS = max(1, int(os.environ.get("LOCAL_CHAT_THREADS", "2")))
AMBIENT_THREADS = max(1, int(os.environ.get("LOCAL_AMBIENT_THREADS", "1")))


def _load_model(path: str, context_size: int, threads: int | None = None):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"GGUF model file does not exist: {path}")
    from llama_cpp import Llama
    thread_count = threads if threads is not None else (os.cpu_count() or 2)
    print(
        f"[llama.cpp] loading model={path} context={context_size} "
        f"threads={thread_count}",
        flush=True,
    )
    return Llama(
        model_path=path,
        n_ctx=context_size,
        n_threads=thread_count,
        verbose=False,
    )


def _get_llm():
    global _llm
    if _llm is None:
        # Bound background inference so it cannot consume every CPU thread.
        _llm = _load_model(MODEL_PATH, 2048, AMBIENT_THREADS)
    return _llm


def _get_chat_llm():
    global _chat_llm
    if _chat_llm is None:
        _chat_llm = _load_model(CHAT_MODEL_PATH, CHAT_CONTEXT_SIZE, CHAT_THREADS)
    return _chat_llm


def local_slm_generate(prompt: str, max_tokens: int = 200, json_schema=None) -> str:
    llm = _get_llm()

    # Reserve room for generated output and chat-template overhead.
    context_size = int(llm.n_ctx())
    output_tokens = min(max(32, int(max_tokens)), context_size // 3)
    prompt_budget = max(256, context_size - output_tokens - 96)

    prompt_tokens = llm.tokenize(prompt.encode("utf-8"), add_bos=False)

    if len(prompt_tokens) > prompt_budget:
        marker = (
            "\n[Middle of ambient context omitted to fit the model window. "
            "Preserve the instructions and use the available recent context.]\n"
        )
        marker_tokens = llm.tokenize(marker.encode("utf-8"), add_bos=False)
        remaining = max(128, prompt_budget - len(marker_tokens))
        head_count = min(384, remaining // 3)
        tail_count = max(1, remaining - head_count)

        head = llm.detokenize(prompt_tokens[:head_count]).decode(
            "utf-8", errors="replace"
        )
        tail = llm.detokenize(prompt_tokens[-tail_count:]).decode(
            "utf-8", errors="replace"
        )
        prompt = head + marker + tail

        # Verify the final text still fits after re-tokenization.
        fitted = llm.tokenize(prompt.encode("utf-8"), add_bos=False)
        if len(fitted) > prompt_budget:
            fitted = fitted[-prompt_budget:]
            prompt = llm.detokenize(fitted).decode("utf-8", errors="replace")

        print(
            f"[Ambient Runtime] Prompt trimmed to fit: "
            f"{len(prompt_tokens)} -> "
            f"{len(llm.tokenize(prompt.encode('utf-8'), add_bos=False))} tokens "
            f"(context={context_size})",
            flush=True,
        )

    request = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": output_tokens,
        "temperature": 0.8,
    }
    if json_schema:
        try:
            out = llm.create_chat_completion(
                response_format={"type": "json_object", "schema": json_schema},
                **request,
            )
        except Exception as e:
            print(
                f"[Ambient Runtime] JSON-constrained decoding failed ({e}); retrying unconstrained",
                flush=True,
            )
            out = llm.create_chat_completion(**request)
    else:
        out = llm.create_chat_completion(**request)
    return out["choices"][0]["message"]["content"].strip()


def local_chat_generate(messages, max_tokens: int = 200) -> str:
    """Generate from native chat messages through the resident local GGUF.

    This preserves system/user/assistant roles instead of flattening the whole
    conversation into one user prompt. Older context is trimmed only when the
    message list exceeds the model's configured context window.
    """
    endpoint = os.environ.get("LOCAL_CHAT_BASE_URL", "").rstrip("/")
    llm = None if endpoint else _get_chat_llm()
    context_size = CHAT_CONTEXT_SIZE
    try:
        context_size = int(llm.n_ctx())
    except Exception:
        pass

    normalized = []
    for item in messages or []:
        role = str(item.get("role", "user")).lower()
        if role not in ("system", "user", "assistant"):
            continue
        content = item.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        if content.strip():
            normalized.append({"role": role, "content": content})
    if not normalized:
        raise ValueError("No usable chat messages supplied to local inference")

    output_tokens = min(max(32, int(max_tokens)), max(64, min(512, context_size // 4)))

    def token_count(items):
        try:
            return len(llm.tokenize(
                "\n".join(item["role"] + ": " + item["content"] for item in items).encode("utf-8")
            ))
        except Exception:
            return sum(len(item["content"]) // 3 + 4 for item in items)

    while len(normalized) > 2 and token_count(normalized) > context_size - output_tokens - 16:
        # Keep the first system instruction and the newest conversational turns.
        if normalized[0]["role"] == "system":
            normalized.pop(1)
        else:
            normalized.pop(0)

    # Leave room for the model's chat-template tokens as well as the
    # completion. Raw message token counts alone do not include that overhead.
    prompt_budget = max(128, context_size - output_tokens - 256)
    if token_count(normalized) > prompt_budget:
        system = dict(normalized[0]) if normalized[0]["role"] == "system" else None
        last = dict(normalized[-1])
        normalized = ([system] if system else []) + [last]

        # The old code shortened only the final message, leaving an oversized
        # system prompt intact. That could still produce a 3k+ token prompt
        # against the configured 2k context. Shrink the system prompt's tail
        # first, preserving its opening instructions, then shorten the input.
        while token_count(normalized) > prompt_budget:
            if system and len(system["content"]) > 256:
                system["content"] = system["content"][:max(256, int(len(system["content"]) * 0.8))]
            elif len(last["content"]) > 256:
                last["content"] = last["content"][-max(256, int(len(last["content"]) * 0.8)):]
            else:
                raise ValueError(
                    f"Unable to fit chat messages into context window: "
                    f"{token_count(normalized)} tokens, budget {prompt_budget}"
                )

    request = {
        "messages": normalized,
        "max_tokens": output_tokens,
        "temperature": 0.7,
    }
    if endpoint:
        import httpx

        response = httpx.post(
            endpoint + "/v1/chat/completions",
            json={"model": "heretic-local", **request},
            timeout=httpx.Timeout(300.0, connect=5.0),
        )
        response.raise_for_status()
        result = response.json()
    else:
        result = llm.create_chat_completion(**request)
    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError("llama.cpp returned no completion choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("llama.cpp returned empty completion content")
    return content.strip()



def preload_chat_model() -> dict:
    """Load the interactive Heretic GGUF now, so startup fails visibly if it cannot load."""
    _get_chat_llm()
    return {"loaded": _chat_llm is not None, "path": CHAT_MODEL_PATH}


def preload_ambient_model() -> dict:
    """Load the ambient cognition GGUF now, before the pulse loop starts."""
    _get_llm()
    return {"loaded": _llm is not None, "path": MODEL_PATH}


def model_status() -> dict:
    """Report actual in-process model load state, not just file existence."""
    return {
        "chat": {
            "path": CHAT_MODEL_PATH,
            "file_present": os.path.isfile(CHAT_MODEL_PATH),
            "loaded": _chat_llm is not None,
        },
        "ambient": {
            "path": MODEL_PATH,
            "file_present": os.path.isfile(MODEL_PATH),
            "loaded": _llm is not None,
        },
    }


AMBIENT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string", "maxLength": 400},
        "salience": {"type": "number"},
    },
    "required": ["thought", "salience"],
}


def local_ambient_generate(prompt: str, max_tokens: int = 200) -> str:
    """Ambient pulse generation constrained to the {thought, salience} JSON shape."""
    return local_slm_generate(prompt, max_tokens, json_schema=AMBIENT_JSON_SCHEMA)
