import time
from datetime import datetime, timezone
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
                PREFIX = "Reconsider and develop: "
                base = concept
                while base.startswith(PREFIX):
                    base = base[len(PREFIX):]
                return {
                    "content": f"{PREFIX}{base}",
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
    current = load_self_state(path)
    workspace = current.get("active_mental_workspace_state", {})

    # Root's active interaction owns attention for ten minutes. Ambient goals
    # remain intact, but the scheduler cannot steal the active workspace.
    priority_until = current.get("participant_priority_until")
    try:
        priority_time = datetime.fromisoformat(
            str(priority_until).replace("Z", "+00:00")
        ) if priority_until else None
    except (TypeError, ValueError):
        priority_time = None
    if priority_time and priority_time.tzinfo is None:
        priority_time = priority_time.replace(tzinfo=timezone.utc)
    if priority_time and datetime.now(timezone.utc) < priority_time:
        return {
            "ran": False,
            "top_goal": None,
            "thought_id": None,
            "thought": None,
            "thought_source": None,
            "amw_action": "root_priority_hold",
            "workspace_released": False,
            "released_workspace": None,
        }

    # If an interactive cycle arrives after the lease expires, restore the
    # interrupted ambient workspace before normal goal arbitration resumes.
    suspended = list(current.get("suspended_workspaces", []) or [])
    if (
        suspended
        and workspace.get("is_active")
        and workspace.get("source_event_type") == "PARTICIPANT_EVENT"
    ):
        prior = suspended.pop()
        concept = str(prior.get("concept_identifier") or "").strip()
        if concept:
            amw.activate_thought(
                concept_identifier=concept,
                description=str(prior.get("description_snapshot") or concept),
                path=path,
            )
            update_self_state({"suspended_workspaces": suspended}, path=path)
            update_self_state({
                "active_mental_workspace_state": {
                    "attention_salience": prior.get("attention_salience", 0.65),
                    "source_event_id": prior.get("source_event_id"),
                    "source_event_type": prior.get("source_event_type"),
                    "resumed_from_root_interrupt": True,
                }
            }, path=path)
            return {
                "ran": True,
                "top_goal": None,
                "thought_id": None,
                "thought": concept,
                "thought_source": "resumed_workspace",
                "amw_action": "restored_suspended_workspace",
                "workspace_released": False,
                "released_workspace": None,
            }

    workspace_released = False
    released_workspace = None

    # A workspace is a focus, not a permanent pin. If it has been refreshed
    # repeatedly without a new development, release it so current goals and
    # newer thoughts can take the lead. The historical record remains intact.
    reflections = workspace.get("internal_reflections", [])
    if workspace.get("is_active") and len(reflections) >= ATTENTION_THRESHOLD:
        released_workspace = workspace.get("concept_identifier")
        amw.deactivate_thought(path=path)
        workspace_released = True
        current = load_self_state(path)

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
            "workspace_released": workspace_released,
            "released_workspace": released_workspace,
        }

    top_goal = ranked[0]
    thought_record = _derive_autonomous_thought(current, ranked)

    if thought_record.get("source") == "persistent_thought":
        # Revisit a persistent thought, but do not let repeated non-progress
        # keep it at the front of cognition forever.
        old_concept = thought_record.get("content", "")
        old_thought_id = thought_record.get("thought_id")
        revisited = thought.revisit_thought(old_thought_id, path=path)
        if revisited and revisited.get("attention_count", 0) >= ATTENTION_THRESHOLD:
            thought.update_thought(
                old_thought_id,
                decision="defer",
                note=f"No development after {revisited['attention_count']} attentions; deferred to rotate focus.",
                path=path,
            )
            current_workspace = load_self_state(path).get("active_mental_workspace_state", {})
            if current_workspace.get("is_active") and current_workspace.get("concept_identifier") == old_concept:
                released_workspace = current_workspace.get("concept_identifier")
                amw.deactivate_thought(path=path)
                workspace_released = True
            current = load_self_state(path)
            thought_record = _derive_autonomous_thought(current, ranked)

    if thought_record.get("source") == "persistent_thought":
        concept = thought_record.get("content", "")
        thought_id = thought_record.get("thought_id")
    else:
        persisted = _persist_autonomous_thought(thought_record, path)
        concept = persisted["content"]
        thought_id = persisted["thought_id"]

    # Reload after lifecycle changes; never refresh a workspace that was just
    # released, and never reactivate the same deferred thought this cycle.
    amw_state = load_self_state(path).get("active_mental_workspace_state", {})

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
        "workspace_released": workspace_released,
        "released_workspace": released_workspace,
    }

