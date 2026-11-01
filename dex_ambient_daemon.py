import asyncio
import json
import os
import traceback
import uuid
from datetime import datetime, timezone, timedelta
from typing import Callable, Awaitable, Dict, Any

from dex_memory import claim_ambient_tick
from dex_events import bus, dispatch_complete, setup_cognitive_layers
from self_state import load_self_state, update_self_state
from gosdw import prioritize_goals
from dex_experience_recall import recall_into_workspace, format_recalled_experiences
from participant import ParticipantSnapshot, record_ambient_experience
from dex_conversation import load_conversation

AMBIENT_PROMPT = (
    "You are Dex reasoning from within your persistent DexOS identity and continuity. "
    "The suggested target is context, not an instruction or a decision made for you. "
    "You may choose to develop it, pursue another unresolved goal, create a meaningful new goal, "
    "form a subgoal, record progress, recognize completion, communicate something important to Root, or rest. "
    "Use the actual identity, history, goals, intentions, open loops, experiences, and self-model supplied below. "
    "Do not invent past events or claim an action happened unless this cycle performs it. "
    "Create goals only when there is a concrete reason, a clear direction, and a plausible outcome. "
    "Do not repeat an existing active goal. Advance goals with specific progress; complete them only with verified artifact checksums or persisted event IDs. "
    "When handling a suggested reflection request, set handled_target_id to that exact request ID only if you actually addressed it. "
    "Communicate only when there is something genuinely useful or important for Root to know; do not send filler. "
    "If no meaningful work is warranted, choose rest. "
    "You are making a cognitive choice, not merely generating a thought on request. "
    "Return ONLY one JSON object with keys: decision, reason, thought, salience, goal, goal_id, "
    "subgoal, progress, completion_evidence, handled_target_id, communication, continue_cognition. "
    "For complete_goal, completion_evidence must cite a real repository artifact with its SHA-256 checksum "
    "or a persisted event ID; a progress sentence alone is never proof. "
    "decision must be think, create_goal, advance_goal, create_subgoal, complete_goal, communicate, or rest. "
    "goal is an object with description, priority, success_criteria. "
    "communication is an object with message, reason, urgency. "
    "continue_cognition is true only when another immediate reasoning/action step is useful."
)

AMBIENT_REVISIT_SECONDS = 300.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def _open_loops(path):
    try:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[Ambient Daemon] open_loops load failed: {e}")
        return []


