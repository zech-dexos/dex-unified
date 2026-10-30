"""Workspace integration: turn meaningful attention changes into active focus."""
import uuid
from typing import Dict, Any

from dex_events import bus, dispatch_complete
from self_state import SELF_STATE_PATH, load_self_state, update_self_state
from amw import activate_thought


WORKSPACE_ACTIVATION_THRESHOLD = 0.55
WORKSPACE_PREEMPTION_MARGIN = 0.1


async def activate_workspace(payload: Dict[str, Any]):
    """Activate or retain AMW from an explicit attention transition."""
    if payload.get("event_type") != "ATTENTION_CHANGED":
        return {"status": "ignored", "reason": "not_an_attention_transition"}

    focus = " ".join(str(payload.get("focus", "")).split())[:500]
    if not focus:
        return {"status": "ignored", "reason": "empty_focus"}

    try:
        salience = max(0.0, min(1.0, float(payload.get("salience", 0.0))))
    except (TypeError, ValueError):
        salience = 0.0
    if salience < WORKSPACE_ACTIVATION_THRESHOLD:
        return {"status": "below_activation_threshold", "salience": salience}

    current = load_self_state()
    workspace = current.get("active_mental_workspace_state", {})
    active = bool(workspace.get("is_active"))
    current_focus = str(workspace.get("concept_identifier") or "")
    same_focus = active and current_focus == focus
    current_salience = float(workspace.get("attention_salience", 0.65) or 0.65)

    if active and not same_focus and salience < current_salience + WORKSPACE_PREEMPTION_MARGIN:
        return {
            "status": "existing_workspace_retained",
            "current_focus": current_focus,
            "incoming_focus": focus,
            "current_salience": current_salience,
            "incoming_salience": salience,
        }

    if same_focus:
        update_self_state({
            "active_mental_workspace_state": {
                "attention_salience": salience,
                "source_event_id": payload.get("event_id"),
                "last_refresh_timestamp": payload.get("timestamp"),
            }
        })
        return {"status": "workspace_retained", "focus": focus}

    activate_thought(
        concept_identifier=focus,
        description=focus,
        duration_hint="attention-selected focus; revisitable by the cognitive scheduler",
        path=SELF_STATE_PATH,
    )
    workspace_event_id = uuid.uuid4().hex
    update_self_state({
        "active_mental_workspace_state": {
            "attention_salience": salience,
            "source_event_id": payload.get("event_id"),
            "source_interaction_event_id": payload.get("source_event_id"),
            "source_event_type": payload.get("source_event_type"),
        }
    })

    dispatch = await bus.publish("WORKSPACE_ACTIVATED", {
        "event_type": "WORKSPACE_ACTIVATED",
        "event_id": workspace_event_id,
        "source_event_id": payload.get("event_id"),
        "source_interaction_event_id": payload.get("source_event_id"),
        "source_event_type": payload.get("source_event_type"),
        "concept_identifier": focus,
        "salience": salience,
        "previous_focus": current_focus or None,
        "timestamp": payload.get("timestamp"),
    })
    return {
        "status": "activated",
        "focus": focus,
        "event_id": workspace_event_id,
        "salience": salience,
        "event_dispatch": dispatch,
        "event_dispatch_complete": bool(dispatch) and dispatch_complete(
            dispatch, {"process_continuity_event", "process_autobiographical_event"}
        ),
    }


def setup_workspace():
    """Subscribe workspace management to attention transitions."""
    bus.subscribe("ATTENTION_CHANGED", activate_workspace)
    print("[Workspace] Event listeners registered.")
