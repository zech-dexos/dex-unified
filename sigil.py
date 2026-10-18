"""DexOS Sigil Memory — restored from ReasonFlow Sigil System v2.

The model is replaceable; the behavioral engine and Dex's continuity are not.
The historical engine anchor is metadata, not a mutable learned sigil.
"""
import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    import paths as _paths
    _STATE_DIR = Path(_paths.LEDGER_PATH).parent
    LINEAGE_FILE = Path(_paths.LEDGER_PATH)
except (ImportError, AttributeError):
    _STATE_DIR = Path(__file__).resolve().parent
    LINEAGE_FILE = _STATE_DIR / "dex_lineage.jsonl"

SIGIL_ENGINE_ANCHOR = "☧Δ🜂"
SIGIL_FILE = _STATE_DIR / "sigils.json"

DOMINANCE_CAP = 0.92
DECAY_FLOOR = 0.10
DECAY_WINDOW_SEC = 86400
MAX_ACTIVE_SET = 5


def _context_key(value):
    """Accept both Talnir's 'coding' and 'CTX:CODING' forms."""
    value = str(value or "ALL").strip().upper()
    if value.startswith("CTX:"):
        value = value[4:]
    return value or "ALL"


def _record(event, **fields):
    """Append lifecycle events to Dex's existing lineage ledger."""
    entry = {
        "ts": round(time.time(), 3),
        "source": "dex:sigil",
        "engine_anchor": SIGIL_ENGINE_ANCHOR,
        "event": event,
        **fields,
    }
    try:
        LINEAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LINEAGE_FILE.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        # A lineage write failure must not silently corrupt sigil state.
        print(f"[sigil] lineage event could not be written: {exc}")


@dataclass
class Sigil:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: str = "PREF"
    name: str = ""
    mode: str = "DRIFT"
    context: str = "CTX:ALL"
    strength: float = 0.6
    confidence: float = 0.5
    created_at: float = field(default_factory=time.time)
    last_activated: float = 0.0
    activation_count: int = 0
    decay_rate: float = 0.02
    failure_count: int = 0

    def __post_init__(self):
        self.strength = max(0.0, min(DOMINANCE_CAP, float(self.strength)))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        self.decay_rate = max(0.0, min(1.0, float(self.decay_rate)))
        if not self.last_activated:
            self.last_activated = self.created_at

    def activate(self):
        self.strength = min(DOMINANCE_CAP, self.strength + 0.05)
        self.last_activated = time.time()
        self.activation_count += 1

    def reinforce(self):
        old = self.strength
        delta = 0.1 * (1.0 - self.strength)
        self.strength = min(DOMINANCE_CAP, self.strength + delta)
        self.confidence = min(1.0, self.confidence + 0.05)
        _record(
            "sigil_reinforcement", sigil_id=self.id, name=self.name,
            delta=round(self.strength - old, 4),
            strength=round(self.strength, 4),
            confidence=round(self.confidence, 4),
        )

    def decay(self):
        if self.mode == "LOCK":
            return
        if time.time() - self.last_activated <= DECAY_WINDOW_SEC:
            return
        old = self.strength
        self.strength = max(DECAY_FLOOR, self.strength * (1.0 - self.decay_rate))
        if old != self.strength:
            _record(
                "sigil_decay", sigil_id=self.id, name=self.name,
                old_strength=round(old, 4),
                new_strength=round(self.strength, 4),
            )

    def mutate(self, new_name, reason="correction"):
        old_name = self.name
        _record(
            "sigil_mutation", sigil_id=self.id, old_name=old_name,
            new_name=str(new_name), reason=str(reason),
        )
        self.name = str(new_name)
        self.mode = "DRIFT"
        self.strength = max(0.3, self.strength - 0.1)
        self.failure_count = 0

    def score(self, context):
        own = _context_key(self.context)
        requested = _context_key(context)
        if own != "ALL" and own != requested:
            return 0.0
        age = max(0.0, time.time() - self.last_activated)
        recency = 1.0 / (1.0 + age / 86400.0)
        return self.strength * self.confidence * recency

    def __str__(self):
        return (
            f"[{self.type}:{self.name}:{self.mode}:{self.context}] "
            f"s={self.strength:.2f}"
        )


