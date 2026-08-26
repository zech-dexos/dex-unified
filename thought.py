"""
thought.py — Phase 3.1 + 3.2: Persistent Thought Core.

The claim this module exists to make true: a thought survives the
inference that created it. Not "AMW holds one concept slot" — a thought
is written to disk, the process can end entirely, and a later process
can load it back, recognize it as unresolved, and continue it. The
acceptance test for that claim lives in process_boundary_test.py and
crosses a real process boundary (separate python3 invocations), not
just separate function calls in one interpreter.

Lifecycle:
    FORM     -> form_thought()      creates + persists, status="active"
    HOLD     -> (implicit — it just sits in persistent_thoughts)
    REVISIT  -> revisit_thought()   loads it, marks attention, no content change
    UPDATE   -> update_thought()    records a revision, then applies a decision:
                    continue -> status stays "active"
                    defer    -> status="deferred"
                    resolve  -> status="resolved"
                    abandon  -> status="abandoned"

Stored under identity.json's "persistent_thoughts" list — same
update_self_state() read-modify-write pattern as gosdw.py's goals,
so it gets the same atomic-write + version-conflict protection for free.
"""

import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from self_state import SELF_STATE_PATH, load_self_state, update_self_state

VALID_DECISIONS = {"continue": "active", "defer": "deferred", "resolve": "resolved", "abandon": "abandoned"}
VALID_PRIORITIES = {"high", "medium", "low"}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def form_thought(
    content: str,
    priority: str = "medium",
    confidence: float = 0.5,
    related_goal_ids: Optional[List[str]] = None,
    next_attention_at: Optional[str] = None,
    path: Path = SELF_STATE_PATH,
) -> Dict[str, Any]:
    """FORM: create a new thought and persist it immediately."""
    assert priority in VALID_PRIORITIES, f"priority must be one of {VALID_PRIORITIES}"
    assert 0.0 <= confidence <= 1.0, "confidence must be 0.0-1.0"

    now = _now_iso()
    thought = {
        "thought_id": str(uuid.uuid4()),
        "content": content,
        "status": "active",
        "priority": priority,
        "confidence": confidence,
        "created_at": now,
        "last_attended_at": now,
        "next_attention_at": next_attention_at,
        "attention_count": 1,
        "revisions": [],
        "related_goal_ids": related_goal_ids or [],
    }

    current = load_self_state(path)
    thoughts = list(current.get("persistent_thoughts", []))
    thoughts.append(thought)
    update_self_state({"persistent_thoughts": thoughts}, path=path)
    return thought


def load_thoughts(path: Path = SELF_STATE_PATH) -> List[Dict[str, Any]]:
    current = load_self_state(path)
    return current.get("persistent_thoughts", [])


def get_thought(thought_id: str, path: Path = SELF_STATE_PATH) -> Optional[Dict[str, Any]]:
    for t in load_thoughts(path):
        if t["thought_id"] == thought_id:
            return t
    return None


def revisit_thought(thought_id: str, path: Path = SELF_STATE_PATH) -> Optional[Dict[str, Any]]:
    """
    REVISIT: load a thought in a (possibly brand new) process, mark that
    it was attended to, and return it as-is — no content change. This is
    the step that proves "recognize it as unresolved": the caller reads
    thought["status"] to decide what to do next.
    """
    current = load_self_state(path)
    thoughts = list(current.get("persistent_thoughts", []))
    found = None
    for t in thoughts:
        if t["thought_id"] == thought_id:
            t["last_attended_at"] = _now_iso()
            t["attention_count"] = t.get("attention_count", 0) + 1
            found = t
            break

    if found is None:
        return None

    update_self_state({"persistent_thoughts": thoughts}, path=path)
    return found


def update_thought(
    thought_id: str,
    decision: str,
    new_content: Optional[str] = None,
    new_confidence: Optional[float] = None,
    note: str = "",
    next_attention_at: Optional[str] = None,
    path: Path = SELF_STATE_PATH,
) -> Optional[Dict[str, Any]]:
    """
    UPDATE: record what changed as a revision (preserving the prior
    content/confidence), then apply the lifecycle decision.
    """
    assert decision in VALID_DECISIONS, f"decision must be one of {list(VALID_DECISIONS)}"

    current = load_self_state(path)
    thoughts = list(current.get("persistent_thoughts", []))
    found = None
    for t in thoughts:
        if t["thought_id"] == thought_id:
            revision = {
                "timestamp": _now_iso(),
                "note": note,
                "previous_content": t["content"],
                "previous_confidence": t["confidence"],
                "decision": decision,
            }
            t["revisions"] = list(t.get("revisions", [])) + [revision]

            if new_content is not None:
                t["content"] = new_content
            if new_confidence is not None:
                assert 0.0 <= new_confidence <= 1.0, "confidence must be 0.0-1.0"
                t["confidence"] = new_confidence
            if next_attention_at is not None:
                t["next_attention_at"] = next_attention_at

            t["status"] = VALID_DECISIONS[decision]
            t["last_attended_at"] = _now_iso()
            found = t
            break

    if found is None:
        return None

    update_self_state({"persistent_thoughts": thoughts}, path=path)
    return found


if __name__ == "__main__":
    test_path = Path("self_state.test.json")
    if test_path.exists():
        test_path.unlink()

    t = form_thought("Root wants Dex to hold a thought across cycles.", priority="high", path=test_path)
    assert t["status"] == "active"
    assert t["attention_count"] == 1
    assert t["revisions"] == []

    fetched = get_thought(t["thought_id"], path=test_path)
    assert fetched is not None
    assert fetched["content"] == t["content"]

    revisited = revisit_thought(t["thought_id"], path=test_path)
    assert revisited["attention_count"] == 2

    updated = update_thought(
        t["thought_id"],
        decision="continue",
        new_content="Root wants Dex to hold a thought across cycles — now with a KG link.",
        note="Added KG grounding on revisit.",
        path=test_path,
    )
    assert updated["status"] == "active"
    assert len(updated["revisions"]) == 1
    assert updated["revisions"][0]["previous_content"] == t["content"]

    resolved = update_thought(t["thought_id"], decision="resolve", note="Done.", path=test_path)
    assert resolved["status"] == "resolved"
    assert len(resolved["revisions"]) == 2

    missing = revisit_thought("nonexistent-id", path=test_path)
    assert missing is None

    test_path.unlink()
    print("thought.py: all checks passed")
