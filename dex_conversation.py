"""
DexOS conversational continuity
===============================
Conversation is an ongoing first-person experience, not a request/response
transaction. A contribution may be answered, held, interrupted, or carried
forward without implying that the conversation ended.
"""

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from paths import SESSION_PATH

_SESSION_LOCK = threading.RLock()


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


def _canonical_participant_id(user_id: str = "default") -> str:
    """Resolve only the root/default alias to the active interlocutor identity."""
    requested_id = str(user_id or "default")
    if requested_id not in {"root", "default"}:
        return requested_id

    try:
        from participant import ParticipantSnapshot
        snapshot = ParticipantSnapshot.load()
        interlocutor = snapshot.current_interlocutor or {}
        canonical_id = str(interlocutor.get("participant_id") or "").strip()
        if canonical_id:
            return canonical_id
    except Exception as e:
        print(f"[conversation] canonical participant resolution failed: {e}")
    return requested_id


def load_conversation(user_id: str = "default") -> Dict[str, Any]:
    """Load conversation state using the canonical participant identity."""
    canonical_id = _canonical_participant_id(user_id)
    try:
        if SESSION_PATH.exists():
            data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                conversations = data.get("conversations", {})
                if isinstance(conversations, dict):
                    if canonical_id in conversations:
                        return conversations[canonical_id]
                    # Preserve any pre-fix state written under the request alias.
                    if user_id in conversations:
                        legacy = dict(conversations[user_id])
                        legacy["conversation_id"] = canonical_id
                        legacy["participant_id"] = canonical_id
                        return legacy
    except Exception as e:
        print(f"[conversation] load failed: {e}")
    return _default_state(canonical_id)


def _merge_conversation_states(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Merge stale concurrent writes without dropping recent contributions."""
    merged = dict(existing)
    merged.update(incoming)

    existing_at = str(existing.get("last_contribution_at") or "")
    incoming_at = str(incoming.get("last_contribution_at") or "")
    if existing_at > incoming_at:
        for key in (
            "interaction_state", "current_attention", "shared_thread",
            "last_contribution_at", "last_experience_id", "first_person_experience",
        ):
            if key in existing:
                merged[key] = existing[key]

    contributions = []
    seen = set()
    for item in list(existing.get("recent_contributions", [])) + list(incoming.get("recent_contributions", [])):
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("timestamp", "")),
            str(item.get("message", "")),
            str(item.get("experience", "")),
        )
        if key not in seen:
            seen.add(key)
            contributions.append(item)
    contributions.sort(key=lambda item: str(item.get("timestamp", "")))
    merged["recent_contributions"] = contributions[-12:]

    ambient_times = [
        str(value) for value in (
            existing.get("last_ambient_at"), incoming.get("last_ambient_at")
        ) if value
    ]
    if ambient_times:
        merged["last_ambient_at"] = max(ambient_times)

    merged["version"] = max(
        int(existing.get("version", 0) or 0),
        int(incoming.get("version", 0) or 0),
    ) + 1
    return merged


def save_conversation(state: Dict[str, Any]) -> Dict[str, Any]:
    """Atomically persist conversational state and merge concurrent local writes."""
    try:
        with _SESSION_LOCK:
            data = {}
            if SESSION_PATH.exists():
                loaded = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            conversations = data.setdefault("conversations", {})
            conversation_id = str(state.get("conversation_id") or state.get("participant_id") or "default")
            existing = conversations.get(conversation_id, {})
            saved = _merge_conversation_states(existing, dict(state))
            saved["conversation_id"] = conversation_id
            saved["participant_id"] = str(saved.get("participant_id") or conversation_id)
            saved["last_contribution_at"] = saved.get("last_contribution_at") or _now_iso()
            conversations[conversation_id] = saved

            SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=str(SESSION_PATH.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(data, stream, indent=2, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp_path, SESSION_PATH)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

            state.update(saved)
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
    canonical_id = str(state.get("conversation_id") or _canonical_participant_id(user_id))
    text = message.strip()
    responded = bool(reply and reply.strip())

    if responded:
        first_person = (
            f"I was with {canonical_id} in an ongoing conversation. "
            f"I received: {text[:500]} "
            f"I responded: {reply[:1000]} "
            f"I remain in the conversation and carry its thread forward."
        )
        state["interaction_state"] = "CONTINUING"
    else:
        first_person = (
            f"I was with {canonical_id} in an ongoing conversation. "
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
