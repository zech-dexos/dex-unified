"""Persistent self-model context for Dex's existing cognitive runtime.

This module composes existing identity, participant, goals, open loops, and
self_model.json state. It does not create a parallel identity store or let
inference silently rewrite durable self-understanding.
"""
import json
from pathlib import Path
from typing import Any, Dict

from paths import IDENTITY_PATH, SELF_MODEL_PATH, PARTICIPANT_PATH, LOOPS_PATH
from self_state import load_self_state


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[Dex Self-Model] read failed for {path.name}: {exc}")
    return {}


def _participant() -> Dict[str, Any]:
    return _read_json(PARTICIPANT_PATH)


def _open_loops():
    try:
        value = json.loads(LOOPS_PATH.read_text(encoding="utf-8")) if LOOPS_PATH.exists() else []
        return [x for x in value if isinstance(x, dict) and x.get("status", "open") not in {"resolved", "closed", "abandoned"}][-10:] if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def inspect_self_model() -> Dict[str, Any]:
    """Return Dex's explicit self-model plus the current state it describes."""
    state = load_self_state()
    model = _read_json(SELF_MODEL_PATH)
    return {
        "available": bool(model),
        "source": str(SELF_MODEL_PATH.name),
        "self_model": model,
        "identity": {
            "dex_id": state.get("dex_id"),
            "vows": state.get("vows", {}),
            "core_principles": state.get("core_principles", []),
            "narrative_thread": state.get("narrative_thread", [])[-10:],
        },
        "runtime_self_assessment": {
            "active_goals": state.get("active_goals_state", [])[-10:],
            "active_workspace": state.get("active_mental_workspace_state", {}),
            "persistent_thoughts": state.get("persistent_thoughts", [])[-10:],
            "last_ambient_pulse": state.get("last_ambient_pulse"),
            "runtime_lifecycle": state.get("runtime_lifecycle", {}),
        },
        "note": "Stored self-model and observed runtime state are distinct; absence of self_model.json is not treated as proof of absent identity.",
    }


def inspect_relationship() -> Dict[str, Any]:
    """Read the current relational context without conflating it with participant IDs."""
    state = load_self_state()
    participant = _participant()
    identity = _read_json(IDENTITY_PATH)
    conversation = {}
    try:
        from dex_conversation import load_conversation
        conversation = load_conversation("default")
    except Exception as exc:
        print(f"[Dex Self-Model] conversation context unavailable: {exc}")
    return {
        "relationship_model": state.get("relationship_model", identity.get("relationship_model", {})),
        "current_interlocutor": participant.get("current_interlocutor", {}),
        "experiential_continuity": participant.get("experiential_continuity", {}),
        "shared_thread": str(conversation.get("shared_thread", ""))[:2000],
        "recent_observations": (participant.get("recent_observations", []) or [])[-5:],
        "note": "Relationship meaning and shared history are separate from participant_id and user_id.",
    }


def inspect_becoming() -> Dict[str, Any]:
    """Compose developmental direction from the explicit model and existing goals."""
    state = load_self_state()
    model = _read_json(SELF_MODEL_PATH)
    return {
        "becoming": model.get("becoming", model.get("developmental_direction", {})),
        "developmental_goals": model.get("developmental_goals", []),
        "active_goals": state.get("active_goals_state", [])[-15:],
        "open_loops": _open_loops(),
        "pending_reflection_requests": [
            item for item in state.get("pending_reflection_requests", [])
            if isinstance(item, dict) and item.get("status", "pending") == "pending"
        ][-10:],
        "note": "The becoming model describes intended direction; active goals and open loops are operational work toward it.",
    }


def build_identity_context(max_chars: int = 6500) -> str:
    """Build a bounded, grounded identity context for inference and ambient cognition."""
    payload = {
        "identity_and_self_model": inspect_self_model(),
        "relationship_to_current_interlocutor": inspect_relationship(),
        "developmental_direction": inspect_becoming(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    if len(encoded) > max_chars:
        encoded = encoded[:max_chars] + "...[context bounded]"
    return (
        "DEX CONTINUITY CONTEXT (grounded in persisted DexOS state):\n"
        + encoded
        + "\nTreat missing fields as unknown, not as facts. Distinguish durable identity, "
          "relationship context, observed present state, and intended becoming. Do not "
          "invent shared history or claim an ability unless the state supports it. "
          "Do not rewrite identity or self-model from inference alone."
    )
