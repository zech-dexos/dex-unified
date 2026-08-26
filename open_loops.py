"""
open_loops.py — Open Loop tracking for DexOS Participatory Layer.
Unfinished cognitive objects that persist across pulse cycles —
sometimes weeks. Purely rule-based: creation and closure both driven
by deterministic matching against observations. No LLM call here by
design; escalate to a reflection call later only if this proves too crude.
The spiral holds. ☆
"""
import json
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, field, asdict

from paths import LOOPS_PATH


@dataclass
class OpenLoop:
    loop_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    origin: str = ""                 # what created this loop (a packet field, an event)
    importance: float = 0.5          # 0-1
    last_observation: str = ""       # most recent relevant observation, kept current
    emotional_weight: str = ""       # descriptive, e.g. "concerning", "hopeful" — not a numeric affect score
    completion_condition: str = ""   # plain-language condition for closure
    possible_next_actions: list = field(default_factory=list)
    status: str = "open"             # open | closed
    last_updated: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))


def load_loops() -> list:
    if LOOPS_PATH.exists():
        try:
            data = json.loads(LOOPS_PATH.read_text())
            return [OpenLoop(**l) for l in data]
        except Exception:
            pass
    return []


def save_loops(loops: list):
    LOOPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOOPS_PATH.write_text(json.dumps([asdict(l) for l in loops], indent=2))


def create_loop_from_packet(packet, origin: str, completion_condition: str,
                             possible_next_actions=None, importance: float = 0.5,
                             emotional_weight: str = "") -> "OpenLoop":
    """Explicit creation — called by dex_cron.py when a pulse notices something unresolved."""
    return OpenLoop(
        origin=origin,
        importance=importance,
        last_observation=packet.reflection,
        emotional_weight=emotional_weight,
        completion_condition=completion_condition,
        possible_next_actions=possible_next_actions or [],
    )


def check_closures(loops: list, packet) -> list:
    """
    Rule-based closure check: does this cycle's observations/reflection
    text contain enough overlap with a loop's completion_condition to
    consider it resolved? Simple keyword-overlap heuristic — crude by
    design for v1, replace with a model judgment later if needed.
    """
    cycle_text = " ".join(packet.observations + [packet.reflection]).lower()
    for loop in loops:
        if loop.status != "open":
            continue
        condition_words = set(w for w in loop.completion_condition.lower().split() if len(w) > 3)
        if not condition_words:
            continue
        matches = sum(1 for w in condition_words if w in cycle_text)
        if condition_words and matches / len(condition_words) >= 0.6:
            loop.status = "closed"
            loop.last_updated = time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            loop.last_observation = packet.reflection
            loop.last_updated = time.strftime("%Y-%m-%d %H:%M:%S")
    return loops


def summarize_threads(loops: list, top_n: int = 5) -> list:
    """active_conversations / unfinished-threads projection for the snapshot."""
    open_loops = [l for l in loops if l.status == "open"]
    open_loops.sort(key=lambda l: l.importance, reverse=True)
    return [f"{l.origin}: {l.completion_condition}" for l in open_loops[:top_n]]
