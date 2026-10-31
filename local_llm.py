"""
local_llm.py — local GGUF inference for ambient and interactive chat.
Models are loaded lazily and kept resident for the life of the container.
"""
import os
import json
import fcntl
import hashlib
import tempfile
import time
from contextlib import contextmanager

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


@contextmanager
def _shared_inference_slot(kind: str):
    """Serialize GGUF generation across the independent chat and ambient processes."""
    state_root = os.path.realpath(
        os.environ.get("DEXOS_STATE_DIR") or os.path.dirname(__file__)
    )
    identity = hashlib.sha256(state_root.encode("utf-8")).hexdigest()[:16]
    lock_path = os.path.join(
        tempfile.gettempdir(),
        f"dexos-inference-{getattr(os, 'getuid', lambda: 0)()}-{identity}.lock",
    )
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    wait_started = time.monotonic()
    acquired_at = None
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        acquired_at = time.monotonic()
        waited = acquired_at - wait_started
        print(
            f"[Inference Coordinator] {kind} slot acquired after {waited:.2f}s",
            flush=True,
        )
        yield
    finally:
        held = time.monotonic() - acquired_at if acquired_at is not None else 0.0
        try:
            if acquired_at is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
        if acquired_at is not None:
            print(
                f"[Inference Coordinator] {kind} slot released after {held:.2f}s",
                flush=True,
            )


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
    with _shared_inference_slot("ambient"):
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


def local_chat_generate(messages, max_tokens: int = 200, on_token=None) -> str:
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

    # Preserve the live conversation before trimming historical context.
    # The previous implementation repeatedly removed index 1 whenever the
    # system prompt was first, silently deleting every prior user correction.
    prompt_budget = max(256, context_size - output_tokens - 256)
    system = dict(normalized[0]) if normalized[0]["role"] == "system" else None
    turns = normalized[1:] if system else list(normalized)

    # Keep the newest three exchanges (up to six messages), including the
    # current user turn. Older transcript entries are the first material cut.
    while len(turns) > 6 and token_count(([system] if system else []) + turns) > prompt_budget:
        turns.pop(0)
    while len(turns) > 2 and token_count(([system] if system else []) + turns) > prompt_budget:
        turns.pop(0)

    def trim_system_content(content, target_tokens):
        if not content:
            return content
        if llm is not None:
            encoded = llm.tokenize(content.encode("utf-8"), add_bos=False)
            if len(encoded) <= target_tokens:
                return content
            # Retain the opening identity/constitution and the closing live
            # conversation rules instead of keeping only a stale prompt prefix.
            head_n = max(128, int(target_tokens * 0.68))
            tail_n = max(64, target_tokens - head_n)
            head = llm.detokenize(encoded[:head_n]).decode("utf-8", errors="replace")
            tail = llm.detokenize(encoded[-tail_n:]).decode("utf-8", errors="replace")
            return head + "\n\n[DexOS context compacted; live conversation retained]\n\n" + tail
        max_chars = max(1024, target_tokens * 3)
        if len(content) <= max_chars:
            return content
        head_n = int(max_chars * 0.68)
        tail_n = max_chars - head_n
        return content[:head_n] + "\n\n[DexOS context compacted; live conversation retained]\n\n" + content[-tail_n:]

    messages_for_budget = ([system] if system else []) + turns
    if token_count(messages_for_budget) > prompt_budget and system:
        conversation_tokens = sum(token_count([turn]) for turn in turns)
        system_budget = max(384, prompt_budget - conversation_tokens)
        system["content"] = trim_system_content(system["content"], system_budget)
        messages_for_budget = [system] + turns

    # If the model's template overhead still makes the context too large,
    # remove only the oldest remaining transcript messages. Never discard
    # the current participant contribution.
    while len(turns) > 1 and token_count(([system] if system else []) + turns) > prompt_budget:
        turns.pop(0)
    normalized = ([system] if system else []) + turns
    if token_count(normalized) > prompt_budget:
        raise ValueError(
            f"Current turn and compacted identity exceed context window: "
            f"{token_count(normalized)} tokens, budget {prompt_budget}"
        )

    request = {
        "messages": normalized,
        "max_tokens": output_tokens,
        "temperature": 0.7,
    }
    # Consume the model's actual generation stream. The callback receives
    # only newly generated text; callers decide how to observe or display it.
    fragments = []
    with _shared_inference_slot("interactive"):
        if endpoint:
            import httpx

            with httpx.stream(
                "POST",
                endpoint + "/v1/chat/completions",
                json={"model": "heretic-local", **request, "stream": True},
                timeout=httpx.Timeout(300.0, connect=5.0),
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except (TypeError, ValueError):
                        continue
                    choices = chunk.get("choices") or []
                    delta = (choices[0].get("delta") or {}).get("content") if choices else None
                    if isinstance(delta, str) and delta:
                        fragments.append(delta)
                        if callable(on_token):
                            on_token(delta)
        else:
            stream = llm.create_chat_completion(**request, stream=True)
            for chunk in stream:
                choices = chunk.get("choices") or []
                delta = (choices[0].get("delta") or {}).get("content") if choices else None
                if isinstance(delta, str) and delta:
                    fragments.append(delta)
                    if callable(on_token):
                        on_token(delta)

    content = "".join(fragments)
    if not content.strip():
        raise RuntimeError("local GGUF returned empty completion content")
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
