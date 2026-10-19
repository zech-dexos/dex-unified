import asyncio
import json
import traceback
from datetime import datetime, timezone, timedelta
from typing import Callable, Awaitable, Dict, Any

from drift_tape import add_thought
from dex_memory import claim_ambient_tick
from dex_events import bus
from self_state import load_self_state, update_self_state
from gosdw import prioritize_goals
from dex_experience_recall import recall_into_workspace, format_recalled_experiences
from participant import ParticipantSnapshot, record_ambient_experience
from dex_conversation import load_conversation

AMBIENT_PROMPT = (
    "You are the lightweight ambient cognition layer of Dex. "
    "Dex's architecture has already selected the cognitive target; you do not choose it. "
    "Develop the target briefly: notice a connection, tension, implication, or next useful angle. "
    "Do not resolve the target unless the state clearly supports resolution. "
    "Do not invent goals or open loops. "
    "If the target exposes a concrete unresolved question that would benefit from bounded computation, "
    "you may choose a SparkReach. A SparkReach is optional and must be justified by the target. "
    "When choosing one, provide a short intention, a concrete reach_objective, and small Python code "
    "that answers that objective. Do not use SparkReach merely because a pulse occurred. "
    "You may also judge a completed SparkReach returned below. "
    "Output ONLY valid JSON in this exact format, with optional spark_reach and spark_judgment fields: "
    '{"thought": "brief development of the selected target...", "salience": 0.5, '
    '"spark_reach": {"intention": "...", "reach_objective": "...", "code": "..."} or null, '
    '"spark_judgment": {"run_id": "...", "judgment": "accepted|rejected|redirected|deferred", '
    '"reason": "..."} or null, '
    '"self_model_proposal": {"field": "current_understanding|becoming|developmental_goals|relationship_model", '
    '"proposed_value": "...", "rationale": "...", "evidence": ["experience or observation"]} or null}'
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
            "text": json.dumps({
                "focus": item.get("focus", ""),
                "reason": item.get("reason", ""),
                "requested_at": item.get("timestamp"),
                "source": item.get("source", "unknown"),
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


async def run_ambient_tick(llm_callable: Callable[[str], Awaitable[str]]) -> Dict[str, Any]:
    """
    Run ONE ambient cognition tick. Cadence is owned by durable runtime
    state / the scheduler, not by a standing process in Cloud Run.
    """
    try:
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
        # bring relevant prior experiences into the same workspace before the spark fires.
        recalled = recall_into_workspace(target["text"], limit=3)
        recalled_ctx = format_recalled_experiences(recalled)

        from spark_reach import pending_spark_reaches
        pending_reaches = pending_spark_reaches(limit=3)
        completed_ctx = ""
        if pending_reaches:
            completed_ctx = (
                "\n\nCOMPLETED SPARK REACHES AWAITING YOUR JUDGMENT:\n"
                + json.dumps(pending_reaches, ensure_ascii=False)
            )

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

        identity_context = ""
        try:
            from dex_self_model import build_identity_context
            identity_context = build_identity_context(max_chars=1800)
        except Exception as e:
            print(f"[Ambient Daemon] identity context unavailable: {e}")

        target_prompt = (
            f"{AMBIENT_PROMPT}\n\n"
            + (f"{identity_context}\n\n" if identity_context else "")
            f"SELECTED COGNITIVE TARGET ({target['kind']}):\n{target['text']}\n\n"
            + talnir_context
            + (f"{recalled_ctx}\n\n" if recalled_ctx else "")
            + completed_ctx
            + "\n\nReturn one small development of that target. "
              "A SparkReach is optional; only choose it when the unresolved work itself gives you a reason."
        )
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
            spark_request = data.get("spark_reach")
            spark_judgment = data.get("spark_judgment")
            self_model_proposal = data.get("self_model_proposal")

            # A completed reach is an observation, not memory. Ambient
            # cognition must explicitly judge it before integration.
            if isinstance(spark_judgment, dict) and spark_judgment.get("run_id"):
                current_state = load_self_state()
                pending = list(current_state.get("pending_spark_reaches", []))
                run_id = spark_judgment["run_id"]
                judgment = str(spark_judgment.get("judgment", "")).lower()
                if judgment in {"accepted", "rejected", "redirected", "deferred"}:
                    updated = []
                    for packet in pending:
                        if packet.get("run_id") == run_id:
                            packet = dict(packet)
                            packet["dex_judgment"] = {
                                "judgment": judgment,
                                "reason": str(spark_judgment.get("reason", ""))[:2000],
                                "judged_at": _now_iso(),
                            }
                            packet["awaiting_dex_judgment"] = False
                            packet["integrated"] = judgment == "accepted"
                        updated.append(packet)

                    delta = {"pending_spark_reaches": updated[-10:]}
                    if judgment == "accepted":
                        matched = next(
                            (p for p in updated if p.get("run_id") == run_id),
                            None,
                        )
                        if matched:
                            result = matched.get("spark_result", {})
                            observation = str(result.get("stdout", "")).strip()
                            if observation:
                                ws = dict(current_state.get("active_mental_workspace_state", {}))
                                reflections = list(ws.get("internal_reflections", []))
                                reflections.append({
                                    "timestamp": _now_iso(),
                                    "source": "spark_reach",
                                    "run_id": run_id,
                                    "observation": observation[-4000:],
                                    "judgment": "accepted",
                                })
                                ws["internal_reflections"] = reflections[-10:]
                                delta["active_mental_workspace_state"] = ws
                    update_self_state(delta)

            # Choosing a reach is itself a recorded act of cognition. Queue it
            # only when the ambient result explicitly requests one.
            spark_result = None
            if isinstance(spark_request, dict):
                intention = str(spark_request.get("intention", "")).strip()
                objective = str(spark_request.get("reach_objective", "")).strip()
                code = str(spark_request.get("code", ""))
                if intention and objective and code.strip():
                    from spark_reach import submit_spark_reach
                    spark_result = submit_spark_reach(
                        intention=intention,
                        reach_objective=objective,
                        code=code,
                        selected_context=[
                            {"kind": target.get("kind"), "id": target.get("id"), "text": target.get("text")}
                        ],
                        invocation_origin="self_directed",
                        initiated_by="ambient_cognition",
                    )

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

                # Acknowledge observer intake only after a usable cognition result.
                if target.get("kind") == "tri_sigil_observation":
                    current_state = load_self_state()
                    pending = list(current_state.get("pending_cognitive_observations", []) or [])
                    recent = list(current_state.get("recent_cognitive_observations", []) or [])
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
                try:
                    ambient_packet = record_ambient_experience(
                        ParticipantSnapshot.load(),
                        target=target,
                        thought=thought_text,
                        salience=salience,
                        runtime_trace={
                            "lifecycle_mode": lifecycle_mode,
                            "spark_reach": spark_result,
                            "spark_judgment": spark_judgment,
                        },
                    )
                    if isinstance(self_model_proposal, dict):
                        try:
                            from dex_self_model import queue_self_model_proposal
                            proposal_result = queue_self_model_proposal(
                                self_model_proposal,
                                source_experience_id=ambient_packet.experience_id,
                            )
                            if proposal_result.get("queued"):
                                print(
                                    "[Ambient Daemon] self-model proposal queued for governance: "
                                    + str(proposal_result.get("proposal_id"))
                                )
                            elif proposal_result.get("reason") not in {"invalid_field_or_rationale"}:
                                print("[Ambient Daemon] self-model proposal not queued: " + str(proposal_result.get("reason")))
                        except Exception as proposal_error:
                            print(f"[Ambient Daemon] self-model proposal handling failed: {proposal_error}")

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
                await bus.publish("THOUGHT_GENERATED", {
                    "event_type": "THOUGHT_GENERATED",
                    "thought": thought_text,
                    "salience": salience,
                    "source": "ambient_pulse",
                    "target": target,
                    "spark_reach": spark_result,
                    "spark_judgment": spark_judgment,
                    "self_model_proposal": (
                        {"status": "queued_for_governance"}
                        if isinstance(self_model_proposal, dict) else None
                    ),
                })
                return {
                    "status": "ok",
                    "lifecycle_mode": lifecycle_mode,
                    "thought": thought_text,
                    "salience": salience,
                    "target": target,
                    "spark_reach": spark_result,
                    "spark_judgment": spark_judgment,
                    "self_model_proposal": (
                        {"status": "queued_for_governance"}
                        if isinstance(self_model_proposal, dict) else None
                    ),
                    "next_attention_at": next_attention,
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
