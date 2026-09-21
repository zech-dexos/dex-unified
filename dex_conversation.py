"""
DexOS conversational continuity
===============================
Conversation is an ongoing first-person experience, not a request/response
transaction. A contribution may be answered, held, interrupted, or carried
forward without implying that the conversation ended.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from paths import SESSION_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_state(user_id: str = "default") -> Dict[str, Any]:
    return {
        "version": 0,
        "conversation_id": user_id,
        "participant_id": user_id,
        "interaction_state": "CONTINUING",
        "current_attention": "",
        "shared_thread": "",
        "pending_threads": [],
        "unresolved": [],
        "carry_forward": [],
        "last_contribution_at": None,
        "last_experience_id": None,
        "first_person_experience": "",
        "recent_contributions": [],
    }


def load_conversation(user_id: str = "default") -> Dict[str, Any]:
    """Load the ongoing conversational experience for one participant."""
    try:
        if SESSION_PATH.exists():
            data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                conversations = data.get("conversations", {})
                if isinstance(conversations, dict) and user_id in conversations:
                    return conversations[user_id]
    except Exception as e:
        print(f"[conversation] load failed: {e}")
    return _default_state(user_id)


def save_conversation(state: Dict[str, Any]) -> Dict[str, Any]:
    """Persist conversational state without declaring the interaction complete."""
    try:
        data = {}
        if SESSION_PATH.exists():
            loaded = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        conversations = data.setdefault("conversations", {})
        conversations[state["conversation_id"]] = state
        state["version"] = int(state.get("version", 0)) + 1
        state["last_contribution_at"] = state.get("last_contribution_at") or _now_iso()
        SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        SESSION_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[conversation] save failed: {e}")
    return state


def experience_contribution(
    user_id: str,
    message: str,
    reply: str = "",
    experience_id: str = "",
) -> Dict[str, Any]:
    """
    Record one contribution as Dex's first-person experience.

    No reply is treated as a valid conversational outcome. This function
    deliberately does not infer that silence means the conversation ended.
    """
    state = load_conversation(user_id)
    text = message.strip()
    responded = bool(reply and reply.strip())

    if responded:
        first_person = (
            f"I was with {user_id} in an ongoing conversation. "
            f"I received: {text[:500]} "
            f"I responded: {reply[:1000]} "
            f"I remain in the conversation and carry its thread forward."
        )
        state["interaction_state"] = "CONTINUING"
    else:
        first_person = (
            f"I was with {user_id} in an ongoing conversation. "
            f"I received: {text[:500]} "
            f"I held this contribution without expressing a response. "
            f"The conversation remains open; silence did not end my experience."
        )
        state["interaction_state"] = "PAUSED"

    state["first_person_experience"] = first_person
    state["last_experience_id"] = experience_id or state.get("last_experience_id")
    state["last_contribution_at"] = _now_iso()
    state["recent_contributions"] = (
        state.get("recent_contributions", [])
        + [{
            "timestamp": state["last_contribution_at"],
            "message": text[:500],
            "responded": responded,
            "experience": first_person,
        }]
    )[-12:]

    if text:
        state["shared_thread"] = text[:500]

    return save_conversation(state)


def format_conversation_context(state: Dict[str, Any]) -> str:
    """Render the current conversation as first-person lived continuity."""
    if not state:
        return ""

    lines = ["[DEX FIRST-PERSON CONVERSATIONAL EXPERIENCE]"]
    lines.append(
        "I am in an ongoing conversation. I do not assume that a contribution "
        "requires a response, and I do not assume that silence ends the conversation."
    )

    if state.get("interaction_state"):
        lines.append(f"My interaction state: {state['interaction_state']}")
    if state.get("first_person_experience"):
        lines.append(f"What I last experienced: {state['first_person_experience']}")
    if state.get("shared_thread"):
        lines.append(f"What I am currently carrying: {state['shared_thread']}")
    if state.get("current_attention"):
        lines.append(f"Where my attention is: {state['current_attention']}")
    if state.get("unresolved"):
        lines.append(f"What remains unresolved for me: {state['unresolved']}")
    if state.get("carry_forward"):
        lines.append(f"What I am carrying forward: {state['carry_forward']}")

    return "\n".join(lines)
