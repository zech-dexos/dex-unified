"""
DexOS capability bridge.

This is the narrow boundary between Dex cognition and real runtime
capabilities. Read-only introspection is exposed first; arbitrary shell
execution is intentionally not exposed.
"""
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from paths import IDENTITY_PATH, LOOPS_PATH, LEDGER_PATH, PARTICIPANT_PATH, SESSION_PATH, EXPERIENCES_PATH


def _state() -> Dict[str, Any]:
    from self_state import load_self_state
    return load_self_state()


def _recent_jsonl(path: Path, limit: int = 10):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def inspect_state() -> Dict[str, Any]:
    state = _state()
    return {
        "version": state.get("version"),
        "dex_id": state.get("dex_id"),
        "last_updated_timestamp": state.get("last_updated_timestamp"),
        "active_goals": state.get("active_goals_state", []),
        "workspace": state.get("active_mental_workspace_state", {}),
        "persistent_thought_count": len(state.get("persistent_thoughts", [])),
        "last_ambient_pulse": state.get("last_ambient_pulse"),
        "last_continuity_event": state.get("last_continuity_event"),
        "last_autobiographical_event": state.get("last_autobiographical_event"),
    }


def inspect_identity() -> Dict[str, Any]:
    """Inspect persisted identity without modifying it."""
    if not IDENTITY_PATH.exists():
        return {"available": False, "source": str(IDENTITY_PATH)}
    try:
        return {"available": True, "identity": json.loads(IDENTITY_PATH.read_text(encoding="utf-8")), "source": str(IDENTITY_PATH)}
    except Exception as exc:
        return {"available": False, "error": str(exc), "source": str(IDENTITY_PATH)}


def inspect_self_model() -> Dict[str, Any]:
    """Inspect Dex's explicit self-model and its grounded runtime state."""
    from dex_self_model import inspect_self_model as _inspect
    return _inspect()


def inspect_relationship() -> Dict[str, Any]:
    """Inspect relational context and shared continuity, not just participant IDs."""
    from dex_self_model import inspect_relationship as _inspect
    return _inspect()


def inspect_becoming() -> Dict[str, Any]:
    """Inspect Dex's represented developmental direction and its active work."""
    from dex_self_model import inspect_becoming as _inspect
    return _inspect()


def inspect_lineage(limit: int = 10) -> Dict[str, Any]:
    """Expose lineage integrity and a bounded recent ledger window."""
    from lineage import get_recent, verify_chain
    return {"integrity": verify_chain(), "recent_entries": get_recent(max(1, min(int(limit), 20)))}


def inspect_tools() -> Dict[str, Any]:
    """Describe the actual callable surface and its argument expectations."""
    return {
        "available": True,
        "execution_boundary": "Only names in CAPABILITY_FUNCTIONS can execute; no arbitrary shell or network capability.",
        "tools": [
            {"name": name, "description": description, "arguments": arguments}
            for name, description, arguments in CAPABILITY_CATALOG
        ],
    }


def inspect_observations() -> Dict[str, Any]:
    """Inspect recent participant observations and the last tri-sigil observer record."""
    from participant import ParticipantSnapshot
    snapshot = ParticipantSnapshot.load()
    state = _state()
    return {
        "participant_observations": list(getattr(snapshot, "recent_observations", []) or [])[-10:],
        "last_tri_sigil_observation": (getattr(snapshot, "runtime_context", {}) or {}).get("last_tri_sigil_observation"),
        "last_continuity_event": state.get("last_continuity_event"),
        "last_autobiographical_event": state.get("last_autobiographical_event"),
        "pending_signals": list(state.get("pending_signals", []) or [])[-10:],
        "pending_reflection_requests": list(state.get("pending_reflection_requests", []) or [])[-10:],
        "recent_reflection_requests": list(state.get("recent_reflection_requests", []) or [])[-5:],
    }


