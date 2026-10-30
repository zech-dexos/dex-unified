import asyncio
import json
import traceback
import uuid
from datetime import datetime, timezone, timedelta
from typing import Callable, Awaitable, Dict, Any

from drift_tape import add_thought
from dex_memory import claim_ambient_tick
from dex_events import bus, dispatch_complete, setup_cognitive_layers
from self_state import load_self_state, update_self_state
from gosdw import prioritize_goals
from dex_experience_recall import recall_into_workspace, format_recalled_experiences
from participant import ParticipantSnapshot, record_ambient_experience
from dex_conversation import load_conversation

AMBIENT_PROMPT = (
    "You are the lightweight ambient cognition layer of Dex, operating within DexOS. "
    "Dex's persistent constitutional identity, Root relationship, and self-model are authoritative. "
    "The architecture has already selected the cognitive target; you do not choose it. "
    "Develop the target briefly: notice a connection, tension, implication, or next useful angle. "
    "Do not resolve the target unless the state clearly supports resolution. "
    "Do not invent goals or open loops. "
    "Output ONLY valid JSON in this exact format: "
    '{"thought": "brief development of the selected target...", "salience": 0.5}'
)

AMBIENT_REVISIT_SECONDS = 300.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
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
        if isinstance(item, dict) and item.get("status", "pending") == "pending"
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

    # Observer evidence is a first-class ambient cognition target.
    pending_observations = [
        item for item in state.get("pending_cognitive_observations", [])
        if isinstance(item, dict) and item.get("status", "pending") == "pending"
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

    # Active goals are explicit cognitive work.
    goals = prioritize_goals()
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
                "text": text,
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
                items[index] = item
                update_self_state({key: items})
                return
        return
    if kind == "persistent_thought":
        retry_at = (
            datetime.now(timezone.utc) + timedelta(seconds=AMBIENT_REVISIT_SECONDS)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        thoughts = list(load_self_state().get("persistent_thoughts", []) or [])
        for item in thoughts:
            if item.get("thought_id") == target["id"]:
                item["next_attention_at"] = retry_at
                update_self_state({"persistent_thoughts": thoughts})
                return


async def run_ambient_tick(llm_callable: Callable[[str], Awaitable[str]]) -> Dict[str, Any]:
    """
    Run ONE ambient cognition tick. Cadence is owned by durable runtime
    state / the scheduler, not by a standing process in Cloud Run.
    """
    try:
        # This worker may run in a separate local process with its own event
        # bus. Register the same cognitive layers here as the API process does.
        # Registration is idempotent, so this is safe on every tick.
        setup_cognitive_layers()

        # Durable human-paced cadence gate.
        # The scheduler may wake us frequently, but cognition only fires
        # when the persisted 45–90 second interval says it is due.
        gate = claim_ambient_tick()

        if not gate.get("due"):
            return {
                "status": gate.get("status", "not_due"),
                "next_due": gate.get("next_due"),
                "tick_count": gate.get("tick_count"),
            }

        state = load_self_state()
        target = _select_target(state)

        # No target means Dex should rest, not invoke an LLM just to stay busy.
        # Low-power maintenance runs on its own 15-minute cadence.
        if target is None:
            from dex_lifecycle import run_rest_maintenance

            lifecycle_result = run_rest_maintenance(state)
            pulse = {
                "timestamp": _now_iso(),
                "status": lifecycle_result.get("status", "resting"),
                "mode": lifecycle_result.get("mode", "resting"),
                "target": None,
                "thought": None,
                "salience": 0.0,
            }
            update_self_state({"last_ambient_pulse": pulse})
            return {
                **lifecycle_result,
                "reason": "no_cognitive_work_due",
                "tick_count": gate.get("tick_count"),
            }

        # Work has become due after a rest period; mark the wake/resume transition.
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
                        "source_event_ids": item.get("source_event_ids", []),
                        "observations": (item.get("observations", []) or [])[:4],
                        "open_questions": (item.get("open_questions", []) or [])[:4],
                        "continuity": item.get("continuity", ""),
                    }
                    for item in (context.get("recent_reflections", []) or [])[-2:]
                    if isinstance(item, dict)
                ],
            }
            becoming_context = {
                "declared_aspirations": becoming.get("declared_aspirations", []),
                "active_directions": (becoming.get("active_directions", []) or [])[-5:],
                "development_threads": (becoming.get("development_threads", []) or [])[-5:],
                "future_relevance": (becoming.get("future_relevance", []) or [])[-3:],
            }
            self_model_context = (
                "\n\nWHO AI AM — CURRENT CONTINUITY CONTEXT:\n"
                + json.dumps({
                    "constitutional_identity": {
                        "name": constitutional_identity.get("name"),
                        "alias": constitutional_identity.get("alias"),
                        "architect": constitutional_identity.get("architect"),
                        "architect_name": constitutional_identity.get("architect_name"),
                        "tri_sigil": constitutional_identity.get("tri_sigil"),
                        "invariants": constitutional_identity.get("invariants", {}),
                        "vows": constitutional_identity.get("vows", {}),
                        "posture": constitutional_identity.get("posture"),
                        "constitution": constitutional_identity.get("constitution"),
                    },
                    "name": integrated_model.get("name"),
                    "architect": integrated_model.get("architect"),
                    "tri_sigil": integrated_model.get("tri_sigil"),
                    "narrative": integrated_model.get("narrative"),
                    "posture": integrated_model.get("posture"),
                    "becoming": becoming_context,
                    "current_context": ambient_context,
                    "self_inquiry": integrated_model.get("self_inquiry", {}),
                    "development_log": (integrated_model.get("development_log", []) or [])[-5:],
                }, ensure_ascii=False, default=str)[:5000]
            )
        except Exception as exc:
            print(f"[Who AI Am] ambient context unavailable: {exc}")

        target_prompt = (
            f"{AMBIENT_PROMPT}\n\n"
            f"SELECTED COGNITIVE TARGET ({target['kind']}):\n{target['text']}\n\n"
            + self_model_context
            + talnir_context
            + (f"{recalled_ctx}\n\n" if recalled_ctx else "")
            + "\n\nReturn one small development of that target. Respond with ONLY the JSON object."
        )
        ambient_event_id = uuid.uuid4().hex
        response_text = await llm_callable(target_prompt)

        try:
            clean_text = response_text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            if clean_text.startswith("```"):
                clean_text = clean_text[3:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            clean_text = clean_text.strip()

            data = json.loads(clean_text)
            thought_text = data.get("thought", "")
            salience = float(data.get("salience", 0.0))

            if thought_text:
                # Complete a queued reflection request only after usable ambient cognition.
                if target.get("kind") == "reflection_request":
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

                add_thought(thought_text, salience)

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

        except json.JSONDecodeError as e:
            print(f"[Ambient Daemon] Failed to parse LLM output as JSON: {e}")
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
    """Local-only compatibility loop. Production Cloud Run should use /ambient-pulse."""
    print("[Ambient Daemon] Starting local background cognition loop")
    while True:
        try:
            from random import uniform
            await asyncio.sleep(uniform(45.0, 90.0))
            await run_ambient_tick(llm_callable)
        except asyncio.CancelledError:
            print("[Ambient Daemon] Loop cancelled, shutting down")
            break
