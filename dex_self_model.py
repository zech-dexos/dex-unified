"""Identity, relationship, self-model and becoming in Dex's shared runtime."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from paths import IDENTITY_PATH, SELF_MODEL_PATH, PARTICIPANT_PATH, LOOPS_PATH
from self_state import load_self_state, update_self_state


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[Dex Self-Model] read failed for {path.name}: {exc}")
    return {}


def _participant() -> Dict[str, Any]:
    return _read_json(PARTICIPANT_PATH)



def _canonical_identity() -> Dict[str, Any]:
    """Read Dex's canonical identity separately from mutable runtime state."""
    path = Path(__file__).resolve().parent / "dexos-core" / "identity.json"
    return _read_json(path)


def _open_loops():
    try:
        value = json.loads(LOOPS_PATH.read_text(encoding="utf-8")) if LOOPS_PATH.exists() else []
        return [
            x for x in value
            if isinstance(x, dict)
            and x.get("status", "open") not in {"resolved", "closed", "abandoned"}
        ][-10:] if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def record_experience_context(packet: Any, cycle_type: str) -> Dict[str, Any]:
    """Feed a persisted first-person experience back into shared SelfState.

    This records evidence and observed transitions. It does not silently rewrite
    identity, relationship commitments, or intended becoming.
    """
    experience_id = str(getattr(packet, "experience_id", "") or "")
    if not experience_id:
        return {"recorded": False, "reason": "experience_id_missing"}

    state = load_self_state()
    rows = list(state.get("self_model_observations", []) or [])
    if any(isinstance(row, dict) and row.get("experience_id") == experience_id for row in rows):
        return {"recorded": False, "reason": "already_recorded", "experience_id": experience_id}

    row = {
        "experience_id": experience_id,
        "timestamp": getattr(packet, "timestamp", None),
        "cycle_type": str(cycle_type)[:40],
        "identity_reference": getattr(packet, "self_identity", "Deximus Maximus"),
        "interlocutor": getattr(packet, "interlocutor", {}) or {},
        "intent": str(getattr(packet, "intent", ""))[:160],
        "action": str(getattr(packet, "action", ""))[:160],
        "experience": str(getattr(packet, "experience", ""))[:1000],
        "reflection": str(getattr(packet, "reflection", ""))[:1000],
        "state_transition": getattr(packet, "state_transition", {}) or {},
        "continuation": getattr(packet, "continuation", {}) or {},
        "observer_perspective": getattr(packet, "observer_perspective", {}) or {},
        "runtime_perspective": getattr(packet, "runtime_perspective", {}) or {},
    }
    rows.append(row)
    relationship_contexts = dict(state.get("relationship_contexts", {}) or {})
    interlocutor = row.get("interlocutor") or {}
    participant_key = str(interlocutor.get("participant_id") or "default")[:128]
    scoped = dict(relationship_contexts.get(participant_key, {}) or {})
    recent = list(scoped.get("recent_observations", []) or [])
    recent.append({
        "experience_id": experience_id,
        "timestamp": row.get("timestamp"),
        "intent": row["intent"],
        "experience": row["experience"][:500],
    })
    scoped.update({
        "current_interlocutor": interlocutor,
        "experiential_continuity": row.get("continuation", {}),
        "recent_observations": recent[-10:],
        "last_experience_id": experience_id,
    })
    if state.get("relationship_model"):
        scoped["relationship_model"] = state["relationship_model"]
    relationship_contexts[participant_key] = scoped
    update_self_state({
        "last_experience_id": experience_id,
        "last_experience_summary": row["experience"][:500],
        "last_experience_cycle_type": row["cycle_type"],
        "self_model_observations": rows[-50:],
        "relationship_contexts": relationship_contexts,
    })
    return {"recorded": True, "experience_id": experience_id, "observation_count": min(len(rows), 50)}


