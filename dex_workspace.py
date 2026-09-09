from typing import Dict, Any
from dex_events import bus

async def activate_workspace(payload: Dict[str, Any]):
    """
    Manages the active cognitive workspace when expensive reasoning is needed.
    Triggered by high salience or specific participation events.
    """
    event_type = payload.get("event_type", "UNKNOWN")
    print(f"[Workspace] Workspace activation evaluated from event: {event_type}")

    # Phase 1 scaffolding:
    # Later this will manage LLM invocations distinct from the lightweight continuous substrate.
    pass

def setup_workspace():
    """Subscribe the cognitive workspace to the shared event fabric."""
    bus.subscribe("ATTENTION_CHANGED", activate_workspace)
    bus.subscribe("PARTICIPANT_EVENT", activate_workspace)
    print("[Workspace] Event listeners registered.")
