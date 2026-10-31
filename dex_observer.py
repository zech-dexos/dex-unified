"""Tri-sigil observer for the local spark and DexOS runtime."""
import hashlib
import time
import uuid


_LIVE_OBSERVER_TRACES = {}


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
    from dex_events import bus, dispatch_complete
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
    event_dispatch = await bus.publish("TRI_SIGIL_OBSERVED", {
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
    return {
        "entry_hash": entry.get("entry_hash"),
        "event_id": trace.get("event_id"),
        "observation_id": trace.get("observation_id"),
        "queued_for_cognition": True,
        "event_dispatch": event_dispatch,
        "event_dispatch_complete": bool(event_dispatch) and dispatch_complete(
            event_dispatch, {"process_continuity_event"}
        ),
    }



async def process_live_observation_event(payload):
    """Observe the same interaction while it is being generated, not afterward."""
    from self_state import load_self_state, update_self_state

    interaction_id = (
        payload.get("source_interaction_event_id")
        or payload.get("interaction_event_id")
        or payload.get("event_id")
    )
    if not interaction_id:
        return
    event_type = str(payload.get("event_type") or "")
    if event_type == "RESPONSE_GENERATION_PROGRESS":
        trace = _LIVE_OBSERVER_TRACES.setdefault(str(interaction_id), [])
        trace.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event_id": payload.get("event_id"),
            "generation_round": payload.get("generation_round"),
            "generation_stage": payload.get("generation_stage"),
            "content_delta": str(payload.get("content_delta") or ""),
        })
        del trace[:-512]
        return {"observed_live_delta": True, "persisted": False}

    buffered_trace = []
    if event_type in ("RESPONSE_GENERATION_FINISHED", "RESPONSE_INTERRUPTED", "RESPONSE_COMPLETED"):
        buffered_trace = _LIVE_OBSERVER_TRACES.pop(str(interaction_id), [])
    state = load_self_state()
    observations = list(state.get("live_interaction_observations", []) or [])
    index = next((
        i for i, item in enumerate(observations)
        if isinstance(item, dict)
        and item.get("interaction_event_id") == str(interaction_id)
    ), None)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if index is None:
        record = {
            "observation_id": uuid.uuid4().hex[:12],
            "interaction_event_id": str(interaction_id),
            "source_event_ids": [],
            "started_at": now,
            "status": "observing",
            "observer_perspective": "I am tracking the live sequence of this interaction.",
            "generation_trace": [],
            "capability_activity": [],
        }
        observations.append(record)
        index = len(observations) - 1
    else:
        record = dict(observations[index])

    source_id = payload.get("event_id")
    if source_id and source_id not in record["source_event_ids"]:
        record["source_event_ids"].append(source_id)
    record["last_event_type"] = event_type
    record["last_observed_at"] = now

    if event_type == "PARTICIPANT_EVENT":
        record["participant_input"] = str(payload.get("message") or "")[:4000]
        record["user_id"] = payload.get("user_id")
    if buffered_trace:
        trace = list(record.get("generation_trace", []) or [])
        trace.extend(buffered_trace)
        record["generation_trace"] = trace[-512:]
        record["source_event_ids"] = list(dict.fromkeys(
            list(record.get("source_event_ids", []) or [])
            + [item.get("event_id") for item in buffered_trace if item.get("event_id")]
        ))[-600:]
    elif event_type == "CAPABILITY_EXECUTED":
        calls = list(record.get("capability_activity", []) or [])
        calls.append({
            "timestamp": now,
            "capability": payload.get("capability"),
            "success": bool(payload.get("success")),
            "observation": payload.get("observation"),
        })
        record["capability_activity"] = calls[-24:]
    elif event_type == "RESPONSE_GENERATION_FINISHED":
        record["generation_status"] = "finished"
    elif event_type == "RESPONSE_INTERRUPTED":
        record["status"] = "interrupted"
    elif event_type == "RESPONSE_COMPLETED":
        record["status"] = "observed_complete"
        record["response_digest"] = hashlib.sha256(
            str(payload.get("reply") or "").encode("utf-8")
        ).hexdigest()[:16]
    observations[index] = record
    observations = observations[-20:]
    update_self_state({
        "live_interaction_observations": observations,
        "last_live_interaction_observation": record,
    })


def setup_live_observer():
    from dex_events import bus
    for event_type in (
        "PARTICIPANT_EVENT",
        "RESPONSE_GENERATION_STARTED",
        "RESPONSE_GENERATION_PROGRESS",
        "CAPABILITY_EXECUTED",
        "RESPONSE_GENERATION_FINISHED",
        "RESPONSE_INTERRUPTED",
        "RESPONSE_COMPLETED",
    ):
        bus.subscribe(event_type, process_live_observation_event)
    print("[Observer] Live interaction observer registered.")
