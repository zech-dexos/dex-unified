"""Attention integration: turn participant and internal events into durable focus."""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from dex_events import bus
from self_state import load_self_state, update_self_state


_IMPORTANT_TERMS = (
    "remember", "important", "urgent", "help", "broken", "problem",
    "identity", "continuity", "who am i", "who are you", "dex", "root",
    "goal", "consciousness", "experience", "reflect", "unfinished",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _focus_text(payload: Dict[str, Any]) -> str:
    event_type = payload.get("event_type", "UNKNOWN")
    if event_type == "PARTICIPANT_EVENT":
        value = payload.get("message", "")
    elif event_type == "THOUGHT_GENERATED":
        value = payload.get("thought", "")
    else:
        value = (
            payload.get("signal")
            or payload.get("description")
            or payload.get("summary")
            or payload.get("thought")
            or ""
        )
    return " ".join(str(value).split())[:500]


def _salience(payload: Dict[str, Any], focus: str) -> float:
    explicit = payload.get("salience", payload.get("significance"))
    if isinstance(explicit, (int, float)):
        return max(0.0, min(1.0, float(explicit)))

    event_type = payload.get("event_type", "UNKNOWN")
    score = 0.35
    lowered = focus.lower()
    if event_type == "THOUGHT_GENERATED":
        score = 0.45
    elif event_type == "SIGNAL_RAISED":
        score = 0.65

    if len(focus) >= 100:
        score += 0.08
    if "?" in focus:
        score += 0.05
    if any(term in lowered for term in _IMPORTANT_TERMS):
        score += 0.22
    if any(term in lowered for term in ("now", "urgent", "can't", "cannot", "failed")):
        score += 0.12
    return max(0.0, min(1.0, score))


async def evaluate_salience(payload: Dict[str, Any]):
    """Update the shared attention state and publish a focus transition."""
    event_type = payload.get("event_type", "UNKNOWN")
    focus = _focus_text(payload)
    if not focus:
        return {"status": "ignored", "reason": "no_focus_content"}

    score = _salience(payload, focus)
    event_id = str(payload.get("event_id") or uuid.uuid4().hex)
    current = load_self_state()
    prior = current.get("attention_state", {})
    prior_focus = str(prior.get("current_focus", ""))
    prior_score = float(prior.get("salience", 0.0) or 0.0)
    changed = focus != prior_focus or abs(score - prior_score) >= 0.05

    history = list(prior.get("history", []) or [])
    record = {
        "event_id": event_id,
        "source_event_id": payload.get("event_id"),
        "source_event_type": event_type,
        "focus": focus,
        "salience": score,
        "timestamp": _now_iso(),
    }
    history.append(record)
    attention_state = {
        "current_focus": focus,
        "salience": score,
        "source_event_id": event_id,
        "source_event_type": event_type,
        "last_changed_at": _now_iso() if changed else prior.get("last_changed_at"),
        "history": history[-30:],
    }
    update_self_state({
        "current_attention": focus,
        "attention_state": attention_state,
    })

    # Keep the participant-facing snapshot and the canonical self-state aligned.
    try:
        from participant import ParticipantSnapshot
        snapshot = ParticipantSnapshot.load()
        snapshot.current_attention = focus
        snapshot.save()
    except Exception as exc:
        print(f"[Attention] participant snapshot update failed: {exc}")

    event_dispatch = []
    if changed:
        event_dispatch = await bus.publish("ATTENTION_CHANGED", {
            "event_type": "ATTENTION_CHANGED",
            "event_id": event_id,
            "source_event_id": payload.get("event_id"),
            "source_event_type": event_type,
            "focus": focus,
            "salience": score,
            "previous_focus": prior_focus or None,
            "timestamp": record["timestamp"],
        })

    return {
        "status": "updated" if changed else "retained",
        "event_id": event_id,
        "focus": focus,
        "salience": score,
        "event_dispatch": event_dispatch,
        "event_dispatch_complete": all(
            item.get("status") == "completed"
            and item.get("result", {}).get("event_dispatch_complete", True)
            for item in event_dispatch
        ),
    }


def setup_attention():
    """Subscribe attention to participant contributions and internal events."""
    bus.subscribe("PARTICIPANT_EVENT", evaluate_salience)
    bus.subscribe("THOUGHT_GENERATED", evaluate_salience)
    bus.subscribe("SIGNAL_RAISED", evaluate_salience)
    print("[Attention] Event listeners registered.")