class SigilMemory:
    def __init__(self):
        self.sigils = []
        self.load()

    def load(self):
        if not SIGIL_FILE.exists():
            self.sigils = []
            return
        try:
            data = json.loads(SIGIL_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("sigils.json must contain a JSON list")
            loaded = []
            for item in data:
                if isinstance(item, dict):
                    # Ignore unknown future fields; preserve compatible fields.
                    allowed = Sigil.__dataclass_fields__
                    loaded.append(Sigil(**{
                        key: value for key, value in item.items()
                        if key in allowed
                    }))
            self.sigils = loaded
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            # Do not overwrite a file we could not safely read.
            raise RuntimeError(f"Cannot load sigil state at {SIGIL_FILE}: {exc}") from exc

    def save(self):
        SIGIL_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [asdict(s) for s in self.sigils],
            ensure_ascii=False, indent=2,
        )
        fd, temp_path = tempfile.mkstemp(
            prefix=".sigils-", suffix=".tmp", dir=str(SIGIL_FILE.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, SIGIL_FILE)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def create(self, type, name, mode="DRIFT", context="CTX:ALL",
               strength=0.6, trigger="explicit"):
        sigil = Sigil(
            type=str(type), name=str(name), mode=str(mode),
            context=str(context), strength=strength,
        )
        self.sigils.append(sigil)
        self.save()
        _record(
            "sigil_creation", sigil_id=sigil.id, name=sigil.name,
            type=sigil.type, context=sigil.context,
            strength=round(sigil.strength, 4), trigger=str(trigger),
        )
        return sigil

    def activate_for_context(self, context):
        active = []
        for sigil in self.sigils:
            sigil.decay()
            score = sigil.score(context)
            if score > 0.05:
                sigil.activate()
                _record(
                    "sigil_activation", sigil_id=sigil.id, name=sigil.name,
                    context=str(context), score=round(score, 4),
                    strength=round(sigil.strength, 4),
                    activation_count=sigil.activation_count,
                )
                active.append(sigil)
        active.sort(key=lambda s: s.score(context), reverse=True)
        self.save()
        return active

    def resolve_conflicts(self, active, context):
        ranked = sorted(
            active, key=lambda s: s.score(context), reverse=True
        )
        winners = ranked[:MAX_ACTIVE_SET]
        losers = ranked[MAX_ACTIVE_SET:]
        if losers and winners:
            _record(
                "sigil_conflict_resolved",
                winner_id=winners[0].id,
                loser_ids=[s.id for s in losers],
                context=str(context),
            )
        return winners

    def apply_to_branches(self, branches, active_sigils):
        modified = []
        for branch in branches:
            weight = float(branch.get("weight", 0.0))
            branch_id = str(branch.get("id", "")).lower()
            for sigil in active_sigils:
                name = sigil.name.lower()
                if not name or name not in branch_id:
                    continue
                if sigil.type == "HEUR":
                    weight = min(1.0, weight + sigil.strength * 0.2)
                elif sigil.type == "RISK":
                    weight = max(0.0, weight - sigil.strength * 0.3)
            modified.append({**branch, "weight": round(weight, 3)})
        return modified

    def mark_failure(self, sigil_id: str):
        for sigil in self.sigils:
            if sigil.id == sigil_id:
                sigil.failure_count += 1
                _record(
                    "sigil_failure", sigil_id=sigil.id, name=sigil.name,
                    failure_count=sigil.failure_count,
                )
                self.save()
                return sigil if sigil.failure_count >= 3 else None
        return None

    def show(self):
        if not self.sigils:
            print("No sigils in memory.")
            return
        for sigil in self.sigils:
            print(sigil)

    def summary(self):
        return {
            "total": len(self.sigils),
            "active": sum(s.strength > 0.5 for s in self.sigils),
            "locked": sum(s.mode == "LOCK" for s in self.sigils),
            "sigils": [str(s) for s in self.sigils],
            "engine_anchor": SIGIL_ENGINE_ANCHOR,
            "lineage_path": str(LINEAGE_FILE),
        }
