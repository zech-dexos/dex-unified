from typing import Dict, Any
from dex_events import bus

async def evaluate_salience(payload: Dict[str, Any]):
    """
    Evaluates events for salience changes and determines if attention should shift.
    """
    event_type = payload.get("event_type", "UNKNOWN")
    print(f"[Attention] Evaluating salience for event: {event_type}")

    # Phase 1 scaffolding:
    # If salience is high, attention may focus and activate the cognitive workspace.
    pass

def setup_attention():
    """Subscribe attention tracking to the shared event fabric."""
    # Attention can evaluate almost any major system event.
    bus.subscribe("PARTICIPANT_EVENT", evaluate_salience)
    bus.subscribe("THOUGHT_GENERATED", evaluate_salience)
    bus.subscribe("SIGNAL_RAISED", evaluate_salience)
    print("[Attention] Event listeners registered.")
