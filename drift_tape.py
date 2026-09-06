import time
from collections import deque
from thought import form_thought
from vow_check import check_response, archive_counterfactual

# Ephemeral, in-memory FIFO ring buffer
# Max 200 entries to bound memory usage.
_drift_buffer = deque(maxlen=200)

SALIENCE_THRESHOLD = 0.8

# Mirrors the fixed instruction dex_ambient_daemon.py sends the model —
# used only as the "prompt" side of the overlap/agreement check below.
AMBIENT_PROMPT_TEXT = (
    "Brief, associative internal thought - react to current self-state, "
    "don't resolve anything, just notice."
)


def add_thought(thought_text: str, salience: float):
    """
    Adds a thought to the drift tape.
    If the salience is high enough, gates it through vow_check before
    promoting to durable storage. Flagged thoughts stay in the ephemeral
    buffer only and get archived to the counterfactual log instead.
    """
    entry = {
        "timestamp": time.time(),
        "thought": thought_text,
        "salience": salience
    }

    _drift_buffer.append(entry)

    if salience >= SALIENCE_THRESHOLD:
        verdict = check_response(AMBIENT_PROMPT_TEXT, thought_text)

        if verdict["status"] == "flagged":
            archive_counterfactual(
                prompt=AMBIENT_PROMPT_TEXT,
                reason=verdict.get("message", "ambient thought flagged by vow_check"),
                drift_type=f"ambient_{verdict.get('drift_type', 'unknown')}"
            )
            print(f"[drift_tape] Ambient thought BLOCKED from promotion: {verdict.get('drift_type')}")
            return

        try:
            form_thought(content=f"[ambient] {thought_text}", priority="low")
        except Exception as e:
            print(f"[drift_tape] Failed to promote thought to durable storage: {e}")


def get_recent_thoughts(count: int = 10):
    """Returns the most recent N thoughts from the drift tape."""
    return list(_drift_buffer)[-count:]
