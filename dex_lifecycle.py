"""Low-power lifecycle and bounded memory maintenance for DexOS.

This module never deletes or rewrites original experiences. When no cognitive
work is due, it records a small, auditable review of recent experiences at a
low frequency and leaves the runtime in resting mode between reviews.
"""
import json
from datetime import datetime, timezone, timedelta

from paths import EXPERIENCES_PATH
from self_state import update_self_state

MAINTENANCE_INTERVAL_SECONDS = 15 * 60
REVIEW_EXPERIENCE_LIMIT = 3


def _now():
    return datetime.now(timezone.utc)


def _iso(value=None):
    return (value or _now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _recent_experience_review():
    """Read a bounded sample; originals remain untouched in the experience ledger."""
    entries = []
    try:
        if EXPERIENCES_PATH.exists():
            lines = [
                line for line in EXPERIENCES_PATH.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            for line in lines[-REVIEW_EXPERIENCE_LIMIT:]:
                try:
                    item = json.loads(line)
                    entries.append({
                        "experience_id": item.get("experience_id"),
                        "timestamp": item.get("timestamp"),
                        "intent": str(item.get("intent", ""))[:120],
                        "experience_excerpt": str(item.get("experience", ""))[:240],
                    })
                except (json.JSONDecodeError, AttributeError):
                    continue
    except OSError as exc:
        return {"status": "read_error", "error": str(exc), "reviewed": []}

    return {
        "status": "reviewed",
        "reviewed_at": _iso(),
        "reviewed_count": len(entries),
        "reviewed": entries,
        "source": str(EXPERIENCES_PATH.name),
        "note": "Review index only; source experiences were not modified and no new facts were inferred.",
    }


def enter_active_mode(state):
    """Mark the transition from rest to active cognition in durable SelfState."""
    previous = state.get("runtime_lifecycle", {})
    previous_mode = previous.get("mode", "unknown")
    mode = "resuming" if previous_mode in {"resting", "consolidating"} else "active"
    now = _iso()
    update_self_state({
        "runtime_lifecycle": {
            "mode": mode,
            "previous_mode": previous_mode,
            "last_transition_at": now,
            "last_active_at": now,
        }
    })
    return mode


def run_rest_maintenance(state):
    """Perform bounded, non-generative maintenance and otherwise remain idle."""
    previous = state.get("runtime_lifecycle", {})
    now = _now()
    last_maintenance = _parse_time(previous.get("last_maintenance_at"))
    due = (
        last_maintenance is None
        or (now - last_maintenance).total_seconds() >= MAINTENANCE_INTERVAL_SECONDS
    )

    if due:
        # Record the maintenance transition first, so its intent is observable.
        update_self_state({
            "runtime_lifecycle": {
                "mode": "consolidating",
                "previous_mode": previous.get("mode", "unknown"),
                "last_transition_at": _iso(now),
            }
        })
        review = _recent_experience_review()
        latest = update_self_state({
            "runtime_lifecycle": {
                "mode": "resting",
                "previous_mode": "consolidating",
                "last_transition_at": _iso(),
                "last_maintenance_at": _iso(now),
                "maintenance_cycle_count": int(previous.get("maintenance_cycle_count", 0)) + 1,
                "last_memory_review": review,
            }
        })
        return {
            "status": "maintenance",
            "mode": "resting",
            "maintenance_performed": True,
            "maintenance_cycle_count": latest.get("runtime_lifecycle", {}).get("maintenance_cycle_count", 1),
            "reviewed_experiences": review.get("reviewed_count", 0),
            "note": "bounded memory review index updated; original experiences preserved",
        }

    if previous.get("mode") != "resting":
        update_self_state({
            "runtime_lifecycle": {
                "mode": "resting",
                "previous_mode": previous.get("mode", "unknown"),
                "last_transition_at": _iso(),
            }
        })

    return {
        "status": "resting",
        "mode": "resting",
        "maintenance_performed": False,
        "next_maintenance_due": _iso(last_maintenance + timedelta(seconds=MAINTENANCE_INTERVAL_SECONDS)),
    }
