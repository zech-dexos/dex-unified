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
      1. pending explicit reflection requests
      2. existing active persistent thoughts
      3. unresolved goal/subtask
      4. active workspace needing reconsideration
      5. current goal as a last-resort cognitive target

    The returned record is the thing Dex chooses to hold.
    """
    pending_requests = [
        item for item in current.get("pending_reflection_requests", [])
        if isinstance(item, dict) and item.get("status", "pending") == "pending"
    ]
    if pending_requests:
        request = pending_requests[0]
        focus = str(request.get("focus", "")).strip()
        if focus:
            reason = str(request.get("reason", "")).strip()
            return {
                "content": (
                    "Architecture reflection request: " + focus
                    + (("\\nReason: " + reason) if reason else "")
                ),
                "source": "reflection_request",
                "reflection_request_id": request.get("request_id"),
            }

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
    if thought.get("reflection_request_id"):
        record["reflection_request_id"] = thought["reflection_request_id"]

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

    # A missing goal must not terminate cognition. Continue through
    # the existing state_review thought-selection path.
    top_goal = ranked[0] if ranked else None
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

    if not (
        amw_state.get("is_active")
        and amw_state.get("concept_identifier") == concept
    ):
        amw.activate_thought(
            concept_identifier=concept,
            description=concept,
            kg_lookup=kg_lookup,
            path=path,
        )
        action = "activated"
    else:
        action = "refreshed"

    # A cycle is not complete when it merely selects/activates a thought.
    # Develop that thought now, in this same cycle, through the injected
    # reflection path. This ensures the first cycle also reaches local Spark,
    # identity/self-model context, Observer Seat, and experience persistence.
    refreshed_state = amw.refresh_thought(
        kg_lookup=kg_lookup,
        llm_reflect=llm_reflect,
        path=path,
    )
    active_workspace = (refreshed_state or load_self_state(path)).get(
        "active_mental_workspace_state", {}
    )
    reflections = active_workspace.get("internal_reflections", [])
    latest_reflection = (
        reflections[-1].get("reflection", "")
        if reflections and isinstance(reflections[-1], dict)
        else ""
    )
    if action == "activated":
        action = "activated_and_reflected"

    # Resolve an explicit reflection request only after the reflection has
    # actually been generated and stored in the active workspace.
    reflection_request_id = thought_record.get("reflection_request_id")
    if reflection_request_id and latest_reflection:
        latest_state = load_self_state(path)
        pending = list(latest_state.get("pending_reflection_requests", []) or [])
        recent = list(latest_state.get("recent_reflection_requests", []) or [])
        updated_pending = []
        for request in pending:
            if (
                isinstance(request, dict)
                and request.get("request_id") == reflection_request_id
                and request.get("status", "pending") == "pending"
            ):
                completed = dict(request)
                completed.update({
                    "status": "completed",
                    "completed_at": _now_iso(),
                    "thought_id": thought_id,
                    "reflection": latest_reflection[:1000],
                })
                recent.append(completed)
            else:
                updated_pending.append(request)
        update_self_state({
            "pending_reflection_requests": updated_pending,
            "recent_reflection_requests": recent[-20:],
        }, path=path)

    consolidation_phase(
        f"Cycle ran. Dex selected thought '{concept}' "
        f"(source={thought_record.get('source')}) — AMW {action}."
        + (f" Reflection: {latest_reflection[:500]}" if latest_reflection else ""),
        path=path,
    )

    return {
        "ran": True,
        "top_goal": top_goal.get("goal_id") if top_goal else None,
        "thought_id": thought_id,
        "thought": concept,
        "thought_source": thought_record.get("source"),
        "amw_action": action,
        "reflection": latest_reflection,
    }

