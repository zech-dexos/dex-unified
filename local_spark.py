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


def _bounded_observation(value, max_chars: int = 1800):
    """Keep capability feedback bounded without emitting malformed JSON."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        encoded = str(value)
    if len(encoded) <= max_chars:
        return value
    return {
        "truncated": True,
        "preview": encoded[:max_chars - 100],
        "original_character_count": len(encoded),
    }


def _parse_tool_request_result(text):
    """Distinguish ordinary prose, valid tool requests, and rejected tool requests."""
    candidate = str(text or "").strip()
    if candidate.startswith("[TOOL CALLS]"):
        candidate = candidate[len("[TOOL CALLS]"):].strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].strip().lower() in ("```json", "```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    looks_like_tool_request = (
        '"tool_calls"' in candidate
        or candidate.startswith("{") and '"tool_calls"' in candidate
    )
    try:
        value = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return {"status": "rejected", "reason": "Tool request was not valid JSON."} if looks_like_tool_request else {"status": "plain"}
    if not isinstance(value, dict) or "tool_calls" not in value:
        return {"status": "plain"}
    calls = value.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        return {"status": "rejected", "reason": "tool_calls must be a non-empty array."}

    valid = []
    errors = []
    for index, call in enumerate(calls[:MAX_CALLS_PER_ROUND]):
        if not isinstance(call, dict):
            errors.append(f"tool call {index + 1} must be an object")
            continue
        name = call.get("name")
        args = call.get("arguments", {})
        if name not in _ALLOWED or not isinstance(args, dict):
            errors.append(f"tool call {index + 1} has an unknown capability or invalid arguments")
            continue
        if name in _NO_ARGS:
            args = {}
        elif name == "inspect_experiences":
            limit = args.get("limit", 10)
            if not isinstance(limit, int) or isinstance(limit, bool):
                errors.append("inspect_experiences.limit must be an integer")
                continue
            args = {"limit": max(1, min(20, limit))}
        elif name == "inspect_lineage":
            limit = args.get("limit", 10)
            if not isinstance(limit, int) or isinstance(limit, bool):
                errors.append("inspect_lineage.limit must be an integer")
                continue
            args = {"limit": max(1, min(20, limit))}
        elif name == "inspect_conversation":
            user_id = args.get("user_id", "default")
            if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 128:
                errors.append("inspect_conversation.user_id is invalid")
                continue
            args = {"user_id": user_id.strip()}
        elif name == "recall_experience":
            query, limit = args.get("query"), args.get("limit", 5)
            if not isinstance(query, str) or not query.strip() or len(query) > 500:
                errors.append("recall_experience.query is required")
                continue
            if not isinstance(limit, int) or isinstance(limit, bool):
                errors.append("recall_experience.limit must be an integer")
                continue
            args = {"query": query.strip(), "limit": max(1, min(10, limit))}
        elif name == "evoke":
            resource = args.get("resource")
            if resource not in _EVOCABLE:
                errors.append("evoke.resource is not available")
                continue
            args = {"resource": resource}
        elif name == "inspect_architecture":
            query = args.get("query", "")
            if not isinstance(query, str) or len(query) > 200:
                errors.append("inspect_architecture.query is invalid")
                continue
            args = {"query": query.strip()}
        elif name == "reason_with_talnir":
            prompt = args.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
                errors.append("reason_with_talnir.prompt is required")
                continue
            args = {"prompt": prompt.strip()}
        elif name == "request_reflection":
            focus, reason = args.get("focus"), args.get("reason", "")
            if not isinstance(focus, str) or not focus.strip() or len(focus) > 500:
                errors.append("request_reflection.focus is required")
                continue
            if not isinstance(reason, str) or len(reason) > 500:
                errors.append("request_reflection.reason is invalid")
                continue
            args = {"focus": focus.strip(), "reason": reason.strip()}
        elif name == "search_architecture":
            query = args.get("query")
            if not isinstance(query, str) or not query.strip() or len(query) > 200:
                errors.append("search_architecture.query is required")
                continue
            args = {"query": query.strip()}
        valid.append({"name": name, "arguments": args})
    if errors:
        return {"status": "rejected", "reason": "; ".join(errors[:4])}
    return {"status": "valid", "requests": valid}


def _parse_tool_request(text):
    """Compatibility helper returning valid calls or None for older callers/tests."""
    result = _parse_tool_request_result(text)
    return result.get("requests") if result.get("status") == "valid" else None


def local_spark_generate(messages, max_tokens=256, max_tool_rounds=MAX_TOOL_ROUNDS, on_token=None, on_event=None):
    """Generate a reply and execute only explicitly allowlisted DexOS capabilities."""
    with _inference_lock:
        from local_llm import local_chat_generate, CHAT_MODEL_PATH
        from dex_capabilities import execute_capability

        conversation = [dict(message) for message in (messages or [])]
        if not conversation:
            raise ValueError("No chat messages supplied to local spark")
        # Pin the actual participant request across every capability round.
        # The latest observation must never replace the task it was produced for.
        root_request = next((
            str(message.get("content", ""))
            for message in reversed(conversation)
            if message.get("role") == "user"
        ), "")
        if not root_request.strip():
            raise ValueError("No participant request supplied to local spark")
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
            def observe_token(delta):
                # Forward each actual llama.cpp/SSE delta immediately. Do not
                # coalesce tokens into character-sized batches: the live
                # cognitive subscribers observe generation as it unfolds.
                if isinstance(delta, str) and delta and callable(on_token):
                    on_token(delta, {
                        "generation_round": round_index,
                        "generation_stage": "model_generation",
                    })

            answer = local_chat_generate(
                conversation, max_tokens=max_tokens, on_token=observe_token
            )
            if not isinstance(answer, str) or not answer.strip():
                raise RuntimeError("local GGUF returned empty text")
            parsed = _parse_tool_request_result(answer)
            if parsed["status"] == "plain":
                return {
                    "reply": answer.strip(),
                    "model": "local:" + CHAT_MODEL_PATH.rsplit("/", 1)[-1],
                    "tool_calls": executed,
                    "capability_execution_available": True,
                }
            if parsed["status"] == "rejected":
                if round_index >= effective_tool_rounds:
                    return {
                        "reply": "[DexOS rejected an invalid capability request after correction attempts.]",
                        "model": "local:" + CHAT_MODEL_PATH.rsplit("/", 1)[-1],
                        "tool_calls": executed,
                        "capability_execution_available": True,
                        "tool_request_rejected": parsed.get("reason", "invalid request"),
                    }
                conversation.append({"role": "assistant", "content": answer.strip()})
                conversation.append({
                    "role": "user",
                    "content": (
                        "[DEXOS TOOL VALIDATION FEEDBACK] Your proposed tool request was rejected: "
                        + parsed.get("reason", "invalid request")
                        + ". Correct the JSON and required arguments, or answer normally if no tool is needed. "
                        "The original request remains: "
                        + root_request
                    ),
                })
                continue
            requests = parsed["requests"]
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
                "content": (
                    "[ROOT'S ORIGINAL REQUEST — KEEP THIS TASK IN VIEW]\n"
                    + root_request
                    + "\n\n[ACTUAL DEXOS CAPABILITY OBSERVATIONS]\n"
                    + json.dumps([
                        {
                            "name": item.get("name"),
                            "arguments": item.get("arguments", {}),
                            "observation": _bounded_observation(item.get("observation")),
                        }
                        for item in observations
                    ], ensure_ascii=False, default=str)
                    + "\nUse these actual observations to answer the original request naturally. "
                      "Never claim observations that are not present here."
                ),
            })

        return {
            "reply": "[DexOS capability round limit reached]",
            "model": "local:" + CHAT_MODEL_PATH.rsplit("/", 1)[-1],
            "tool_calls": executed,
            "capability_execution_available": True,
        }
