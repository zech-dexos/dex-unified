"""
local_spark.py — local inference bridge between the Heretic spark and DexOS.

The model generates cognition; this bridge gives it a narrow, explicit
capability protocol. Identity, governance, memory, and capability behavior
remain in DexOS, not in the GGUF.
"""
import json
import threading

_inference_lock = threading.Lock()
MAX_TOOL_ROUNDS = 4
MAX_CALLS_PER_ROUND = 3

_CAPABILITY_PROTOCOL = r"""
DEXOS RUNTIME CAPABILITY PROTOCOL

You are the local inference spark operating inside DexOS. Use the existing
DexOS architecture and state; never claim to have inspected anything unless
a capability actually ran and its observation was returned.

If you need a runtime capability, return ONLY one JSON object in this form:
{"tool_calls":[{"name":"inspect_state","arguments":{}}]}

Allowed capabilities and argument shapes:
- inspect_state: {}
- inspect_tools: {}
- inspect_observations: {}
- inspect_architecture: {"query": optional string}
- reason_with_talnir: {"prompt": string, max 2000}
- request_reflection: {"focus": string, max 500, "reason": optional string, max 500}; queue a future ambient architecture pass
- inspect_identity: {}
- inspect_lineage: {"limit": integer 1..20}
- inspect_workspace: {}
- inspect_goals: {}
- inspect_open_loops: {}
- inspect_thoughts: {}
- inspect_experiences: {"limit": integer 1..20}
- inspect_participant: {}
- inspect_conversation: {"user_id": string}
- recall_experience: {"query": string, "limit": integer 1..10}
- listen: {}
- evoke: {"resource": "state|workspace|goals|open_loops|thoughts|experiences|participant|conversation|signals|tools|observations|architecture"}
- search_architecture: {"query": string}

Do not request shell execution, network calls, or arbitrary code. Do not invent capability results. After observations are
returned, answer naturally or request another allowed capability if needed.
If no capability is needed, answer normally in plain text.
"""


_NO_ARGS = {
    "inspect_state", "inspect_identity", "inspect_tools", "inspect_observations", "inspect_workspace", "inspect_goals", "inspect_open_loops",
    "inspect_thoughts", "inspect_participant", "listen",
}
_ALLOWED = _NO_ARGS | {
    "inspect_experiences", "inspect_lineage", "inspect_conversation", "recall_experience",
    "evoke", "search_architecture", "inspect_architecture", "reason_with_talnir", "request_reflection",
}
_EVOCABLE = {
    "state", "workspace", "goals", "open_loops", "thoughts", "experiences",
    "participant", "conversation", "signals", "tools", "observations", "architecture",
}


