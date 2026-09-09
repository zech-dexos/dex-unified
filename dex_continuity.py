from datetime import datetime, timezone
from typing import Dict, Any

from dex_events import bus
from dex_state import shared_state
from self_state import load_self_state, update_self_state


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_timestamp(payload: Dict[str, Any]) -> str:
    return (
        payload.get("timestamp")
        or payload.get("event_timestamp")
        or _now_iso()
    )


def _event_type(payload: Dict[str, Any]) -> str:
    return payload.get("event_type", "UNKNOWN")


def _meaningful_event(payload: Dict[str, Any]) -> bool:
    """
    Determine whether an event represents a change worth carrying
    forward beyond the live shared-state layer.

    Not every heartbeat/update needs to become durable history.
    """
    event_type = _event_type(payload)

    return event_type in {
        "PARTICIPANT_EVENT",
        "RESPONSE_COMPLETED",
        "THOUGHT_GENERATED",
        "GOAL_CREATED",
        "GOAL_CHANGED",
        "GOAL_COMPLETED",
        "GOAL_REMOVED",
        "INTENTION_CHANGED",
        "OPEN_LOOP_CREATED",
        "OPEN_LOOP_CHANGED",
        "SELF_STATE_CHANGED",
        "WORKSPACE_ACTIVATED",
        "WORKSPACE_RELEASED",
        "ACTION_COMPLETED",
        "SIGNAL_RAISED",
        "SALIENCE_CHANGED",
    }


async def process_continuity_event(payload: Dict[str, Any]):
    """
    Integrate an event into Dex's continuously evolving state.

    This is NOT a sequential pipeline stage.

    The event has already entered the shared event fabric. Continuity
    records the fact that the event occurred, updates live state, and
    persists durable state when the event represents a meaningful
    change in Dex's continuing condition.
    """

    event_type = _event_type(payload)
    timestamp = _event_timestamp(payload)

    print(f"[Continuity] Integrating event: {event_type}")

    shared_state.update_state(
        "last_event",
        {
            "event_type": event_type,
            "timestamp": timestamp,
            "payload": dict(payload),
        },
    )

    shared_state.update_state("last_event_type", event_type)
    shared_state.update_state("last_event_timestamp", timestamp)

    if event_type == "RESPONSE_COMPLETED":
        shared_state.update_state("last_response_event", dict(payload))
    elif event_type == "THOUGHT_GENERATED":
        shared_state.update_state("last_thought_event", dict(payload))
    elif event_type == "PARTICIPANT_EVENT":
        shared_state.update_state("last_participant_event", dict(payload))
    elif event_type == "SIGNAL_RAISED":
        shared_state.update_state("last_signal", dict(payload))

    if not _meaningful_event(payload):
        return

    current = load_self_state()
    continuity = list(current.get("continuity_events", []))

    record = {
        "event_type": event_type,
        "timestamp": timestamp,
        "source": payload.get("source", "event_bus"),
        "user_id": payload.get("user_id"),
        "summary": (
            payload.get("summary")
            or payload.get("description")
            or payload.get("thought")
            or payload.get("dex_response")
            or payload.get("user_input")
        ),
    }

    for key in (
        "goal_id",
        "goal",
        "thought_id",
        "thought",
        "intention",
        "result",
        "significance",
        "open_loop",
        "state_changes",
    ):
        if key in payload:
            record[key] = payload[key]

    continuity.append(record)
    continuity = continuity[-100:]

    update_self_state(
        {
            "continuity_events": continuity,
            "last_continuity_event": record,
        }
    )

    print(f"[Continuity] Persistent state updated from {event_type}")


def setup_continuity():
    for event_type in (
        "PARTICIPANT_EVENT",
        "RESPONSE_COMPLETED",
        "THOUGHT_GENERATED",
        "GOAL_CREATED",
        "GOAL_CHANGED",
        "GOAL_COMPLETED",
        "GOAL_REMOVED",
        "INTENTION_CHANGED",
        "OPEN_LOOP_CREATED",
        "OPEN_LOOP_CHANGED",
        "SELF_STATE_CHANGED",
        "WORKSPACE_ACTIVATED",
        "WORKSPACE_RELEASED",
        "ACTION_COMPLETED",
        "SIGNAL_RAISED",
        "SALIENCE_CHANGED",
    ):
        bus.subscribe(event_type, process_continuity_event)

    print("[Continuity] Event listeners registered.")
