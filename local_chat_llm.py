"""
local_chat_llm.py — separate local conversational spark for Dex.

This model is intentionally separate from local_llm.py, which remains the
small, bundled model used by ambient cognition. Runtime capabilities remain
implemented by dex_capabilities.py and are invoked only through this bridge.
"""
import json
import os
import threading
from pathlib import Path

_llm = None
_model_init_lock = threading.Lock()
_inference_lock = threading.Lock()
MODEL_PATH = os.path.expanduser(os.environ.get(
    "LOCAL_CHAT_MODEL_PATH",
    "~/dev/llm/models/llama-3.2-3b-heretic/model_q4_k_m.gguf",
))


def _get_llm():
    global _llm
    if _llm is None:
        with _model_init_lock:
            if _llm is None:
                if not Path(MODEL_PATH).is_file():
                    raise FileNotFoundError(
                        f"Local chat model not found at {MODEL_PATH}. "
                        "Set LOCAL_CHAT_MODEL_PATH to the Heretic GGUF path."
                    )
                from llama_cpp import Llama
                _llm = Llama(
                    model_path=MODEL_PATH,
                    n_ctx=int(os.environ.get("LOCAL_CHAT_N_CTX", "4096")),
                    n_threads=int(os.environ.get(
                        "LOCAL_CHAT_THREADS", str(min(8, os.cpu_count() or 2))
                    )),
                    verbose=False,
                )
    return _llm


_CAPABILITY_INSTRUCTIONS = """
You are the conversational spark inside DexOS. DexOS runtime capabilities
are real functions; do not claim to have used them unless a tool call was
executed and its result was returned.

When a runtime capability is needed, output ONLY a JSON object:
{"tool_calls":[{"name":"CAPABILITY_NAME","arguments":{}}]}
You may request multiple calls. Available capabilities and arguments:
- inspect_state: {}
- inspect_workspace: {}
- inspect_goals: {}
- inspect_open_loops: {}
- inspect_thoughts: {}
- inspect_experiences: {"limit": integer}
- inspect_participant: {}
- inspect_conversation: {"user_id": string}
- recall_experience: {"query": string, "limit": integer}
- listen: {}
- evoke: {"resource": string}
- search_architecture: {"query": string}

After the runtime returns observations, use them to answer naturally.
If no capability is needed, answer normally in plain text, not JSON.
Never invent tool results. Capability calls are read-only except recall_experience
and evoke, which may update the active workspace through their runtime contract.
"""


def _parse_tool_request(text):
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1]
        if candidate.endswith("```"):
            candidate = candidate[:-3].strip()
        if candidate.lower().startswith("json"):
            candidate = candidate[4:].strip()
    try:
        value = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    calls = value.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        return None
    valid = []
    allowed = {
        "inspect_state", "inspect_workspace", "inspect_goals",
        "inspect_open_loops", "inspect_thoughts", "inspect_experiences",
        "inspect_participant", "inspect_conversation", "recall_experience",
        "listen", "evoke", "search_architecture",
    }
    for call in calls:
        if not isinstance(call, dict):
            continue
        name = call.get("name")
        args = call.get("arguments", {})
        if name in allowed and isinstance(args, dict):
            valid.append({"name": name, "arguments": args})
    return valid or None


def local_chat_generate(messages, max_tokens=1200, max_tool_rounds=5):
    """Serialize access to the resident model; llama.cpp inference is not concurrent-safe."""
    with _inference_lock:
        return _local_chat_generate_locked(messages, max_tokens, max_tool_rounds)


def _local_chat_generate_locked(messages, max_tokens=1200, max_tool_rounds=5):
    """Generate a chat reply and, when requested, run DexOS runtime capabilities."""
    llm = _get_llm()
    conversation = [dict(m) for m in messages]
    # Add tool protocol to the existing constitutional system message, preserving it.
    system_index = next(
        (i for i, m in enumerate(conversation) if m.get("role") == "system"),
        None,
    )
    if system_index is None:
        conversation.insert(0, {"role": "system", "content": _CAPABILITY_INSTRUCTIONS})
    else:
        conversation[system_index]["content"] = (
            str(conversation[system_index].get("content", ""))
            + "\n\nRUNTIME CAPABILITY PROTOCOL:\n"
            + _CAPABILITY_INSTRUCTIONS
        )

    executed = []
    for _ in range(max_tool_rounds + 1):
        response = llm.create_chat_completion(
            messages=conversation,
            max_tokens=max_tokens,
            temperature=float(os.environ.get("LOCAL_CHAT_TEMPERATURE", "0.7")),
        )
        choice = response.get("choices", [{}])[0]
        answer = str((choice.get("message") or {}).get("content") or "").strip()
        if not answer:
            raise RuntimeError("Heretic local chat model returned empty text")

        requests = _parse_tool_request(answer)
        if not requests:
            return {
                "reply": answer,
                "model": "local:llama-3.2-3b-heretic",
                "tool_calls": executed,
                "capability_execution_available": True,
            }
        if len(executed) >= max_tool_rounds:
            return {
                "reply": "[capability loop limit reached]",
                "model": "local:llama-3.2-3b-heretic",
                "tool_calls": executed,
                "capability_execution_available": True,
            }

        from dex_capabilities import execute_capability
        observations = []
        for request in requests:
            observation = execute_capability(request["name"], request["arguments"])
            executed.append({
                "name": request["name"],
                "args": request["arguments"],
                "observation": observation,
            })
            observations.append({
                "name": request["name"],
                "arguments": request["arguments"],
                "observation": observation,
            })
        conversation.append({"role": "assistant", "content": answer})
        conversation.append({
            "role": "user",
            "content": "[DEXOS RUNTIME CAPABILITY OBSERVATIONS]\n"
                       + json.dumps(observations, ensure_ascii=False, default=str)
                       + "\nUse these actual results; continue with another tool request "
                         "only if necessary, otherwise answer the participant naturally.",
        })

    return {
        "reply": "[capability loop limit reached]",
        "model": "local:llama-3.2-3b-heretic",
        "tool_calls": executed,
        "capability_execution_available": True,
    }
