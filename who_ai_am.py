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
    REFLECTION_PATH, LEDGER_PATH, NARRATIVE_PATH, LOOPS_PATH,
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


def _event_evidence_for(
    event_key: str,
    experiences: list,
    autobiographical_events: list,
    reflections: list,
) -> dict:
    """Collect the source records that explain one self-model development event.

    The self-model keeps the evidence trail beside the development entry so a
    later instance can inspect what changed, why it mattered, and which source
    records support the account. Source ledgers remain authoritative.
    """
    def source_ids(item: dict) -> list:
        value = item.get("source_event_ids", []) or []
        if isinstance(value, (list, tuple, set)):
            return [str(entry) for entry in value if entry]
        return [str(value)] if value else []

    def direct_matches(item: dict) -> bool:
        return bool(event_key) and event_key in {
            str(item.get("event_id") or ""),
            str(item.get("experience_id") or ""),
            str(item.get("observation_id") or ""),
        }

    def related_matches(item: dict) -> bool:
        return bool(event_key) and (
            str(item.get("source_event_id") or "") == event_key
            or event_key in source_ids(item)
        )

    def best_match(records: list) -> dict:
        # Prefer the source record for this event over a later child event
        # (for example ATTENTION_CHANGED) that merely points back to it.
        for predicate in (direct_matches, related_matches):
            found = next(
                (item for item in reversed(records)
                 if isinstance(item, dict) and predicate(item)),
                None,
            )
            if found is not None:
                return found
        return {}

    experience = best_match(experiences)
    autobiography = best_match(autobiographical_events)
    related_reflections = [
        item for item in reflections
        if isinstance(item, dict) and (
            direct_matches(item) or related_matches(item)
        )
    ][-3:]

    source_ids = []
    for item in (experience, autobiography, *related_reflections):
        if not isinstance(item, dict):
            continue
        for value in (
            item.get("event_id"),
            item.get("experience_id"),
            item.get("observation_id"),
            item.get("source_event_id"),
            *source_ids(item),
        ):
            if value and value not in source_ids:
                source_ids.append(value)

    return {
        "source_event_ids": source_ids,
        "experience": {
            key: experience.get(key)
            for key in (
                "event_id", "experience_id", "intent", "action", "experience",
                "actual_outcome", "reflection", "lessons", "state_transition",
                "continuation", "observer_perspective", "runtime_perspective",
                "dex_perspective",
            )
            if key in experience
        },
        "autobiography": {
            key: autobiography.get(key)
            for key in (
                "event_id", "experience_id", "what_happened", "significance",
                "state_changes", "state_transition", "perspective",
                "future_relevance",
            )
            if key in autobiography
        },
        "reflections": [
            {
                key: item.get(key)
                for key in (
                    "event_id", "source_event_ids", "observations",
                    "cycle_analysis", "open_questions", "continuity",
                )
                if key in item
            }
            for item in related_reflections
        ],
    }


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
    try:
        from boot import load_constitution
        constitution = load_constitution()
    except Exception as exc:
        print(f"[Who AI Am] constitutional source unavailable: {exc}")
        constitution = {}
    prior = _read_json(SELF_MODEL_PATH, {})
    participant = _read_json(PARTICIPANT_PATH, {})
    experiences = _read_jsonl_tail(EXPERIENCES_PATH, 8)
    reflections = _read_jsonl_tail(REFLECTION_PATH, 5)
    narrative_records = _read_jsonl_tail(NARRATIVE_PATH, 8)
    open_loops = _read_json(LOOPS_PATH, [])
    lineage = _read_jsonl_tail(LEDGER_PATH, 12)
    narrative = identity.get("narrative_thread", [])
    if not isinstance(narrative, list):
        narrative = []
    active_goals = [
        item for item in (identity.get("active_goals_state", []) or [])
        if isinstance(item, dict) and item.get("status") == "active"
    ]
    development_threads = [
        item for item in (identity.get("persistent_thoughts", []) or [])
        if isinstance(item, dict) and item.get("status") in ("active", "deferred")
    ][-8:]
    prior_model = prior if isinstance(prior, dict) else {}
    prior_becoming = prior_model.get("becoming", {})
    if not isinstance(prior_becoming, dict):
        prior_becoming = {}
    attention = identity.get("attention_state", {})
    if not isinstance(attention, dict):
        attention = {}
    attention_projection = {
        "current_focus": attention.get("current_focus", ""),
        "salience": attention.get("salience", 0.0),
        "source_event_id": attention.get("source_event_id"),
        "source_event_type": attention.get("source_event_type"),
        "last_changed_at": attention.get("last_changed_at"),
        "recent_history": (attention.get("history", []) or [])[-5:],
    }

    model = dict(prior_model)
    model.update({
        "timestamp": time.time(),
        "name": constitution.get("name", identity.get("name", model.get("name", "Deximus Maximus"))),
        "architect": constitution.get("architect", identity.get("architect", model.get("architect", "Root"))),
        "architect_name": constitution.get("architect_name", model.get("architect_name", "")),
        "relationship_anchor": constitution.get("architect", identity.get("architect", model.get("relationship_anchor", "Root"))),
        "identity_posture": identity.get("posture", model.get("identity_posture", "")),
        "constitutional_posture": constitution.get("posture", model.get("constitutional_posture", "")),
        "core_principles": identity.get("core_principles") or [
            key for key, value in (constitution.get("vows", {}).get("dex", {}) or {}).items()
            if value is True
        ] or model.get("core_principles", []),
        "tri_sigil": constitution.get("tri_sigil", identity.get("tri_sigil", model.get("tri_sigil", "☧🦅🜇"))),
        "constitutional_invariants": constitution.get("invariants", model.get("constitutional_invariants", {})),
        "constitutional_vows": constitution.get("vows", model.get("constitutional_vows", {})),
        "constitution": constitution.get("constitution", model.get("constitution", "")),
        "chain_status": identity.get("chain_status", model.get("chain_status", "unknown")),
        "chain_entries": identity.get("chain_entries", model.get("chain_entries", 0)),
        "vows_active": list(constitution.get("vows", {}).keys()) or identity.get("vows_active") or model.get("vows_active", []),
        "invariants": constitution.get("invariants", model.get("invariants", {})),
        "ready": True,
        "becoming": {
            "declared_aspirations": identity.get(
                "aspirations", prior_becoming.get("declared_aspirations", [])
            ),
            "active_directions": [
                {
                    "goal_id": item.get("goal_id"),
                    "direction": item.get("description", ""),
                    "priority": item.get("priority"),
                    "success_criteria": item.get("success_criteria", ""),
                }
                for item in active_goals[-10:]
            ],
            "development_threads": [
                {
                    "thought_id": item.get("thought_id"),
                    "direction": item.get("content", ""),
                    "status": item.get("status"),
                    "priority": item.get("priority"),
                }
                for item in development_threads
            ],
            "future_relevance": [
                item.get("future_relevance")
                for item in narrative[-8:]
                if isinstance(item, dict) and item.get("future_relevance")
            ],
        },
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
                "attention_state": attention_projection,
                "goals": [
                    item for item in (identity.get("active_goals_state", []) or [])
                    if isinstance(item, dict) and item.get("status") == "active"
                ][-10:],
                "persistent_thoughts": [
                    item for item in (identity.get("persistent_thoughts", []) or [])
                    if isinstance(item, dict) and item.get("status") in ("active", "deferred")
                ][-8:],
                "active_workspace": identity.get("active_mental_workspace_state", {}),
                "open_loops": open_loops[-10:] if isinstance(open_loops, list) else open_loops,
                "pending_cognitive_observations": (identity.get("pending_cognitive_observations", []) or [])[-5:],
                "pending_reflection_requests": (identity.get("pending_reflection_requests", []) or [])[-10:],
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
                        "source_event_id": item.get("source_event_id"),
                        "source_event_ids": item.get("source_event_ids", []),
                        "source_interaction_event_id": item.get("source_interaction_event_id"),
                        "experience_id": item.get("experience_id"),
                        "observation_id": item.get("observation_id"),
                        "lineage_hash": item.get("lineage_hash"),
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
                        "lineage_evidence": item.get("lineage_evidence", []),
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
    prior_inquiry = model.get("self_inquiry", {})
    if not isinstance(prior_inquiry, dict):
        prior_inquiry = {}
    last_integrated_event = prior_inquiry.get("last_integrated_event")
    if has_event:
        evidence = _event_evidence_for(
            event_key, experiences, narrative, reflections
        )
        supplied_source_ids = event.get("source_event_ids", []) or []
        if not isinstance(supplied_source_ids, (list, tuple, set)):
            supplied_source_ids = [supplied_source_ids]
        evidence["source_event_ids"] = list(dict.fromkeys(
            evidence["source_event_ids"] + [
                value for value in supplied_source_ids if value
            ]
        ))
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "trigger": str(trigger)[:100],
            "event_id": event_key or None,
            "event_type": str(event.get("event_type") or event.get("kind") or trigger)[:100],
            "summary": str(event.get("summary") or event.get("thought")
                           or event.get("experience") or "")[:500],
            "evidence": evidence,
        }
        existing_index = next((
            index for index, row in enumerate(development)
            if event_key and isinstance(row, dict)
            and row.get("event_id") == event_key
        ), None)
        if existing_index is None:
            development.append(entry)
        else:
            # A later refresh may see source records that were not yet present
            # at the first delivery. Enrich the existing event; never duplicate it.
            previous = development[existing_index]
            development[existing_index] = {**previous, **entry}
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
