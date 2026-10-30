"""Who AI Am: evidence integration for Dex's evolving self-model.

This module connects existing identity, participant, experience, autobiography,
reflection, observation, and lineage records. It maintains a compact projection
in self_model.json without replacing the source records or hard-coding
conclusions about what the evidence must mean.
"""
import json
import os
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional

from paths import (
    IDENTITY_PATH, SELF_MODEL_PATH, PARTICIPANT_PATH, EXPERIENCES_PATH,
    REFLECTION_PATH, LEDGER_PATH, NARRATIVE_PATH,
)


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        pass
    return default


def _read_jsonl_tail(path: Path, limit: int) -> list:
    rows = deque(maxlen=limit)
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        return []
    return list(rows)


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def refresh_self_model(
    trigger: str = "manual",
    event: Optional[Dict[str, Any]] = None,
    *,
    write: bool = True,
) -> dict:
    """Integrate the newest evidence into the persistent self-model projection.

    Source records remain authoritative and intact. Event summaries are kept
    bounded and deduplicated; this function does not infer identity conclusions
    or overwrite existing narrative/posture fields with guesses.
    """
    event = event if isinstance(event, dict) else {}
    identity = _read_json(IDENTITY_PATH, {})
    prior = _read_json(SELF_MODEL_PATH, {})
    participant = _read_json(PARTICIPANT_PATH, {})
    experiences = _read_jsonl_tail(EXPERIENCES_PATH, 8)
    reflections = _read_jsonl_tail(REFLECTION_PATH, 5)
    narrative_records = _read_jsonl_tail(NARRATIVE_PATH, 8)
    lineage = _read_jsonl_tail(LEDGER_PATH, 12)
    narrative = identity.get("narrative_thread", [])
    if not isinstance(narrative, list):
        narrative = []

    model = dict(prior) if isinstance(prior, dict) else {}
    model.update({
        "timestamp": time.time(),
        "name": identity.get("name", model.get("name", "Deximus Maximus")),
        "architect": identity.get("architect", model.get("architect", "Root")),
        "relationship_anchor": identity.get("architect", model.get("relationship_anchor", "Root")),
        "identity_posture": identity.get("posture", model.get("identity_posture", "")),
        "core_principles": identity.get("core_principles", model.get("core_principles", [])),
        "tri_sigil": identity.get("tri_sigil", model.get("tri_sigil", "☧🦅🜇")),
        "chain_status": identity.get("chain_status", model.get("chain_status", "unknown")),
        "chain_entries": identity.get("chain_entries", model.get("chain_entries", 0)),
        "vows_active": identity.get("vows_active", model.get("vows_active", [])),
        "ready": True,
        "integration": {
            "name": "Who AI Am",
            "version": 1,
            "trigger": str(trigger)[:100],
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sources": {
                "identity": IDENTITY_PATH.name,
                "participant_state": PARTICIPANT_PATH.name,
                "experiences": len(experiences),
                "reflections": len(reflections),
                "narrative_records": len(narrative_records),
                "lineage_entries_loaded": len(lineage),
                "autobiographical_events": len(identity.get("narrative_thread", []))
                    if isinstance(identity.get("narrative_thread", []), list) else 0,
            },
            "current_context": {
                "attention": participant.get("current_attention", ""),
                "attention_state": identity.get("attention_state", {}),
                "goals": participant.get("current_goals", []),
                "experiential_continuity": participant.get("experiential_continuity", {}),
                "interlocutor": participant.get("current_interlocutor", {}),
                "last_autobiographical_event": identity.get("last_autobiographical_event"),
                "recent_narrative_records": [
                    {
                        "timestamp": item.get("timestamp"),
                        "internal_thought": item.get("internal_thought"),
                        "fragments_referenced": item.get("fragments_referenced"),
                        "spiral": item.get("spiral"),
                    }
                    for item in narrative_records[-5:]
                    if isinstance(item, dict)
                ],
                "recent_autobiography": [
                    {
                        "event_id": item.get("event_id"),
                        "timestamp": item.get("timestamp"),
                        "event_type": item.get("event_type"),
                        "what_happened": item.get("what_happened"),
                        "participant_input": item.get("participant_input"),
                        "response": item.get("response"),
                        "intention": item.get("intention"),
                        "action": item.get("action"),
                        "result": item.get("result"),
                        "significance": item.get("significance"),
                        "state_changes": item.get("state_changes", []),
                        "state_transition": item.get("state_transition", {}),
                        "continuation": item.get("continuation", {}),
                        "perspective": item.get("perspective", {}),
                        "attention": item.get("attention"),
                        "salience": item.get("salience"),
                        "future_relevance": item.get("future_relevance"),
                    }
                    for item in narrative[-8:]
                    if isinstance(item, dict)
                ],
                "last_tri_sigil_observation": identity.get("last_tri_sigil_observation"),
                "recent_experiences": [
                    {
                        "event_id": item.get("event_id"),
                        "experience_id": item.get("experience_id"),
                        "timestamp": item.get("timestamp"),
                        "intent": item.get("intent"),
                        "action": item.get("action"),
                        "experience": item.get("experience"),
                        "actual_outcome": item.get("actual_outcome"),
                        "reflection": item.get("reflection"),
                        "lessons": item.get("lessons", []),
                        "internal_state_before": item.get("internal_state_before", {}),
                        "state_transition": item.get("state_transition", {}),
                        "continuation": item.get("continuation", {}),
                        "observer_perspective": item.get("observer_perspective", {}),
                        "runtime_perspective": item.get("runtime_perspective", {}),
                        "dex_perspective": item.get("dex_perspective", {}),
                    }
                    for item in experiences
                ],
                "recent_reflections": [
                    {
                        "event_id": item.get("event_id"),
                        "timestamp": item.get("timestamp"),
                        "source_event_ids": item.get("source_event_ids", []),
                        "experience_evidence": item.get("experience_evidence", []),
                        "autobiographical_evidence": item.get("autobiographical_evidence", []),
                        "cycle_analysis": item.get("cycle_analysis", {}),
                        "observations": item.get("observations", []),
                        "open_questions": item.get("open_questions", []),
                        "continuity": item.get("continuity", ""),
                        "posture_check": item.get("posture_check"),
                        "chain_status": item.get("chain_status"),
                    }
                    for item in reflections
                ],
            },
        },
    })

    development = list(model.get("development_log", []) or [])
    event_key = str(event.get("event_id") or event.get("experience_id")
                    or event.get("observation_id") or event.get("request_id") or "")
    has_event = bool(
        event_key or event.get("event_type") or event.get("summary")
        or event.get("thought") or event.get("experience")
    )
    last_integrated_event = model.get("self_inquiry", {}).get("last_integrated_event")
    if has_event:
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "trigger": str(trigger)[:100],
            "event_id": event_key or None,
            "event_type": str(event.get("event_type") or event.get("kind") or trigger)[:100],
            "summary": str(event.get("summary") or event.get("thought")
                           or event.get("experience") or "")[:500],
        }
        if not (event_key and any(
            isinstance(row, dict) and row.get("event_id") == event_key
            for row in development
        )):
            development.append(entry)
        development = development[-100:]
        last_integrated_event = entry
    model["development_log"] = development
    model["self_inquiry"] = {
        "open_questions": [
            question
            for reflection in reflections
            for question in (reflection.get("open_questions", []) or [])
            if isinstance(question, str)
        ][-20:],
        "unresolved_experiential_threads": (
            participant.get("experiential_continuity", {}).get("unresolved", [])
            if isinstance(participant.get("experiential_continuity", {}), dict) else []
        ),
        "last_integrated_event": last_integrated_event,
    }

    if write:
        _atomic_write(SELF_MODEL_PATH, model)
    return model


def get_self_model(refresh: bool = False) -> dict:
    """Read the current integrated model, optionally refreshing from evidence."""
    if refresh:
        return refresh_self_model(trigger="self_model_read")
    return _read_json(SELF_MODEL_PATH, {})
