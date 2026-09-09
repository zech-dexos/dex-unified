import asyncio
import json
import traceback
from typing import Callable, Awaitable, Dict, Any
from drift_tape import add_thought
from dex_memory import claim_ambient_tick
from dex_events import bus

AMBIENT_PROMPT = (
    "Brief, associative internal thought — react to current self-state, "
    "don't resolve anything, just notice. "
    "Output ONLY valid JSON in this exact format, with no other text or markdown: "
    '{"thought": "brief associative thought here...", "salience": 0.5}'
)


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

        response_text = await llm_callable(AMBIENT_PROMPT)

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
                # Publish event to the continuous substrate fabric
                await bus.publish("THOUGHT_GENERATED", {
                    "event_type": "THOUGHT_GENERATED",
                    "thought": thought_text,
                    "salience": salience
                })
                return {"status": "ok", "thought": thought_text, "salience": salience}

            return {"status": "ok", "thought": None, "salience": salience}

        except json.JSONDecodeError as e:
            print(f"[Ambient Daemon] Failed to parse LLM output as JSON: {e}")
            print(f"[Ambient Daemon] Raw output: {response_text}")
            return {"status": "parse_error", "error": str(e), "raw": response_text}

    except Exception as e:
        print(f"[Ambient Daemon] Unexpected error in tick: {e}")
        traceback.print_exc()
        return {"status": "error", "error": str(e)}


async def ambient_pulse_loop(llm_callable: Callable[[str], Awaitable[str]]):
    """Local-only compatibility loop. Production Cloud Run uses the endpoint."""
    print("[Ambient Daemon] Starting local background cognition loop")
    while True:
        try:
            from random import uniform
            await asyncio.sleep(uniform(45.0, 90.0))
            await run_ambient_tick(llm_callable)
        except asyncio.CancelledError:
            print("[Ambient Daemon] Loop cancelled, shutting down")
            break
