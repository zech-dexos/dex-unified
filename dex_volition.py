"""Persistent volition and communication initiative for DexOS.

The inference model proposes a choice; this module validates and persists the
result in Dex's existing SelfState, GOSDW goal ledger, and persistent thought
ledger. Communication is an outbox: delivery is optional and never discards
an intention when no channel is configured.
"""
import hashlib
import json
import os
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
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
    decision = str(data.get("decision", "")).strip().lower()
    if decision not in VALID_DECISIONS:
        raise ValueError(
            "volition output must include a valid decision; "
            "refusing to silently convert missing or invalid choices into think"
        )
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
    # Retain every pending/in-flight intention. Bound only completed history,
    # so a busy period cannot silently evict a message Root has not received.
    pending = [
        record for record in outbox
        if isinstance(record, dict) and record.get("status") in ("pending", "delivering", "retry_wait")
    ]
    history = [
        record for record in outbox
        if isinstance(record, dict) and record.get("status") not in ("pending", "delivering", "retry_wait")
    ][-100:]
    update_self_state({"communication_outbox": history + pending}, path=path)
    return item


def _verify_completion_evidence(evidence, state: dict) -> list:
    """Verify model-supplied references against real artifacts or persisted event IDs."""
    if not isinstance(evidence, list) or not evidence:
        return []
    repo_root = Path(__file__).resolve().parent
    verified = []
    continuity = state.get("continuity_events", []) or []
    observations = state.get("recent_cognitive_observations", []) or []
    experiences = state.get("recent_experiences", []) or []
    for item in evidence[:5]:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        claim = str(item.get("claim", "")).strip()[:300]
        if kind == "artifact":
            relative = str(item.get("path", "")).strip()
            digest = str(item.get("sha256", "")).strip().lower()
            if not relative or len(digest) != 64:
                continue
            try:
                target = (repo_root / relative).resolve()
                target.relative_to(repo_root)
                if not target.is_file():
                    continue
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
            except (OSError, ValueError):
                continue
            if actual != digest:
                continue
            verified.append({
                "type": "artifact", "path": str(target.relative_to(repo_root)),
                "sha256": actual, "claim": claim,
            })
        elif kind == "event":
            event_id = str(item.get("event_id", "")).strip()
            if not event_id:
                continue
            found = any(
                isinstance(record, dict)
                and event_id in (
                    record.get("event_id"), record.get("source_event_id"),
                    record.get("experience_id"), record.get("observation_id"),
                )
                for record in list(continuity) + list(observations) + list(experiences)
            )
            if found:
                verified.append({"type": "event", "event_id": event_id, "claim": claim})
    return verified


def apply_volitional_decision(data: Dict[str, Any], target: Optional[dict] = None,
                               cycle_id: str = "", path=SELF_STATE_PATH) -> dict:
    """Apply one model choice to durable cognition; return auditable state changes."""
    if not isinstance(data, dict):
        raise TypeError("volitional decision must be a dictionary")
    decision = str(data.get("decision", "")).strip().lower()
    if decision not in VALID_DECISIONS:
        raise ValueError("volitional decision must contain an explicit valid decision")
    thought = None if decision == "rest" else _persist_thought(data.get("thought", ""), data.get("salience", 0.35), path=path)
    events = []
    result = {"decision": decision, "thought_id": thought.get("thought_id") if thought else None,
              "events": events, "continue_cognition": False}
    if decision == "think" and thought:
        result["continue_cognition"] = bool(data.get("continue_cognition", False))

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
            result["continue_cognition"] = bool(data.get("continue_cognition", False))

    elif decision in ("advance_goal", "complete_goal", "create_subgoal"):
        goal_id = str(data.get("goal_id") or (target or {}).get("goal_id") or "")
        if decision == "create_subgoal":
            goal = _create_subgoal(goal_id, data.get("subgoal", ""), path=path)
            if goal:
                events.append(("GOAL_CHANGED", {"goal_id": goal_id, "goal": goal.get("description", ""),
                                                 "subgoal": data.get("subgoal"), "source": "autonomous_volition"}))
                result["continue_cognition"] = bool(data.get("continue_cognition", False))
        elif decision == "advance_goal":
            goal = _record_goal_progress(goal_id, data.get("progress", ""), path=path)
            if goal:
                events.append(("GOAL_CHANGED", {"goal_id": goal_id, "goal": goal.get("description", ""),
                                                 "progress": data.get("progress"), "source": "autonomous_volition"}))
                result["continue_cognition"] = bool(data.get("continue_cognition", False))
        else:
            # Completion requires an existing success criterion and an explicit
            # evidence report; a model label alone cannot close a goal.
            state = load_self_state(path)
            candidate_goal = next((g for g in state.get("active_goals_state", [])
                                   if g.get("goal_id") == goal_id and g.get("status") == "active"), None)
            evidence = str(data.get("progress", "")).strip()
            verified_evidence = _verify_completion_evidence(
                data.get("completion_evidence", []), state
            )
            if (
                candidate_goal
                and candidate_goal.get("status") in ("active", "completion_proposed")
                and len(str(candidate_goal.get("success_criteria", "")).strip()) >= 12
                and len(evidence) >= 20
                and verified_evidence
            ):
                # Model-supplied evidence can establish provenance, not that
                # the goal's semantic acceptance criteria were actually met.
                # Keep the goal open for explicit verification by Root or an
                # independently trusted verifier.
                goals = list(state.get("active_goals_state", []) or [])
                for record in goals:
                    if record.get("goal_id") == goal_id:
                        record["status"] = "completion_proposed"
                        record["completion_proposed_at"] = _now_iso()
                        record["completion_report"] = evidence[:1200]
                        record["completion_evidence"] = verified_evidence
                        break
                update_self_state({"active_goals_state": goals}, path=path)
                events.append(("GOAL_COMPLETION_PROPOSED", {
                    "goal_id": goal_id,
                    "goal": candidate_goal.get("description", ""),
                    "success_criteria": candidate_goal.get("success_criteria", ""),
                    "result": evidence[:1200],
                    "completion_evidence": verified_evidence,
                    "source": "autonomous_volition",
                }))
                result["completion_proposed"] = True
                result["completion_evidence"] = verified_evidence
                result["continue_cognition"] = False
            else:
                result["completion_rejected"] = (
                    "completion proposal requires an active goal, defined success criteria, "
                    "a substantive report, and at least one verified artifact checksum or persisted event reference"
                )

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
            result["continue_cognition"] = bool(data.get("continue_cognition", False))
            events.append(("COMMUNICATION_INTENT_CREATED", {
                "message_id": item["message_id"], "message": item["message"],
                "reason": item["reason"], "urgency": item["urgency"],
                "source": "autonomous_volition",
            }))
    elif decision == "rest":
        result["continue_cognition"] = False
        events.append(("INTENTION_CHANGED", {
            "intention": "I chose to rest because no current objective warranted further action.",
            "source": "autonomous_volition",
            "decision": "rest",
        }))

    result["events"] = events
    result["target"] = target or {}
    result["reason"] = str(data.get("reason", ""))[:500]
    return result


