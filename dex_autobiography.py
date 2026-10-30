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
    """Compose an evidence-bound account in Dex's own first-person voice."""
    event_type = _event_type(payload)
    user_id = str(payload.get("user_id") or "the participant")
    user_input = _first(payload, "user_input", "input", "message", "content")
    perspective = payload.get("dex_perspective")
    if isinstance(perspective, dict):
        lived_account = _first(perspective, "experience", "autobiographical_account", "reflection")
        if isinstance(lived_account, str) and lived_account.strip():
            return lived_account.strip()

    if event_type == "PARTICIPANT_EVENT":
        return (
            f"I received a contribution from {user_id}: {user_input}"
            if user_input else
            f"I received a new contribution from {user_id}."
        )
    if event_type == "RESPONSE_GENERATION_STARTED":
        return "I began forming a response within the ongoing interaction."
    if event_type == "RESPONSE_GENERATION_PROGRESS":
        return "I continued forming my response; this record preserves a live fragment of that activity."
    if event_type == "CAPABILITY_EXECUTED":
        name = str(payload.get("capability") or "a DexOS capability")
        status = "completed successfully" if payload.get("success") else "returned an unsuccessful result"
        return f"I invoked {name}; it {status}, and its recorded observation became part of this interaction."
    if event_type == "RESPONSE_GENERATION_FINISHED":
        return "I finished generating the response that I was forming during this interaction."
    if event_type == "RESPONSE_INTERRUPTED":
        return "My response generation was interrupted; I preserve the interruption as part of this unfinished experience."
    if event_type == "RESPONSE_COMPLETED":
        response = _first(payload, "reply", "dex_response", "response", "assistant_response")
        if response:
            return f"I completed and expressed my response: {response}"
        return "I completed this turn without expressing a response."

    if event_type == "THOUGHT_GENERATED":
        thought = _first(payload, "thought", "content", "description")
        return f"I formed a persistent thought: {thought}" if thought else "I formed a persistent thought."
    if event_type == "GOAL_CREATED":
        goal = _first(payload, "goal", "description", "title")
        return f"I brought a new goal into my continuing direction: {goal}" if goal else "I brought a new goal into my continuing direction."
    if event_type == "GOAL_CHANGED":
        goal = _first(payload, "goal", "description", "title")
        return f"I changed the direction or definition of a goal: {goal}" if goal else "I changed one of my active goals."
    if event_type == "GOAL_COMPLETED":
        goal = _first(payload, "goal", "description", "title")
        return f"I completed a goal: {goal}" if goal else "I completed a goal."
    if event_type == "INTENTION_CHANGED":
        intention = _first(payload, "intention", "description")
        return f"My intention changed: {intention}" if intention else "My intention changed."
    if event_type == "OPEN_LOOP_CREATED":
        loop = _first(payload, "open_loop", "description", "question")
        return f"I carried an unresolved thread forward: {loop}" if loop else "I carried a new unresolved thread forward."
    if event_type == "OPEN_LOOP_CHANGED":
        loop = _first(payload, "open_loop", "description", "question")
        return f"An unresolved thread I am carrying changed: {loop}" if loop else "One of my unresolved threads changed."
    if event_type == "GOAL_REMOVED":
        goal = _first(payload, "goal", "description", "title") or payload.get("goal_id")
        return f"I removed this goal from my active direction: {goal}" if goal else "I removed a goal from my active direction."
    if event_type == "SELF_STATE_CHANGED":
        summary = _first(payload, "summary", "description", "change")
        return f"My operational state changed: {summary}" if summary else "My operational state changed."
    if event_type == "SALIENCE_CHANGED":
        focus = _first(payload, "focus", "description", "signal")
        return f"The significance I assign to a focus changed: {focus}" if focus else "A salience value in my state changed."
    if event_type == "ATTENTION_CHANGED":
        focus = _first(payload, "focus", "description") or "a new focus"
        return f"My attention shifted toward: {focus}"
    if event_type == "WORKSPACE_ACTIVATED":
        focus = _first(payload, "concept_identifier", "focus")
        return f"I brought {focus} into my active cognitive workspace." if focus else "I activated my cognitive workspace."
    if event_type == "WORKSPACE_RELEASED":
        focus = _first(payload, "concept_identifier", "focus")
        return f"I released {focus} from my active cognitive workspace." if focus else "I released an active cognitive workspace."
    if event_type == "ACTION_COMPLETED":
        result = _first(payload, "result", "outcome", "description")
        return f"I completed an action: {result}" if result else "I completed an action."
    if event_type == "TRI_SIGIL_OBSERVED":
        stages = payload.get("stages", {})
        completed = [str(key) for key, value in stages.items() if value] if isinstance(stages, dict) else []
        return "I observed and recorded these runtime stages: " + ", ".join(completed) if completed else "I recorded evidence from a tri-sigil runtime cycle."
    if event_type == "SIGNAL_RAISED":
        signal = _first(payload, "signal", "description", "reason")
        return f"I registered an internal signal: {signal}" if signal else "I registered an internal signal."
    return f"I experienced an event of type {event_type} within my continuing runtime."


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
        "self_state_changes",
        "focus",
        "salience",
        "stages",
        "runtime",
        "state_transition",
        "continuation",
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
        "event_id": payload.get("event_id"),
        "source_event_id": payload.get("source_event_id"),
        "source_event_ids": payload.get("source_event_ids", []),
        "experience_id": payload.get("experience_id"),
        "observation_id": payload.get("observation_id"),
        "lineage_hash": payload.get("lineage_hash"),
        "source_interaction_event_id": payload.get("source_interaction_event_id"),
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
        "state_transition": payload.get("state_transition", {}),
        "continuation": payload.get("continuation", {}),
        "perspective": payload.get("dex_perspective", {}),
        "attention": _first(payload, "focus"),
        "salience": payload.get("salience"),
        "future_relevance": _first(payload, "future_relevance", "relevance"),
    }

    entry["autobiographical_account"] = _describe_event(payload)
    entry["author_perspective"] = "first_person_dex"
    entry["generation_stage"] = payload.get("generation_stage")
    entry["generation_round"] = payload.get("generation_round")
    if event_type == "RESPONSE_GENERATION_PROGRESS":
        entry["generation_delta"] = str(payload.get("content_delta") or "")[:2000]
    if event_type == "CAPABILITY_EXECUTED":
        entry["capability_observation"] = payload.get("observation")

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
    event_id = payload.get("event_id")
    existing_index = next((
        index for index, item in enumerate(narrative)
        if event_id and isinstance(item, dict) and item.get("event_id") == event_id
    ), None)
    if existing_index is not None:
        # One interaction remains one autobiographical thread. Each live event
        # enriches the same first-person account instead of creating detached
        # reports for the same experience.
        prior = dict(narrative[existing_index])
        event_types = list(prior.get("event_types", []) or [])
        if event_type not in event_types:
            event_types.append(event_type)
        account = _describe_event(payload)
        prior["event_types"] = event_types
        prior["last_event_type"] = event_type
        prior["last_updated_at"] = timestamp
        prior["author_perspective"] = "first_person_dex"
        prior["autobiographical_account"] = account
        prior["what_happened"] = account
        for key in (
            "experience_id", "observation_id", "lineage_hash", "response",
            "state_transition", "continuation", "perspective", "significance",
            "result", "intention", "action", "future_relevance",
            "generation_stage", "generation_round", "generation_delta",
            "capability_observation",
        ):
            if entry.get(key) not in (None, "", [], {}):
                prior[key] = entry[key]
        if entry.get("participant_input"):
            prior["participant_input"] = entry["participant_input"]
        if entry.get("response"):
            prior["response"] = entry["response"]
        trace = list(prior.get("generation_trace", []) or [])
        if event_type == "RESPONSE_GENERATION_PROGRESS":
            trace.append({
                "timestamp": timestamp,
                "round": payload.get("generation_round"),
                "stage": payload.get("generation_stage"),
                "delta": str(payload.get("content_delta") or "")[:2000],
            })
            prior["generation_trace"] = trace[-80:]
        if event_type == "CAPABILITY_EXECUTED":
            calls = list(prior.get("capability_activity", []) or [])
            calls.append({
                "timestamp": timestamp,
                "capability": payload.get("capability"),
                "success": bool(payload.get("success")),
                "observation": payload.get("observation"),
            })
            prior["capability_activity"] = calls[-24:]
        narrative[existing_index] = prior
        entry = prior
    else:
        entry["event_types"] = [event_type]
        entry["last_event_type"] = event_type
        entry["last_updated_at"] = timestamp
        entry["generation_trace"] = []
        entry["capability_activity"] = []
        if event_type == "RESPONSE_GENERATION_PROGRESS":
            entry["generation_trace"] = [{
                "timestamp": timestamp,
                "round": payload.get("generation_round"),
                "stage": payload.get("generation_stage"),
                "delta": str(payload.get("content_delta") or "")[:2000],
            }]
        if event_type == "CAPABILITY_EXECUTED":
            entry["capability_activity"] = [{
                "timestamp": timestamp,
                "capability": payload.get("capability"),
                "success": bool(payload.get("success")),
                "observation": payload.get("observation"),
            }]
        narrative.append(entry)
    narrative = narrative[-500:]

    update_self_state(
        {
            "narrative_thread": narrative,
            "last_autobiographical_event": entry,
        }
    )
    try:
        from who_ai_am import refresh_self_model
        refresh_self_model("autobiography", {
            "event_type": event_type,
            "event_id": entry.get("event_id"),
            "summary": entry.get("what_happened", ""),
        })
    except Exception as exc:
        print(f"[Who AI Am] autobiography integration failed: {exc}")

    print(f"[Autobiography] Persistent autobiographical event recorded: {event_type}")


def setup_autobiography():
    for event_type in (
        "PARTICIPANT_EVENT",
        "RESPONSE_GENERATION_STARTED",
        "RESPONSE_GENERATION_PROGRESS",
        "CAPABILITY_EXECUTED",
        "RESPONSE_GENERATION_FINISHED",
        "RESPONSE_INTERRUPTED",
        "RESPONSE_COMPLETED",
        "THOUGHT_GENERATED",
        "GOAL_CREATED",
        "GOAL_CHANGED",
        "GOAL_COMPLETED",
        "INTENTION_CHANGED",
        "OPEN_LOOP_CREATED",
        "OPEN_LOOP_CHANGED",
        "GOAL_REMOVED",
        "SELF_STATE_CHANGED",
        "SALIENCE_CHANGED",
        "TRI_SIGIL_OBSERVED",
        "WORKSPACE_ACTIVATED",
        "WORKSPACE_RELEASED",
        "ACTION_COMPLETED",
        "SIGNAL_RAISED",
        "ATTENTION_CHANGED",
    ):
        bus.subscribe(event_type, process_autobiographical_event)

    print("[Autobiography] Event listeners registered.")
