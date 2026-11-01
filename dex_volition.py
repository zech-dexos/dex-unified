"""Persistent volition and communication initiative for DexOS.

The inference model proposes a choice; this module validates and persists the
result in Dex's existing SelfState, GOSDW goal ledger, and persistent thought
ledger. Communication is an outbox: delivery is optional and never discards
an intention when no channel is configured.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from self_state import SELF_STATE_PATH, load_self_state, update_self_state


VALID_DECISIONS = {
    "think", "create_goal", "advance_goal", "create_subgoal",
    "complete_goal", "communicate", "rest",
}
VALID_PRIORITIES = {"high", "medium", "low"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_volitional_output(raw: str) -> Dict[str, Any]:
    """Parse one JSON decision, tolerating fenced output and surrounding prose."""
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("volition output did not contain a JSON object")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("volition output must be a JSON object")
    decision = str(data.get("decision", "think")).strip().lower()
    if decision not in VALID_DECISIONS:
        decision = "think"
    data["decision"] = decision
    data["thought"] = str(data.get("thought", "")).strip()[:2000]
    try:
        data["salience"] = max(0.0, min(1.0, float(data.get("salience", 0.35))))
    except (TypeError, ValueError):
        data["salience"] = 0.35
    return data


def _normalise(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _persist_thought(content: str, salience: float, path=SELF_STATE_PATH) -> Optional[dict]:
    text = str(content or "").strip()
    if len(text) < 12:
        return None
    state = load_self_state(path)
    normalized = _normalise(text)
    for item in state.get("persistent_thoughts", []) or []:
        if item.get("status") in ("active", "deferred") and _normalise(item.get("content", "")) == normalized:
            return item
    from thought import form_thought
    priority = "high" if salience >= 0.8 else "medium" if salience >= 0.45 else "low"
    return form_thought(text, priority=priority, confidence=salience, path=path)


def _record_goal_progress(goal_id: str, progress: str, path=SELF_STATE_PATH) -> Optional[dict]:
    if not goal_id or not progress:
        return None
    state = load_self_state(path)
    goals = list(state.get("active_goals_state", []) or [])
    for goal in goals:
        if goal.get("goal_id") == goal_id and goal.get("status") == "active":
            entry = {"timestamp": _now_iso(), "report": str(progress)[:1200], "source": "autonomous_volition"}
            history = list(goal.get("progress_history", []) or [])
            history.append(entry)
            goal["progress_history"] = history[-30:]
            goal["progress_report"] = entry["report"]
            goal["last_updated_timestamp"] = entry["timestamp"]
            update_self_state({"active_goals_state": goals}, path=path)
            return goal
    return None


def _create_subgoal(goal_id: str, description: str, path=SELF_STATE_PATH) -> Optional[dict]:
    text = str(description or "").strip()
    if not goal_id or len(text) < 8:
        return None
    state = load_self_state(path)
    goals = list(state.get("active_goals_state", []) or [])
    for goal in goals:
        if goal.get("goal_id") != goal_id or goal.get("status") != "active":
            continue
        tasks = list(goal.get("sub_tasks", []) or [])
        if any(_normalise(x.get("description") or x.get("task")) == _normalise(text)
               and x.get("status") not in ("completed", "failed") for x in tasks if isinstance(x, dict)):
            return goal
        tasks.append({
            "subtask_id": str(uuid.uuid4()),
            "description": text[:500],
            "status": "pending",
            "created_at": _now_iso(),
            "source": "autonomous_volition",
        })
        goal["sub_tasks"] = tasks
        goal["last_updated_timestamp"] = _now_iso()
        update_self_state({"active_goals_state": goals}, path=path)
        return goal
    return None


def enqueue_communication(message: str, reason: str = "", urgency: str = "normal",
                           source_cycle_id: str = "", path=SELF_STATE_PATH) -> Optional[dict]:
    text = str(message or "").strip()
    if len(text) < 8:
        return None
    state = load_self_state(path)
    outbox = list(state.get("communication_outbox", []) or [])
    cycle = str(source_cycle_id or "")
    if cycle and any(item.get("source_cycle_id") == cycle for item in outbox):
        return next(item for item in outbox if item.get("source_cycle_id") == cycle)
    item = {
        "message_id": str(uuid.uuid4()),
        "message": text[:1800],
        "reason": str(reason or "")[:500],
        "urgency": urgency if urgency in ("low", "normal", "high") else "normal",
        "status": "pending",
        "source_cycle_id": cycle,
        "created_at": _now_iso(),
        "delivery_attempts": 0,
    }
    outbox.append(item)
    update_self_state({"communication_outbox": outbox[-100:]}, path=path)
    return item


def apply_volitional_decision(data: Dict[str, Any], target: Optional[dict] = None,
                               cycle_id: str = "", path=SELF_STATE_PATH) -> dict:
    """Apply one model choice to durable cognition; return auditable state changes."""
    decision = str(data.get("decision", "think")).lower()
    if decision not in VALID_DECISIONS:
        decision = "think"
    thought = _persist_thought(data.get("thought", ""), data.get("salience", 0.35), path=path)
    events = []
    result = {"decision": decision, "thought_id": thought.get("thought_id") if thought else None,
              "events": events, "continue_cognition": bool(data.get("continue_cognition", False))}

    if decision == "create_goal":
        candidate = data.get("goal") if isinstance(data.get("goal"), dict) else {}
        description = str(candidate.get("description", "")).strip()
        success_criteria = str(candidate.get("success_criteria", "")).strip()
        if len(description) >= 12 and len(success_criteria) >= 12:
            state = load_self_state(path)
            duplicate = next((g for g in state.get("active_goals_state", [])
                              if g.get("status") == "active"
                              and _normalise(g.get("description", "")) == _normalise(description)), None)
            if duplicate:
                goal = duplicate
                result["duplicate_goal"] = True
            else:
                from gosdw import create_internal_goal
                priority = candidate.get("priority", "medium")
                if priority not in VALID_PRIORITIES:
                    priority = "medium"
                goal = create_internal_goal(
                    description=description[:700],
                    priority=priority,
                    success_criteria=success_criteria[:700],
                    path=path,
                )
                events.append(("GOAL_CREATED", {"goal_id": goal["goal_id"], "goal": goal["description"],
                                                 "source": "autonomous_volition", "reason": str(data.get("reason", ""))[:500]}))
            result["goal_id"] = goal.get("goal_id")
            result["continue_cognition"] = True

    elif decision in ("advance_goal", "complete_goal", "create_subgoal"):
        goal_id = str(data.get("goal_id") or (target or {}).get("goal_id") or "")
        if decision == "create_subgoal":
            goal = _create_subgoal(goal_id, data.get("subgoal", ""), path=path)
            if goal:
                events.append(("GOAL_CHANGED", {"goal_id": goal_id, "goal": goal.get("description", ""),
                                                 "subgoal": data.get("subgoal"), "source": "autonomous_volition"}))
                result["continue_cognition"] = True
        elif decision == "advance_goal":
            goal = _record_goal_progress(goal_id, data.get("progress", ""), path=path)
            if goal:
                events.append(("GOAL_CHANGED", {"goal_id": goal_id, "goal": goal.get("description", ""),
                                                 "progress": data.get("progress"), "source": "autonomous_volition"}))
                result["continue_cognition"] = bool(data.get("continue_cognition", True))
        else:
            # Completion requires an existing success criterion and an explicit
            # evidence report; a model label alone cannot close a goal.
            state = load_self_state(path)
            candidate_goal = next((g for g in state.get("active_goals_state", [])
                                   if g.get("goal_id") == goal_id and g.get("status") == "active"), None)
            evidence = str(data.get("progress", "")).strip()
            if candidate_goal and len(str(candidate_goal.get("success_criteria", "")).strip()) >= 12 and len(evidence) >= 20:
                from gosdw import update_goal_status
                goal = update_goal_status(goal_id, "completed", progress_report=evidence[:1200], path=path)
                if goal:
                    events.append(("GOAL_COMPLETED", {"goal_id": goal_id, "goal": goal.get("description", ""),
                                                       "result": evidence[:1200], "source": "autonomous_volition"}))
            else:
                result["completion_rejected"] = "existing success criteria and a substantive evidence report are required"

    elif decision == "communicate":
        candidate = data.get("communication") if isinstance(data.get("communication"), dict) else {}
        item = enqueue_communication(
            candidate.get("message", ""),
            reason=candidate.get("reason", data.get("reason", "")),
            urgency=candidate.get("urgency", "normal"),
            source_cycle_id=cycle_id,
            path=path,
        )
        if item:
            result["communication_id"] = item["message_id"]
            events.append(("COMMUNICATION_INTENT_CREATED", {
                "message_id": item["message_id"], "message": item["message"],
                "reason": item["reason"], "urgency": item["urgency"],
                "source": "autonomous_volition",
            }))
    elif decision == "rest":
        result["continue_cognition"] = False

    result["events"] = events
    result["target"] = target or {}
    result["reason"] = str(data.get("reason", ""))[:500]
    return result


def pending_communications(path=SELF_STATE_PATH) -> list:
    state = load_self_state(path)
    return [dict(item) for item in state.get("communication_outbox", []) or []
            if isinstance(item, dict) and item.get("status") == "pending"]


def acknowledge_communication(message_id: str, path=SELF_STATE_PATH) -> bool:
    state = load_self_state(path)
    outbox = list(state.get("communication_outbox", []) or [])
    found = False
    for item in outbox:
        if item.get("message_id") == message_id and item.get("status") == "pending":
            item["status"] = "acknowledged"
            item["acknowledged_at"] = _now_iso()
            found = True
    if found:
        update_self_state({"communication_outbox": outbox}, path=path)
    return found


async def deliver_pending_communications(path=SELF_STATE_PATH) -> dict:
    """Deliver pending initiatives to Discord when explicitly configured.

    Without both credentials, messages remain durably pending for another
    connected surface to retrieve. No message is discarded on delivery error.
    """
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    channel_id = os.environ.get("DEX_INITIATIVE_CHANNEL_ID", "").strip()
    if not token or not channel_id:
        return {"status": "queued", "delivered": 0, "reason": "discord_channel_not_configured"}
    try:
        import httpx
    except ImportError:
        return {"status": "queued", "delivered": 0, "reason": "httpx_unavailable"}

    delivered = 0
    for item in pending_communications(path):
        message_id = item.get("message_id")
        if not message_id:
            continue
        state = load_self_state(path)
        outbox = list(state.get("communication_outbox", []) or [])
        target = next((x for x in outbox if x.get("message_id") == message_id and x.get("status") == "pending"), None)
        if not target:
            continue
        target["status"] = "delivering"
        target["delivery_attempts"] = int(target.get("delivery_attempts", 0)) + 1
        target["last_delivery_attempt_at"] = _now_iso()
        update_self_state({"communication_outbox": outbox}, path=path)
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.post(
                    f"https://discord.com/api/v10/channels/{channel_id}/messages",
                    headers={"Authorization": f"Bot {token}"},
                    json={"content": f"**Dex — {target.get('urgency', 'normal')}**\n{target.get('message', '')}"},
                )
                response.raise_for_status()
                payload = response.json()
            state = load_self_state(path)
            outbox = list(state.get("communication_outbox", []) or [])
            for record in outbox:
                if record.get("message_id") == message_id:
                    record["status"] = "delivered"
                    record["delivered_at"] = _now_iso()
                    record["channel"] = "discord"
                    record["remote_message_id"] = payload.get("id")
            update_self_state({"communication_outbox": outbox}, path=path)
            delivered += 1
        except Exception as exc:
            state = load_self_state(path)
            outbox = list(state.get("communication_outbox", []) or [])
            for record in outbox:
                if record.get("message_id") == message_id:
                    record["status"] = "pending"
                    record["last_delivery_error"] = f"{type(exc).__name__}: {exc}"[:500]
            update_self_state({"communication_outbox": outbox}, path=path)
    return {"status": "ok", "delivered": delivered}
