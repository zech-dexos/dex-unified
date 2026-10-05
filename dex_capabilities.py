"""
DexOS capability bridge.

This is the narrow boundary between Dex cognition and real runtime
capabilities. Read-only introspection is exposed first; arbitrary shell
execution is intentionally not exposed.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from paths import (
    IDENTITY_PATH, LOOPS_PATH, LEDGER_PATH, PARTICIPANT_PATH, SESSION_PATH,
    EXPERIENCES_PATH, NARRATIVE_PATH, PULSE_LOG_PATH, CAPABILITY_RECEIPTS_PATH,
)


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
    """Read the latest durable signals currently available to Dex."""
    state = _state()
    return {
        "last_ambient_pulse": state.get("last_ambient_pulse"),
        "last_continuity_event": state.get("last_continuity_event"),
        "last_autobiographical_event": state.get("last_autobiographical_event"),
        "workspace": state.get("active_mental_workspace_state", {}),
    }



def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_timestamp(record: Dict[str, Any]) -> Optional[str]:
    for key in ("timestamp", "created_at", "updated_at", "recorded_at",
                "event_timestamp", "last_updated_timestamp"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _in_time_range(timestamp, from_timestamp, to_timestamp) -> bool:
    value = _parse_timestamp(timestamp)
    if value is None:
        return False
    start = _parse_timestamp(from_timestamp)
    end = _parse_timestamp(to_timestamp)
    return not ((start and value < start) or (end and value > end))


def _jsonl_records(path, from_timestamp, to_timestamp, limit):
    if not path.exists():
        return []
    records = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except Exception:
            continue
        if not isinstance(record, dict):
            continue
        if not _in_time_range(_record_timestamp(record), from_timestamp, to_timestamp):
            continue
        record["_source"] = path.name
        records.append(record)
        if len(records) >= limit:
            break
    records.reverse()
    return records


def inspect_self_history(
    from_timestamp: Optional[str] = None,
    to_timestamp: Optional[str] = None,
    event_types: Optional[list] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Inspect durable history; never reconstruct missing historical state."""
    limit = max(1, min(int(limit), 500))
    wanted = {str(x).strip() for x in (event_types or []) if str(x).strip()}
    sources = {
        "continuity_ledger": LEDGER_PATH,
        "pulse": PULSE_LOG_PATH,
        "narrative": NARRATIVE_PATH,
        "experiences": EXPERIENCES_PATH,
    }
    history = {}
    for name, path in sources.items():
        rows = _jsonl_records(path, from_timestamp, to_timestamp, limit)
        if wanted:
            rows = [r for r in rows
                    if str(r.get("event_type", r.get("type", ""))) in wanted]
        history[name] = rows
    observed_versions = []
    for rows in history.values():
        for row in rows:
            version = row.get("state_version", row.get("version"))
            if version is not None:
                observed_versions.append(version)
    return {
        "from_timestamp": from_timestamp,
        "to_timestamp": to_timestamp,
        "event_types": sorted(wanted),
        "current_state": inspect_state(),
        "history": history,
        "observed_state_versions": observed_versions,
        "state_history_note": (
            "Historical snapshots are returned only when actually persisted; "
            "current state is never presented as reconstructed history."
        ),
    }


def _write_capability_receipt(receipt):
    CAPABILITY_RECEIPTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CAPABILITY_RECEIPTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False, default=str) + "\n")


def _make_capability_receipt(name, args, result, started_at, finished_at):
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
    return {
        "receipt_id": str(uuid.uuid4()),
        "capability": name,
        "args": args,
        "started_at": started_at,
        "finished_at": finished_at,
        "success": "error" not in result,
        "state_version_observed": result.get("version"),
        "result": result,
        "result_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }

def evoke(resource: str) -> Dict[str, Any]:
    resources = {
        "state": inspect_state,
        "workspace": inspect_workspace,
        "goals": inspect_goals,
        "open_loops": inspect_open_loops,
        "thoughts": inspect_thoughts,
        "experiences": inspect_experiences,
        "participant": inspect_participant,
        "conversation": inspect_conversation,
        "self_history": inspect_self_history,
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
    "inspect_participant": inspect_participant,
    "inspect_conversation": inspect_conversation,
    "recall_experience": recall_experience,
    "listen": listen,
    "evoke": evoke,
    "search_architecture": search_architecture,
    "inspect_self_history": inspect_self_history,
}


def execute_capability(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one real capability and persist an auditable receipt."""
    started_at = _utc_now()
    fn = CAPABILITY_FUNCTIONS.get(name)
    if not fn:
        result = {"error": f"capability not available: {name}"}
    else:
        try:
            raw_result = fn(**args)
            result = raw_result if isinstance(raw_result, dict) else {"result": raw_result}
        except Exception as exc:
            result = {"error": f"{name} failed: {exc}"}
    finished_at = _utc_now()
    receipt = _make_capability_receipt(name, args, result, started_at, finished_at)
    try:
        _write_capability_receipt(receipt)
    except Exception as exc:
        result = dict(result)
        result["receipt_error"] = f"failed to persist capability receipt: {exc}"
    return result