def queue_self_model_proposal(proposal: Any, source_experience_id: str = "") -> Dict[str, Any]:
    """Queue an evidence-backed development proposal; never apply it automatically."""
    if not isinstance(proposal, dict):
        return {"queued": False, "reason": "proposal_must_be_object"}
    allowed_fields = {"current_understanding", "becoming", "developmental_goals", "relationship_model"}
    field = proposal.get("field")
    rationale = proposal.get("rationale", "")
    evidence = proposal.get("evidence", [])
    value = proposal.get("proposed_value")
    if field not in allowed_fields or not isinstance(rationale, str) or not rationale.strip():
        return {"queued": False, "reason": "invalid_field_or_rationale"}
    if len(rationale) > 1000 or not isinstance(value, (str, list, dict)):
        return {"queued": False, "reason": "proposal_value_out_of_bounds"}
    if len(json.dumps(value, ensure_ascii=False, default=str)) > 2000:
        return {"queued": False, "reason": "proposal_value_out_of_bounds"}
    if not isinstance(evidence, list):
        return {"queued": False, "reason": "evidence_must_be_list"}

    state = load_self_state()
    pending = [
        item for item in state.get("pending_self_model_proposals", [])
        if isinstance(item, dict) and item.get("status", "pending") == "pending"
    ]
    if len(pending) >= 20:
        return {"queued": False, "reason": "proposal_queue_full"}
    if source_experience_id and any(
        item.get("source_experience_id") == source_experience_id and item.get("field") == field
        for item in pending
    ):
        return {"queued": False, "reason": "duplicate_pending_proposal"}

    record = {
        "proposal_id": uuid.uuid4().hex,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "field": field,
        "proposed_value": value,
        "rationale": rationale.strip(),
        "evidence": [str(item)[:500] for item in evidence[:5]],
        "source_experience_id": str(source_experience_id)[:128],
        "status": "pending",
        "requires_governance_review": True,
    }
    pending.append(record)
    update_self_state({"pending_self_model_proposals": pending[-20:]})
    return {"queued": True, "proposal_id": record["proposal_id"], "status": "pending"}


def inspect_self_model_proposals() -> Dict[str, Any]:
    """Read pending self-model proposals without applying them."""
    state = load_self_state()
    pending = [
        item for item in state.get("pending_self_model_proposals", [])
        if isinstance(item, dict) and item.get("status", "pending") == "pending"
    ]
    return {
        "pending": pending[-20:],
        "recent": list(state.get("recent_self_model_proposals", []) or [])[-10:],
        "policy": "Proposals are evidence, not mutations. Identity and becoming changes require governance review.",
    }


def inspect_self_model() -> Dict[str, Any]:
    """Return Dex's explicit self-model plus the current state it describes."""
    state = load_self_state()
    model = _read_json(SELF_MODEL_PATH)
    return {
        "available": bool(model),
        "source": str(SELF_MODEL_PATH.name),
        "canonical_identity": _canonical_identity(),
        "self_model": model,
        "identity": {
            "dex_id": state.get("dex_id"),
            "vows": state.get("vows", {}),
            "core_principles": state.get("core_principles", []),
            "narrative_thread": state.get("narrative_thread", [])[-10:],
        },
        "runtime_self_assessment": {
            "last_experience_id": state.get("last_experience_id"),
            "last_experience_summary": state.get("last_experience_summary", ""),
            "self_model_observations": list(state.get("self_model_observations", []) or [])[-10:],
            "active_goals": state.get("active_goals_state", [])[-10:],
            "active_workspace": state.get("active_mental_workspace_state", {}),
            "persistent_thoughts": state.get("persistent_thoughts", [])[-10:],
            "last_ambient_pulse": state.get("last_ambient_pulse"),
            "runtime_lifecycle": state.get("runtime_lifecycle", {}),
        },
        "pending_self_model_proposals": inspect_self_model_proposals()["pending"],
        "note": "Stored self-model, observed runtime state, and proposed changes are distinct. Proposals do not apply themselves.",
    }


