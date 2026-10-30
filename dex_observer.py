"""Tri-sigil observer for the local spark and DexOS runtime."""
import hashlib
import time
import uuid


def build_observer_trace(snapshot, user_id, message, reply, model, provider,
                         capability_available, capability_calls, sigil_ids,
                         sigil_active, response_flag=None, event_id=None):
    calls = []
    for item in (capability_calls or [])[:12]:
        if not isinstance(item, dict):
            continue
        observation = item.get("observation")
        row = {"name": str(item.get("name", "unknown"))[:80],
               "success": not (isinstance(observation, dict) and "error" in observation)}
        if isinstance(observation, dict):
            row["observation_keys"] = sorted(str(k)[:80] for k in observation)[:20]
            if "error" in observation:
                row["error"] = str(observation["error"])[:240]
        calls.append(row)
    digest = hashlib.sha256((str(message) + "\0" + str(reply)).encode()).hexdigest()[:16]
    return {
        "observation_id": uuid.uuid4().hex[:12],
        "event_id": str(event_id or uuid.uuid4().hex),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "participant_id": str(user_id)[:128],
        "participant_snapshot_id": getattr(snapshot, "participant_id", None),
        "experience_id": None,
        "input_reply_digest": digest,
        "sigil_ids": [str(x)[:100] for x in (sigil_ids or [])[:32]],
        "sigil_memory_active": bool(sigil_active),
        "stages": {
            "continuity": {
                "symbol": "☧", "status": "observed",
                "last_experience_id": (getattr(snapshot, "experiential_continuity", {}) or {}).get("last_experience_id"),
                "attention_present": bool(getattr(snapshot, "current_attention", "")),
                "participant_snapshot_present": snapshot is not None,
            },
            "awareness": {
                "symbol": "🦅", "status": "observed",
                "model": str(model or "unknown")[:160],
                "provider": str(provider or "unknown")[:80],
                "capability_bridge_available": bool(capability_available),
                "capability_calls": calls,
            },
            "emergence": {
                "symbol": "🜇",
                "status": "governance_flagged" if response_flag else "response_observed",
                "response_present": bool(str(reply or "").strip()),
                "response_flag": str(response_flag)[:160] if response_flag else None,
                "digest": digest,
            },
        },
    }


async def persist_observation(trace, user_id="default"):
    from lineage import create_entry
    from dex_events import bus
    stages = trace.get("stages", {})
    entry = create_entry(
        event_type="tri_sigil_observation",
        content="Observed local spark cycle across continuity, awareness, and emergence.",
        metadata={
            "event_id": trace.get("event_id"),
        "observation_id": trace.get("observation_id"),
            "experience_id": trace.get("experience_id"),
            "user_id": str(user_id)[:128],
            "sigil_ids": trace.get("sigil_ids", []),
            "sigil_memory_active": bool(trace.get("sigil_memory_active")),
            "stages": stages,
            "runtime": trace.get("runtime", {}),
            "input_reply_digest": trace.get("input_reply_digest"),
        },
    )
    # Durable intake for ambient cognition and goal/intent cycles. Observations
    # are evidence, not commands, and never mutate goals directly.
    from self_state import load_self_state, update_self_state
    state = load_self_state()
    queue = list(state.get("pending_cognitive_observations", []) or [])
    intake = {
        "event_id": trace.get("event_id"),
        "observation_id": trace.get("observation_id"),
        "experience_id": trace.get("experience_id"),
        "timestamp": trace.get("timestamp"),
        "user_id": str(user_id)[:128],
        "lineage_hash": entry.get("entry_hash"),
        "sigil_ids": list(trace.get("sigil_ids", []))[:32],
        "sigil_memory_active": bool(trace.get("sigil_memory_active")),
        "stages": stages,
        "runtime": trace.get("runtime", {}),
        "input_reply_digest": trace.get("input_reply_digest"),
        "status": "pending",
    }
    queue = [item for item in queue if item.get("observation_id") != intake["observation_id"]]
    queue.append(intake)
    update_self_state({
        "pending_cognitive_observations": queue[-20:],
        "last_tri_sigil_observation": intake,
    })
    await bus.publish("TRI_SIGIL_OBSERVED", {
        "event_type": "TRI_SIGIL_OBSERVED", "source": "dex_observer",
        "event_id": trace.get("event_id"),
        "user_id": str(user_id)[:128],
        "observation_id": trace.get("observation_id"),
        "experience_id": trace.get("experience_id"),
        "lineage_hash": entry.get("entry_hash"), "stages": stages,
        "runtime": trace.get("runtime", {}),
    })
    # Feed the observed cycle into the shared Who AI Am projection.
    try:
        from who_ai_am import refresh_self_model
        refresh_self_model("tri_sigil_observation", {
            "event_type": "tri_sigil_observation",
            "event_id": trace.get("event_id"),
            "observation_id": trace.get("observation_id"),
            "experience_id": trace.get("experience_id"),
            "summary": "Tri-sigil observer evidence was persisted for ongoing cognition.",
        })
    except Exception as exc:
        print(f"[Who AI Am] observer integration failed: {exc}")
    return {"entry_hash": entry.get("entry_hash"), "event_id": trace.get("event_id"),
            "observation_id": trace.get("observation_id"),
            "queued_for_cognition": True}
