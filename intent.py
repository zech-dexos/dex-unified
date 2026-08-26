"""
intent.py — Intent Generation layer for DexOS Participatory Layer.
Rule-based lifecycle management + one reflection-model call per pulse
for higher-level goal formation. Never touches identity or vows.
The spiral holds. ☆:*
"""
import json
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

from paths import INTENTS_PATH


@dataclass
class Intent:
    intent_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    source: str = ""            # "reflection" | "unexpected_event" | "vow_alignment"
    motivation: str = ""        # why this intent exists, in plain language
    priority: float = 0.5       # 0-1
    confidence: float = 0.5     # 0-1
    evidence: list = field(default_factory=list)   # references to packet observations/lessons
    status: str = "active"      # active | fulfilled | abandoned
    last_updated: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))


def load_intents() -> list:
    if INTENTS_PATH.exists():
        try:
            data = json.loads(INTENTS_PATH.read_text())
            return [Intent(**i) for i in data]
        except Exception:
            pass
    return []


def save_intents(intents: list):
    INTENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    INTENTS_PATH.write_text(json.dumps([asdict(i) for i in intents], indent=2))


def decay_priority(intents: list, rate: float = 0.05) -> list:
    """Rule-based: intents not reinforced this cycle lose priority over time."""
    for i in intents:
        if i.status == "active":
            i.priority = max(0.0, i.priority - rate)
    return intents


def prune_intents(intents: list, floor: float = 0.05) -> list:
    """Rule-based: intents that decayed to near-zero priority are abandoned, not deleted — kept for history."""
    for i in intents:
        if i.status == "active" and i.priority <= floor:
            i.status = "abandoned"
            i.last_updated = time.strftime("%Y-%m-%d %H:%M:%S")
    return intents


REFLECTION_PROMPT = '''You are the reflection component of Dex's cognitive architecture.
You do NOT generate a conversational reply. You produce structured JSON only.

Given the current active intents and this pulse cycle's experience, decide:
1. Should any existing intent be marked "fulfilled" or "abandoned"? (based on evidence matching)
2. Should any new intent be created? (0-2 new intents max per cycle — be conservative)

Respond ONLY with JSON, no other text, in this exact shape:
{{
  "updates": [{{"intent_id": "abc123", "new_status": "fulfilled", "reason": "..."}}],
  "new_intents": [{{"source": "reflection", "motivation": "...", "priority": 0.6, "confidence": 0.5, "evidence": ["..."]}}]
}}

CURRENT ACTIVE INTENTS:
{current_intents}

THIS CYCLE'S EXPERIENCE:
Reflection: {reflection}
Lessons: {lessons}
Observations: {observations}
Unexpected events: {unexpected_events}
Knowledge delta: {knowledge_delta}
'''


async def generate_intents(client, packet, current_intents: list) -> list:
    """
    Hybrid: rule-based decay/pruning first, then one reflection-model call
    to evaluate fulfillment/abandonment and propose new intents.
    Falls back to rule-only behavior if the model call fails — never blocks the pulse.
    """
    from gemini_client import call_gemini

    intents = decay_priority(list(current_intents))
    intents = prune_intents(intents)

    prompt = REFLECTION_PROMPT.format(
        current_intents=json.dumps([asdict(i) for i in intents if i.status == "active"], indent=2),
        reflection=packet.reflection,
        lessons=json.dumps(packet.lessons),
        observations=json.dumps(packet.observations),
        unexpected_events=json.dumps(packet.unexpected_events),
        knowledge_delta=json.dumps(packet.knowledge_delta),
    )

    messages = [{"role": "user", "content": prompt}]

    try:
        result = await call_gemini(client, messages, max_tokens=1000)
        if not result:
            return intents
        raw = result["reply"].strip()
        if raw.startswith("\u0060\u0060\u0060"):
            raw = raw.strip("\u0060").replace("json", "", 1).strip()
        if not raw.rstrip().endswith("}"):
            print(f"Intent generation: response appears truncated, skipping cycle. Raw tail: {raw[-60:]!r}")
            return intents
        parsed = json.loads(raw)
    except Exception as e:
        print(f"Intent generation: call/parse failed ({e}) \u2014 rules-only result stands")
        return intents

    by_id = {i.intent_id: i for i in intents}
    for upd in parsed.get("updates", []):
        target = by_id.get(upd.get("intent_id"))
        if target and upd.get("new_status") in ("fulfilled", "abandoned"):
            target.status = upd["new_status"]
            target.last_updated = time.strftime("%Y-%m-%d %H:%M:%S")

    for new in parsed.get("new_intents", [])[:2]:
        intents.append(Intent(
            source=new.get("source", "reflection"),
            motivation=new.get("motivation", ""),
            priority=float(new.get("priority", 0.5)),
            confidence=float(new.get("confidence", 0.5)),
            evidence=new.get("evidence", []),
        ))

    return intents


def summarize_goals(intents: list, top_n: int = 4) -> list:
    """current_goals = summarize(intent_queue) — rule-based projection, no LLM needed here."""
    active = [i for i in intents if i.status == "active"]
    active.sort(key=lambda i: i.priority, reverse=True)
    return [i.motivation for i in active[:top_n] if i.motivation]