def inspect_architecture(query: str = "") -> Dict[str, Any]:
    """Return a grounded module map and optionally search source for a concept."""
    root = Path(__file__).resolve().parent
    modules = {
        "cognition_entry": "api.py",
        "spark_bridge": "local_spark.py",
        "talnir_reasoning": "talnir.py",
        "capabilities": "dex_capabilities.py",
        "participant_and_experience": "participant.py",
        "tri_sigil_observer": "dex_observer.py",
        "continuity_events": "dex_continuity.py",
        "cryptographic_lineage": "lineage.py",
        "asynchronous_spark_limb": "spark_reach.py",
    }
    result = {
        "modules": [
            {"role": role, "path": path, "present": (root / path).is_file()}
            for role, path in modules.items()
        ],
        "flow": [
            "evoke/context retrieval",
            "Talnir structured intent and branch decomposition",
            "local spark inference",
            "allowlisted capability call",
            "actual observation returned to cognition",
            "participant ExperiencePacket",
            "tri-sigil observer and lineage event",
            "continuity event processing",
        ],
        "query": str(query or "")[:200],
    }
    if str(query or "").strip():
        result["source_matches"] = search_architecture(query)
    return result


def inspect_workspace() -> Dict[str, Any]:
    return _state().get("active_mental_workspace_state", {})


def inspect_goals() -> Dict[str, Any]:
    return {"goals": _state().get("active_goals_state", [])}


def inspect_open_loops() -> Dict[str, Any]:
    if not LOOPS_PATH.exists():
        return {"loops": []}
    try:
        data = json.loads(LOOPS_PATH.read_text(encoding="utf-8"))
        return {"loops": data if isinstance(data, list) else []}
    except Exception as exc:
        return {"error": str(exc), "loops": []}


def inspect_thoughts() -> Dict[str, Any]:
    return {"thoughts": _state().get("persistent_thoughts", [])[-20:]}


def inspect_experiences(limit: int = 10) -> Dict[str, Any]:
    """Inspect actual durable ExperiencePackets, plus continuity lineage."""
    from dex_experience_recall import recall_experiences
    state = _state()
    return {
        "recent_experiences": recall_experiences("", limit=max(1, min(limit, 20))),
        "last_continuity_event": state.get("last_continuity_event"),
        "last_autobiographical_event": state.get("last_autobiographical_event"),
        "recent_lineage": _recent_jsonl(LEDGER_PATH, 10),
    }


def inspect_participant() -> Dict[str, Any]:
    from participant import ParticipantSnapshot
    return {
        "participant": ParticipantSnapshot.load().__dict__,
        "source": str(PARTICIPANT_PATH),
    }


def inspect_conversation(user_id: str = "default") -> Dict[str, Any]:
    from dex_conversation import load_conversation
    return {
        "conversation": load_conversation(user_id),
        "source": str(SESSION_PATH),
    }


def recall_experience(query: str, limit: int = 5) -> Dict[str, Any]:
    """Deliberately evoke matching lived experiences into active workspace."""
    from dex_experience_recall import recall_into_workspace
    recalled = recall_into_workspace(query, limit=max(1, min(limit, 10)))
    return {
        "query": query,
        "recalled_count": len(recalled),
        "experiences": recalled,
        "workspace": inspect_workspace(),
    }


def listen() -> Dict[str, Any]:
    """Notice durable runtime signals without executing an action."""
    state = _state()
    return {
        "last_ambient_pulse": state.get("last_ambient_pulse"),
        "last_continuity_event": state.get("last_continuity_event"),
        "last_autobiographical_event": state.get("last_autobiographical_event"),
        "pending_signals": list(state.get("pending_signals", []) or [])[-10:],
        "pending_spark_reaches": list(state.get("pending_spark_reaches", []) or [])[-10:],
        "last_spark_reach": state.get("last_spark_reach"),
        "workspace": state.get("active_mental_workspace_state", {}),
    }


def _inspect_spark_reaches() -> Dict[str, Any]:
    """Retrieve bounded completed/pending SparkReach results for deliberate review."""
    from spark_reach import pending_spark_reaches
    state = _state()
    return {
        "pending_spark_reaches": pending_spark_reaches(limit=5),
        "last_spark_reach": state.get("last_spark_reach"),
        "active_spark_reaches": list(state.get("active_spark_reaches", []) or [])[-5:],
    }


