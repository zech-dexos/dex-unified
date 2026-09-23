from typing import Dict, Any
from dex_events import bus
from self_state import load_self_state, update_self_state


async def activate_workspace(payload: Dict[str, Any]):
    """Synchronize the active mental workspace with a meaningful attention event."""
    focus = payload.get("focus") or payload.get("message") or payload.get("thought")
    salience = float(payload.get("salience", 0.0) or 0.0)
    if not focus or salience < 0.7:
        return

    current = load_self_state()
    workspace = current.get("active_mental_workspace_state", {})
    if workspace.get("is_active") and workspace.get("concept_identifier") == focus:
        return

    update_self_state({
        "active_mental_workspace_state": {
            "is_active": True,
            "concept_identifier": str(focus)[:500],
            "description_snapshot": str(focus)[:1000],
            "activation_timestamp": workspace.get("activation_timestamp"),
            "last_refresh_timestamp": payload.get("timestamp"),
            "focus_strength": salience,
            "related_knowledge_nodes": workspace.get("related_knowledge_nodes", []),
            "internal_reflections": workspace.get("internal_reflections", [])[-5:],
            "duration_hint": workspace.get("duration_hint"),
        }
    })

    try:
        from dex_perspective import refresh_perspective
        refresh_perspective(reason="workspace_activation")
    except Exception as e:
        print(f"[Workspace] perspective refresh failed: {e}")


def setup_workspace():
    bus.subscribe("ATTENTION_CHANGED", activate_workspace)
    print("[Workspace] Event listeners registered.")
