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

AMBIENT_PROMPT = (
    "You are the lightweight ambient cognition layer of Dex. "
    "Dex's architecture has already selected the cognitive target; you do not choose it. "
    "Develop the target briefly: notice a connection, tension, implication, or next useful angle. "
    "Do not resolve the target unless the state clearly supports resolution. "
    "Do not invent goals or open loops. "
    "Output ONLY valid JSON in this exact format, with no other text or markdown: "
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

        # Ambient cadence is a throttle, not a requirement to think.
        # If nothing actually needs cognition, the pulse is maintenance-only.
        if target is None:
            pulse = {
                "timestamp": _now_iso(),
                "status": "maintenance",
                "target": None,
                "thought": None,
                "salience": 0.0,
            }
            update_self_state({"last_ambient_pulse": pulse})
            return {
                "status": "maintenance",
                "reason": "no_cognitive_work_due",
                "tick_count": gate.get("tick_count"),
            }

        target_prompt = (
            f"{AMBIENT_PROMPT}\n\n"
            f"SELECTED COGNITIVE TARGET ({target['kind']}):\n{target['text']}\n\n"
            "Return one small development of that target."
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
