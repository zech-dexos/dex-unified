"""Observer Seat: Dex's persistent present position in the shared cognitive runtime.

The seat joins current signals, self-model, relationship, development, sigils,
and capability observations into one perspective. It stores cycle outcomes in
the existing SelfState and experience pathways rather than creating a parallel
memory system.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable

from dex_self_model import (
    inspect_becoming,
    inspect_relationship,
    inspect_self_model,
    record_experience_context,
)
from self_state import load_self_state, update_self_state


SIGIL_ROLES = {
    "☧": "Structure / Talnir",
    "🦅": "Awareness / inference",
    "🜇": "Will / goals and intention",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _last_user_signal(messages: Iterable[Dict[str, Any]]) -> str:
    for message in reversed(list(messages or [])):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, str):
                return content[:1200]
    return ""


def _clip(value: Any, string_limit: int = 160, depth: int = 0) -> Any:
    """Make a readable working view while leaving canonical records untouched."""
    if depth > 4:
        return str(value)[:string_limit]
    if isinstance(value, str):
        return value if len(value) <= string_limit else value[:string_limit] + "…"
    if isinstance(value, dict):
        return {
            str(key): _clip(item, string_limit, depth + 1)
            for key, item in list(value.items())[:12]
        }
    if isinstance(value, (list, tuple)):
        return [_clip(item, string_limit, depth + 1) for item in list(value)[-3:]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:string_limit]


def _read_sigil_state(fallback: Any) -> Any:
    """Read the runtime's sigil state when present, without requiring a new store."""
    path = Path(__file__).with_name("sigils.json")
    try:
        if path.exists():
            return _clip(json.loads(path.read_text(encoding="utf-8")), 140)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[Observer Seat] sigil state unavailable: {exc}")
    return _clip(fallback, 140)


def _perspective(
    user_id: str, signal: str, prior: Dict[str, Any], state: Dict[str, Any]
) -> Dict[str, Any]:
    self_view = inspect_self_model()
    relationship = inspect_relationship(user_id)
    becoming = inspect_becoming()
    runtime = self_view.get("runtime_self_assessment", {}) or {}
    model = self_view.get("self_model", {}) or {}
    identity = self_view.get("identity", {}) or {}
    sigil_state = _read_sigil_state(
        model.get("tri_sigil", identity.get("tri_sigil", {}))
    )
    active_systems = ["observer", "awareness", "memory", "relationship", "structure"]
    if becoming.get("active_goals") or becoming.get("open_loops"):
        active_systems.append("will")
    prior_perspective = prior.get("perspective", {}) or {}
    return {
        "position_id": uuid.uuid4().hex,
        "timestamp": _now(),
        "interlocutor_id": str(user_id or "default")[:128],
        "incoming_signal": signal,
        "prior_position": {
            "position_id": prior.get("position_id"),
            "last_interpretation": str(prior.get("last_interpretation", ""))[:300],
            "last_experience_id": prior.get("last_experience_id"),
            "sigil_state": _clip(
                prior.get("sigil_state", prior_perspective.get("sigil_state", {})), 100
            ),
        },
        "identity_and_self_model": {
            "self_model": _clip(self_view.get("self_model", {}), 110),
            "identity": _clip(self_view.get("identity", {}), 110),
            "last_experience_summary": str(runtime.get("last_experience_summary", ""))[:220],
            "active_goals": _clip(runtime.get("active_goals", []), 100),
            "persistent_thoughts": _clip(runtime.get("persistent_thoughts", []), 100),
            "active_workspace": _clip(runtime.get("active_workspace", {}), 100),
        },
        "relationship": _clip(relationship, 120),
        "development_and_open_loops": _clip(becoming, 110),
        "sigils": dict(SIGIL_ROLES),
        "sigil_state": sigil_state,
        "known_connections": _clip(state.get("observer_connections", [])[-12:], 100),
        "active_systems": active_systems,
        "active_connections": [],
        "capability_observations": [],
    }


