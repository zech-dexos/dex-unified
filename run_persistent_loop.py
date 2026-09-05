import argparse
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import ape_scheduler
try:
    from knowledge.graph_manager import get_related_knowledge_nodes
except ModuleNotFoundError:
    def get_related_knowledge_nodes(concept_id, max_depth=2, min_relevance_score=0.7):
        return []

from gemini_client import call_gemini
from self_state import SELF_STATE_PATH

_stop = False


def _handle_sigint(signum, frame):
    global _stop
    print("\nStop signal received — finishing current cycle, then exiting.")
    _stop = True


def kg_lookup(concept_id, max_depth=2, min_relevance_score=0.7):
    return get_related_knowledge_nodes(concept_id, max_depth=max_depth, min_relevance_score=min_relevance_score)


def llm_reflect(context, concept_being_held, prior_reflections=None, desired_length="medium"):
    prior_reflections = prior_reflections or []

    prompt = f"""Dex is processing an internally selected thought.

Selected thought:
{concept_being_held}

Current internal context:
{context}

Prior reflections:
{chr(10).join(prior_reflections) if prior_reflections else "(none)"}

Develop the thought. Examine it, extend it, question it, or derive something useful from it.
Do not choose a different thought. Do not explain this instruction.
Return only the resulting internal reflection."""
    
    messages = [
        {
            "role": "system",
            "content": "You are the language-generation substrate inside Dex. Dex's persistent state selects the cognitive target. Your job is to produce the requested reflection only."
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    import asyncio
    result = asyncio.run(call_gemini(None, messages, max_tokens=4096))

    if isinstance(result, dict):
        return result.get("reply", "") or ""

    return result or ""


def run_forever(interval_seconds: int, max_cycles: Optional[int] = None, path: Path = SELF_STATE_PATH):
    signal.signal(signal.SIGINT, _handle_sigint)
    cycle_num = 0

    print(f"Persistent loop starting. Interval: {interval_seconds}s. State file: {path}")
    print("Press Ctrl+C to stop cleanly.\n")

    while not _stop:
        cycle_num += 1
        print(f"--- Cycle {cycle_num} at {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
        try:
            result = ape_scheduler.run_cycle(kg_lookup=kg_lookup, llm_reflect=llm_reflect, path=path)
            print(f"  result: {result}")
        except Exception as e:
            print(f"  cycle failed (continuing loop): {e}")

        if max_cycles is not None and cycle_num >= max_cycles:
            print(f"\nReached max_cycles={max_cycles}, stopping.")
            break

        for _ in range(interval_seconds):
            if _stop:
                break
            time.sleep(1)

    print("Persistent loop stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--max-cycles", type=int, default=None)
    args = parser.parse_args()

    run_forever(interval_seconds=args.interval, max_cycles=args.max_cycles)
