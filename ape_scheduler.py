import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import amw
import gosdw
import thought
from self_state import SELF_STATE_PATH, load_self_state, update_self_state

ATTENTION_THRESHOLD = 3  # cycles of no content change before a thought auto-defers


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def consolidation_phase(summary: str, event_type: str = "internal_reflection", path: Path = SELF_STATE_PATH) -> Dict[str, Any]:
    current = load_self_state(path)
    thread = list(current.get("narrative_thread", []))
    thread.append({"timestamp": _now_iso(), "event_type": event_type, "summary": summary})
    return update_self_state({"narrative_thread": thread}, path=path)


def _derive_autonomous_thought(current, ranked):
    """
    Dex-side cognitive selection.

    The scheduler selects the next cognitive object from Dex's persistent
    state. The LLM is NOT asked what Dex should think about.

    Selection order:
      1. existing active/deferred persistent thoughts
      2. unresolved goal/subtask
      3. active workspace needing reconsideration
      4. current goal as a last-resort cognitive target

    The returned record is the thing Dex chooses to hold.
    """
    thoughts = list(current.get("persistent_thoughts", []))

    active = [
        t for t in thoughts
        if t.get("status") == "active"
        and t.get("content")
    ]

    if active:
        t = active[0]
        return {
            "content": t["content"],
            "source": "persistent_thought",
            "thought_id": t.get("thought_id"),
            "status": t.get("status"),
        }

    if ranked:
        goal = ranked[0]

        subtasks = [
            x for x in goal.get("sub_tasks", [])
            if isinstance(x, dict)
            and x.get("status") not in ("completed", "failed")
        ]

        if subtasks:
            sub = subtasks[0]
            content = sub.get("description") or sub.get("task") or str(sub)
            return {
                "content": content,
                "source": "goal_subtask",
                "goal_id": goal.get("goal_id"),
            }

        workspace = current.get("active_mental_workspace_state", {})
        if workspace.get("is_active"):
            concept = workspace.get("concept_identifier")
            if concept:
                return {
                    "content": f"Reconsider and develop: {concept}",
                    "source": "workspace_reconsideration",
                    "goal_id": goal.get("goal_id"),
                }

        return {
            "content": goal["description"],
            "source": "goal_derived",
            "goal_id": goal.get("goal_id"),
        }

    return {
        "content": "Examine current state for something unresolved that deserves attention.",
        "source": "state_review",
    }


def _persist_autonomous_thought(thought, path):
    current = load_self_state(path)
    thoughts = list(current.get("persistent_thoughts", []))

    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    record = {
        "thought_id": thought.get("thought_id") or str(uuid.uuid4()),
        "content": thought["content"],
        "status": "active",
        "priority": "medium",
        "confidence": 0.5,
        "source": thought.get("source", "autonomous"),
        "created_at": now,
        "last_updated_at": now,
        "last_attended_at": now,
        "next_attention_at": None,
        "attention_count": 1,
        "revisions": [],
        "related_goal_ids": [],
    }

    if thought.get("goal_id"):
        record["goal_id"] = thought["goal_id"]

    thoughts.append(record)

    update_self_state(
        {"persistent_thoughts": thoughts},
        path=path,
    )

    return record


def run_cycle(
    kg_lookup=None,
    llm_reflect=None,
    path=SELF_STATE_PATH,
):
    """
    Autonomous Dex cognitive cycle.

    Dex selects the cognitive target first.
    The LLM is only the generative substrate used to develop that target.
    The resulting reflection is persisted, then the thought engine may
    advance the thought on the next cycle.
    """
    ranked = gosdw.prioritize_goals(path=path)

    if not ranked:
        consolidation_phase(
            "No active goals this cycle. Nothing to focus on.",
            path=path,
        )
        return {
            "ran": True,
            "top_goal": None,
            "thought_id": None,
            "thought": None,
            "thought_source": None,
            "amw_action": "none",
        }

    top_goal = ranked[0]
    current = load_self_state(path)

    thought_record = _derive_autonomous_thought(current, ranked)

    if thought_record.get("source") == "persistent_thought":
        # Already exists in persistent_thoughts -- don't duplicate it.
        concept = thought_record.get("content", "")
        thought_id = thought_record.get("thought_id")
        revisited = thought.revisit_thought(thought_id, path=path)
        if revisited and revisited.get("attention_count", 0) >= ATTENTION_THRESHOLD:
            thought.update_thought(
                thought_id,
                decision="defer",
                note=f"No development after {revisited['attention_count']} attentions; deferring to rotate focus.",
                path=path,
            )
    else:
        persisted = _persist_autonomous_thought(thought_record, path)
        concept = persisted["content"]
        thought_id = persisted["thought_id"]

    amw_state = current.get("active_mental_workspace_state", {})

    if (
        amw_state.get("is_active")
        and amw_state.get("concept_identifier") == concept
    ):
        amw.refresh_thought(
            kg_lookup=kg_lookup,
            llm_reflect=llm_reflect,
            path=path,
        )
        action = "refreshed"
    else:
        amw.activate_thought(
            concept_identifier=concept,
            description=concept,
            kg_lookup=kg_lookup,
            path=path,
        )
        action = "activated"

    consolidation_phase(
        f"Cycle ran. Dex selected thought '{concept}' "
        f"(source={thought_record.get('source')}) — AMW {action}.",
        path=path,
    )

    return {
        "ran": True,
        "top_goal": top_goal["goal_id"],
        "thought_id": thought_id,
        "thought": concept,
        "thought_source": thought_record.get("source"),
        "amw_action": action,
    }