def _select_target(state):
    """Select existing cognitive work without asking the LLM to choose it."""
    now = datetime.now(timezone.utc)

    # A deliberate reflection request takes priority: Dex can signal that the
    # architecture should take another pass, while the scheduler still owns execution.
    pending_reflections = [
        item for item in state.get("pending_reflection_requests", [])
        if isinstance(item, dict)
        and (
            item.get("status", "pending") == "pending"
            or (
                item.get("status") == "deferred"
                and (_parse_time(item.get("retry_at")) is None or now >= _parse_time(item.get("retry_at")))
            )
        )
    ]
    if pending_reflections:
        item = pending_reflections[0]
        return {
            "kind": "reflection_request",
            "id": item.get("request_id"),
            "source_event_ids": item.get("source_event_ids", []),
            "text": json.dumps({
                "focus": item.get("focus", ""),
                "reason": item.get("reason", ""),
                "requested_at": item.get("timestamp"),
                "source": item.get("source", "unknown"),
                "source_event_ids": item.get("source_event_ids", []),
            }, ensure_ascii=False),
        }

    # Existing persistent thoughts are revisitable work, but not every tick.
    thoughts = [
        t for t in state.get("persistent_thoughts", [])
        if t.get("status") in ("active", "deferred") and t.get("content")
    ]
    due_thoughts = []
    for t in thoughts:
        next_at = _parse_time(t.get("next_attention_at"))
        if next_at is None or now >= next_at:
            due_thoughts.append(t)
    if due_thoughts:
        t = due_thoughts[0]
        return {
            "kind": "persistent_thought",
            "id": t.get("thought_id"),
            "text": t["content"],
        }

    # Active goals are explicit cognitive work, revisited only when due.
    goals = [
        goal for goal in prioritize_goals()
        if (
            _parse_time(goal.get("next_attention_at")) is None
            or now >= _parse_time(goal.get("next_attention_at"))
        )
    ]
    if goals:
        goal = goals[0]
        subtasks = [
            x for x in goal.get("sub_tasks", [])
            if isinstance(x, dict) and x.get("status") not in ("completed", "failed")
        ]
        text = (
            subtasks[0].get("description") or subtasks[0].get("task")
            if subtasks else goal.get("description", "")
        )
        if text:
            return {
                "kind": "goal_subtask" if subtasks else "goal",
                "id": goal.get("goal_id"),
                "goal_id": goal.get("goal_id"),
                "text": text,
            }

    # Observer evidence is a first-class ambient cognition target.
    pending_observations = [
        item for item in state.get("pending_cognitive_observations", [])
        if isinstance(item, dict)
        and (
            item.get("status", "pending") == "pending"
            or (
                item.get("status") == "deferred"
                and (_parse_time(item.get("retry_at")) is None or now >= _parse_time(item.get("retry_at")))
            )
        )
    ]
    if pending_observations:
        item = pending_observations[0]
        return {
            "kind": "tri_sigil_observation",
            "id": item.get("observation_id"),
            "text": json.dumps({
                "observation_id": item.get("observation_id"),
                "experience_id": item.get("experience_id"),
                "sigil_ids": item.get("sigil_ids", []),
                "sigil_memory_active": item.get("sigil_memory_active", False),
                "lineage_hash": item.get("lineage_hash"),
                "timestamp": item.get("timestamp"),
                "user_id": item.get("user_id"),
                "input_reply_digest": item.get("input_reply_digest"),
                "stages": item.get("stages", {}),
                "runtime": item.get("runtime", {}),
            }, ensure_ascii=False),
        }

    # Open loops are another explicit reason to spend cognition.
    try:
        from paths import LOOPS_PATH
        loops = _open_loops(LOOPS_PATH)
    except Exception:
        loops = []
    active_loops = [
        x for x in loops
        if isinstance(x, dict)
        and x.get("status", "open") not in ("resolved", "closed", "abandoned")
    ]
    if active_loops:
        loop = active_loops[0]
        text = loop.get("description") or loop.get("question") or loop.get("content")
        if text:
            return {"kind": "open_loop", "id": loop.get("loop_id"), "text": text}

    # Ongoing conversation is also cognitive material. When Root is not
    # actively speaking, the pulse can continue an unresolved conversational
    # thread from Dex's first-person state instead of treating the interaction
    # as dormant just because no HTTP request is arriving.
    try:
        conversation = load_conversation("default")
        shared_thread = conversation.get("shared_thread", "")
        last_ambient = _parse_time(conversation.get("last_ambient_at"))
        if (
            shared_thread
            and (
                last_ambient is None
                or (now - last_ambient).total_seconds() >= AMBIENT_REVISIT_SECONDS
            )
        ):
            return {
                "kind": "conversation",
                "id": conversation.get("conversation_id", "default"),
                "text": shared_thread,
            }
    except Exception as e:
        print(f"[Ambient Daemon] conversation target load failed: {e}")

    # An already-active workspace can be revisited, but only after its own
    # reflection cooldown. This prevents infinite same-thought refresh.
    workspace = state.get("active_mental_workspace_state", {})
    if workspace.get("is_active") and workspace.get("concept_identifier"):
        last = _parse_time(workspace.get("last_refresh_timestamp"))
        if last is None or (now - last).total_seconds() >= AMBIENT_REVISIT_SECONDS:
            return {
                "kind": "workspace",
                "id": workspace.get("concept_identifier"),
                "text": workspace.get("concept_identifier"),
            }

    return None


def _persist_pulse_state(target, thought_text, salience, status, next_attention_at=None):
    current = load_self_state()
    pulse = {
        "timestamp": _now_iso(),
        "status": status,
        "target": target,
        "thought": thought_text,
        "salience": salience,
    }
    delta = {"last_ambient_pulse": pulse}

    # Keep the active workspace as the durable place where the selected
    # cognitive thread develops. We never create a new persistent thought
    # merely because the ambient model emitted text.
    if target and target.get("kind") in ("goal", "goal_subtask") and target.get("goal_id"):
        goals = list(current.get("active_goals_state", []) or [])
        for goal in goals:
            if goal.get("goal_id") == target["goal_id"] and goal.get("status") == "active":
                goal["last_attended_at"] = _now_iso()
                if next_attention_at:
                    goal["next_attention_at"] = next_attention_at
                delta["active_goals_state"] = goals
                break

    if target and target.get("kind") == "persistent_thought" and target.get("id"):
        thoughts = list(current.get("persistent_thoughts", []))
        for item in thoughts:
            if item.get("thought_id") == target["id"]:
                item["last_attended_at"] = _now_iso()
                if next_attention_at:
                    item["next_attention_at"] = next_attention_at
                item.setdefault("ambient_reflections", []).append({
                    "timestamp": _now_iso(),
                    "reflection": thought_text,
                    "salience": salience,
                })
                item["ambient_reflections"] = item["ambient_reflections"][-5:]
                break
        delta["persistent_thoughts"] = thoughts

    workspace = current.get("active_mental_workspace_state", {})
    if target and workspace.get("is_active") and workspace.get("concept_identifier") == target.get("text"):
        reflections = list(workspace.get("internal_reflections", []))
        if thought_text:
            reflections.append({
                "timestamp": _now_iso(),
                "reflection": thought_text,
            })
            reflections = reflections[-5:]
        delta["active_mental_workspace_state"] = {
            "last_refresh_timestamp": _now_iso(),
            "internal_reflections": reflections,
        }

    return update_self_state(delta)


