"""
DexOS capability bridge.

This is the narrow boundary between Dex cognition and real runtime
capabilities. Read-only introspection is exposed first; arbitrary shell
execution is intentionally not exposed.
"""
import json
from pathlib import Path
from typing import Any, Dict

from paths import IDENTITY_PATH, LOOPS_PATH, STATE_PATH


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


def inspect_experiences() -> Dict[str, Any]:
    state = _state()
    return {
        "last_continuity_event": state.get("last_continuity_event"),
        "last_autobiographical_event": state.get("last_autobiographical_event"),
        "recent_lineage": _recent_jsonl(STATE_PATH.parent / "dex_lineage.jsonl", 10),
    }


def listen() -> Dict[str, Any]:
    """Read the latest durable signals currently available to Dex."""
    state = _state()
    return {
        "last_ambient_pulse": state.get("last_ambient_pulse"),
        "last_continuity_event": state.get("last_continuity_event"),
        "last_autobiographical_event": state.get("last_autobiographical_event"),
        "workspace": state.get("active_mental_workspace_state", {}),
    }


def evoke(resource: str) -> Dict[str, Any]:
    resources = {
        "state": inspect_state,
        "workspace": inspect_workspace,
        "goals": inspect_goals,
        "open_loops": inspect_open_loops,
        "thoughts": inspect_thoughts,
        "experiences": inspect_experiences,
        "signals": listen,
    }
    fn = resources.get(resource)
    if not fn:
        return {"error": f"unknown resource: {resource}", "available": sorted(resources)}
    return fn()


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


CAPABILITY_FUNCTIONS = {
    "inspect_state": inspect_state,
    "inspect_workspace": inspect_workspace,
    "inspect_goals": inspect_goals,
    "inspect_open_loops": inspect_open_loops,
    "inspect_thoughts": inspect_thoughts,
    "inspect_experiences": inspect_experiences,
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
