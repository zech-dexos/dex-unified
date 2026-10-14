"""
local_llm.py — CPU-only tiny local model for cheap/frequent calls (ambient
pulse ticks) that don't warrant a paid API call. Loaded once per container,
kept resident in memory for the life of the instance.
"""
import os

_llm = None
MODEL_PATH = os.environ.get(
    "LOCAL_SLM_PATH",
    "/app/models/qwen2.5-0.5b-instruct-q4_k_m.gguf",
)


def _get_llm():
    global _llm
    if _llm is None:
        from llama_cpp import Llama
        _llm = Llama(
            model_path=MODEL_PATH,
            n_ctx=2048,
            n_threads=os.cpu_count() or 2,
            verbose=False,
        )
    return _llm


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
    message list exceeds the model's context window.
    """
    llm = _get_llm()
    context_size = 2048
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
                "\\n".join(item["role"] + ": " + item["content"] for item in items).encode("utf-8")
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