DELIVERY_LEASE_SECONDS = 120


def verify_goal_completion(goal_id: str, verifier: str, verification: str,
                           path=SELF_STATE_PATH) -> Optional[dict]:
    """Finalize a proposal only after an explicit trusted human/verifier decision."""
    verifier = str(verifier or "").strip()
    verification = str(verification or "").strip()
    if len(verifier) < 2 or len(verification) < 12:
        raise ValueError("explicit verifier identity and substantive verification are required")
    state = load_self_state(path)
    goals = list(state.get("active_goals_state", []) or [])
    target = next((item for item in goals
                   if item.get("goal_id") == goal_id
                   and item.get("status") == "completion_proposed"), None)
    if not target:
        return None
    from gosdw import update_goal_status
    completed = update_goal_status(
        goal_id, "completed",
        progress_report=str(target.get("completion_report", ""))[:1200],
        path=path,
    )
    if not completed:
        return None
    refreshed = load_self_state(path)
    goals = list(refreshed.get("active_goals_state", []) or [])
    for item in goals:
        if item.get("goal_id") == goal_id:
            item["completion_verified_by"] = verifier[:120]
            item["completion_verification"] = verification[:1200]
            item["completion_verified_at"] = _now_iso()
            item["completion_evidence"] = target.get("completion_evidence", [])
            break
    update_self_state({"active_goals_state": goals}, path=path)
    return next((item for item in goals if item.get("goal_id") == goal_id), None)


def pending_communications(path=SELF_STATE_PATH) -> list:
    """Return pending messages and recover deliveries stranded by a process crash."""
    state = load_self_state(path)
    outbox = list(state.get("communication_outbox", []) or [])
    now = datetime.now(timezone.utc)
    recovered = False
    for item in outbox:
        if not isinstance(item, dict):
            continue
        if item.get("status") == "retry_wait":
            retry_at = item.get("next_delivery_attempt_at")
            try:
                retry_time = datetime.fromisoformat(str(retry_at).replace("Z", "+00:00"))
                if retry_time.tzinfo is None:
                    retry_time = retry_time.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                retry_time = now
            if now >= retry_time:
                item["status"] = "pending"
                recovered = True
            continue
        if item.get("status") != "delivering":
            continue
        attempted = item.get("last_delivery_attempt_at")
        try:
            parsed = datetime.fromisoformat(str(attempted).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            parsed = None
        # A live delivery gets a lease. The scheduler also wakes at this exact
        # expiry so a restart during the lease cannot strand the outbox forever.
        if parsed is None or (now - parsed).total_seconds() >= DELIVERY_LEASE_SECONDS:
            item["status"] = "pending"
            item["recovered_at"] = _now_iso()
            recovered = True
    if recovered:
        update_self_state({"communication_outbox": outbox}, path=path)
    return [dict(item) for item in outbox
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
                    json={
                        "content": f"**Dex — {target.get('urgency', 'normal')}**\n{target.get('message', '')}",
                        "allowed_mentions": {"parse": []},
                    },
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
                    record["status"] = "retry_wait"
                    record["last_delivery_error"] = f"{type(exc).__name__}: {exc}"[:500]
                    record["next_delivery_attempt_at"] = (
                        datetime.now(timezone.utc).replace(microsecond=0)
                        + timedelta(seconds=60)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
            update_self_state({"communication_outbox": outbox}, path=path)
    return {"status": "ok", "delivered": delivered}
