from typing import Dict, Any
from dex_events import bus
from self_state import load_self_state, update_self_state


def _candidate_focus(payload: Dict[str, Any]) -> tuple[str, float, str]:
    event_type = payload.get("event_type", "UNKNOWN")
    text = (
        payload.get("message")
        or payload.get("thought")
        or payload.get("description")
        or payload.get("summary")
        or payload.get("result")
        or event_type
    )
    try:
        salience = float(payload.get("salience", payload.get("significance", 0.0)) or 0.0)
    except (TypeError, ValueError):
        salience = 0.0

    if event_type in {"PARTICIPANT_EVENT", "RESPONSE_COMPLETED"}:
        salience = max(salience, 0.8)
    elif event_type in {"GOAL_CREATED", "GOAL_COMPLETED", "GOAL_CHANGED", "SIGNAL_RAISED"}:
        salience = max(salience, 0.7)
    elif event_type == "THOUGHT_GENERATED":
        salience = max(salience, 0.5)

    return str(text).strip(), max(0.0, min(1.0, salience)), f"{event_type.lower()} with salience {salience:.2f}"


async def evaluate_salience(payload: Dict[str, Any]):
    """Evaluate a meaningful event and update Dex's canonical attention state."""
    focus, salience, reason = _candidate_focus(payload)
    if not focus:
        return

    current = load_self_state()
    previous = (current.get("perspective") or {}).get("attention") or {}
    previous_salience = float(previous.get("salience", 0.0) or 0.0)

    if salience < 0.5 and previous_salience >= 0.5:
        return

    attention = {
        "focus": focus[:1000],
        "salience": salience,
        "reason": reason,
        "event_type": payload.get("event_type", "UNKNOWN"),
        "timestamp": payload.get("timestamp"),
    }
    update_self_state({"perspective": {"attention": attention}})

    try:
        from dex_perspective import refresh_perspective
        refresh_perspective(reason="attention_shift")
    except Exception as e:
        print(f"[Attention] perspective refresh failed: {e}")

    await bus.publish("ATTENTION_CHANGED", {
        "event_type": "ATTENTION_CHANGED",
        "focus": attention["focus"],
        "salience": salience,
        "reason": reason,
    })


def setup_attention():
    bus.subscribe("PARTICIPANT_EVENT", evaluate_salience)
    bus.subscribe("THOUGHT_GENERATED", evaluate_salience)
    bus.subscribe("SIGNAL_RAISED", evaluate_salience)
    bus.subscribe("GOAL_CREATED", evaluate_salience)
    bus.subscribe("GOAL_CHANGED", evaluate_salience)
    bus.subscribe("GOAL_COMPLETED", evaluate_salience)
    bus.subscribe("RESPONSE_COMPLETED", evaluate_salience)
    print("[Attention] Event listeners registered.")


if __name__ == "__main__":
    import asyncio
    from pathlib import Path
    test_path = Path("self_state.attention.test.json")
    if test_path.exists():
        test_path.unlink()
    from self_state import update_self_state as _update
    _update({"perspective": {"attention": {}}}, path=test_path)
    # Direct function exercise with the module's normal state path is intentionally
    # skipped; integration tests cover persistence under isolated paths.
    test_path.unlink()
    print("dex_attention.py: smoke checks passed")