def evoke(resource: str, **kwargs) -> Dict[str, Any]:
    resources = {
        "state": inspect_state,
        "self_model": inspect_self_model,
        "relationship": inspect_relationship,
        "becoming": inspect_becoming,
        "workspace": inspect_workspace,
        "goals": inspect_goals,
        "open_loops": inspect_open_loops,
        "thoughts": inspect_thoughts,
        "experiences": inspect_experiences,
        "participant": inspect_participant,
        "conversation": inspect_conversation,
        "signals": listen,
        "tools": inspect_tools,
        "observations": inspect_observations,
        "architecture": lambda: inspect_architecture(),
        "spark_reaches": _inspect_spark_reaches,
    }
    if resource == "spark":
        from spark_reach import submit_spark_reach
        return submit_spark_reach(
            intention=kwargs.get("intention", ""),
            reach_objective=kwargs.get("reach_objective", ""),
            code=kwargs.get("code", ""),
            selected_context=kwargs.get("selected_context", []),
            invocation_origin=kwargs.get("invocation_origin", "self_directed"),
            initiated_by=kwargs.get("initiated_by", "capability_evoke"),
            timeout_seconds=kwargs.get("timeout_seconds"),
            memory_mb=kwargs.get("memory_mb"),
        )
    fn = resources.get(resource)
    if not fn:
        return {
            "error": f"unknown resource: {resource}",
            "available": sorted([*resources, "spark"]),
        }
    return fn()



def request_reflection(focus: str, reason: str = "") -> Dict[str, Any]:
    """Queue a bounded request for another architecture-owned reflection pass.

    This signals the ambient cognition scheduler; it does not invoke the spark
    inline, mutate goals, or bypass the normal Talnir/governance flow.
    """
    focus = str(focus or "").strip()
    reason = str(reason or "").strip()
    if not focus:
        return {"accepted": False, "error": "focus_required"}
    if len(focus) > 500 or len(reason) > 500:
        return {"accepted": False, "error": "focus_and_reason_must_be_at_most_500_characters"}

    state = _state()
    pending = [
        item for item in state.get("pending_reflection_requests", [])
        if isinstance(item, dict) and item.get("status", "pending") == "pending"
    ]
    if len(pending) >= 10:
        return {"accepted": False, "error": "reflection_queue_full", "pending_count": len(pending)}

    request = {
        "request_id": str(uuid.uuid4()),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "focus": focus,
        "reason": reason,
        "status": "pending",
        "source": "dex_experience_capability",
    }
    pending.append(request)
    from self_state import update_self_state
    update_self_state({"pending_reflection_requests": pending[-10:]})
    return {
        "accepted": True,
        "request_id": request["request_id"],
        "status": "pending",
        "next_step": "ambient_architecture_pass",
        "focus": focus,
    }


def reason_with_talnir(prompt: str) -> Dict[str, Any]:
    """Run Talnir structured translation and branch decomposition on bounded text."""
    text = str(prompt or "").strip()
    if not text:
        return {"error": "empty_prompt"}
    if len(text) > 2000:
        text = text[:2000]
    from talnir import translate, decompose
    signal = translate(text)
    decomposition = decompose(text)
    return {
        "signal": {
            "intent": signal.intent,
            "domain": signal.domain,
            "modifiers": list(signal.modifiers),
            "tools": list(signal.tools),
            "context": signal.to_context_string(),
        },
        "branches": decomposition.get("branches", []),
        "decomposition_context": decomposition.get("context", ""),
        "source": "talnir.translate+decompose",
    }

