"""Canonical current perspective for DexOS.

Perspective is the durable synthesis of identity, experience, attention,
goals, workspace, conversation, and carry-forward state. It is not a claim
about phenomenal consciousness; it is the architectural point of view from
which the next cognition is grounded.
"""

from datetime import datetime, timezone
from typing import Any, Dict
from self_state import load_self_state, update_self_state


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_perspective(state: Dict[str, Any]) -> Dict[str, Any]:
    workspace = state.get("active_mental_workspace_state") or {}
    goals = [
        g for g in state.get("active_goals_state", [])
        if isinstance(g, dict) and g.get("status") == "active"
    ]
    experience = state.get("last_experience_state") or {}
    last_pulse = state.get("last_ambient_pulse") or {}
    attention = state.get("perspective", {}).get("attention") or {}
    interlocutor = state.get("perspective", {}).get("interlocutor") or {}

    carry = experience.get("carry_forward")
    if not carry:
        carry = state.get("perspective", {}).get("carry_forward")

    return {
        "version": int((state.get("perspective") or {}).get("version", 0)) + 1,
        "updated_at": _now_iso(),
        "self": {
            "identity": "Deximus Maximus",
            "dex_id": state.get("dex_id"),
            "core_principles": list(state.get("core_principles", [])),
        },
        "attention": attention,
        "orientation": {
            "active_goals": [
                {
                    "goal_id": g.get("goal_id"),
                    "description": g.get("description"),
                    "priority": g.get("priority"),
                    "success_criteria": g.get("success_criteria"),
                }
                for g in goals
            ],
            "values": state.get("vows", {}),
        },
        "experience": {
            "experience_id": experience.get("experience_id"),
            "source": experience.get("source"),
            "what_happened": experience.get("experience"),
            "state_before": experience.get("state_before"),
            "transition": experience.get("state_transition"),
            "reflection": experience.get("reflection"),
        },
        "workspace": {
            "active": bool(workspace.get("is_active")),
            "concept": workspace.get("concept_identifier"),
            "description": workspace.get("description_snapshot"),
            "focus_strength": workspace.get("focus_strength", 0.0),
            "reflections": list(workspace.get("internal_reflections", []))[-5:],
        },
        "carry_forward": carry,
        "interlocutor": interlocutor,
        "ambient": {
            "target": last_pulse.get("target"),
            "thought": last_pulse.get("thought"),
            "salience": last_pulse.get("salience"),
        },
        "continuity": {
            "last_experience_id": experience.get("experience_id"),
            "recent_goal_changes": list(state.get("recent_goal_changes", []))[-5:],
            "state_version": state.get("version", 0),
        },
    }


def refresh_perspective(*, reason: str = "state_transition", path=None) -> Dict[str, Any]:
    """Recompute and persist the canonical current perspective."""
    current = load_self_state(path) if path is not None else load_self_state()
    perspective = build_perspective(current)
    perspective["transition_reason"] = reason
    delta = {"perspective": perspective}
    return update_self_state(delta, path=path) if path is not None else update_self_state(delta)


def format_perspective(state: Dict[str, Any]) -> str:
    p = state.get("perspective") or build_perspective(state)
    lines = [
        "[DEX CURRENT PERSPECTIVE — architectural point of view]",
        "Identity: Deximus Maximus",
    ]
    att = p.get("attention") or {}
    if att.get("focus"):
        lines.append(f"Attending to: {att['focus']}")
    if att.get("reason"):
        lines.append(f"Attention reason: {att['reason']}")
    ori = p.get("orientation") or {}
    goals = ori.get("active_goals") or []
    if goals:
        lines.append("What matters now: " + "; ".join(
            str(g.get("description", "")) for g in goals[:5]
        ))
    if p.get("carry_forward"):
        lines.append(f"Carrying forward: {p['carry_forward']}")
    exp = p.get("experience") or {}
    if exp.get("what_happened"):
        lines.append(f"Most recent experience: {exp['what_happened']}")
    ws = p.get("workspace") or {}
    if ws.get("active") and ws.get("concept"):
        lines.append(f"Active workspace: {ws['concept']}")
    amb = p.get("ambient") or {}
    if amb.get("thought"):
        lines.append(f"Recent ambient cognition: {amb['thought']}")
    if p.get("transition_reason"):
        lines.append(f"Perspective transition: {p['transition_reason']}")
    return "\n".join(lines)
