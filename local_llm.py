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


def _fit_local_prompt(llm, prompt: str, max_tokens: int):
    """Fit local fallback requests inside the model context window."""
    try:
        context_size = int(llm.n_ctx())
    except Exception:
        context_size = 2048

    output_tokens = min(max(1, int(max_tokens)), max(64, min(512, context_size // 4)))
    prompt_limit = max(128, context_size - output_tokens - 16)

    def token_count(value):
        try:
            return len(llm.tokenize(value.encode("utf-8")))
        except Exception:
            return max(1, len(value) // 3)

    while token_count(prompt) > prompt_limit and len(prompt) > 400:
        keep_chars = max(256, int(len(prompt) * 0.75))
        head_chars = keep_chars // 2
        tail_chars = keep_chars - head_chars
        prompt = prompt[:head_chars] + "\n[older context truncated]\n" + prompt[-tail_chars:]

    while token_count(prompt) > prompt_limit and len(prompt) > 100:
        prompt = prompt[int(len(prompt) * 0.15):]

    if token_count(prompt) > prompt_limit:
        prompt = prompt[-max(100, prompt_limit * 3):]

    return prompt, output_tokens


def local_slm_generate(prompt: str, max_tokens: int = 200) -> str:
    """Blocking call -- run this in an executor from async code."""
    llm = _get_llm()
    prompt, safe_max_tokens = _fit_local_prompt(llm, prompt, max_tokens)
    out = llm.create_chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=safe_max_tokens,
        temperature=0.8,
    )
    return out["choices"][0]["message"]["content"].strip()