def _parse_tool_request(text):
    candidate = str(text or "").strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].strip().lower() in ("```json", "```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        value = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("tool_calls"), list):
        return None

    valid = []
    for call in value["tool_calls"][:MAX_CALLS_PER_ROUND]:
        if not isinstance(call, dict):
            continue
        name = call.get("name")
        args = call.get("arguments", {})
        if name not in _ALLOWED or not isinstance(args, dict):
            continue
        if name in _NO_ARGS:
            args = {}
        elif name == "inspect_experiences":
            limit = args.get("limit", 10)
            if not isinstance(limit, int) or isinstance(limit, bool):
                continue
            args = {"limit": max(1, min(20, limit))}
        elif name == "inspect_lineage":
            limit = args.get("limit", 10)
            if not isinstance(limit, int) or isinstance(limit, bool):
                continue
            args = {"limit": max(1, min(20, limit))}
        elif name == "inspect_conversation":
            user_id = args.get("user_id", "default")
            if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 128:
                continue
            args = {"user_id": user_id.strip()}
        elif name == "recall_experience":
            query, limit = args.get("query"), args.get("limit", 5)
            if not isinstance(query, str) or not query.strip() or len(query) > 500:
                continue
            if not isinstance(limit, int) or isinstance(limit, bool):
                continue
            args = {"query": query.strip(), "limit": max(1, min(10, limit))}
        elif name == "evoke":
            resource = args.get("resource")
            if resource not in _EVOCABLE:
                continue
            args = {"resource": resource}
        elif name == "inspect_architecture":
            query = args.get("query", "")
            if not isinstance(query, str) or len(query) > 200:
                continue
            args = {"query": query.strip()}
        elif name == "reason_with_talnir":
            prompt = args.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
                continue
            args = {"prompt": prompt.strip()}
        elif name == "request_reflection":
            focus, reason = args.get("focus"), args.get("reason", "")
            if not isinstance(focus, str) or not focus.strip() or len(focus) > 500:
                continue
            if not isinstance(reason, str) or len(reason) > 500:
                continue
            args = {"focus": focus.strip(), "reason": reason.strip()}
        elif name == "search_architecture":
            query = args.get("query")
            if not isinstance(query, str) or not query.strip() or len(query) > 200:
                continue
            args = {"query": query.strip()}
        valid.append({"name": name, "arguments": args})
    return valid or None


def local_spark_generate(messages, max_tokens=256, max_tool_rounds=MAX_TOOL_ROUNDS, on_token=None, on_event=None):
    """Generate a reply and execute only explicitly allowlisted DexOS capabilities."""
    with _inference_lock:
        from local_llm import local_chat_generate, CHAT_MODEL_PATH
        from dex_capabilities import execute_capability

        conversation = [dict(message) for message in (messages or [])]
        if not conversation:
            raise ValueError("No chat messages supplied to local spark")
        system_index = next(
            (i for i, message in enumerate(conversation) if message.get("role") == "system"),
            None,
        )
        if system_index is None:
            conversation.insert(0, {"role": "system", "content": _CAPABILITY_PROTOCOL})
        else:
            original = str(conversation[system_index].get("content", ""))
            # Prefix protocol so the existing local_llm context trimmer preserves
            # the capability contract and the opening of Dex's constitutional prompt.
            conversation[system_index]["content"] = (
                _CAPABILITY_PROTOCOL + "\n\nDEXOS CONSTITUTIONAL CONTEXT:\n" + original
            )

        executed = []
        effective_tool_rounds = max(
            0, min(int(max_tool_rounds), MAX_TOOL_ROUNDS)
        )
        for round_index in range(effective_tool_rounds + 1):
            if callable(on_event):
                on_event("MODEL_PASS_STARTED", {"generation_round": round_index})
            token_buffer = []

            def observe_token(delta):
                if not isinstance(delta, str) or not delta:
                    return
                token_buffer.append(delta)
                if sum(len(part) for part in token_buffer) >= 128:
                    chunk = "".join(token_buffer)
                    token_buffer.clear()
                    if callable(on_token):
                        on_token(chunk, {
                            "generation_round": round_index,
                            "generation_stage": "model_generation",
                        })

            answer = local_chat_generate(
                conversation, max_tokens=max_tokens, on_token=observe_token
            )
            if token_buffer and callable(on_token):
                on_token("".join(token_buffer), {
                    "generation_round": round_index,
                    "generation_stage": "model_generation",
                })
            if not isinstance(answer, str) or not answer.strip():
                raise RuntimeError("local GGUF returned empty text")
            requests = _parse_tool_request(answer)
            if not requests:
                return {
                    "reply": answer.strip(),
                    "model": "local:" + CHAT_MODEL_PATH.rsplit("/", 1)[-1],
                    "tool_calls": executed,
                    "capability_execution_available": True,
                }
            if round_index >= effective_tool_rounds:
                return {
                    "reply": "[DexOS capability round limit reached]",
                    "model": "local:" + CHAT_MODEL_PATH.rsplit("/", 1)[-1],
                    "tool_calls": executed,
                    "capability_execution_available": True,
                }

            observations = []
            for request in requests:
                observation = execute_capability(request["name"], request["arguments"])
                if callable(on_event):
                    on_event("CAPABILITY_EXECUTED", {
                        "generation_round": round_index,
                        "capability": request["name"],
                        "arguments": request["arguments"],
                        "success": not (isinstance(observation, dict) and "error" in observation),
                        "observation": observation,
                    })
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
            conversation.append({"role": "assistant", "content": answer.strip()})
            conversation.append({
                "role": "user",
                "content": "[ACTUAL DEXOS CAPABILITY OBSERVATIONS]\n"
                           + json.dumps(observations, ensure_ascii=False, default=str)
                           + "\nUse these actual observations to answer naturally. "
                             "Never claim observations that are not present here.",
            })

        return {
            "reply": "[DexOS capability round limit reached]",
            "model": "local:" + CHAT_MODEL_PATH.rsplit("/", 1)[-1],
            "tool_calls": executed,
            "capability_execution_available": True,
        }