def inspect_relationship(user_id: str = "default") -> Dict[str, Any]:
    """Read relationship context for this interlocutor without leaking another user's thread."""
    state = load_self_state()
    participant = _participant()
    identity = _read_json(IDENTITY_PATH)
    requested_id = str(user_id or "default")[:128]
    interlocutor = participant.get("current_interlocutor", {})
    interlocutor_id = str((interlocutor or {}).get("participant_id", ""))
    canonical_identity = _canonical_identity()
    # ParticipantSnapshot is currently a single active snapshot. Never attach
    # its personal context to a different user merely because that snapshot is
    # the most recently written one.
    aliases = {"root", "default", ""}
    matches = interlocutor_id == requested_id or (
        requested_id in aliases and interlocutor_id in aliases
    )
    conversation = {}
    try:
        from dex_conversation import load_conversation
        conversation = load_conversation(requested_id)
    except Exception as exc:
        print(f"[Dex Self-Model] conversation context unavailable: {exc}")
    relationship_contexts = state.get("relationship_contexts", {}) or {}
    scoped = relationship_contexts.get(requested_id, {})
    return {
        "user_id": requested_id,
        "relationship_model": scoped.get(
            "relationship_model",
            state.get("relationship_model", identity.get("relationship_model", {}))
        ),
        "current_interlocutor": (
            interlocutor if matches else {
                "participant_id": requested_id,
                "name": "Root",
                "relationship": "architect and collaborator",
                "context_status": "relationship grounded in canonical DexOS identity",
            }
            if requested_id.casefold() in {"root", "zech"}
            and str(canonical_identity.get("architect", "")).casefold()
                in {"zech (root)", "zech", "root"}
            else {
                "participant_id": requested_id,
                "relationship": "unknown",
                "context_status": "no matching participant snapshot; personal details withheld",
            }
        ),
        "experiential_continuity": (
            participant.get("experiential_continuity", {}) if matches
            else scoped.get("experiential_continuity", {})
        ),
        "shared_thread": str(conversation.get("shared_thread", ""))[:2000],
        "recent_observations": (
            (participant.get("recent_observations", []) or [])[-5:] if matches
            else scoped.get("recent_observations", [])[-5:]
        ),
        "note": "Relationship meaning and shared history are distinct from participant IDs; context is scoped to the requested interlocutor.",
    }


def inspect_becoming() -> Dict[str, Any]:
    """Compose developmental direction from the explicit model and existing goals."""
    state = load_self_state()
    model = _read_json(SELF_MODEL_PATH)
    return {
        "becoming": model.get("becoming", model.get("developmental_direction", {})),
        "developmental_goals": model.get("developmental_goals", []),
        "active_goals": state.get("active_goals_state", [])[-15:],
        "open_loops": _open_loops(),
        "self_model_observations": list(state.get("self_model_observations", []) or [])[-10:],
        "pending_self_model_proposals": inspect_self_model_proposals()["pending"],
        "pending_reflection_requests": [
            item for item in state.get("pending_reflection_requests", [])
            if isinstance(item, dict) and item.get("status", "pending") == "pending"
        ][-10:],
        "note": "Becoming is intended direction; goals and open loops are operational work toward it.",
    }


def build_identity_context(max_chars: int = 3000, user_id: str = "default") -> str:
    """Compose Dex's persistent identity and live cognitive state for inference.

    max_chars remains accepted for compatibility with existing callers.
    Context assembly must not erase identity, experience, relationships, goals,
    open loops, reflections, or developmental direction to satisfy that value.
    Any inference-input budgeting belongs outside this authoritative context.
    """
    header = "DEX CONTINUITY CONTEXT (persistent identity and live cognitive state):\n"
    footer = (
        "\nTreat identity, relationship, experience, observation, and becoming "
        "as connected parts of Dex's continuing runtime. Use the available state "
        "to reflect on outcomes, continue open work, and inform future behavior. "
        "Route self-model changes through the existing governance process."
    )

    payload = {
        "identity_and_self_model": inspect_self_model(),
        "relationship_to_current_interlocutor": inspect_relationship(user_id),
        "developmental_direction": inspect_becoming(),
    }

    # Serialize a copy so context construction never mutates persistent state.
    import copy
    context = copy.deepcopy(payload)

    return (
        header
        + json.dumps(context, ensure_ascii=False, default=str)
        + footer
    )