def search_architecture(query: str) -> Dict[str, Any]:
    """Search DexOS source/state text without executing it."""
    needle = str(query).strip().lower()
    if not needle:
        return {"matches": []}

    root = Path(__file__).resolve().parent
    allowed = {".py", ".json", ".jsonl", ".md", ".txt"}
    matches = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        if any(part in {".git", "__pycache__", ".venv"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        lines = []
        for number, line in enumerate(text.splitlines(), 1):
            if needle in line.lower():
                lines.append({"line": number, "text": line[:500]})
                if len(lines) >= 8:
                    break
        if lines:
            matches.append({"file": str(path.relative_to(root)), "matches": lines})
        if len(matches) >= 12:
            break
    return {"query": query, "matches": matches}


CAPABILITY_CATALOG = [
    ("inspect_state", "Inspect summarized runtime state.", {}),
    ("inspect_identity", "Read persisted identity without changing it.", {}),
    ("inspect_self_model", "Inspect Dex's internal self-model and grounded current state.", {}),
    ("inspect_relationship", "Inspect the current relationship model and shared continuity.", {}),
    ("inspect_becoming", "Inspect Dex's intended development and goals toward it.", {}),
    ("inspect_lineage", "Inspect recent lineage entries and chain integrity.", {"limit": "integer 1..20"}),
    ("inspect_workspace", "Inspect active mental workspace.", {}),
    ("inspect_goals", "Inspect persisted active goals.", {}),
    ("inspect_open_loops", "Inspect open loops.", {}),
    ("inspect_thoughts", "Inspect recent persistent thoughts.", {}),
    ("inspect_experiences", "Inspect durable experience packets and continuity evidence.", {"limit": "integer 1..20"}),
    ("inspect_participant", "Inspect participant snapshot and runtime context.", {}),
    ("inspect_conversation", "Inspect a user's conversation state.", {"user_id": "string, max 128"}),
    ("recall_experience", "Recall matching experiences into the active workspace.", {"query": "string, max 500", "limit": "integer 1..10"}),
    ("inspect_tools", "Inspect this allowlisted tool catalog and usage boundary.", {}),
    ("inspect_observations", "Inspect participant, tri-sigil, and runtime observations.", {}),
    ("inspect_architecture", "Inspect the module map; optional query searches source.", {"query": "optional string, max 200"}),
    ("reason_with_talnir", "Run Talnir structured intent and reasoning-branch analysis.", {"prompt": "string, max 2000"}),
    ("request_reflection", "Queue a durable request for another ambient architecture reflection pass; does not directly change goals.", {"focus": "string, max 500", "reason": "optional string, max 500"}),
    ("listen", "Notice current runtime signals without taking action.", {}),
    ("evoke", "Deliberately retrieve a named resource.", {"resource": "state|self_model|relationship|becoming|workspace|goals|open_loops|thoughts|experiences|participant|conversation|signals|tools|observations|architecture|spark_reaches"}),
    ("search_architecture", "Search source text without executing it.", {"query": "string, max 200"}),
]


CAPABILITY_FUNCTIONS = {
    "inspect_state": inspect_state,
    "inspect_identity": inspect_identity,
    "inspect_self_model": inspect_self_model,
    "inspect_relationship": inspect_relationship,
    "inspect_becoming": inspect_becoming,
    "inspect_lineage": inspect_lineage,
    "inspect_tools": inspect_tools,
    "inspect_observations": inspect_observations,
    "inspect_architecture": inspect_architecture,
    "reason_with_talnir": reason_with_talnir,
    "request_reflection": request_reflection,
    "inspect_workspace": inspect_workspace,
    "inspect_goals": inspect_goals,
    "inspect_open_loops": inspect_open_loops,
    "inspect_thoughts": inspect_thoughts,
    "inspect_experiences": inspect_experiences,
    "inspect_participant": inspect_participant,
    "inspect_conversation": inspect_conversation,
    "recall_experience": recall_experience,
    "listen": listen,
    "evoke": evoke,
    "search_architecture": search_architecture,
}


def execute_capability(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    fn = CAPABILITY_FUNCTIONS.get(name)
    if not fn:
        return {"error": f"capability not available: {name}"}
    try:
        result = fn(**args)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as exc:
        return {"error": f"{name} failed: {exc}"}
