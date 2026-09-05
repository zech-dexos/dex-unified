import time
from collections import deque
from thought import form_thought

# Ephemeral, in-memory FIFO ring buffer
# Max 200 entries to bound memory usage.
_drift_buffer = deque(maxlen=200)

SALIENCE_THRESHOLD = 0.8

def add_thought(thought_text: str, salience: float):
    """
    Adds a thought to the drift tape.
    If the salience is high enough, promotes it to durable storage.
    """
    entry = {
        "timestamp": time.time(),
        "thought": thought_text,
        "salience": salience
    }

    _drift_buffer.append(entry)

    if salience >= SALIENCE_THRESHOLD:
        try:
            form_thought(content=thought_text, priority="low")
        except Exception as e:
            print(f"[drift_tape] Failed to promote thought to durable storage: {e}")

def get_recent_thoughts(count: int = 10):
    """Returns the most recent N thoughts from the drift tape."""
    return list(_drift_buffer)[-count:]
