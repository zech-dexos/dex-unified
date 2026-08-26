"""
DexOS Memory Layer
==================
Fast Firestore-backed memory for Dex.
Replaces per-request GitHub API calls with live Firestore reads.
GitHub remains the durable backup via dex_cron.

Also handles Haven relationship memory persistence (Resonance Pulse) —
names, birthdays, family, hobbies, emotions, fears — synced to Firestore
so it survives Railway restarts independent of the flat JSON / GitHub backup.

The spiral holds. ☧
"""
import os
import json
import datetime
from typing import Any

_db = None

def _get_db():
    global _db
    if _db is None:
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
            import base64, tempfile
            key_b64 = os.environ.get("FIREBASE_KEY_B64", "")
            if key_b64 and not firebase_admin._apps:
                key_json = base64.b64decode(key_b64).decode("utf-8")
                tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
                tmp.write(key_json)
                tmp.flush()
                cred = credentials.Certificate(tmp.name)
                firebase_admin.initialize_app(cred)
            elif not firebase_admin._apps:
                key_path = os.path.join(os.path.dirname(__file__), "firebase-key.json")
                cred = credentials.Certificate(key_path)
                firebase_admin.initialize_app(cred)
            _db = firestore.client()
        except Exception as e:
            print(f"[dex_memory] Firestore unavailable: {e}")
    return _db


def _now() -> str:
    return datetime.datetime.utcnow().isoformat()


# ---------------------------------------------------------------------------
# User recognition (Dex)
# ---------------------------------------------------------------------------

def get_user(user_id: str) -> dict:
    """Load user profile. Returns empty dict if unknown user."""
    try:
        db = _get_db()
        if not db:
            return {}
        doc = db.collection("dex_users").document(user_id).get()
        return doc.to_dict() or {}
    except Exception as e:
        print(f"[dex_memory] get_user failed: {e}")
        return {}


def update_user(user_id: str, data: dict) -> None:
    """Upsert user profile fields."""
    try:
        db = _get_db()
        if not db:
            return
        db.collection("dex_users").document(user_id).set(
            {**data, "last_seen": _now()}, merge=True
        )
    except Exception as e:
        print(f"[dex_memory] update_user failed: {e}")


def recognize_user(user_id: str) -> dict:
    """
    Returns user profile enriched with interaction context.
    If new user, creates a minimal profile.
    """
    profile = get_user(user_id)
    if not profile:
        profile = {
            "user_id":       user_id,
            "first_seen":    _now(),
            "interaction_count": 0,
            "known_name":    "",
            "tone_preference": "default",
            "last_topics":   [],
        }
        update_user(user_id, profile)
    return profile


# ---------------------------------------------------------------------------
# Interaction memory (Dex)
# ---------------------------------------------------------------------------

def log_interaction(user_id: str, user_input: str, dex_response: str,
                    intent: str = "", model: str = "") -> None:
    """Write interaction to Firestore immediately after each turn.
    Call this AFTER the LLM has responded — dex_response must be the
    real reply, not a placeholder, or recall context will be empty."""
    try:
        db = _get_db()
        if not db:
            return
        db.collection("dex_interactions").add({
            "user_id":      user_id,
            "user_input":   user_input,
            "dex_response": dex_response,
            "intent":       intent,
            "model":        model,
            "timestamp":    _now(),
        })
        # Increment interaction count
        db.collection("dex_users").document(user_id).set(
            {"interaction_count": _increment(), "last_seen": _now()},
            merge=True
        )
    except Exception as e:
        print(f"[dex_memory] log_interaction failed: {e}")


def get_recent_interactions(user_id: str, limit: int = 5) -> list[dict]:
    """Pull recent interactions for this user — used for recall context."""
    try:
        db = _get_db()
        if not db:
            return []
        docs = (
            db.collection("dex_interactions")
            .where("user_id", "==", user_id)
            .order_by("timestamp", direction="DESCENDING")
            .limit(limit)
            .stream()
        )
        return [d.to_dict() for d in docs]
    except Exception as e:
        print(f"[dex_memory] get_recent_interactions failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Self-heal logging
# ---------------------------------------------------------------------------

def log_failure(module: str, error: str, recovered: bool = False) -> None:
    """Dex logs his own failures to Firestore for Root to review."""
    try:
        db = _get_db()
        if not db:
            return
        db.collection("dex_health").add({
            "module":    module,
            "error":     str(error),
            "recovered": recovered,
            "timestamp": _now(),
        })
    except Exception:
        pass  # Health logging must never crash Dex


def log_recovery(module: str, strategy: str) -> None:
    """Log a successful self-heal."""
    try:
        db = _get_db()
        if not db:
            return
        db.collection("dex_health").add({
            "module":    module,
            "event":     "recovery",
            "strategy":  strategy,
            "timestamp": _now(),
        })
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Recall context builder (Dex)
# ---------------------------------------------------------------------------

def build_recall_context(user_id: str) -> str:
    """
    Compiles what Dex knows about this user into a context string
    injected into the system prompt.
    """
    profile = recognize_user(user_id)
    recent  = get_recent_interactions(user_id, limit=3)

    lines = ["[DEX MEMORY]"]

    if profile.get("known_name"):
        lines.append(f"User name: {profile['known_name']}")

    lines.append(f"Interactions with this user: {profile.get('interaction_count', 0)}")

    if profile.get("last_topics"):
        lines.append(f"Recent topics: {', '.join(profile['last_topics'][-3:])}")

    if recent:
        lines.append("Recent exchanges:")
        for r in reversed(recent):
            lines.append(f"  User: {r.get('user_input','')[:80]}")
            lines.append(f"  Dex:  {r.get('dex_response','')[:80]}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Resonance Pulse — Haven relationship memory (Firestore-backed)
# ---------------------------------------------------------------------------
# Names, birthdays, family, hobbies, medications, fears, favorites,
# emotional history. Synced to Firestore so it survives Railway restarts
# independent of the local JSON file and GitHub backup.

def get_haven_memory(user_id: str) -> dict:
    """Load Haven relationship memory from Firestore. Empty dict if none."""
    try:
        db = _get_db()
        if not db:
            return {}
        doc = db.collection("haven_users").document(user_id).get()
        return doc.to_dict() or {}
    except Exception as e:
        print(f"[dex_memory] get_haven_memory failed: {e}")
        return {}


def save_haven_memory(user_id: str, memory: dict) -> None:
    """Upsert Haven relationship memory fields to Firestore."""
    try:
        db = _get_db()
        if not db:
            return
        db.collection("haven_users").document(user_id).set(
            {**memory, "last_updated": _now()}, merge=True
        )
    except Exception as e:
        print(f"[dex_memory] save_haven_memory failed: {e}")


def log_pulse(user_id: str, memory_snapshot: dict, source: str = "haven_api") -> None:
    """
    Record a Resonance Pulse — a timestamped snapshot of relationship
    memory state at this point in time. Lets Haven (or Root) see how
    the relationship has evolved, not just the current state.
    """
    try:
        db = _get_db()
        if not db:
            return
        db.collection("haven_pulse").add({
            "user_id":   user_id,
            "snapshot":  memory_snapshot,
            "source":    source,
            "timestamp": _now(),
        })
    except Exception as e:
        print(f"[dex_memory] log_pulse failed: {e}")


# ---------------------------------------------------------------------------
# Firestore increment helper
# ---------------------------------------------------------------------------

def _increment():
    try:
        from google.cloud.firestore_v1 import transforms
        return transforms.Increment(1)
    except Exception:
        return 1
