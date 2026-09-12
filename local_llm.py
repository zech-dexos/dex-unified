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
