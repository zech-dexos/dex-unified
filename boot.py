"""DexOS boot: authoritative constitution plus persistent operational state."""
import json
import time
from pathlib import Path

from lineage import create_entry, verify_chain, get_recent
from paths import IDENTITY_PATH, SELF_MODEL_PATH

CONSTITUTION_PATH = Path(__file__).resolve().parent / "identity_constitution.json"


def _read_json(path, default):
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, type(default)) else default
    except (OSError, ValueError):
        return default


def load_constitution():
    constitution = _read_json(CONSTITUTION_PATH, {})
    required = ("name", "architect", "tri_sigil", "vows", "invariants", "posture", "constitution")
    if not isinstance(constitution, dict) or any(key not in constitution for key in required):
        raise ValueError("Authoritative identity constitution is missing or incomplete")
    if not isinstance(constitution["vows"], dict) or not isinstance(constitution["invariants"], dict):
        raise ValueError("Constitution vows and invariants must be objects")
    return constitution


def apply_identity_authority(identity, constitution=None):
    """Return a governed runtime view without rewriting or discarding state."""
    if not isinstance(identity, dict):
        raise TypeError("Operational identity must be an object")
    constitution = constitution or load_constitution()
    merged = dict(identity)
    for key in ("name", "alias", "architect", "architect_name", "tri_sigil", "posture", "constitution"):
        if key in constitution:
            merged[key] = constitution[key]
    merged["invariants"] = dict(constitution["invariants"])
    vows = identity.get("vows", {})
    merged["vows"] = {**(vows if isinstance(vows, dict) else {}), **constitution["vows"]}
    if "ashline" in constitution["vows"]:
        merged["vows"]["ashline_vow_text"] = constitution["vows"]["ashline"]
    return merged


def load_identity():
    constitution = load_constitution()
    if IDENTITY_PATH.exists():
        try:
            identity = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Operational identity cannot be read; refusing to replace it: {exc}") from exc
        if not isinstance(identity, dict):
            raise ValueError("Operational identity must be a JSON object; refusing to replace it")
    else:
        identity = {"version": 1, "created": time.time(), "narrative_thread": [], "core_principles": [], "vows": {}}
        IDENTITY_PATH.write_text(json.dumps(identity, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return apply_identity_authority(identity, constitution)


def verify_identity(identity):
    try:
        constitution = load_constitution()
    except (OSError, ValueError):
        return False
    required = ("name", "architect", "tri_sigil", "vows", "invariants", "posture", "constitution")
    return (
        all(key in identity for key in required)
        and identity["name"] == constitution["name"]
        and identity["architect"] == constitution["architect"]
        and identity["tri_sigil"] == constitution["tri_sigil"]
        and all(key in identity["vows"] for key in constitution["vows"])
    )


def reconstruct_narrative(entries):
    if not entries:
        return "No prior lineage entries available; continuity begins with this boot."
    parts = []
    for kind, label in (("boot", "Last boot"), ("conversation", "Last conversation"), ("vow_check", "Previous vow check")):
        entry = next((e for e in reversed(entries) if e.get("event_type") == kind), None)
        if not entry:
            continue
        if kind == "boot":
            try:
                parts.append(f"{label} {max(0, time.time() - float(entry.get('timestamp', time.time()))) / 3600:.1f} hours ago.")
            except (TypeError, ValueError):
                pass
        elif kind == "conversation":
            parts.append(f"{label}: {str(entry.get('content', ''))[:100]}")
        else:
            parts.append("Vows were checked in a previous session.")
    return " ".join(parts) or "Continuity established from lineage."


def generate_self_model(identity, narrative, chain_status):
    # Merge into the prior self-model: newer cognition/autobiography fields survive.
    model = _read_json(SELF_MODEL_PATH, {})
    if not isinstance(model, dict):
        model = {}
    model.update({
        "timestamp": time.time(),
        "name": identity["name"],
        "architect": identity["architect"],
        "tri_sigil": identity["tri_sigil"],
        "posture": identity["posture"],
        "narrative": narrative,
        "chain_status": chain_status["status"],
        "chain_entries": chain_status["entries"],
        "vows_active": list(identity["vows"]),
        "invariants": identity["invariants"],
        "ready": True,
    })
    SELF_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SELF_MODEL_PATH.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return model


def boot():
    print("\n☧ DexOS Boot Sequence Initiated ☧")
    chain = verify_chain()
    if chain["status"] == "BROKEN":
        create_entry(event_type="security_alert", content=f"CHAIN INTEGRITY VIOLATION: {chain['message']}", metadata={"alert_level": "critical"})
        return {"status": "lockdown", "reason": chain["message"]}
    try:
        identity = load_identity()
    except (OSError, ValueError) as exc:
        create_entry(event_type="security_alert", content=f"Identity constitution invalid: {exc}", metadata={"alert_level": "critical"})
        return {"status": "lockdown", "reason": str(exc)}
    if not verify_identity(identity):
        create_entry(event_type="security_alert", content="Constitutional identity integrity check failed.", metadata={"alert_level": "critical"})
        return {"status": "lockdown", "reason": "Constitutional identity corrupted"}
    recent = get_recent(20)
    narrative = reconstruct_narrative(recent)
    model = generate_self_model(identity, narrative, chain)
    create_entry(
        event_type="boot",
        content=f"Boot sequence complete. {identity['name']} online. Chain: {chain['status']}. Entries: {chain['entries']}.",
        metadata={"tri_sigil": identity["tri_sigil"], "narrative": narrative, "chain_entries": chain["entries"]},
    )
    print(f"✓ {identity['name']} is online. The spiral holds. ☧")
    return {"status": "online", "self_model": model, "identity": identity}


if __name__ == "__main__":
    result = boot()
    if result["status"] != "online":
        raise SystemExit(1)

