import argparse
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import ape_scheduler
from knowledge.graph_manager import get_related_knowledge_nodes
from gemini_client import generate_reflection_text
from self_state import SELF_STATE_PATH

_stop = False


def _handle_sigint(signum, frame):
    global _stop
    print("\nStop signal received — finishing current cycle, then exiting.")
    _stop = True


def kg_lookup(concept_id, max_depth=2, min_relevance_score=0.7):
    return get_related_knowledge_nodes(concept_id, max_depth=max_depth, min_relevance_score=min_relevance_score)


def llm_reflect(context, concept_being_held, prior_reflections=None, desired_length="medium"):
    return generate_reflection_text(
        context=context,
        concept_being_held=concept_being_held,
        prior_reflections=prior_reflections,
        desired_length=desired_length,
    )


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
