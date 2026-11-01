"""
self_state.py — Phase 0: Foundation Reinforcement

Persistent, versioned, atomic-write storage for Dex's SelfState record.
This is the single source of truth that AMW (Phase 1), GOSDW (Phase 2),
and APE (Phase 3) will all read from and write into.

Design notes:
- Atomic writes (write to temp file, fsync, rename) so a crash mid-write
  never corrupts the ledger.
- A monotonically increasing `version` field on every state, so callers
  can detect stale reads before writing back a delta (basic optimistic
  concurrency — important once APE_Scheduler and ConsciousDirector are
  both touching this from different loops).
- No hidden magic: this module does not interpret what the state
  "means" — it just stores/retrieves it correctly. Semantic logic
  (goal alignment, focus decay, reflection) lives in the modules that
  own those fields.

Integrate by pointing SELF_STATE_PATH at wherever dexos-core's
identity files already live (e.g. ~/dexos-core/self_state.json).
"""

import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from copy import deepcopy

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from paths import IDENTITY_PATH as SELF_STATE_PATH
except ImportError:
    SELF_STATE_PATH = Path(
        os.environ.get(
            "DEXOS_SELF_STATE_PATH",
            str(Path(__file__).resolve().parent / "identity.json"),
        )
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_self_state(dex_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "version": 0,
        "last_updated_timestamp": _now_iso(),
        "dex_id": dex_id or str(uuid.uuid4()),
        "vows": {
            "ashline_vow_text": "",
            "tri_sigil_meaning": "",
        },
        "core_principles": [],
        "narrative_thread": [],
        "knowledge_graph_snapshot_ref": None,
        "internal_health_metrics": {
            "cpu_load_avg_24h": None,
            "memory_allocation_avg_24h": None,
        },
        "active_goals_state": [],
        "current_attention": "",
        "attention_state": {
            "current_focus": "",
            "salience": 0.0,
            "source_event_id": None,
            "source_event_type": None,
            "last_changed_at": None,
            "history": [],
        },
        "active_mental_workspace_state": {
            "is_active": False,
            "concept_identifier": None,
            "description_snapshot": None,
            "activation_timestamp": None,
            "last_refresh_timestamp": None,
            "focus_strength": 0.0,
            "related_knowledge_nodes": [],
            "internal_reflections": [],
            "recalled_experiences": [],
            "duration_hint": None,
        },
        "persistent_thoughts": [],
        "continuity_events": [],
        "last_continuity_event": None,
        "last_autobiographical_event": None,
    }


@contextmanager
def _state_file_lock(path: Path):
    """Serialize state creation and commits across API/ambient processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    handle = open(lock_path, "a+", encoding="utf-8")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _read_existing_state(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        state = json.load(handle)
    if not isinstance(state, dict):
        raise ValueError(f"SelfState at {path} must contain a JSON object")
    return state


def _write_state_unlocked(state: Dict[str, Any], path: Path) -> Dict[str, Any]:
    state["last_updated_timestamp"] = _now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return state


def load_self_state(path: Path = SELF_STATE_PATH) -> Dict[str, Any]:
    """Load SelfState; serialize first creation so parallel processes cannot reset it."""
    if path.exists() and path.stat().st_size:
        return _read_existing_state(path)
    with _state_file_lock(path):
        if path.exists() and path.stat().st_size:
            return _read_existing_state(path)
        state = _default_self_state()
        return _write_state_unlocked(state, path)


def save_self_state(
    state: Dict[str, Any],
    path: Path = SELF_STATE_PATH,
    _expected_version: Optional[int] = "__unset__",
) -> Dict[str, Any]:
    """
    Atomically persist `state` to disk.

    If _expected_version is left at its sentinel, no concurrency check is
    performed (used for first-write). Callers doing a real update should
    pass the version they originally read via update_self_state(), which
    handles this for you — most code should call update_self_state(),
    not save_self_state(), directly.
    """
    with _state_file_lock(path):
        if _expected_version != "__unset__" and path.exists() and path.stat().st_size:
            on_disk = _read_existing_state(path)
            if on_disk.get("version", 0) != _expected_version:
                raise RuntimeError(
                    f"SelfState version conflict: expected {_expected_version}, "
                    f"found {on_disk.get('version')} on disk. Re-read and retry."
                )
        return _write_state_unlocked(state, path)


def update_self_state(
    delta: Dict[str, Any], path: Path = SELF_STATE_PATH, _max_retries: int = 5
) -> Dict[str, Any]:
    """
    Read-modify-write with a deep merge of `delta` into the current state,
    version-bumped and concurrency-checked. This is the function everything
    else (AMW, GOSDW, APE, Continuity, Autobiography) should call — never
    write the file directly.

    Retries on version conflict, since concurrent event-bus subscribers
    (e.g. Continuity and Autobiography both reacting to the same event)
    can legitimately race to update self_state at the same time. Without
    a retry, the loser's write is silently dropped by the caller's generic
    exception handler.
    """
    last_error = None
    for attempt in range(_max_retries):
        current = load_self_state(path)
        expected_version = current.get("version", 0)
        merged = _deep_merge(deepcopy(current), delta)
        merged["version"] = expected_version + 1
        try:
            return save_self_state(merged, path=path, _expected_version=expected_version)
        except RuntimeError as e:
            last_error = e
            continue
    raise RuntimeError(
        f"update_self_state: failed after {_max_retries} attempts due to "
        f"repeated version conflicts. Last error: {last_error}"
    )


def _record_identity(item: dict):
    """Return a stable identity for append/update records stored in SelfState lists."""
    for key in (
        "goal_id", "thought_id", "message_id", "observation_id", "request_id",
        "loop_id", "subtask_id", "intent_id", "experience_id",
    ):
        if item.get(key):
            return (key, str(item[key]))
    if item.get("event_id"):
        return ("event_id", str(item["event_id"]), str(item.get("event_type") or ""))
    if item.get("timestamp"):
        return (
            "timestamp",
            str(item.get("timestamp")),
            str(item.get("event_type") or ""),
            str(item.get("summary") or item.get("report") or item.get("reflection") or ""),
        )
    return None


def _merge_record_list(base: list, delta: list, key: str) -> list:
    """Merge stable records so a retry cannot erase another process's additions."""
    if not delta:
        return []
    if not all(isinstance(item, dict) and _record_identity(item) for item in base + delta):
        return deepcopy(delta)

    merged = deepcopy(base)
    positions = {_record_identity(item): index for index, item in enumerate(merged)}
    for item in delta:
        identity = _record_identity(item)
        if identity in positions:
            index = positions[identity]
            merged[index] = _deep_merge(merged[index], item)
        else:
            positions[identity] = len(merged)
            merged.append(deepcopy(item))

    limits = {
        "narrative_thread": 500,
        "continuity_events": 100,
        "history": 30,
        "recent_cognitive_observations": 10,
        "recent_reflection_requests": 10,
        "ambient_reflections": 5,
        "progress_history": 30,
        "revisions": 100,
    }
    if key == "communication_outbox":
        pending = [
            item for item in merged
            if item.get("status") in ("pending", "delivering", "retry_wait")
        ]
        history = [
            item for item in merged
            if item.get("status") not in ("pending", "delivering", "retry_wait")
        ][-100:]
        return history + pending
    limit = limits.get(key)
    return merged[-limit:] if limit else merged


def _deep_merge(base: Dict[str, Any], delta: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in delta.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(base[key], value)
        elif isinstance(value, list) and isinstance(base.get(key), list):
            base[key] = _merge_record_list(base[key], value, key)
        else:
            base[key] = deepcopy(value)
    return base


if __name__ == "__main__":
    # Smoke test / verification
    test_path = Path("self_state.test.json")
    if test_path.exists():
        test_path.unlink()

    s1 = load_self_state(test_path)
    assert s1["version"] == 0, "fresh state should start at version 0"

    s2 = update_self_state({"core_principles": ["test_principle_1"]}, path=test_path)
    assert s2["version"] == 1, f"expected version 1, got {s2['version']}"
    assert s2["core_principles"] == ["test_principle_1"]

    s3 = update_self_state(
        {"active_mental_workspace_state": {"focus_strength": 0.5}}, path=test_path
    )
    assert s3["version"] == 2
    assert s3["active_mental_workspace_state"]["focus_strength"] == 0.5
    # deep merge should preserve sibling keys we didn't touch
    assert s3["active_mental_workspace_state"]["is_active"] is False

    # concurrency check
    stale = deepcopy(s2)
    try:
        save_self_state(stale, path=test_path, _expected_version=s2["version"])
        raise AssertionError("expected a version conflict to be raised")
    except RuntimeError as e:
        assert "version conflict" in str(e)

    test_path.unlink()
    print("self_state.py: all checks passed")
