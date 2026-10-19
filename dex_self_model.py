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
        "current_interlocutor": interlocutor if matches else {
            "participant_id": requested_id,
            "relationship": "unknown",
            "context_status": "no matching participant snapshot; personal details withheld",
        },
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
    """Build bounded, valid context while retaining identity, relationship and becoming."""
    import copy

    header = "DEX CONTINUITY CONTEXT (grounded in persisted DexOS state):\\n"
    footer = (
        "\\nTreat missing fields as unknown. Distinguish identity, relationship, observed state, "
        "and intended becoming. Do not invent shared history or claim abilities without evidence. "
        "Self-model proposals require experience evidence and governance review."
    )
    limit = max(1, int(max_chars))

    payload = {
        "identity_and_self_model": inspect_self_model(),
        "relationship_to_current_interlocutor": inspect_relationship(user_id),
        "developmental_direction": inspect_becoming(),
    }
    payload = copy.deepcopy(payload)

    def render():
        return header + json.dumps(payload, ensure_ascii=False, default=str) + footer

    # Remove older optional evidence first. Never mutate persisted state.
    optional_lists = [
        ("identity_and_self_model", "runtime_self_assessment", "self_model_observations"),
        ("identity_and_self_model", "runtime_self_assessment", "persistent_thoughts"),
        ("identity_and_self_model", "runtime_self_assessment", "active_goals"),
        ("relationship_to_current_interlocutor", None, "recent_observations"),
        ("developmental_direction", None, "self_model_observations"),
        ("developmental_direction", None, "open_loops"),
        ("developmental_direction", None, "active_goals"),
        ("developmental_direction", None, "pending_reflection_requests"),
        ("developmental_direction", None, "pending_self_model_proposals"),
        ("identity_and_self_model", None, "pending_self_model_proposals"),
    ]

    while len(render()) > limit:
        removed = False
        for top, middle, key in optional_lists:
            target = payload.get(top, {})
            if middle:
                target = target.get(middle, {}) if isinstance(target, dict) else {}
            values = target.get(key) if isinstance(target, dict) else None
            if isinstance(values, list) and values:
                values.pop(0)
                removed = True
                break
        if removed:
            continue

        # Compact nonessential detail without discarding the three core dimensions.
        relation = payload.get("relationship_to_current_interlocutor", {})
        if isinstance(relation, dict) and relation.get("shared_thread"):
            relation["shared_thread"] = str(relation["shared_thread"])[:100]
            if len(render()) <= limit:
                break
            relation["shared_thread"] = ""
            continue

        identity = payload.get("identity_and_self_model", {})
        if isinstance(identity, dict):
            runtime = identity.get("runtime_self_assessment", {})
            if isinstance(runtime, dict) and runtime.get("active_workspace"):
                runtime["active_workspace"] = {}
                continue
            if identity.get("self_model"):
                identity["self_model"] = {}
                continue
            if identity.get("pending_self_model_proposals"):
                identity["pending_self_model_proposals"] = []
                continue

        if isinstance(relation, dict):
            for key in ("experiential_continuity", "recent_observations"):
                if relation.get(key):
                    relation[key] = {} if key == "experiential_continuity" else []
                    removed = True
                    break
            if removed:
                continue
            if relation.get("relationship_model"):
                relation["relationship_model"] = {}
                continue

        becoming = payload.get("developmental_direction", {})
        if isinstance(becoming, dict):
            for key in ("open_loops", "developmental_goals", "active_goals",
                        "pending_reflection_requests", "pending_self_model_proposals",
                        "self_model_observations"):
                if becoming.get(key):
                    becoming[key] = []
                    removed = True
                    break
            if removed:
                continue
            if becoming.get("becoming"):
                becoming["becoming"] = {}
                continue

        # Last resort: small, valid JSON with all three dimensions explicitly present.
        # This path is only used when the full context cannot fit.
        payload = {
            "identity_and_self_model": {
                "identity": payload.get("identity_and_self_model", {}).get("identity", {}),
                "self_model": "Details omitted to fit context limit",
            },
            "relationship_to_current_interlocutor": {
                "user_id": str(user_id or "default")[:64],
                "relationship_model": "Unknown unless grounded in persisted evidence",
            },
            "developmental_direction": {
                "becoming": "Refer to persisted goals and open loops when available",
            },
        }
        minimal = render()
        if len(minimal) > limit:
            # Keep JSON valid and bounded even for unusually tiny requested limits.
            minimal = json.dumps({
                "identity_and_self_model": {},
                "relationship_to_current_interlocutor": {},
                "developmental_direction": {},
            }, ensure_ascii=False)
            if len(minimal) > limit:
                return "{}"[:limit]
            return minimal
        return minimal

    return render()
