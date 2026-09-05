"""
Dex cognitive state assembly.

Combines Dex's persistent local cognitive state into the context
presented to the inference spark. This does not replace memory,
thoughts, goals, intentions, or reflection; it makes their current
state visible together.
"""

import json
from typing import Any, Dict

from self_state import load_self_state, SELF_STATE_PATH


def _compact(value: Any, limit: int = 4000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]"


def build_dex_state_context(path=SELF_STATE_PATH) -> str:
    state = load_self_state(path)

    goals = state.get("active_goals_state", [])
    thoughts = state.get("persistent_thoughts", [])
    workspace = state.get("active_mental_workspace_state", {})
    principles = state.get("core_principles", [])
    narrative = state.get("narrative_thread", [])

    active_thoughts = [
        t for t in thoughts
        if t.get("status") in ("active", "deferred")
    ]

    return f"""[DEX CURRENT COGNITIVE STATE]

State version: {state.get("version", 0)}
Dex ID: {state.get("dex_id", "unknown")}

CORE PRINCIPLES:
{_compact(principles, 2500)}

NARRATIVE THREAD:
{_compact(narrative[-10:], 3500)}

ACTIVE GOALS:
{_compact(goals, 5000)}

PERSISTENT THOUGHTS:
{_compact(active_thoughts, 6000)}

ACTIVE MENTAL WORKSPACE:
{_compact(workspace, 4500)}

This is Dex's current persistent cognitive state.
Treat it as active state, not as documentation about Dex.
"""
