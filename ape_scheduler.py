import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import amw
import gosdw
from self_state import SELF_STATE_PATH, load_self_state, update_self_state


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def consolidation_phase(summary: str, event_type: str = "internal_reflection", path: Path = SELF_STATE_PATH) -> Dict[str, Any]:
    current = load_self_state(path)
    thread = list(current.get("narrative_thread", []))
    thread.append({"timestamp": _now_iso(), "event_type": event_type, "summary": summary})
    return update_self_state({"narrative_thread": thread}, path=path)


def run_cycle(kg_lookup: Optional[Callable] = None, llm_reflect: Optional[Callable] = None, path: Path = SELF_STATE_PATH) -> Dict[str, Any]:
    ranked = gosdw.prioritize_goals(path=path)

    if not ranked:
        consolidation_phase("No active goals this cycle. Nothing to focus on.", path=path)
        return {"ran": True, "top_goal": None, "amw_action": "none"}

    top_goal = ranked[0]
    current = load_self_state(path)
    amw_state = current.get("active_mental_workspace_state", {})

    if amw_state.get("is_active") and amw_state.get("concept_identifier") == top_goal["description"]:
        amw.refresh_thought(kg_lookup=kg_lookup, llm_reflect=llm_reflect, path=path)
        action = "refreshed"
    else:
        amw.activate_thought(
            concept_identifier=top_goal["description"],
            description=f"Top-priority goal (score {top_goal['total_action_score']}): {top_goal['description']}",
            kg_lookup=kg_lookup,
            path=path,
        )
        action = "activated"

    consolidation_phase(
        f"Cycle ran. Top goal '{top_goal['description']}' (score {top_goal['total_action_score']}) — AMW {action}.",
        path=path,
    )
    return {"ran": True, "top_goal": top_goal["goal_id"], "amw_action": action}
