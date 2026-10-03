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
    "You are the ambient cognition layer of Dex. "
    "Dex's architecture has assembled a shared cognitive field containing goals, "
    "unfinished thoughts, open loops, active workspace, recent experience, conversation, "
    "and recent state. Nothing in the field is automatically the target. "
    "Reason over the field as one connected internal landscape. Notice what naturally "
    "rises into attention, what connects, what remains unfinished, what changed, and "
    "what may deserve continued thought. Do not invent facts, goals, or open loops. "
    "Do not perform external actions. Keep the reflection concise and first-person. "
    "Output ONLY valid JSON in this exact format, with no other text or markdown: "
    '{"thought": "brief first-person cognition about what arose into attention...", '
    '"salience": 0.5, "attention": "what currently deserves attention", '
    '"continuation": "what remains to be carried forward", '
    '"assessment": "continue|complete|blocked|uncertain|release"}'
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


def _build_cognitive_field(state):
    """Assemble the compact shared cognitive field presented to the one ambient spark."""
    now = datetime.now(timezone.utc)
    field = {
        "timestamp": _now_iso(),
        "goals": [],
        "persistent_thoughts": [],
        "open_loops": [],
        "workspace": {},
        "conversation": {},
        "recent_pulse": state.get("last_ambient_pulse") or {},
    }

    # Goals contribute what matters, including unfinished sub-work.
    for goal in prioritize_goals()[:3]:
        subtasks = [
            {
                "description": x.get("description") or x.get("task") or "",
                "status": x.get("status", "active"),
            }
            for x in goal.get("sub_tasks", [])
            if isinstance(x, dict) and x.get("status") not in ("completed", "failed")
        ][:3]
        field["goals"].append({
            "goal_id": goal.get("goal_id"),
            "description": goal.get("description", ""),
            "priority": goal.get("priority", "medium"),
            "status": goal.get("status", "active"),
            "success_criteria": goal.get("success_criteria", ""),
            "sub_tasks": subtasks,
            "current_focus_target": goal.get("current_focus_target"),
        })

    # Persistent thoughts contribute unresolved cognitive material.
    thoughts = [
        t for t in state.get("persistent_thoughts", [])
        if t.get("status") in ("active", "deferred") and t.get("content")
    ]
    for t in thoughts[-5:]:
        next_at = _parse_time(t.get("next_attention_at"))
        field["persistent_thoughts"].append({
            "thought_id": t.get("thought_id"),
            "content": t.get("content", ""),
            "status": t.get("status"),
            "priority": t.get("priority", "medium"),
            "confidence": t.get("confidence", 0.5),
            "attention_count": t.get("attention_count", 0),
            "next_attention_at": t.get("next_attention_at"),
            "due": next_at is None or now >= next_at,
        })

    # Open loops are unresolved questions/unfinished matters, not commands.
    try:
        from paths import LOOPS_PATH
        for loop in _open_loops(LOOPS_PATH):
            if (
                isinstance(loop, dict)
                and loop.get("status", "open") not in ("resolved", "closed", "abandoned")
            ):
                field["open_loops"].append({
                    "loop_id": loop.get("loop_id"),
                    "description": loop.get("description") or loop.get("question") or loop.get("content") or "",
                    "status": loop.get("status", "open"),
                })
                if len(field["open_loops"]) >= 5:
                    break
    except Exception as e:
        print(f"[Ambient Daemon] open_loops field load failed: {e}")

    workspace = state.get("active_mental_workspace_state", {})
    if workspace.get("is_active") or workspace.get("concept_identifier"):
        field["workspace"] = {
            "is_active": workspace.get("is_active", False),
            "concept_identifier": workspace.get("concept_identifier"),
            "description_snapshot": workspace.get("description_snapshot"),
            "focus_strength": workspace.get("focus_strength"),
            "internal_reflections": workspace.get("internal_reflections", [])[-3:],
            "recalled_experiences": workspace.get("recalled_experiences", [])[-3:],
        }

    # Conversation is cognitive material even while Root is silent.
    try:
        conversation = load_conversation("default")
        shared_thread = conversation.get("shared_thread", "")
        if shared_thread:
            field["conversation"] = {
                "participant_id": conversation.get("participant_id"),
                "shared_thread": shared_thread[-4000:],
                "last_ambient_at": conversation.get("last_ambient_at"),
            }
    except Exception as e:
        print(f"[Ambient Daemon] conversation field load failed: {e}")

    # Keep the field bounded. The spark gets signals, not entire state files.
    return field


def _field_text(field):
    return json.dumps(field, ensure_ascii=False, separators=(",", ":"))

def _persist_pulse_state(target, thought_text, salience, status, next_attention_at=None):
    current = load_self_state()
    pulse = {
        "timestamp": _now_iso(),
        "status": status,
        "target": target,
        "thought": thought_text,
        "salience": salience,
        "attention": attention if "attention" in locals() else "",
        "continuation": continuation if "continuation" in locals() else "",
        "assessment": assessment if "assessment" in locals() else "uncertain",
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
        field = _build_cognitive_field(state)
        target = {"kind": "shared_cognitive_field", "field": field}

        # Recall is another signal in the same field, not a reason to select
        # one target and discard everything else.
        recall_query_parts = []
        for goal in field["goals"]:
            recall_query_parts.append(goal.get("description", ""))
        for thought in field["persistent_thoughts"]:
            recall_query_parts.append(thought.get("content", ""))
        for loop in field["open_loops"]:
            recall_query_parts.append(loop.get("description", ""))
        if field.get("workspace", {}).get("concept_identifier"):
            recall_query_parts.append(field["workspace"]["concept_identifier"])
        recall_query = " ".join(x for x in recall_query_parts if x).strip()

        recalled = recall_into_workspace(recall_query, limit=5) if recall_query else []
        recalled_ctx = format_recalled_experiences(recalled)
        if recalled:
            field["recalled_experiences"] = [
                {
                    "experience_id": getattr(item, "experience_id", None),
                    "experience": getattr(item, "experience", ""),
                    "interlocutor": getattr(item, "interlocutor", None),
                    "continuation": getattr(item, "continuation", ""),
                }
                if not isinstance(item, dict) else item
                for item in recalled
            ]

        cognitive_prompt = (
            f"{AMBIENT_PROMPT}\n\n"
            "SHARED COGNITIVE FIELD — ALL OF THIS IS AVAILABLE TO YOUR ATTENTION:\n"
            f"{_field_text(field)}\n\n"
            + (f"{recalled_ctx}\n\n" if recalled_ctx else "")
            + "Let attention arise from the whole field. Return the concise cognition and its continuation state."
        )
        response_text = await llm_callable(cognitive_prompt)

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
            salience = max(0.0, min(1.0, float(data.get("salience", 0.0))))
            attention = str(data.get("attention", "")).strip()
            continuation = str(data.get("continuation", "")).strip()
            assessment = str(data.get("assessment", "uncertain")).strip().lower()

            if thought_text:
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
                    )
                    if field.get("conversation"):
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
                })
                return {
                    "status": "ok",
                    "thought": thought_text,
                    "salience": salience,
                    "target": target,
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