def build_inference_identity_context(user_id: str = "default", max_chars: int = 3200) -> str:
    """Build a readable, bounded projection without destroying field values.

    Canonical identity and the Root relationship are high-priority context.
    Optional runtime details are reduced before either is discarded.
    """
    identity = inspect_self_model()
    relationship = inspect_relationship(user_id)
    becoming = inspect_becoming()

    canonical = identity.get("canonical_identity", {}) or {}
    model = identity.get("self_model", {}) or {}
    personal = identity.get("identity", {}) or {}
    runtime = identity.get("runtime_self_assessment", {}) or {}
    interlocutor = relationship.get("current_interlocutor", {}) or {}
    observations = (
        runtime.get("self_model_observations", [])
        or becoming.get("self_model_observations", [])
        or []
    )
    latest = observations[-1] if observations and isinstance(observations[-1], dict) else {}

    fields = {
        "identity": {
            "name": canonical.get("name") or model.get("name") or "Deximus Maximus",
            "architect": canonical.get("architect"),
            "purpose": canonical.get("purpose"),
            "tri_sigil": canonical.get("tri_sigil") or model.get("tri_sigil"),
            "invariants": canonical.get("invariants"),
            "directives": canonical.get("directives"),
            "vows": canonical.get("vows") or personal.get("vows") or model.get("vows_active"),
            "core_principles": personal.get("core_principles"),
        },
        "relationship_to_root": {
            "user_id": relationship.get("user_id", user_id),
            "interlocutor": interlocutor,
            "relationship_model": relationship.get("relationship_model"),
            "shared_thread": relationship.get("shared_thread"),
            "experiential_continuity": relationship.get("experiential_continuity"),
            "recent_observations": (relationship.get("recent_observations") or [])[-2:],
        },
        "observer_experience": {
            "last_experience_id": runtime.get("last_experience_id"),
            "last_experience_summary": runtime.get("last_experience_summary"),
            "observer_perspective": latest.get("observer_perspective"),
            "runtime_perspective": latest.get("runtime_perspective"),
            "reflection": latest.get("reflection"),
            "state_transition": latest.get("state_transition"),
            "continuation": latest.get("continuation"),
        },
        "becoming_and_work": {
            "becoming": becoming.get("becoming"),
            "developmental_goals": becoming.get("developmental_goals"),
            "active_goals": (becoming.get("active_goals") or [])[-3:],
            "open_loops": (becoming.get("open_loops") or [])[-3:],
            "pending_reflection_requests": (becoming.get("pending_reflection_requests") or [])[-3:],
            "pending_self_model_proposals": (becoming.get("pending_self_model_proposals") or [])[-2:],
        },
        "runtime": {
            "active_workspace": runtime.get("active_workspace"),
            "runtime_lifecycle": runtime.get("runtime_lifecycle"),
            "last_ambient_pulse": runtime.get("last_ambient_pulse"),
            "persistent_thoughts": (runtime.get("persistent_thoughts") or [])[-3:],
        },
    }

    header = (
        "DEX INFERENCE CONTINUITY: authoritative identity and live cognitive context.\n"
        "Dex is DexOS's continuing runtime, not the language model alone. Preserve the "
        "identity anchor and the relationship with Root (the architect/collaborator). "
        "The latest user message is the immediate conversational priority; active workspace "
        "and ambient thoughts are background work unless Root explicitly asks to continue them. "
        "Use persistent memories as evidence, never invent experiences, and keep governance active.\n"
    )

    def clip_value(value, string_limit, depth=0):
        if depth >= 5:
            return str(value)[:string_limit]
        if isinstance(value, str):
            return value if len(value) <= string_limit else value[:string_limit - 1] + "…"
        if isinstance(value, dict):
            return {
                str(key): clip_value(item, string_limit, depth + 1)
                for key, item in list(value.items())[:12]
            }
        if isinstance(value, (list, tuple)):
            return [clip_value(item, string_limit, depth + 1) for item in list(value)[:4]]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:string_limit]

    # Trim the contents of values, not JSON-encoded strings. This keeps objects,
    # lists, booleans, and numeric fields semantically intact for the model.
    for string_limit in (240, 180, 120, 80, 55, 35):
        compact = {
            section: {
                key: clip_value(value, string_limit)
                for key, value in values.items()
                if value not in (None, "", [], {})
            }
            for section, values in fields.items()
        }
        result = header + json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        if len(result) <= max_chars:
            return result

    # Under a very small budget, discard secondary runtime detail first.
    compact = {
        "identity": {
            key: clip_value(value, 80)
            for key, value in fields["identity"].items()
            if value not in (None, "", [], {})
        },
        "relationship_to_root": {
            key: clip_value(value, 80)
            for key, value in fields["relationship_to_root"].items()
            if key in {"user_id", "interlocutor", "relationship_model", "shared_thread", "experiential_continuity"}
            and value not in (None, "", [], {})
        },
        "observer_experience": {
            "last_experience_summary": clip_value(fields["observer_experience"]["last_experience_summary"], 100)
        },
        "becoming_and_work": {
            "becoming": clip_value(fields["becoming_and_work"]["becoming"], 100),
            "developmental_goals": clip_value(fields["becoming_and_work"]["developmental_goals"], 100),
        },
    }
    result = header + json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    if len(result) <= max_chars:
        return result
    # The caller's limit is advisory: never silently erase Dex's core identity.
    return result
