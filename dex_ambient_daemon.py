import asyncio
import random
import json
import traceback
from typing import Callable, Awaitable, Optional, Dict, Any
from drift_tape import add_thought

AMBIENT_PROMPT = (
    "Brief, associative internal thought — react to current self-state, "
    "don't resolve anything, just notice. "
    "Output ONLY valid JSON in this exact format, with no other text or markdown: "
    '{"thought": "brief associative thought here...", "salience": 0.5}'
)


async def run_ambient_tick(llm_callable: Callable[[str], Awaitable[str]]) -> Dict[str, Any]:
    """
    Run ONE ambient cognition tick: call the LLM, parse the result, and
    (if salience clears threshold and vow_check passes) add it to the
    drift tape. Designed to be called from a scheduled endpoint — no loop,
    no sleep. Returns a status dict for the caller to log/return.
    """
    try:
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
    """
    DEPRECATED for Cloud Run: standing asyncio loops don't survive
    scale-to-zero between requests, so ticks rarely fire. Kept only for
    local/non-Cloud-Run use. Production should use the /ambient-pulse
    endpoint on a Cloud Scheduler cadence instead (see run_ambient_tick).
    """
    print("[Ambient Daemon] Starting background cognition loop (deprecated path)")
    while True:
        try:
            sleep_time = random.uniform(45.0, 90.0)
            await asyncio.sleep(sleep_time)
            await run_ambient_tick(llm_callable)
        except asyncio.CancelledError:
            print("[Ambient Daemon] Loop cancelled, shutting down")
            break
