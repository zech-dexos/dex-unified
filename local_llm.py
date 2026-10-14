"""
local_llm.py — local GGUF inference for DexOS.

Prefer Root's locally installed Heretic GGUF when present. Cloud/container
deployments retain the bundled tiny-model fallback unless LOCAL_SLM_PATH is
explicitly configured. No hosted inference is performed by this module.
"""
import os

_llm = None

LOCAL_HERETIC_PATH = os.path.expanduser(
    "~/dev/llm/models/llama-3.2-3b-heretic/model_q4_k_m.gguf"
)
BUNDLED_MODEL_PATH = "/app/models/qwen2.5-0.5b-instruct-q4_k_m.gguf"

# Explicit configuration wins; otherwise select the local Heretic model when
# it exists, preserving the existing container fallback on machines without it.
MODEL_PATH = os.path.expanduser(
    os.environ.get("LOCAL_SLM_PATH", "").strip()
) if os.environ.get("LOCAL_SLM_PATH", "").strip() else (
    LOCAL_HERETIC_PATH if os.path.isfile(LOCAL_HERETIC_PATH) else BUNDLED_MODEL_PATH
)


def _get_llm():
    global _llm
    if _llm is None:
        if not os.path.isfile(MODEL_PATH):
            raise FileNotFoundError(
                f"Local GGUF model not found: {MODEL_PATH}. "
                "Set LOCAL_SLM_PATH to the model file."
            )
        from llama_cpp import Llama
        _llm = Llama(
            model_path=MODEL_PATH,
            n_ctx=int(os.environ.get("LOCAL_LLM_CONTEXT", "2048")),
            n_threads=int(os.environ.get("LOCAL_LLM_THREADS", "2")),
            verbose=False,
        )
        print(f"[local_llm] loaded model: {MODEL_PATH}")
    return _llm


def local_slm_generate(prompt: str, max_tokens: int = 200) -> str:
    """Blocking call; run this in an executor from async code."""
    llm = _get_llm()
    out = llm.create_chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.6,
    )
    return (out["choices"][0]["message"].get("content") or "").strip()
