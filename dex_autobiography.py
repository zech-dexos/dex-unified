from datetime import datetime, timezone
from typing import Dict, Any, List

from dex_events import bus
from self_state import load_self_state, update_self_state


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_type(payload: Dict[str, Any]) -> str:
    return payload.get("event_type", "UNKNOWN")


def _timestamp(payload: Dict[str, Any]) -> str:
    return (
        payload.get("timestamp")
        or payload.get("event_timestamp")
        or _now_iso()
    )


def _first(payload: Dict[str, Any], *keys):
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _describe_event(payload: Dict[str, Any]) -> str:
    event_type = _event_type(payload)

    if event_type == "PARTICIPANT_EVENT":
        user_input = _first(payload, "user_input", "input", "message", "content")
        if user_input:
            return f"Participant interaction occurred: {user_input}"
        return "A participant interaction entered Dex's active system."

    if event_type == "RESPONSE_COMPLETED":
        response = _first(payload, "reply", "dex_response", "response", "assistant_response")
        if response:
            return "Dex completed a response to the participant."
        return "Dex completed a participant response."

    if event_type == "THOUGHT_GENERATED":
        thought = _first(payload, "thought", "content", "description")
        if thought:
            return f"Dex generated a persistent thought: {thought}"
        return "Dex generated a thought."

    if event_type == "GOAL_CREATED":
        goal = _first(payload, "goal", "description", "title")
        if goal:
            return f"A goal entered Dex's persistent goal state: {goal}"
        return "A new persistent goal was created."

    if event_type == "GOAL_CHANGED":
        goal = _first(payload, "goal", "description", "title")
        if goal:
            return f"A persistent goal changed: {goal}"
        return "A persistent goal changed."

    if event_type == "GOAL_COMPLETED":
        goal = _first(payload, "goal", "description", "title")
        if goal:
            return f"A persistent goal was completed: {goal}"
        return "A persistent goal was completed."

    if event_type == "INTENTION_CHANGED":
        intention = _first(payload, "intention", "description")
        if intention:
            return f"Dex's intention changed: {intention}"
        return "Dex's intention changed."

    if event_type == "OPEN_LOOP_CREATED":
        loop = _first(payload, "open_loop", "description", "question")
        if loop:
            return f"An unresolved thread entered Dex's continuing state: {loop}"
        return "An unresolved thread was created."

    if event_type == "ACTION_COMPLETED":
        result = _first(payload, "result", "outcome", "description")
        if result:
            return f"Dex completed an action: {result}"
        return "Dex completed an action."

    if event_type == "WORKSPACE_ACTIVATED":
        return "Dex's active cognitive workspace was activated."

    if event_type == "WORKSPACE_RELEASED":
        return "Dex released the active cognitive workspace."

    if event_type == "SIGNAL_RAISED":
        signal = _first(payload, "signal", "description", "reason")
        if signal:
            return f"An internal signal was raised: {signal}"
        return "An internal signal was raised."

    return f"Dex experienced event: {event_type}"


def _extract_state_changes(payload: Dict[str, Any]) -> List[Any]:
    changes = payload.get("state_changes")

    if isinstance(changes, list):
        return changes
    if changes:
        return [changes]

    result = []
    for key in (
        "goal_change",
        "thought_change",
        "intention_change",
        "workspace_change",
        "self_state_change",
        "open_loop",
    ):
        if key in payload:
            result.append({"type": key, "value": payload[key]})

    return result


def _extract_significance(payload: Dict[str, Any]) -> Any:
    return _first(payload, "significance", "salience", "importance")


async def process_autobiographical_event(payload: Dict[str, Any]):
    """
    Convert meaningful events into autobiographical history.

    Transcript memory answers: What was said?
    Autobiography answers: What happened to Dex? What changed? Why did it matter?
    """

    event_type = _event_type(payload)
    print(f"[Autobiography] Analyzing event for autobiographical significance: {event_type}")

    timestamp = _timestamp(payload)

    entry = {
        "timestamp": timestamp,
        "event_type": event_type,
        "what_happened": _describe_event(payload),
        "intention": _first(payload, "intention", "active_intention"),
        "action": _first(payload, "action", "operation"),
        "result": _first(payload, "result", "outcome"),
        "significance": _extract_significance(payload),
        "state_changes": _extract_state_changes(payload),
        "goal_changes": payload.get("goal_changes", []),
        "open_loops": payload.get("open_loops", []),
        "self_state_changes": payload.get("self_state_changes", []),
        "future_relevance": _first(payload, "future_relevance", "relevance"),
    }

    user_input = _first(payload, "user_input", "input", "message")
    response = _first(payload, "reply", "dex_response", "response", "assistant_response")

    if user_input:
        entry["participant_input"] = user_input
    if response:
        entry["response"] = response
    if payload.get("user_id"):
        entry["user_id"] = payload["user_id"]

    current = load_self_state()
    narrative = list(current.get("narrative_thread", []))
    narrative.append(entry)
    narrative = narrative[-500:]

    update_self_state(
        {
            "narrative_thread": narrative,
            "last_autobiographical_event": entry,
        }
    )

    print(f"[Autobiography] Persistent autobiographical event recorded: {event_type}")


def setup_autobiography():
    for event_type in (
        "RESPONSE_COMPLETED",
        "THOUGHT_GENERATED",
        "GOAL_CREATED",
        "GOAL_CHANGED",
        "GOAL_COMPLETED",
        "INTENTION_CHANGED",
        "OPEN_LOOP_CREATED",
        "OPEN_LOOP_CHANGED",
        "ACTION_COMPLETED",
        "SIGNAL_RAISED",
    ):
        bus.subscribe(event_type, process_autobiographical_event)

    print("[Autobiography] Event listeners registered.")