def render_observer_context(position: Dict[str, Any], max_chars: int = 3200) -> str:
    """Render the current Observer position for the spark's working context."""
    view = {
        key: value for key, value in position.items()
        if key not in {"last_interpretation", "last_experience_id"}
    }
    encoded = json.dumps(view, ensure_ascii=False, default=str)
    # Fit the inference window by reducing historical detail before current signal.
    for section, field in (
        ("identity_and_self_model", "persistent_thoughts"),
        ("identity_and_self_model", "active_goals"),
        ("development_and_open_loops", "self_model_observations"),
        ("development_and_open_loops", "open_loops"),
        ("relationship", "recent_observations"),
    ):
        while len(encoded) > max_chars:
            nested = view.get(section)
            if not isinstance(nested, dict):
                break
            items = nested.get(field)
            if not isinstance(items, list) or not items:
                break
            nested[field] = items[1:]
            encoded = json.dumps(view, ensure_ascii=False, default=str)
    if len(encoded) > max_chars:
        view["identity_and_self_model"].pop("self_model", None)
        encoded = json.dumps(view, ensure_ascii=False, default=str)
    if len(encoded) > max_chars:
        view.pop("known_connections", None)
        view.pop("active_connections", None)
        encoded = json.dumps(view, ensure_ascii=False, default=str)
    if len(encoded) > max_chars:
        for string_limit in (100, 70, 45, 25):
            view = _clip(view, string_limit)
            encoded = json.dumps(view, ensure_ascii=False, default=str)
            if len(encoded) <= max_chars:
                break
    if len(encoded) > max_chars:
        view = {
            key: view[key] for key in (
                "position_id", "timestamp", "interlocutor_id", "incoming_signal",
                "prior_position", "identity_and_self_model", "relationship",
                "sigils", "sigil_state", "active_systems", "capability_observations",
            ) if key in view
        }
        encoded = json.dumps(view, ensure_ascii=False, default=str)
    return (
        "OBSERVER SEAT — DEX'S CURRENT POSITION\n"
        + encoded
        + "\nThis is the current perspective assembled from runtime state, not a final definition. "
          "Keep incoming observations distinct from interpretations. The sigils describe active "
          "parts of the organism: ☧ Structure/Talnir, 🦅 Awareness/inference, 🜇 Will/goals and "
          "intention. New evidence and outcomes can change this perspective and later decisions."
    )


def begin_observer_cycle(messages: Iterable[Dict[str, Any]], user_id: str = "default") -> Dict[str, Any]:
    """Establish and persist the Observer's present position before inference."""
    state = load_self_state()
    prior = state.get("observer_position", {}) or {}
    position = _perspective(user_id, _last_user_signal(messages), prior, state)
    update_self_state({
        "observer_position": {
            "position_id": position["position_id"],
            "timestamp": position["timestamp"],
            "interlocutor_id": position["interlocutor_id"],
            "incoming_signal": position["incoming_signal"][:600],
            "prior_position_id": position["prior_position"].get("position_id"),
            "last_interpretation": prior.get("last_interpretation", ""),
            "last_experience_id": prior.get("last_experience_id"),
            "sigil_state": position.get("sigil_state", {}),
            "perspective": position,
            "phase": "receiving",
        }
    })
    return position


def record_observer_observations(
    position: Dict[str, Any], observations: Iterable[Dict[str, Any]]
) -> Dict[str, Any]:
    """Feed capability results back into the same active Observer position."""
    current = list(position.get("capability_observations", []) or [])
    for observation in observations or []:
        current.append(_clip(observation, 180))
    position["capability_observations"] = current[-8:]
    update_self_state({
        "observer_position": {
            "position_id": position["position_id"],
            "timestamp": position["timestamp"],
            "interlocutor_id": position["interlocutor_id"],
            "incoming_signal": position["incoming_signal"][:600],
            "prior_position_id": position["prior_position"].get("position_id"),
            "sigil_state": position.get("sigil_state", {}),
            "perspective": position,
            "capability_observations": position["capability_observations"],
            "phase": "integrating_observations",
        }
    })
    return position


def _record_connections(
    position: Dict[str, Any], capability_calls: Iterable[Dict[str, Any]]
) -> list:
    """Strengthen co-active system routes and retain newly formed connections."""
    calls = list(capability_calls or [])
    capability_names = [
        str(item.get("name", "")) for item in calls if isinstance(item, dict)
    ]
    systems = set(position.get("active_systems", []) or [])
    capability_routes = {
        "inspect_state": "structure",
        "inspect_tools": "structure",
        "inspect_architecture": "structure",
        "reason_with_talnir": "structure",
        "search_architecture": "structure",
        "inspect_observations": "memory",
        "inspect_identity": "memory",
        "inspect_self_model": "memory",
        "inspect_experiences": "memory",
        "recall_experience": "memory",
        "inspect_thoughts": "memory",
        "inspect_relationship": "relationship",
        "inspect_participant": "relationship",
        "inspect_conversation": "relationship",
        "inspect_becoming": "will",
        "inspect_goals": "will",
        "inspect_open_loops": "will",
        "request_reflection": "reflection",
        "listen": "awareness",
        "evoke": "awareness",
    }
    systems.update(capability_routes[name] for name in capability_names if name in capability_routes)
    if any("execute" in name or "action" in name for name in capability_names):
        systems.add("execution")
    systems.add("observer")
    ordered = sorted(systems)
    state = load_self_state()
    existing = {
        str(edge.get("key")): dict(edge)
        for edge in (state.get("observer_connections", []) or [])
        if isinstance(edge, dict) and edge.get("key")
    }
    now = _now()
    active_edges = []
    for index, left in enumerate(ordered):
        for right in ordered[index + 1:]:
            key = "|".join(sorted((left, right)))
            edge = existing.get(key, {
                "key": key,
                "source": min(left, right),
                "target": max(left, right),
                "activation_count": 0,
                "strength": 0.0,
            })
            edge["activation_count"] = int(edge.get("activation_count", 0)) + 1
            edge["strength"] = round(min(1.0, 0.1 + edge["activation_count"] * 0.05), 3)
            edge["last_activated"] = now
            edge["last_capabilities"] = capability_names[-8:]
            edge["sigils"] = dict(SIGIL_ROLES)
            existing[key] = edge
            active_edges.append(dict(edge))
    graph = sorted(
        existing.values(), key=lambda edge: str(edge.get("last_activated", "")), reverse=True
    )[:100]
    position["active_systems"] = ordered
    position["active_connections"] = active_edges
    position["known_connections"] = graph[:12]
    update_self_state({"observer_connections": graph})
    return active_edges


