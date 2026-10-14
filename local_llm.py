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
CHAT_CONTEXT_SIZE = max(512, int(os.environ.get("LOCAL_CHAT_N_CTX", "2048")))
CHAT_THREADS = max(1, int(os.environ.get("LOCAL_CHAT_THREADS", "2")))


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
        _llm = _load_model(MODEL_PATH, 2048)
    return _llm


def _get_chat_llm():
    global _chat_llm
    if _chat_llm is None:
        _chat_llm = _load_model(CHAT_MODEL_PATH, CHAT_CONTEXT_SIZE, CHAT_THREADS)
    return _chat_llm


def local_slm_generate(prompt: str, max_tokens: int = 200) -> str:
    """Blocking call -- run this in an executor from async code."""
    llm = _get_llm()
    out = llm.create_chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.8,
    )
    return out["choices"][0]["message"]["content"].strip()


def local_chat_generate(messages, max_tokens: int = 200) -> str:
    """Generate from native chat messages through the resident local GGUF.

    This preserves system/user/assistant roles instead of flattening the whole
    conversation into one user prompt. Older context is trimmed only when the
    message list exceeds the model's configured context window.
    """
    llm = _get_chat_llm()
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

    if token_count(normalized) > context_size - output_tokens - 16:
        system = normalized[0] if normalized[0]["role"] == "system" else None
        last = normalized[-1]
        budget = max(128, context_size * 3)
        last = {"role": last["role"], "content": last["content"][-budget:]}
        normalized = ([system] if system else []) + [last]

    result = llm.create_chat_completion(
        messages=normalized,
        max_tokens=output_tokens,
        temperature=0.7,
    )
    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError("llama.cpp returned no completion choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("llama.cpp returned empty completion content")
    return content.strip()