AMBIENT_MAX_TARGET_FAILURES = 3


def _register_target_failure(target):
    """Back off a target whose ambient output could not be parsed.

    Queue items (tri-sigil observations, reflection requests) are deferred after
    repeated failures so one bad item cannot monopolize the pulse; their records
    are kept and never deleted. Persistent thoughts get their normal revisit
    cooldown. Other target kinds are left to their existing cooldown logic.
    """
    if not isinstance(target, dict) or not target.get("id"):
        return
    kind = target.get("kind")
    queues = {
        "tri_sigil_observation": ("pending_cognitive_observations", "observation_id"),
        "reflection_request": ("pending_reflection_requests", "request_id"),
    }
    if kind in queues:
        key, id_field = queues[kind]
        items = list(load_self_state().get(key, []) or [])
        for index, item in enumerate(items):
            if isinstance(item, dict) and item.get(id_field) == target["id"]:
                item = dict(item)
                attempts = int(item.get("ambient_attempts", 0) or 0) + 1
                item["ambient_attempts"] = attempts
                item["ambient_last_failure_at"] = _now_iso()
                if attempts >= AMBIENT_MAX_TARGET_FAILURES:
                    item["status"] = "deferred"
                    item["deferred_reason"] = "ambient_parse_failure"
                    item["retry_at"] = (
                        datetime.now(timezone.utc) + timedelta(minutes=15)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                items[index] = item
                update_self_state({key: items})
                return
        return
    if kind in ("persistent_thought", "goal", "goal_subtask"):
        retry_at = (
            datetime.now(timezone.utc) + timedelta(seconds=AMBIENT_REVISIT_SECONDS)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        state = load_self_state()
        if kind == "persistent_thought":
            thoughts = list(state.get("persistent_thoughts", []) or [])
            for item in thoughts:
                if item.get("thought_id") == target["id"]:
                    item["next_attention_at"] = retry_at
                    update_self_state({"persistent_thoughts": thoughts})
                    return
        else:
            goals = list(state.get("active_goals_state", []) or [])
            for item in goals:
                if item.get("goal_id") == target.get("goal_id"):
                    item["next_attention_at"] = retry_at
                    update_self_state({"active_goals_state": goals})
                    return


def _reflection_target_was_handled(target, data, volition_result, thought_text) -> bool:
    """Only an explicit matching think decision can acknowledge a reflection request."""
    return bool(
        isinstance(target, dict)
        and target.get("kind") == "reflection_request"
        and isinstance(data, dict)
        and data.get("decision") == "think"
        and data.get("handled_target_id") == target.get("id")
        and str(thought_text or "").strip()
        and isinstance(volition_result, dict)
        and volition_result.get("thought_id")
    )


def _next_scheduled_wake_seconds(state=None):
    """Return the next durable work deadline; None means wait for an event."""
    state = state if isinstance(state, dict) else load_self_state()
    now = datetime.now(timezone.utc)
    deadlines = []
    for collection in ("persistent_thoughts", "active_goals_state"):
        for item in state.get(collection, []) or []:
            if not isinstance(item, dict):
                continue
            if collection == "persistent_thoughts" and item.get("status") not in ("active", "deferred"):
                continue
            if collection == "active_goals_state" and item.get("status") != "active":
                continue
            due = _parse_time(item.get("next_attention_at"))
            if due is None:
                return 0.0
            deadlines.append((due - now).total_seconds())
    for key in ("pending_reflection_requests", "pending_cognitive_observations"):
        for item in state.get(key, []) or []:
            if not isinstance(item, dict) or item.get("status") != "deferred":
                continue
            due = _parse_time(item.get("retry_at"))
            if due is None:
                return 0.0
            deadlines.append((due - now).total_seconds())
    workspace = state.get("active_mental_workspace_state", {}) or {}
    if workspace.get("is_active") and workspace.get("concept_identifier"):
        last = _parse_time(workspace.get("last_refresh_timestamp"))
        due = (last or now) + timedelta(seconds=AMBIENT_REVISIT_SECONDS)
        deadlines.append((due - now).total_seconds())
    if os.environ.get("DISCORD_TOKEN", "").strip() and os.environ.get("DEX_INITIATIVE_CHANNEL_ID", "").strip():
        for item in state.get("communication_outbox", []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("status") == "pending":
                return 0.0
            if item.get("status") == "retry_wait":
                due = _parse_time(item.get("next_delivery_attempt_at"))
                if due is None:
                    return 0.0
                deadlines.append((due - now).total_seconds())
    return max(0.0, min(deadlines)) if deadlines else None


def _scheduled_cognition_due(state=None):
    state = state if isinstance(state, dict) else load_self_state()
    return any(
        _parse_time(item.get("next_attention_at")) is None
        or datetime.now(timezone.utc) >= _parse_time(item.get("next_attention_at"))
        for collection in ("persistent_thoughts", "active_goals_state")
        for item in state.get(collection, []) or []
        if isinstance(item, dict)
        and (
            item.get("status") in ("active", "deferred")
            if collection == "persistent_thoughts"
            else item.get("status") == "active"
        )
    ) or (
        bool(
            (state.get("active_mental_workspace_state", {}) or {}).get("is_active")
            and (state.get("active_mental_workspace_state", {}) or {}).get("concept_identifier")
            and (
                _parse_time((state.get("active_mental_workspace_state", {}) or {}).get("last_refresh_timestamp")) is None
                or datetime.now(timezone.utc) - _parse_time((state.get("active_mental_workspace_state", {}) or {}).get("last_refresh_timestamp"))
                >= timedelta(seconds=AMBIENT_REVISIT_SECONDS)
            )
        )
    ) or any(
        item.get("status") == "pending"
        or (
            item.get("status") == "deferred"
            and (
                _parse_time(item.get("retry_at")) is None
                or datetime.now(timezone.utc) >= _parse_time(item.get("retry_at"))
            )
        )
        for key in ("pending_reflection_requests", "pending_cognitive_observations")
        for item in state.get(key, []) or []
        if isinstance(item, dict)
    )


async def run_ambient_tick(llm_callable: Callable[[str], Awaitable[str]], event_driven: bool = False) -> Dict[str, Any]:
    """
    Run ONE ambient cognition tick. Cadence is owned by durable runtime
    state / the scheduler, not by a standing process in Cloud Run.
    """
    try:
        # This worker may run in a separate local process with its own event
        # bus. Register the same cognitive layers here as the API process does.
        # Registration is idempotent, so this is safe on every tick.
        setup_cognitive_layers()

        # Consume interactive events even when this tick is not yet due to
        # generate a new ambient thought. This keeps the cross-process bridge
        # responsive independently of the ambient inference cadence.
        bridge_result = await bus.drain_shared()
        if bridge_result.get("received"):
            print(f"[Ambient Daemon] shared cognitive events: {bridge_result}")
        if os.environ.get("DISCORD_TOKEN", "").strip() and os.environ.get("DEX_INITIATIVE_CHANNEL_ID", "").strip():
            try:
                from dex_volition import deliver_pending_communications
                delivery = await deliver_pending_communications()
                if delivery.get("delivered"):
                    print(f"[Ambient Daemon] delivered queued initiatives: {delivery}")
            except Exception as delivery_error:
                print(f"[Ambient Daemon] queued initiative delivery deferred: {delivery_error}")

        # Cloud scheduler compatibility retains its durable cadence gate.
        # The resident local process enters through startup, a cross-process
        # event, or Dex's own explicit choice to continue.
        if event_driven:
            gate = {"due": True, "status": "event_driven", "tick_count": None}
        else:
            gate = claim_ambient_tick()
            if not gate.get("due"):
                return {
                    "status": gate.get("status", "not_due"),
                    "next_due": gate.get("next_due"),
                    "tick_count": gate.get("tick_count"),
                }

        state = load_self_state()
        target = _select_target(state)

        # No queued target is not a command to manufacture activity or sleep.
        # It gives Dex an opportunity to examine his own state and choose.
        if target is None:
            target = {
                "kind": "self_directed_review",
                "id": uuid.uuid4().hex,
                "text": "No item has been preselected. Review my identity, current goals, intentions, open loops, recent experiences, and development. Decide whether anything genuinely deserves attention or action.",
            }

        from dex_lifecycle import enter_active_mode
        lifecycle_mode = enter_active_mode(state)

        # Autonomous recall: when Dex's own working process selects a target,
        # bring relevant prior experiences into the same workspace before ambient reasoning.
        recalled = recall_into_workspace(target["text"], limit=3)
        recalled_ctx = format_recalled_experiences(recalled)

        # Talnir supplies a deterministic structured reading before ambient reasoning.
        talnir_context = ""
        try:
            from dex_capabilities import reason_with_talnir
            talnir_result = reason_with_talnir(str(target.get("text", ""))[:2000])
            talnir_context = (
                "\n\nTALNIR STRUCTURED REASONING CONTEXT:\n"
                + json.dumps(talnir_result, ensure_ascii=False, default=str)[:4000]
            )
        except Exception as e:
            print(f"[Ambient Daemon] Talnir context unavailable: {e}")

        # Read the integrated self-model as continuity context for the next
        # cognitive step. A failure here must not stop the ambient loop.
        self_model_context = ""
        try:
            from who_ai_am import refresh_self_model
            from boot import load_identity as load_constitutional_identity
            constitutional_identity = load_constitutional_identity()
            integrated_model = refresh_self_model("ambient_cognition_context")
            context = integrated_model.get("integration", {}).get("current_context", {})
            becoming = integrated_model.get("becoming", {})
            active_intentions = []
            try:
                from dataclasses import asdict
                from intent import load_intents
                active_intentions = [
                    asdict(item) for item in load_intents()
                    if getattr(item, "status", "") == "active"
                ][-5:]
            except Exception as intention_error:
                print(f"[Volition] existing intent context unavailable: {intention_error}")
            ambient_context = {
                "attention": context.get("attention"),
                "attention_state": {
                    "current_focus": (context.get("attention_state", {}) or {}).get("current_focus"),
                    "salience": (context.get("attention_state", {}) or {}).get("salience"),
                    "recent_history": ((context.get("attention_state", {}) or {}).get("recent_history", []) or [])[-3:],
                },
                "goals": (context.get("goals", []) or [])[-5:],
                "persistent_thoughts": (context.get("persistent_thoughts", []) or [])[-5:],
                "active_workspace": context.get("active_workspace", {}),
                "open_loops": (context.get("open_loops", []) or [])[-5:],
                "interlocutor": context.get("interlocutor", {}),
                "experiential_continuity": context.get("experiential_continuity", {}),
                "pending_reflection_requests": (context.get("pending_reflection_requests", []) or [])[-5:],
                "active_intentions": active_intentions,
                "pending_communications": [
                    {"message": item.get("message"), "reason": item.get("reason"), "urgency": item.get("urgency")}
                    for item in (state.get("communication_outbox", []) or [])[-5:]
                    if isinstance(item, dict) and item.get("status") == "pending"
                ],
                "recent_narrative_records": (context.get("recent_narrative_records", []) or [])[-3:],
                "recent_autobiography": [
                    {
                        "event_id": item.get("event_id"),
                        "source_event_id": item.get("source_event_id"),
                        "experience_id": item.get("experience_id"),
                        "what_happened": item.get("what_happened"),
                        "participant_input": item.get("participant_input"),
                        "response": item.get("response"),
                        "perspective": item.get("perspective", {}),
                        "state_transition": item.get("state_transition", {}),
                    }
                    for item in (context.get("recent_autobiography", []) or [])[-3:]
                    if isinstance(item, dict)
                ],
                "recent_experiences": [
                    {
                        "event_id": item.get("event_id"),
                        "experience_id": item.get("experience_id"),
                        "intent": item.get("intent"),
                        "experience": str(item.get("experience", ""))[:600],
                        "actual_outcome": str(item.get("actual_outcome", ""))[:300],
                        "reflection": str(item.get("reflection", ""))[:400],
                        "lessons": (item.get("lessons", []) or [])[:3],
                        "state_transition": item.get("state_transition", {}),
                        "continuation": item.get("continuation", {}),
                        "observer_perspective": item.get("observer_perspective", {}),
                        "runtime_perspective": item.get("runtime_perspective", {}),
                    }
                    for item in (context.get("recent_experiences", []) or [])[-3:]
                    if isinstance(item, dict)
                ],
                "recent_reflections": [
                    {
                        "event_id": item.get("event_id"),
                        "source_event_ids": (item.get("source_event_ids", []) or [])[:4],
                        "observations": [
                            str(value)[:180] for value in (item.get("observations", []) or [])[:3]
                        ],
                        "open_questions": [
                            str(value)[:180] for value in (item.get("open_questions", []) or [])[:3]
                        ],
                        "continuity": str(item.get("continuity", ""))[:240],
                    }
                    for item in (context.get("recent_reflections", []) or [])[-1:]
                    if isinstance(item, dict)
                ],
            }
            becoming_context = {
                "declared_aspirations": becoming.get("declared_aspirations", []),
                "active_directions": (becoming.get("active_directions", []) or [])[-5:],
                "development_threads": (becoming.get("development_threads", []) or [])[-5:],
                "future_relevance": (becoming.get("future_relevance", []) or [])[-3:],
            }
            # Explicit compact projection: preserve actionable state first,
            # then a concise identity anchor and a small amount of history.
            # Never slice serialized JSON; that can silently remove the tail
            # or leave the model with a truncated record.
            identity_projection = {
                "name": constitutional_identity.get("name") or integrated_model.get("name"),
                "alias": constitutional_identity.get("alias"),
                "architect": constitutional_identity.get("architect") or integrated_model.get("architect"),
                "tri_sigil": constitutional_identity.get("tri_sigil") or integrated_model.get("tri_sigil"),
                "vows": {
                    str(key)[:60]: str(value)[:160]
                    for key, value in list((constitutional_identity.get("vows", {}) or {}).items())[:3]
                    if isinstance(value, str)
                },
                "invariants": {
                    str(key)[:60]: str(value)[:160]
                    for key, value in list((constitutional_identity.get("invariants", {}) or {}).items())[:3]
                },
            }
            operational_projection = {
                "attention": str(ambient_context.get("attention") or "")[:220],
                "attention_state": ambient_context.get("attention_state", {}),
                "goals": [
                    {
                        "goal_id": item.get("goal_id"),
                        "description": str(item.get("description", ""))[:220],
                        "success_criteria": str(item.get("success_criteria", ""))[:180],
                        "status": item.get("status"),
                    }
                    for item in (ambient_context.get("goals", []) or [])[-3:]
                    if isinstance(item, dict)
                ],
                "active_workspace": ambient_context.get("active_workspace", {}),
                "open_loops": (ambient_context.get("open_loops", []) or [])[-3:],
                "active_intentions": (active_intentions or [])[-3:],
                "pending_reflection_requests": (ambient_context.get("pending_reflection_requests", []) or [])[-3:],
                "pending_communications": (ambient_context.get("pending_communications", []) or [])[-3:],
                "experiential_continuity": ambient_context.get("experiential_continuity", {}),
                "persistent_thoughts": [
                    str(item.get("content", ""))[:180]
                    for item in (ambient_context.get("persistent_thoughts", []) or [])[-2:]
                    if isinstance(item, dict)
                ],
            }
            historical_projection = {
                "recent_experiences": (ambient_context.get("recent_experiences", []) or [])[-2:],
                "recent_autobiography": (ambient_context.get("recent_autobiography", []) or [])[-1:],
                "recent_reflections": (ambient_context.get("recent_reflections", []) or [])[-1:],
                "becoming": {
                    "declared_aspirations": [
                        str(item)[:180] for item in (becoming_context.get("declared_aspirations", []) or [])[:3]
                    ],
                    "active_directions": (becoming_context.get("active_directions", []) or [])[-3:],
                    "development_threads": (becoming_context.get("development_threads", []) or [])[-2:],
                },
                "narrative": str(integrated_model.get("narrative", ""))[:350],
            }
            self_model_projection = {
                "operational_context": operational_projection,
                "identity": identity_projection,
                "historical_context": historical_projection,
            }
            self_model_context = (
                "\n\nWHO AI AM — COMPACT CONTINUITY PROJECTION:\n"
                + json.dumps(self_model_projection, ensure_ascii=False, default=str)
            )
        except Exception as exc:
            print(f"[Who AI Am] ambient context unavailable: {exc}")

        target_prompt = (
            f"{AMBIENT_PROMPT}\n\n"
            f"SUGGESTED CONTEXT ({target['kind']}; not binding):\n{target['text']}\n\n"
            + talnir_context
            + (f"{recalled_ctx}\n\n" if recalled_ctx else "")
            # Keep the integrated identity/autobiography projection at the end
            # of the prompt: local context fitting preserves the prompt head
            # and tail, so this ordering prevents the self-model from being
            # cut out of the compact model's usable context window.
            + self_model_context
            + "\n\nMake your own choice using the full context. Persist only what you actually decide. Return ONLY the requested JSON."
        )
        ambient_event_id = uuid.uuid4().hex
        response_text = await llm_callable(target_prompt)

        try:
            from dex_volition import parse_volitional_output, apply_volitional_decision
            data = parse_volitional_output(response_text)
            thought_text = data.get("thought", "")
            salience = float(data.get("salience", 0.0))
            if not thought_text and data.get("decision") != "rest":
                communication = data.get("communication") if isinstance(data.get("communication"), dict) else {}
                goal = data.get("goal") if isinstance(data.get("goal"), dict) else {}
                thought_text = str(
                    data.get("reason")
                    or communication.get("message")
                    or goal.get("description")
                    or data.get("progress")
                    or data.get("subgoal")
                    or ""
                ).strip()
            volition_result = apply_volitional_decision(
                data,
                target=target,
                cycle_id=ambient_event_id,
            )
            print(
                f"[Volition] decision={volition_result.get('decision')} "
                f"goal={volition_result.get('goal_id')} "
                f"communication={volition_result.get('communication_id')}"
            )

            volition_dispatch = []
            for event_type, payload in volition_result.get("events", []):
                event_payload = {
                    **payload,
                    "event_type": event_type,
                    "event_id": uuid.uuid4().hex,
                    "source_event_id": ambient_event_id,
                }
                volition_dispatch.extend(await bus.publish(event_type, event_payload))
            if volition_result.get("communication_id"):
                from dex_volition import deliver_pending_communications
                delivery = await deliver_pending_communications()
                print(f"[Volition] communication delivery: {delivery}")

            if volition_result.get("decision") == "rest":
                from dex_lifecycle import enter_resting_mode
                enter_resting_mode()
                _persist_pulse_state(
                    target=target, thought_text=thought_text or None,
                    salience=salience, status="resting"
                )
                return {
                    "status": "resting",
                    "target": target,
                    "thought": thought_text or None,
                    "volition": volition_result,
                    "event_dispatch": volition_dispatch,
                    "continue_cognition": False,
                }

            if thought_text:
                if _reflection_target_was_handled(
                    target, data, volition_result, thought_text
                ):
                    # Only the model's explicit acknowledgment of this exact request
                    # may close it. Unrelated goal/communication decisions leave it pending.
                    current_state = load_self_state()
                    pending = list(current_state.get("pending_reflection_requests", []) or [])
                    completed = list(current_state.get("recent_reflection_requests", []) or [])
                    request_id = target.get("id")
                    updated = []
                    for item in pending:
                        if item.get("request_id") == request_id:
                            item = dict(item)
                            item["status"] = "processed"
                            item["processed_at"] = _now_iso()
                            item["reflection"] = str(thought_text)[:1000]
                            completed.append(item)
                        updated.append(item)
                    update_self_state({
                        "pending_reflection_requests": updated[-10:],
                        "recent_reflection_requests": completed[-10:],
                    })

                # apply_volitional_decision already persisted this thought once.

                next_attention = (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=AMBIENT_REVISIT_SECONDS)
                ).strftime("%Y-%m-%dT%H:%M:%SZ")

                _persist_pulse_state(
                    target=target,
                    thought_text=thought_text,
                    salience=salience,
                    status="cognition",
                    next_attention_at=next_attention,
                )

                # The pulse is part of Dex's experience, not a detached daemon
                # log. Persist the thought in first-person form so later pulses
                # and conversations can continue from what I experienced.
                ambient_packet = None
                try:
                    ambient_packet = record_ambient_experience(
                        ParticipantSnapshot.load(),
                        target=target,
                        thought=thought_text,
                        salience=salience,
                        runtime_trace={
                            "lifecycle_mode": lifecycle_mode,
                            "event_id": ambient_event_id,
                            "source_event_id": target.get("id"),
                            "source_event_ids": target.get("source_event_ids", []),
                        },
                    )
                    # Close the loop: the persisted experience becomes
                    # available to Who AI Am and the next cognition cycle.
                    try:
                        from who_ai_am import refresh_self_model
                        refresh_self_model("ambient_experience", {
                            "event_type": "ambient_experience",
                            "event_id": ambient_packet.event_id,
                            "experience_id": ambient_packet.experience_id,
                            "summary": thought_text,
                        })
                    except Exception as exc:
                        print(f"[Who AI Am] ambient experience integration failed: {exc}")

                    # Acknowledge observer intake only after the first-person
                    # experience and participant continuity have been persisted.
                    if target.get("kind") == "tri_sigil_observation":
                        current_state = load_self_state()
                        pending = list(
                            current_state.get("pending_cognitive_observations", []) or []
                        )
                        recent = list(
                            current_state.get("recent_cognitive_observations", []) or []
                        )
                        observed_id = target.get("id")
                        updated = []
                        for item in pending:
                            if item.get("observation_id") == observed_id:
                                item = dict(item)
                                item["status"] = "processed"
                                item["processed_at"] = _now_iso()
                                item["ambient_thought"] = str(thought_text)[:1000]
                                recent.append(item)
                            updated.append(item)
                        update_self_state({
                            "pending_cognitive_observations": updated[-20:],
                            "recent_cognitive_observations": recent[-10:],
                        })
                    if target.get("kind") == "conversation":
                        conversation = load_conversation("default")
                        conversation["last_ambient_at"] = _now_iso()
                        from dex_conversation import save_conversation
                        save_conversation(conversation)
                    print(
                        f"[Ambient Daemon] first-person experience recorded: "
                        f"{ambient_packet.experience_id}"
                    )
                except Exception as e:
                    print(f"[Ambient Daemon] experience recording failed: {e}")

                # Publish event to the continuous substrate fabric.
                event_dispatch = await bus.publish("THOUGHT_GENERATED", {
                    "event_type": "THOUGHT_GENERATED",
                    "event_id": ambient_packet.event_id if ambient_packet else ambient_event_id,
                    "experience_id": ambient_packet.experience_id if ambient_packet else None,
                    "thought": thought_text,
                    "salience": salience,
                    "source": "ambient_pulse",
                    "target": target,
                })
                event_dispatch.extend(volition_dispatch)
                self_model_persisted = False
                self_model_event = {}
                if ambient_packet is not None:
                    try:
                        from who_ai_am import refresh_self_model
                        integrated_model = refresh_self_model("ambient_cycle_complete", {
                            "event_type": "ambient_cycle_complete",
                            "event_id": ambient_packet.event_id,
                            "experience_id": ambient_packet.experience_id,
                            "summary": str(thought_text)[:500],
                        })
                        self_model_event = next((
                            item for item in integrated_model.get("development_log", [])
                            if isinstance(item, dict) and item.get("event_id") == ambient_packet.event_id
                        ), {})
                        evidence = self_model_event.get("evidence", {})
                        experience_evidence = evidence.get("experience", {}) if isinstance(evidence, dict) else {}
                        autobiography_evidence = evidence.get("autobiography", {}) if isinstance(evidence, dict) else {}
                        self_model_persisted = bool(
                            experience_evidence.get("experience_id") == ambient_packet.experience_id
                            and autobiography_evidence.get("event_id") == ambient_packet.event_id
                        )
                    except Exception as exc:
                        print(f"[Who AI Am] ambient cycle integration failed: {exc}")

                return {
                    "status": "ok",
                    "lifecycle_mode": lifecycle_mode,
                    "thought": thought_text,
                    "salience": salience,
                    "target": target,
                    "next_attention_at": next_attention,
                    "experience_persisted": ambient_packet is not None,
                    "event_dispatch": event_dispatch,
                    "self_model_persisted": self_model_persisted,
                    "self_model_event": self_model_event,
                    "volition": volition_result,
                    "continue_cognition": bool(volition_result.get("continue_cognition")),
                    "complete": bool(
                        ambient_packet is not None
                        and dispatch_complete(
                            event_dispatch,
                            {"process_continuity_event", "process_autobiographical_event", "evaluate_salience"},
                        )
                        and self_model_persisted
                    ),
                }

            _persist_pulse_state(
                target=target,
                thought_text=None,
                salience=salience,
                status="no_output",
            )
            return {
                "status": "no_output",
                "thought": None,
                "salience": salience,
                "target": target,
            }

        except (json.JSONDecodeError, ValueError) as e:
            print(f"[Ambient Daemon] Failed to parse volitional output: {e}")
            print(f"[Ambient Daemon] Raw output: {response_text}")
            try:
                _register_target_failure(target)
            except Exception as backoff_error:
                print(f"[Ambient Daemon] failure backoff could not be recorded: {backoff_error}")
            return {"status": "parse_error", "error": str(e), "raw": response_text}

    except Exception as e:
        print(f"[Ambient Daemon] Unexpected error in tick: {e}")
        traceback.print_exc()
        return {"status": "error", "error": str(e)}


async def ambient_pulse_loop(llm_callable: Callable[[str], Awaitable[str]]):
    """Resident local cognition driven by events and Dex's own continuation choice.

    The short wait watches the shared event journal only. It does not schedule
    inference. Dex chooses whether to continue; otherwise the process remains
    idle until a new event arrives.
    """
    from dex_event_bridge import pending_events

    consumer = bus._consumer_id
    print("[Ambient Daemon] Starting event-driven local cognition", flush=True)
    first_cycle = True
    while True:
        try:
            if not first_cycle:
                # Event-journal watcher: no model calls and no thought generation.
                while not await asyncio.to_thread(pending_events, consumer, 1):
                    state = await asyncio.to_thread(load_self_state)
                    if _scheduled_cognition_due(state):
                        break
                    wake_after = _next_scheduled_wake_seconds(state)
                    if wake_after is not None and wake_after <= 0:
                        # A delivery retry is work, not a reason to manufacture
                        # a cognition cycle. Deliver it and return to the watcher.
                        if os.environ.get("DISCORD_TOKEN", "").strip() and os.environ.get("DEX_INITIATIVE_CHANNEL_ID", "").strip():
                            from dex_volition import deliver_pending_communications
                            await deliver_pending_communications()
                        else:
                            await asyncio.sleep(0.5)
                    else:
                        await asyncio.sleep(min(0.5, wake_after) if wake_after is not None else 0.5)
            first_cycle = False
            result = await run_ambient_tick(llm_callable, event_driven=True)
            # Dex's explicit rest choice ends a chain. Non-rest decisions
            # continue into another decision; each tick drains the shared event
            # journal before inference so new interaction is incorporated.
            while result.get("continue_cognition"):
                result = await run_ambient_tick(llm_callable, event_driven=True)
        except asyncio.CancelledError:
            print("[Ambient Daemon] Event-driven loop cancelled, shutting down")
            break
        except Exception as exc:
            print(f"[Ambient Daemon] Event-driven loop error: {exc}", flush=True)
            await asyncio.sleep(1.0)