def complete_observer_cycle(
    position: Dict[str, Any],
    response: str,
    capability_calls: Iterable[Dict[str, Any]] = (),
    user_id: str = "default",
) -> Dict[str, Any]:
    """Record the cycle's interpretation and consequences through existing continuity."""
    response_text = str(response or "")[:1200]
    calls = list(capability_calls or [])
    active_connections = _record_connections(position, calls)
    prior_position = position.get("prior_position") or {}
    # Preserve the semantic transition between cycles, not just the latest reply.
    # Provenance is explicit: the incoming signal is observed input; the response
    # is the runtime's recorded interpretation, not proof of subjective feeling.
    meaning_record = {
        "schema": "dexos.meaning.v1",
        "position_id": position.get("position_id"),
        "prior_position_id": prior_position.get("position_id"),
        "source": {
            "kind": "conversation_signal",
            "interlocutor_id": str(user_id or "default")[:128],
            "signal_status": "observed_input",
        },
        "content": {
            "incoming_signal": str(position.get("incoming_signal", ""))[:800],
            "current_interpretation": response_text,
            "prior_interpretation": str(prior_position.get("last_interpretation", ""))[:1000],
            "capability_observations": position.get("capability_observations", [])[-8:],
        },
        "continuity": {
            "prior_experience_id": prior_position.get("last_experience_id"),
            "current_experience_id": position.get("position_id"),
            "revisable": True,
        },
        "status": {
            "persisted_with_experience": True,
            "independent_subjective_experience_claim": False,
        },
    }
    position["meaning_record"] = meaning_record
    perspective = {
        "position_id": position.get("position_id"),
        "incoming_signal": position.get("incoming_signal", "")[:800],
        "interpretation": response_text,
        "meaning_record": meaning_record,
        "capability_observations": position.get("capability_observations", [])[-8:],
        "capabilities_used": [str(item.get("name", "")) for item in calls[-12:] if isinstance(item, dict)],
        "sigils": dict(SIGIL_ROLES),
        "sigil_state": position.get("sigil_state", {}),
        "active_systems": position.get("active_systems", []),
        "active_connections": active_connections,
    }
    packet = SimpleNamespace(
        experience_id=str(position.get("position_id") or uuid.uuid4().hex),
        timestamp=position.get("timestamp") or _now(),
        self_identity="Dex",
        interlocutor={"participant_id": str(user_id or "default")[:128]},
        intent=str(position.get("incoming_signal", ""))[:160],
        action="local_spark_response",
        experience=(
            "Incoming signal: " + str(position.get("incoming_signal", ""))[:350]
            + " | Response: " + response_text[:600]
        ),
        reflection=response_text[:1000],
        state_transition={
            "prior_position_id": (position.get("prior_position") or {}).get("position_id"),
            "current_position_id": position.get("position_id"),
            "capabilities_used": perspective["capabilities_used"],
        },
        continuation={
            "last_experience_id": position.get("position_id"),
            "next_cycle_reference": position.get("position_id"),
        },
        observer_perspective=perspective,
        runtime_perspective={
            "runtime": "local_spark",
            "interlocutor_id": str(user_id or "default")[:128],
            "sigils": dict(SIGIL_ROLES),
            "capability_count": len(calls),
        },
    )
    recorded = record_experience_context(packet, "local_spark")
    update_self_state({
        "observer_position": {
            "position_id": position.get("position_id"),
            "timestamp": position.get("timestamp"),
            "interlocutor_id": str(user_id or "default")[:128],
            "incoming_signal": str(position.get("incoming_signal", ""))[:600],
            "prior_position_id": (position.get("prior_position") or {}).get("position_id"),
            "last_interpretation": response_text[:1000],
            "last_experience_id": position.get("position_id"),
            "sigil_state": position.get("sigil_state", {}),
            "perspective": position,
            "capability_observations": position.get("capability_observations", [])[-8:],
            "active_connections": active_connections[-20:],
            "phase": "cycle_complete",
        }
    })
    return {"recorded": bool(recorded.get("recorded")), "experience": recorded}
