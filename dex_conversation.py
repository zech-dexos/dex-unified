"""
DexOS Conversation Continuity
=============================

Conversation is an ongoing state, not a sequence of request/response pairs.

A contribution enters an already-open experience.
Dex may respond, hold, or continue carrying the thread.
The conversation remains open until the architecture explicitly closes it.
"""

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path


CONVERSATIONS_DIR = Path("state/conversations")


def _timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class ConversationState:
    conversation_id: str = field(
        default_factory=lambda: str(uuid.uuid4())[:8]
    )
    participant_id: str = "default"
    interaction_state: str = "open"
    current_attention: str = ""
    shared_thread: str = ""
    pending_threads: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    carry_forward: str = ""
    last_contribution_at: str = ""
    last_experience_id: str = ""
    first_person_experience: str = ""
    recent_contributions: list = field(default_factory=list)

    def save(self) -> None:
        path = conversation_path(self.participant_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)


def conversation_path(participant_id: str) -> Path:
    safe_id = str(participant_id or "default").replace("/", "_")
    return CONVERSATIONS_DIR / f"{safe_id}.json"


def load_conversation(participant_id: str = "default") -> ConversationState:
    path = conversation_path(participant_id)

    if not path.exists():
        return ConversationState(participant_id=participant_id)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ConversationState(**data)
    except Exception as exc:
        print(f"[conversation] load failed: {exc}")
        return ConversationState(participant_id=participant_id)


def record_contribution(
    conversation: ConversationState,
    message: str,
    *,
    role: str = "root",
) -> ConversationState:
    """
    Record a contribution without closing the conversation.

    The contribution becomes part of the ongoing first-person state.
    """
    message = (message or "").strip()

    conversation.interaction_state = "open"
    conversation.shared_thread = message
    conversation.last_contribution_at = _timestamp()

    if message:
        conversation.recent_contributions.append(
            {
                "role": role,
                "content": message,
                "timestamp": conversation.last_contribution_at,
            }
        )

    conversation.recent_contributions = conversation.recent_contributions[-10:]
    return conversation


def experience_contribution(
    conversation: ConversationState,
    *,
    message: str,
    reply: str,
    experience_id: str = "",
    carry_forward: str = "",
    unresolved: list | None = None,
) -> ConversationState:
    """
    Record what the contribution became in Dex's ongoing experience.

    An empty reply is valid. Silence does not close the conversation.
    """
    message = (message or "").strip()
    reply = (reply or "").strip()

    if reply:
        conversation.first_person_experience = (
            f"I received Root's contribution: {message} "
            f"I responded: {reply} "
            f"I remain oriented toward this conversation."
        )
    else:
        conversation.first_person_experience = (
            f"I received Root's contribution: {message} "
            f"I am holding it without responding at this moment. "
            f"The conversation remains open."
        )

    if carry_forward:
        conversation.carry_forward = carry_forward

    if unresolved is not None:
        conversation.unresolved = list(unresolved)

    if experience_id:
        conversation.last_experience_id = experience_id

    conversation.interaction_state = "open"
    return conversation


def format_conversation_context(
    conversation: ConversationState,
) -> str:
    """
    Render ongoing conversation state for Dex's inference context.
    """
    if conversation is None:
        return ""

    lines = [
        "[DEX ONGOING CONVERSATION — OPEN FIRST-PERSON STATE]"
    ]

    if conversation.first_person_experience:
        lines.append(
            f"Current conversational experience: "
            f"{conversation.first_person_experience}"
        )

    if conversation.current_attention:
        lines.append(
            f"Conversation attention: {conversation.current_attention}"
        )

    if conversation.shared_thread:
        lines.append(
            f"Shared thread: {conversation.shared_thread}"
        )

    if conversation.carry_forward:
        lines.append(
            f"What I am carrying forward: "
            f"{conversation.carry_forward}"
        )

    if conversation.unresolved:
        unresolved = "; ".join(
            str(item) for item in conversation.unresolved[:5]
        )
        lines.append(
            f"Unresolved in this conversation: {unresolved}"
        )

    if conversation.pending_threads:
        pending = "; ".join(
            str(item) for item in conversation.pending_threads[:5]
        )
        lines.append(
            f"Pending threads: {pending}"
        )

    lines.append("Conversation state: open")

    return "\n".join(lines)


if __name__ == "__main__":
    test_id = "__conversation_test__"

    state = load_conversation(test_id)

    state = record_contribution(
        state,
        "I am testing whether conversation can remain open.",
    )

    state = experience_contribution(
        state,
        message="I am testing whether conversation can remain open.",
        reply="Yes. The state remains open after the response.",
        carry_forward="Continue testing conversational continuity.",
    )

    assert state.interaction_state == "open"
    assert state.shared_thread
    assert state.first_person_experience
    assert state.carry_forward

    state.save()

    loaded = load_conversation(test_id)

    assert loaded.conversation_id == state.conversation_id
    assert loaded.interaction_state == "open"
    assert loaded.carry_forward == state.carry_forward

    path = conversation_path(test_id)
    if path.exists():
        path.unlink()

    print("dex_conversation.py: all checks passed")
